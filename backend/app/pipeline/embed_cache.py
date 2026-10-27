"""嵌入向量磁盘缓存：按文本哈希复用已编码的向量。

必要性（实测驱动）：
    同一篇论文会在不同任务里被反复嵌入——用户先跑「领域探索」，再跑
    「研究空白识别」，两次检索到的论文高度重叠（实测 301 篇语料中绝大部分相同），
    但每次都从头编码一遍，实测单次编码耗时约 26s。
    按文本内容哈希缓存向量后，第二次可大幅命中，直接省掉重复编码。

设计取舍：
    - 单个 npz 全量读写：单次语料在千级以内（384 维 × 1000 篇 ≈ 1.5MB），
      全量读写的开销远小于重新编码，无需引入更难维护的分片方案。
    - 带容量上限，超出后淘汰最早写入的条目，避免无限增长。
    - 任何读写异常都不影响主链路，读失败即视为无缓存。
"""

import hashlib
from pathlib import Path

import numpy as np

from app.config import EMBED_DIM

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "embed_cache.npz"
MAX_ENTRIES = 20000


def text_hash(text: str) -> str:
    """文本指纹。用 SHA1 截断即可满足去重需求，无需抗碰撞强度。"""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:20]


class EmbeddingCache:
    """文本指纹 -> 向量的磁盘缓存。"""

    def __init__(self, path: Path = CACHE_PATH) -> None:
        self._path = path
        self._index: dict[str, int] = {}
        self._vectors = np.zeros((0, EMBED_DIM), dtype=np.float32)
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = np.load(self._path, allow_pickle=False)
            keys = [str(item) for item in data["keys"]]
            vectors = np.asarray(data["vectors"], dtype=np.float32)
        except Exception as exc:  # noqa: BLE001
            print(f"[embed-cache] 读取失败，按无缓存处理: {type(exc).__name__}: {exc}")
            return
        if len(keys) != vectors.shape[0]:
            # 历史版本写入过"同一文本被登记两次"的不一致缓存，其索引行号可能错位。
            # 错位的向量会让相似度计算得出错误结果，直接影响聚类与相关性过滤，
            # 因此按「质量优先」原则整体丢弃并从头积累——绝不尝试修复后继续使用。
            # 当前版本的 store/save 已从源头保证一一对应，不会再生此类数据。
            print(
                f"[embed-cache] 检测到不一致的缓存"
                f"（{len(keys)} vs {vectors.shape[0]}），已丢弃并重新积累"
            )
            keys = []
            vectors = np.zeros((0, EMBED_DIM), dtype=np.float32)

        self._index = {key: position for position, key in enumerate(keys)}
        self._vectors = vectors

    def lookup(
        self, texts: list[str]
    ) -> tuple[dict[int, np.ndarray], list[tuple[int, str]]]:
        """返回（命中: 原下标 -> 向量, 未命中: [(原下标, 文本)]）。

        保留原下标是为了把结果按输入顺序还原——顺序错位会直接破坏
        聚类与相关性计算，因此不能只返回一个"命中列表"。
        """
        cached: dict[int, np.ndarray] = {}
        missing: list[tuple[int, str]] = []
        total = self._vectors.shape[0]
        for position, text in enumerate(texts):
            row = self._index.get(text_hash(text))
            if row is None or row >= total:
                missing.append((position, text))
                continue
            cached[position] = self._vectors[row]
        return cached, missing

    def store(self, texts: list[str], vectors: np.ndarray) -> None:
        if not texts or vectors.shape[0] != len(texts):
            return

        # 同一批内可能有重复文本，也可能与已有缓存重复。
        # 只登记未出现过的指纹，保证「索引条目数 == 向量行数」——
        # 一旦不相等，这份缓存会在下次加载时被判定为损坏而整份失效。
        pending: list[tuple[str, np.ndarray]] = []
        seen: set[str] = set()
        # strict=True 是安全的：方法开头已保证 vectors 行数与 texts 长度一致，
        # 若将来这个不变式被破坏，宁可在这里抛出也不要静默截断成错位的缓存。
        for text, vector in zip(texts, vectors, strict=True):
            fingerprint = text_hash(text)
            if fingerprint in self._index or fingerprint in seen:
                continue
            seen.add(fingerprint)
            pending.append((text, vector))

        if not pending:
            return

        base = self._vectors.shape[0]
        self._vectors = np.vstack(
            [self._vectors, np.asarray([item[1] for item in pending], dtype=np.float32)]
        )
        for offset, (text, _) in enumerate(pending):
            self._index[text_hash(text)] = base + offset
        self._dirty = True
        if self._vectors.shape[0] > MAX_ENTRIES:
            self._trim()

    def _trim(self) -> None:
        """超出上限时保留最新的 MAX_ENTRIES 条，按行号顺序重建索引。"""
        keep = MAX_ENTRIES
        ordered = sorted(self._index.items(), key=lambda item: item[1])[-keep:]
        offset = self._vectors.shape[0] - keep
        self._vectors = self._vectors[-keep:]
        self._index = {key: position - offset for position, (key, _) in enumerate(ordered)}

    def save(self) -> None:
        if not self._dirty or not self._index:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # 按索引重建后再落盘，从数据源头保证 keys 与 vectors 一一对应
            rows = sorted(self._index.items(), key=lambda item: item[1])
            keys = np.array([key for key, _ in rows])
            matrix = np.vstack([self._vectors[row] for _, row in rows])
            np.savez_compressed(self._path, keys=keys, vectors=matrix)
            self._dirty = False
        except Exception as exc:  # noqa: BLE001
            print(f"[embed-cache] 写入失败（不影响本次分析）: {type(exc).__name__}: {exc}")


_CACHE: EmbeddingCache | None = None


def get_embedding_cache() -> EmbeddingCache:
    """进程级单例：避免每个任务都重新读取缓存文件。"""
    global _CACHE
    if _CACHE is None:
        _CACHE = EmbeddingCache()
        if _CACHE._vectors.shape[0]:
            print(f"[embed-cache] 已载入 {_CACHE._vectors.shape[0]} 条历史向量")
    return _CACHE
