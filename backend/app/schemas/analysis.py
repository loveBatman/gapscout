"""分析结果契约：主题、机会点、任务与 SSE 进度事件。

前端只依赖本模块定义的结构，是前后端唯一约定。
"""

from typing import Literal

from pydantic import BaseModel, Field

Stage = Literal[
    "queued",
    "understanding",
    "retrieving",
    "dedup",
    "filtering",
    "embedding",
    "clustering",
    "naming",
    "extracting",
    "analyzing",
    "criticizing",
    "generating",
    "verifying",
    "done",
    "failed",
]


class EvidenceRef(BaseModel):
    """证据引用：让"所有结论可溯源"在数据结构层面强制落地。"""

    uid: str
    title: str
    year: int | None = None
    venue: str | None = None
    url: str
    quote: str | None = None
    level: str | None = None  # L1 全文 / L2 PDF / L3 摘要级
    signal: str | None = None  # A / B / C


class TopicOut(BaseModel):
    """主题簇：领域探索的产出单元。"""

    id: int | None = None
    label: str
    summary: str | None = None
    core_problem: str | None = None
    keywords: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    size: int = 0
    trend_slope: float | None = None
    year_from: int | None = None
    year_to: int | None = None
    top_papers: list[EvidenceRef] = Field(default_factory=list)


class GapOut(BaseModel):
    """机会点卡片：M2 三路信号融合的产出。"""

    title: str
    description: str
    signals: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    value_note: str | None = None
    feasibility: str | None = None
    risk: str | None = None
    novelty: float | None = None
    confidence: float | None = None


class MatrixCell(BaseModel):
    """方法-任务矩阵单元格（信号 B 的可视化载体）。"""

    task: str
    method: str
    count: int
    is_gap: bool = False
    neighbor_score: float = 0.0


class TimelineNode(BaseModel):
    year: int
    label: str
    method: str | None = None
    paper: EvidenceRef | None = None


class PaperBrief(BaseModel):
    uid: str
    title: str
    year: int | None = None
    venue: str | None = None
    authors: list[str] = Field(default_factory=list)
    citation_count: int | None = None
    url: str
    abstract: str | None = None
    source: str
    topic_id: int | None = None
    # 2D 投影坐标：用于领域全景散点图（论文在语义空间中的位置）
    x: float | None = None
    y: float | None = None


class ExploreResult(BaseModel):
    """领域探索完整结果。"""

    task_id: str
    query: str
    terms: list[str] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)
    topics: list[TopicOut] = Field(default_factory=list)
    timeline: list[TimelineNode] = Field(default_factory=list)
    trend: list[dict] = Field(default_factory=list)
    papers: list[PaperBrief] = Field(default_factory=list)


class MatrixView(BaseModel):
    """方法-任务矩阵的前端视图（信号 B 可视化）。"""

    tasks: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    matrix: list[list[int]] = Field(default_factory=list)
    gap_cells: list[dict] = Field(default_factory=list)


class GapResult(BaseModel):
    """研究空白识别完整结果（M2）。"""

    task_id: str
    query: str
    terms: list[str] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)
    topics: list[TopicOut] = Field(default_factory=list)
    gaps: list[GapOut] = Field(default_factory=list)
    signals: dict = Field(default_factory=dict)
    matrix: MatrixView | None = None


class SimilarWork(BaseModel):
    """与新想法相似度较高的已有工作。"""

    uid: str
    title: str
    year: int | None = None
    venue: str | None = None
    url: str
    similarity: float
    difference_hint: str | None = None


class FeasibilityResult(BaseModel):
    """选题可行性评估结果（M3）。"""

    task_id: str
    idea: str
    parsed: dict = Field(default_factory=dict)
    novelty_score: float | None = None
    novelty_level: str = "unknown"  # high / medium / low
    novelty_basis: str | None = None
    similar_works: list[SimilarWork] = Field(default_factory=list)
    competition: dict = Field(default_factory=dict)
    resources: dict = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    verdict: str | None = None
    stats: dict = Field(default_factory=dict)


class ReviewSection(BaseModel):
    title: str
    content: str
    citations: list[int] = Field(default_factory=list)
    mode: str = "generated"  # generated / structured


class ReviewResult(BaseModel):
    """综述生成结果（M5）。"""

    task_id: str
    direction: str
    title: str
    sections: list[ReviewSection] = Field(default_factory=list)
    references: list[dict] = Field(default_factory=list)
    bibtex: str = ""
    verification: dict = Field(default_factory=dict)
    stats: dict = Field(default_factory=dict)


class ProgressEvent(BaseModel):
    stage: Stage
    message: str
    percent: int = 0
    source: str | None = None
    count: int | None = None


class TaskStatus(BaseModel):
    task_id: str
    kind: str
    query: str
    status: str
    stage: str | None = None
    progress: int = 0
    message: str | None = None
    error: str | None = None
    stats: dict = Field(default_factory=dict)
    result: dict | None = None
