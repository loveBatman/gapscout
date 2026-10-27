"""批量嵌入：为聚类与相关性过滤提供向量。

可插拔三级后端（自动探测，无需人工切换）：
    1. 远程嵌入 API   —— 配置 EMBED_API_KEY / EMBED_BASE_URL 时启用（推荐 bge-m3）
    2. 本地 sentence-transformers —— 已安装时启用
    3. TF-IDF + SVD   —— 纯 sklearn，任何环境都能跑

降级不是妥协：它保证系统在任意部署环境下都能产出结果，
并在结果中显式标注所用后端，便于评测时区分（不同后端的效果差异本身就是评测素材）。

维度对齐：所有后端输出统一补齐/截断到 EMBED_DIM。
补齐零维不会改变余弦相似度（零分量不贡献点积与模长），因此聚类结果不受影响。
"""

import asyncio
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.config import EMBED_DIM, get_settings
from app.pipeline.embed_cache import get_embedding_cache
from app.schemas.paper import Paper

_ABSTRACT_CHARS = 1500

# 进程级模型缓存。
# 必要性（实测）：各 service 都是 `embedder = Embedder()` 新建实例，
# 模型若挂在实例属性上，每个任务都要重新初始化 SentenceTransformer——
# 实测这一开销约 10.1s（首次构造并编码 10.4s，第二次仅 0.3s）。
# 模型只读，跨任务共享是安全的。
_MODEL_CACHE: dict[str, object] = {}
_MODEL_LOCK = threading.Lock()


def _load_model(model_path: str):
    """按路径缓存模型实例，避免重复初始化。"""
    model = _MODEL_CACHE.get(model_path)
    if model is not None:
        return model
    with _MODEL_LOCK:
        model = _MODEL_CACHE.get(model_path)
        if model is None:
            from sentence_transformers import SentenceTransformer

            print(f"[embed] 加载模型 {model_path} ...")
            model = SentenceTransformer(model_path)
            _MODEL_CACHE[model_path] = model
    return model


@dataclass
class EmbeddingResult:
    vectors: np.ndarray
    backend: str
    dim: int

    @property
    def count(self) -> int:
        return int(self.vectors.shape[0])


def fit_dimension(vectors: np.ndarray, target_dim: int = EMBED_DIM) -> np.ndarray:
    """把向量矩阵补齐或截断到目标维度，保证与 pgvector 表结构一致。"""
    if vectors.ndim != 2:
        raise ValueError("嵌入矩阵必须是二维数组")
    current = vectors.shape[1]
    if current == target_dim:
        return vectors.astype(np.float32)
    if current > target_dim:
        return vectors[:, :target_dim].astype(np.float32)
    padding = np.zeros((vectors.shape[0], target_dim - current), dtype=np.float32)
    return np.hstack([vectors, padding]).astype(np.float32)


def normalize_rows(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32)


