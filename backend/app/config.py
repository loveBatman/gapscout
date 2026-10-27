"""全局配置：统一由 pydantic-settings 管理，禁止在业务代码中散落 os.environ。"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# 嵌入向量维度，需与 embedding 模型输出一致；pgvector 建表时依赖此常量。
# 默认对应 BAAI/bge-small-en-v1.5（384 维，体积小、英文语义聚类效果好）。
# 若切换到 bge-m3（1024 维）等多语言模型，需同步修改此处并重建 paper.embedding 列。
EMBED_DIM = 384


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 应用 ----------
    app_name: str = "空白侦察 GapScout"
    app_version: str = "0.1.0"
    debug: bool = True

    # ---------- 数据库 ----------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/gapscout"
    db_echo: bool = False

    # ---------- LLM ----------
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    llm_model_main: str = "deepseek-reasoner"
    llm_model_cheap: str = "deepseek-chat"
    llm_timeout: float = 180.0
    llm_max_retries: int = 3
    llm_max_concurrency: int = 4

    # ---------- 嵌入 ----------
    embed_api_key: str = ""
    embed_base_url: str = ""
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_batch_size: int = 32
    embed_max_concurrency: int = 2
    # HuggingFace 端点：部分网络环境无法直连 huggingface.co，可配置镜像，
    # 例如 https://hf-mirror.com。留空则使用官方端点。
    hf_endpoint: str = ""

    # ---------- 数据源 ----------
    contact_email: str = "researcher@example.com"
    s2_api_key: str = ""
    # arXiv 实测限流比文档更严，密集请求会触发 429 并进入冷却期，因此取值更保守
    arxiv_min_interval: float = 5.0
    openalex_min_interval: float = 0.15
    s2_min_interval: float = 0.5
    http_timeout: float = 40.0

    # ---------- 检索参数 ----------
    default_search_limit_per_source: int = 200
    min_year: int = 2019

    # ---------- 全文抓取（信号 A） ----------
    # 以下两项只影响抓取速度，不改变抓取范围与分析结果，属于无损提速参数。
    # ar5iv 是静态 HTML 站点，与 arXiv API 的限流策略不同（后者实测 5s 间隔仍有 429）。
    # 触发 429 时抓取器会自动放慢间隔，因此这里取相对积极的值。
    fulltext_concurrency: int = 8
    fulltext_min_interval: float = 0.25

    # ---------- 聚类 ----------
    cluster_min_size: int = 6
    cluster_merge_similarity: float = 0.85
    # UMAP 降维目标维度：5 是文本聚类的事实标准取值
    reduce_dim: int = 5

    # ---------- 跨域 ----------
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ]

    @property
    def has_llm(self) -> bool:
        return bool(self.deepseek_api_key and self.deepseek_api_key.startswith("sk-"))


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _apply_hf_endpoint() -> None:
    """把 HuggingFace 镜像端点写入环境变量。

    必须在 huggingface_hub 首次被导入之前执行：该库在模块加载时读取一次
    HF_ENDPOINT 并缓存，之后再设置环境变量不会生效。

    这一条踩过坑：沙箱环境明明配置了镜像，日志也打印了「使用镜像端点」，
    但模型下载仍然访问 huggingface.co 而失败——原因是 _resolve_backend()
    中的可用性探测已经先导入了 sentence_transformers（连带 huggingface_hub），
    而当时端点尚未写入环境变量。放在此处可保证早于任何相关导入。
    """
    endpoint = (get_settings().hf_endpoint or "").strip()
    if endpoint and not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = endpoint.rstrip("/")


_apply_hf_endpoint()
