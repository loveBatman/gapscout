"""ORM 模型：六张核心表。

设计要点：
- paper 表同时承载元数据与向量（pgvector），避免引入独立向量库
- paper_reference 用边表存储引用关系，千级节点用 NetworkX 内存计算即可，无需 Neo4j
- cache_entry 以内容 hash 为主键，让重复检索与重复 LLM 调用零成本
- analysis_task 承载长任务状态，SSE 断开后可凭 task_id 恢复中间结果
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import EMBED_DIM


class Base(DeclarativeBase):
    pass


class Paper(Base):
    """论文：所有结论的最终证据来源。"""

    __tablename__ = "paper"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), index=True)
    source_id: Mapped[str] = mapped_column(String(160))
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(String(512), index=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[list] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    venue: Mapped[str | None] = mapped_column(String(512), nullable=True)
    citation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    html_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    tldr: Mapped[str | None] = mapped_column(Text, nullable=True)
    concepts: Mapped[list] = mapped_column(JSON, default=list)
    embedding: Mapped[list | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_paper_source_id"),
    )


class PaperReference(Base):
    """引用边：src 引用 dst。dst_paper_id 为空表示该被引文献尚未入库。"""

    __tablename__ = "paper_reference"

    id: Mapped[int] = mapped_column(primary_key=True)
    src_paper_id: Mapped[int] = mapped_column(ForeignKey("paper.id"), index=True)
    dst_key: Mapped[str] = mapped_column(String(255), index=True)
    dst_paper_id: Mapped[int | None] = mapped_column(
        ForeignKey("paper.id"), nullable=True, index=True
    )


class AnalysisTask(Base):
    """分析任务：探索 / 空白识别 / 可行性 / 综述 共用一张任务表。"""

    __tablename__ = "analysis_task"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Topic(Base):
    """主题簇：领域探索的产出单元。"""

    __tablename__ = "topic"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("analysis_task.id"), index=True)
    label: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    core_problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    methods: Mapped[list] = mapped_column(JSON, default=list)
    paper_ids: Mapped[list] = mapped_column(JSON, default=list)
    size: Mapped[int] = mapped_column(Integer, default=0)
    trend_slope: Mapped[float | None] = mapped_column(Float, nullable=True)
    centroid: Mapped[list | None] = mapped_column(Vector(EMBED_DIM), nullable=True)


class Gap(Base):
    """机会点卡片：M2 核心创新产出。"""

    __tablename__ = "gap"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("analysis_task.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    signals: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    value_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    feasibility: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk: Mapped[str | None] = mapped_column(Text, nullable=True)
    novelty: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class CacheEntry(Base):
    """内容级缓存：检索结果与 LLM 输出均按内容 hash 复用。"""

    __tablename__ = "cache_entry"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