class Embedder:
    """嵌入器：自动选择可用后端，并缓存已加载的本地模型。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._backend: str | None = None

    @property
    def backend(self) -> str:
        return self._resolve_backend()

    def _resolve_backend(self) -> str:
        if self._backend:
            return self._backend
        if self._settings.embed_api_key and self._settings.embed_base_url:
            self._backend = "api"
        else:
            try:
                import sentence_transformers  # noqa: F401

                self._backend = "sentence-transformers"
            except ImportError:
                self._backend = "tfidf"
        return self._backend

    @staticmethod
    def paper_text(paper: Paper) -> str:
        """论文的嵌入文本：标题权重最高，摘要截断控制成本。"""
        abstract = (paper.abstract or paper.tldr or "")[:_ABSTRACT_CHARS]
        return f"{paper.title}. {abstract}".strip()

    async def embed_papers(self, papers: list[Paper]) -> EmbeddingResult:
        texts = [self.paper_text(paper) for paper in papers]
        return await self.embed_texts(texts)

    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        """批量嵌入，命中磁盘缓存的文本直接复用向量。

        缓存按文本指纹匹配：同一篇论文在不同任务、不同方向下会被反复嵌入，
        复用向量可省掉重复编码（实测单次编码约 26s），且不改变任何结果——
        相同文本的向量本来就是同一个。
        """
        if not texts:
            return EmbeddingResult(
                vectors=np.zeros((0, EMBED_DIM), dtype=np.float32),
                backend=self.backend,
                dim=EMBED_DIM,
            )

        backend = self._resolve_backend()
        cache = get_embedding_cache()
        cached, missing = cache.lookup(texts)
        if cached:
            print(f"[embed] 向量缓存命中 {len(cached)}/{len(texts)} 条")

        computed = np.zeros((0, EMBED_DIM), dtype=np.float32)
        if missing:
            computed = await self._compute([text for _, text in missing], backend)
            cache.store([text for _, text in missing], computed)
            cache.save()

        matrix = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
        for position, vector in cached.items():
            matrix[position] = vector
        for offset, (position, _) in enumerate(missing):
            if offset < computed.shape[0]:
                matrix[position] = computed[offset]

        return EmbeddingResult(
            vectors=normalize_rows(matrix),
            backend=self._resolve_backend(),
            dim=matrix.shape[1],
        )

    async def _compute(self, texts: list[str], backend: str) -> np.ndarray:
        """按后端分派计算，并把同步的 CPU 计算卸载到线程。

        卸载的必要性：本地编码是同步的 CPU 密集操作，直接在事件循环里执行
        会阻塞 SSE 事件推送，表现出来就是"进度条长时间不动然后突然跳变"。
        """
        if backend == "api":
            return await self._embed_api(texts)
        if backend == "sentence-transformers":
            vectors = await asyncio.to_thread(self._embed_local, texts)
            if vectors is not None:
                return vectors
            # 模型不可用时降级，保证链路不中断
            self._backend = "tfidf"
            return await asyncio.to_thread(self._embed_tfidf, texts)
        return await asyncio.to_thread(self._embed_tfidf, texts)

    async def embed_one(self, text: str) -> np.ndarray:
        result = await self.embed_texts([text])
        return result.vectors[0]

    def _ensure_hf_endpoint(self) -> None:
        """配置 HuggingFace 端点与超时。

        必须在导入 transformers 之前设置环境变量，否则配置不生效。

        超时保护的必要性：若所在网络无法访问 huggingface.co，
        huggingface_hub 会对每个待检查文件做多次重试，每次连接超时可达 20 秒以上，
        累积造成十几分钟的静默阻塞（实测出现过 900 秒级等待）。
        这里把超时压到可控范围，让失败快速暴露而不是长时间挂起。
        """
        endpoint = (self._settings.hf_endpoint or "").strip()
        if endpoint and not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = endpoint.rstrip("/")
            print(f"[embed] 使用 HuggingFace 镜像端点: {os.environ['HF_ENDPOINT']}")
        os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    def _resolve_model_path(self) -> str:
        """解析模型来源：优先使用随项目分发的本地模型目录。

        必要性（实测问题）：部分部署环境无法访问 HuggingFace——即使配置了镜像，
        模型权重下载仍可能失败，导致嵌入降级为 TF-IDF、聚类质量显著下滑。
        把模型随项目一起分发可以彻底消除这一外部依赖。

        约定的目录为 backend/models/<模型名>。
        """
        model_name = Path(self._settings.embed_model).name
        local_dir = Path(__file__).resolve().parents[2] / "models" / model_name
        if local_dir.is_dir() and any(local_dir.iterdir()):
            print(f"[embed] 使用随项目分发的本地模型 {local_dir}")
            return str(local_dir)
        return self._settings.embed_model

    def _embed_local(self, texts: list[str]) -> np.ndarray | None:
        """本地语义嵌入：失败时返回 None，由调用方降级到 TF-IDF。"""
        try:
            self._ensure_hf_endpoint()
            model = _load_model(self._resolve_model_path())
            vectors = model.encode(
                texts,
                batch_size=self._settings.embed_batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return fit_dimension(normalize_rows(np.asarray(vectors, dtype=np.float32)))
        except Exception as exc:  # noqa: BLE001
            print(f"[embed] 本地模型不可用（{type(exc).__name__}: {exc}），降级为 TF-IDF")
            return None

    async def _embed_api(self, texts: list[str]) -> np.ndarray:
        import httpx

        endpoint = f"{self._settings.embed_base_url.rstrip('/')}/embeddings"
        headers = {"Authorization": f"Bearer {self._settings.embed_api_key}"}
        batch_size = max(1, self._settings.embed_batch_size)
        collected: list[list[float]] = []

        async with httpx.AsyncClient(timeout=90.0) as client:
            for start in range(0, len(texts), batch_size):
                chunk = texts[start : start + batch_size]
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json={"model": self._settings.embed_model, "input": chunk},
                )
                if response.status_code != 200:
                    print(f"[embed] API 返回 {response.status_code}: {response.text[:160]}")
                    return self._embed_tfidf(texts)
                payload = response.json()
                collected.extend(item["embedding"] for item in payload.get("data", []))

        if len(collected) != len(texts):
            print(f"[embed] API 返回数量不匹配（{len(collected)}/{len(texts)}），降级为 TF-IDF")
            return self._embed_tfidf(texts)
        return fit_dimension(normalize_rows(np.asarray(collected, dtype=np.float32)))

    def _embed_tfidf(self, texts: list[str]) -> np.ndarray:
        """无模型降级：TF-IDF + 截断 SVD + L2 归一化。"""
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import Normalizer

        vectorizer = TfidfVectorizer(
            max_features=12000,
            stop_words="english",
            sublinear_tf=True,
        )
        matrix = vectorizer.fit_transform(texts)
        upper = min(matrix.shape[0] - 1, matrix.shape[1] - 1)
        if upper < 2:
            return fit_dimension(normalize_rows(np.asarray(matrix.todense(), dtype=np.float32)))
        n_components = min(EMBED_DIM, 128, upper)
        reduced = TruncatedSVD(
            n_components=n_components, random_state=42, algorithm="randomized", n_iter=4
        ).fit_transform(matrix)
        normalized = Normalizer(copy=False).fit_transform(reduced).astype(np.float32)
        return fit_dimension(normalized)
