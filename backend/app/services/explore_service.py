"""领域探索服务：M1 完整链路编排。

链路：查询理解 -> 多源检索 -> 三级去重 -> 质量过滤 -> 语义嵌入
      -> 相关性闸门 -> UMAP + HDBSCAN 聚类 -> c-TF-IDF/LLM 主题命名

设计要点：
- 每个阶段都推送 SSE 进度，让"AI 正在做什么"可见（产品体验关键）
- 每个阶段都记录耗时与计数，直接进入 stats 供评测报告使用
- LLM 未配置时全链路仍可运行（查询理解与命名走确定性降级路径）
"""

import time
import uuid

import numpy as np

from app.agents.llm import LLMClient
from app.agents.topic_naming import TopicDraft, name_topics
from app.common.text import contains_chinese, extract_keywords
from app.config import get_settings
from app.pipeline.cache import make_key, read_cache, write_cache
from app.pipeline.cluster import cluster_topics, top_papers_per_cluster
from app.pipeline.embed import Embedder
from app.pipeline.filter import (
    filter_by_relevance,
    quality_filter,
    trend_slope,
    year_trend,
)
from app.pipeline.normalize import dedup_papers
from app.pipeline.topic_naming import ctfidf_keywords
from app.schemas.analysis import (
    EvidenceRef,
    ExploreResult,
    PaperBrief,
    TimelineNode,
    TopicOut,
)
from app.schemas.paper import Paper, Query
from app.services.event_bus import bus
from app.sources.registry import SourceRegistry

QUERY_SYSTEM = """你是学术检索助手，负责把研究方向转换为英文检索术语。
要求：
- terms 给出 3 到 6 个英文关键词或短语，覆盖核心概念与其常见同义表达
- 术语要具体，避免 machine learning 这类过宽的词
- 只输出 JSON：{"terms":["...","..."]}"""


QUERY_CACHE_KIND = "query"


async def understand_query(raw: str, llm: LLMClient) -> Query:
    """查询理解：把研究方向转成可用于英文学术库的检索术语。

    中文方向无法直接检索 arXiv / OpenAlex，必须转成英文术语。
    无 LLM 时降级为启发式关键词抽取（对英文输入有效，中文输入效果有限）。

    术语结果按方向缓存：生成的术语不仅决定检索表达式，还被拼成 probe
    用于语义相关性闸门——若同一方向每次得到不同术语，会出现
    「同一方向两次分析结果不同」（实测语料规模在 278 ~ 303 篇之间漂移，
    主题数在 6 ~ 7 之间波动）。缓存后同一方向的结果可复现。
    """
    cache_key = make_key(QUERY_CACHE_KIND, {"q": (raw or "").strip().lower()})
    cached = read_cache(QUERY_CACHE_KIND, cache_key)
    if cached and cached.get("terms"):
        return Query(
            raw=raw, terms=list(cached["terms"]), year_from=get_settings().min_year
        )

    terms: list[str] = []
    if llm.available:
        payload = await llm.complete_json(
            f"研究方向：{raw}", system=QUERY_SYSTEM, model=llm.cheap_model
        )
        if payload and isinstance(payload.get("terms"), list):
            terms = [str(item).strip() for item in payload["terms"] if str(item).strip()][:6]
    if not terms:
        stripped = (raw or "").strip()
        words = stripped.split()
        # 英文输入保留原短语：学术术语多为固定搭配，拆词会引入歧义
        # （"retrieval augmented generation" 拆开后 "augmented" 会匹配到增强现实论文）
        if stripped and not contains_chinese(stripped) and 1 <= len(words) <= 6:
            terms = [stripped]
        else:
            terms = extract_keywords(raw, limit=5)

    if terms:
        write_cache(QUERY_CACHE_KIND, cache_key, {"terms": terms})
    return Query(raw=raw, terms=terms, year_from=get_settings().min_year)


