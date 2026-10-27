"""论文数据契约：检索、去重、聚类与证据引用的公共模型。"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.common.text import normalize_title

SourceName = Literal["arxiv", "openalex", "s2"]


class Paper(BaseModel):
    """统一的论文模型，所有数据源适配器都必须产出该结构。"""

    source: SourceName
    source_id: str
    doi: str | None = None
    arxiv_id: str | None = None
    title: str = ""
    normalized_title: str = ""
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    citation_count: int | None = None
    html_url: str | None = None
    pdf_url: str | None = None
    references: list[str] = Field(default_factory=list)
    tldr: str | None = None
    concepts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ensure_normalized_title(self) -> "Paper":
        if not self.normalized_title:
            self.normalized_title = normalize_title(self.title)
        return self

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def display_venue(self) -> str:
        return self.venue or "arXiv 预印本"

    @property
    def abstract_or_tldr(self) -> str:
        return self.abstract or self.tldr or ""

    @property
    def citation_key(self) -> str:
        """用于构建引用图谱的被引键，优先 DOI，其次 arXiv ID。"""
        return self.doi or self.arxiv_id or self.source_id

    def landing_url(self) -> str:
        if self.source == "arxiv":
            return f"https://arxiv.org/abs/{self.source_id}"
        if self.source == "openalex":
            return f"https://openalex.org/{self.source_id}"
        return f"https://www.semanticscholar.org/paper/{self.source_id}"

    def web_url(self) -> str:
        return self.html_url or self.pdf_url or self.landing_url()

    def evidence_ref(self) -> dict:
        """生成前端可点击跳转的证据引用，是"所有结论可溯源"的最小单元。"""
        return {
            "uid": self.uid,
            "title": self.title,
            "year": self.year,
            "venue": self.display_venue,
            "url": self.web_url(),
        }


class Query(BaseModel):
    """检索查询：由查询理解节点产出，支持多语言与多轮扩展。"""

    raw: str
    terms: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    year_from: int | None = None
    min_citations: int | None = None
    open_access_only: bool = False

    def all_terms(self) -> list[str]:
        seen: list[str] = []
        for term in [self.raw, *self.terms]:
            cleaned = (term or "").strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
        return seen


class SearchStats(BaseModel):
    """检索统计：直接喂给前端进度条与评测报告。"""

    per_source: dict[str, int] = Field(default_factory=dict)
    fetched: int = 0
    after_dedup: int = 0
    after_filter: int = 0
    duplicates_removed: int = 0
    elapsed_seconds: float = 0.0
    errors: list[str] = Field(default_factory=list)