async def run_explore(task_id: str, raw_direction: str) -> ExploreResult:
    started = time.monotonic()
    settings = get_settings()
    llm = LLMClient()
    stages: dict[str, float] = {}

    # ---------- 1. 查询理解 ----------
    await bus.progress(task_id, "understanding", "正在解析研究方向并生成检索术语", 4)
    mark = time.monotonic()
    query = await understand_query(raw_direction, llm)
    stages["understanding"] = round(time.monotonic() - mark, 2)
    await bus.partial(task_id, "terms", {"terms": query.terms})

    # ---------- 2. 多源检索 ----------
    await bus.progress(
        task_id, "retrieving", "正在并发检索 arXiv / OpenAlex / Semantic Scholar", 10
    )
    mark = time.monotonic()

    async def on_source_done(name: str, count: int) -> None:
        await bus.progress(
            task_id,
            "retrieving",
            f"{name} 返回 {count} 篇",
            18,
            source=name,
            count=count,
        )

    registry = SourceRegistry()
    papers, search_stats = await registry.search_all(
        query, settings.default_search_limit_per_source, on_source_done=on_source_done
    )
    await registry.aclose()
    stages["retrieving"] = round(time.monotonic() - mark, 2)
    await bus.progress(
        task_id, "retrieving", f"共召回 {len(papers)} 篇文献", 26, count=len(papers)
    )

    # ---------- 3. 去重 ----------
    await bus.progress(task_id, "dedup", "正在执行三级去重（标题 / DOI / 模糊匹配）", 30)
    mark = time.monotonic()
    deduped, dedup_report = dedup_papers(papers)
    stages["dedup"] = round(time.monotonic() - mark, 2)
    await bus.progress(
        task_id,
        "dedup",
        f"去重后 {len(deduped)} 篇（移除 {dedup_report.removed} 篇重复）",
        36,
        count=len(deduped),
    )

    # ---------- 4. 质量过滤 ----------
    await bus.progress(task_id, "filtering", "正在按年份与引用密度做质量分层", 40)
    mark = time.monotonic()
    filtered, dropped = quality_filter(deduped, query)
    stages["filtering"] = round(time.monotonic() - mark, 2)
    await bus.progress(
        task_id, "filtering", f"保留 {len(filtered)} 篇代表性文献", 44, count=len(filtered)
    )

    if not filtered:
        summary = _build_result(task_id, raw_direction, query, papers, [], [], stages, llm)
        summary.stats["message"] = "未检索到满足条件的文献，请尝试更具体或更常见的方向"
        return summary

    # ---------- 5. 语义嵌入 ----------
    await bus.progress(task_id, "embedding", "正在生成语义向量", 50)
    mark = time.monotonic()
    embedder = Embedder()
    embedding = await embedder.embed_papers(filtered)
    stages["embedding"] = round(time.monotonic() - mark, 2)
    await bus.progress(
        task_id,
        "embedding",
        f"已向量化 {embedding.count} 篇（后端 {embedding.backend}）",
        58,
        count=embedding.count,
    )

    # ---------- 6. 相关性闸门 ----------
    proceed = await _apply_relevance(task_id, filtered, embedding, query, embedder)
    filtered, vectors, relevance_dropped = proceed
    if relevance_dropped:
        await bus.progress(
            task_id,
            "filtering",
            f"语义相关性闸门剔除 {relevance_dropped} 篇跨学科噪声",
            62,
            count=len(filtered),
        )

    # ---------- 7. 聚类 ----------
    await bus.progress(task_id, "clustering", "正在执行 UMAP 降维与密度聚类", 66)
    mark = time.monotonic()
    outcome = cluster_topics(vectors)
    stages["clustering"] = round(time.monotonic() - mark, 2)
    await bus.progress(
        task_id,
        "clustering",
        f"识别出 {outcome.n_clusters} 个主题簇（降维 {outcome.reducer}）",
        72,
        count=outcome.n_clusters,
    )

    # ---------- 8. 关键词抽取 ----------
    documents = [Embedder.paper_text(paper) for paper in filtered]
    keywords_map = ctfidf_keywords(documents, outcome.labels)
    representatives = top_papers_per_cluster(vectors, outcome.labels, top_k=4)

    # ---------- 9. 主题命名 ----------
    await bus.progress(task_id, "naming", "正在生成主题标签与核心问题", 78)
    mark = time.monotonic()
    drafts: list[TopicDraft] = []
    trend = year_trend(filtered)
    for cluster_id, size in outcome.sizes().items():
        if cluster_id < 0:
            continue
        indices = np.where(outcome.labels == cluster_id)[0]
        years = [filtered[i].year for i in indices if filtered[i].year]
        cluster_trend = year_trend([filtered[i] for i in indices])
        drafts.append(
            TopicDraft(
                cluster_id=cluster_id,
                keywords=keywords_map.get(cluster_id, _empty_keywords()).keywords,
                size=size,
                titles=[filtered[i].title for i in representatives.get(cluster_id, [])],
                year_from=min(years) if years else None,
                year_to=max(years) if years else None,
                trend_slope=trend_slope(cluster_trend),
            )
        )

    topics = await name_topics(drafts, llm, direction=raw_direction)
    topics = _attach_papers(topics, representatives, filtered)
    stages["naming"] = round(time.monotonic() - mark, 2)

    for topic in topics:
        await bus.partial(task_id, "topic", topic.model_dump())

    # ---------- 10. 汇总 ----------
    result = _build_result(
        task_id,
        raw_direction,
        query,
        filtered,
        topics,
        trend,
        stages,
        llm,
        labels=outcome.labels,
        projection=outcome.projection,
    )
    result.stats.update(
        {
            "per_source": search_stats.per_source,
            "search_errors": search_stats.errors,
            "dedup": dedup_report.as_dict(),
            "filter_dropped": dropped,
            "relevance_dropped": relevance_dropped,
            "embed_backend": embedding.backend,
            "cluster": {
                "n_clusters": outcome.n_clusters,
                "noise": outcome.noise_count,
                "reducer": outcome.reducer,
                "merged": outcome.merged_count,
                "reassigned": outcome.reassigned_count,
            },
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "llm": llm.usage.as_dict(),
            "database": "memory",
        }
    )
    return result


def _empty_keywords():
    from app.pipeline.topic_naming import ClusterKeywords

    return ClusterKeywords(label=-1, keywords=[], size=0)


async def _apply_relevance(
    task_id: str,
    papers: list[Paper],
    embedding,
    query: Query,
    embedder: Embedder,
) -> tuple[list[Paper], np.ndarray, int]:
    """语义相关性闸门：剔除关键词匹配引入的跨学科论文。"""
    probe = query.raw if not query.terms else f"{query.raw} {' '.join(query.terms)}"
    query_vector = await embedder.embed_one(probe)
    similarities = embedding.vectors @ query_vector
    kept, indices, dropped = filter_by_relevance(papers, similarities)
    vectors = embedding.vectors[indices]
    await bus.partial(task_id, "relevance", {"dropped": dropped, "kept": len(kept)})
    return kept, vectors, dropped


def _attach_papers(
    topics: list[TopicOut], representatives: dict[int, list[int]], papers: list[Paper]
) -> list[TopicOut]:
    for topic in topics:
        indices = representatives.get(topic.id if topic.id is not None else -1, [])
        topic.top_papers = [_evidence(papers[index]) for index in indices if index < len(papers)]
    return topics


def _evidence(paper: Paper) -> EvidenceRef:
    return EvidenceRef(
        uid=paper.uid,
        title=paper.title,
        year=paper.year,
        venue=paper.display_venue,
        url=paper.web_url(),
        level="L3",
    )


def _build_result(
    task_id: str,
    direction: str,
    query: Query,
    papers: list[Paper],
    topics: list[TopicOut],
    trend: list[dict],
    stages: dict[str, float],
    llm: LLMClient,
    labels: np.ndarray | None = None,
    projection: np.ndarray | None = None,
) -> ExploreResult:
    briefs: list[PaperBrief] = []
    for index, paper in enumerate(papers):
        briefs.append(
            PaperBrief(
                uid=paper.uid,
                title=paper.title,
                year=paper.year,
                venue=paper.display_venue,
                authors=paper.authors[:6],
                citation_count=paper.citation_count,
                url=paper.web_url(),
                abstract=(paper.abstract_or_tldr or "")[:600] or None,
                source=paper.source,
                topic_id=_label_at(labels, index),
                x=_coord(projection, index, 0),
                y=_coord(projection, index, 1),
            )
        )

    # 技术演化时间线：每年挑引用密度最高的代表论文
    by_year: dict[int, Paper] = {}
    for paper in papers:
        if not paper.year:
            continue
        current = by_year.get(paper.year)
        if current is None or (paper.citation_count or 0) > (current.citation_count or 0):
            by_year[paper.year] = paper
    timeline = [
        TimelineNode(year=year, label=paper.title[:60], paper=_evidence(paper))
        for year, paper in sorted(by_year.items())
    ]

    return ExploreResult(
        task_id=task_id,
        query=direction,
        terms=query.terms,
        stats={"stages": stages},
        topics=topics,
        timeline=timeline,
        trend=trend,
        papers=briefs,
    )


def _label_at(labels: np.ndarray | None, index: int) -> int | None:
    if labels is None or index >= len(labels):
        return None
    value = int(labels[index])
    return value if value >= 0 else None


def _coord(projection: np.ndarray | None, index: int, axis: int) -> float | None:
    if projection is None or index >= len(projection) or axis >= projection.shape[1]:
        return None
    return round(float(projection[index][axis]), 4)


def new_task_id() -> str:
    return str(uuid.uuid4())
