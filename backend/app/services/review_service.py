"""综述生成服务（M5）。

链路：语料构建 -> 大纲规划 -> 分节撰写 -> 逐句引用校验 -> 导出 BibTeX

与普通"让模型写综述"的区别：正文严格基于检索到的论文摘要撰写，
生成后逐句核查引用是否成立，并把未通过校验的句子暴露给用户。
未配置 LLM 时退化为结构化文献梳理，不生成自由行文。
"""

import time
from collections import defaultdict

import numpy as np

from app.agents.llm import LLMClient
from app.agents.review_agent import (
    build_bibtex,
    build_citation_json,
    plan_outline,
    write_section,
)
from app.agents.topic_naming import TopicDraft, name_topics
from app.agents.verify import verify_review
from app.config import get_settings
from app.pipeline.cluster import cluster_topics
from app.pipeline.embed import Embedder
from app.pipeline.filter import filter_by_relevance, quality_filter, trend_slope, year_trend
from app.pipeline.normalize import dedup_papers
from app.pipeline.topic_naming import ctfidf_keywords
from app.schemas.analysis import ReviewResult, ReviewSection
from app.schemas.paper import Paper
from app.services.event_bus import bus
from app.services.explore_service import understand_query
from app.sources.registry import SourceRegistry

# 综述引用的文献上限：过多会让每节取材分散、引用编号爆炸
MAX_REFERENCE_PAPERS = 60


async def run_review(task_id: str, direction: str) -> ReviewResult:
    started = time.monotonic()
    settings = get_settings()
    llm = LLMClient()
    stages: dict[str, float] = {}

    # ---------- 语料构建 ----------
    await bus.progress(task_id, "understanding", "解析研究方向", 4)
    query = await understand_query(direction, llm)

    await bus.progress(task_id, "retrieving", "检索相关文献", 10)
    mark = time.monotonic()
    registry = SourceRegistry()
    try:
        papers, search_stats = await registry.search_all(
            query, settings.default_search_limit_per_source
        )
        deduped, dedup_report = dedup_papers(papers)
        filtered, filter_dropped = quality_filter(deduped, query)

        if not filtered:
            return ReviewResult(
                task_id=task_id,
                direction=direction,
                title=f"{direction} 研究综述",
                stats={"message": "未检索到满足条件的文献", "stages": stages},
            )

        await bus.progress(task_id, "embedding", f"向量化 {len(filtered)} 篇文献", 22)
        embedder = Embedder()
        embedding = await embedder.embed_papers(filtered)
        probe = " ".join(query.terms[:5]) if query.terms else direction
        query_vector = await embedder.embed_one(probe)
        similarities = embedding.vectors @ query_vector
        filtered, indices, relevance_dropped = filter_by_relevance(filtered, similarities)
        vectors = embedding.vectors[indices]
        stages["corpus"] = round(time.monotonic() - mark, 2)

        await bus.progress(task_id, "clustering", "主题聚类", 30)
        outcome = cluster_topics(vectors)
        documents = [Embedder.paper_text(paper) for paper in filtered]
        keywords_map = ctfidf_keywords(documents, outcome.labels)
        topics = await name_topics(
            _build_drafts(outcome, filtered, keywords_map), llm, direction=direction
        )
        topic_dicts = [topic.model_dump() for topic in topics]

        # 参考文献池：优先保留高引用与近三年工作
        reference_papers = filtered[:MAX_REFERENCE_PAPERS]

        # ---------- 大纲规划 ----------
        await bus.progress(task_id, "analyzing", "规划综述大纲", 44)
        mark = time.monotonic()
        outline = await plan_outline(reference_papers, topic_dicts, llm, direction=direction)
        stages["outline"] = round(time.monotonic() - mark, 2)
        # 大纲是「章节标题列表」，与逐节正文是两种不同的消费品：前者用于在生成早期
        # 渲染章节骨架，后者用于渲染正文。必须使用独立事件类型——曾因两者共用
        # "section" 类型，前端按类型过滤时把大纲混进正文章节数组，渲染到缺失字段即
        # 抛错，导致综述页整页白屏。
        await bus.partial(task_id, "outline", {"titles": [s.title for s in outline.sections]})

        # ---------- 分节撰写 ----------
        groups = _group_by_topic(reference_papers, filtered, outcome, indices)
        sections: list[ReviewSection] = []
        mark = time.monotonic()
        for position, section_draft in enumerate(outline.sections):
            percent = 50 + int(30 * position / max(1, len(outline.sections)))
            await bus.progress(
                task_id, "generating", f"撰写第 {position + 1}/{len(outline.sections)} 节：{section_draft.title}", percent
            )
            material = groups[position % len(groups)]
            payload = await write_section(section_draft, material, llm)
            result_section = ReviewSection(
                title=payload["title"],
                content=payload["content"],
                citations=payload["citations"],
                mode=payload["mode"],
            )
            sections.append(result_section)
            await bus.partial(task_id, "section", result_section.model_dump())
        stages["writing"] = round(time.monotonic() - mark, 2)

        # ---------- 引用校验 ----------
        await bus.progress(task_id, "verifying", "逐句校验引用一致性", 84)
        mark = time.monotonic()
        report = await verify_review(
            [{"title": section.title, "content": section.content} for section in sections],
            reference_papers,
            llm,
        )
        stages["verification"] = round(time.monotonic() - mark, 2)
        await bus.progress(
            task_id,
            "verifying",
            f"引用校验通过率 {report.pass_rate:.0%}（{report.passed}/{report.checked}）",
            92,
        )

        # ---------- 汇总 ----------
        bibtex = build_bibtex(reference_papers)
        references = _parse_references(build_citation_json(reference_papers))

        return ReviewResult(
            task_id=task_id,
            direction=direction,
            title=outline.title,
            sections=sections,
            references=references,
            bibtex=bibtex,
            verification=report.as_dict(),
            stats={
                "stages": stages,
                "per_source": search_stats.per_source,
                "search_errors": search_stats.errors,
                "dedup": dedup_report.as_dict(),
                "filter_dropped": filter_dropped,
                "relevance_dropped": relevance_dropped,
                "embed_backend": embedding.backend,
                "topics": len(topic_dicts),
                "reference_count": len(reference_papers),
                "generation_mode": "generated" if llm.available else "structured",
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "llm": llm.usage.as_dict(),
            },
        )
    finally:
        await registry.aclose()


def _group_by_topic(
    reference_papers: list[Paper],
    filtered: list[Paper],
    outcome,
    indices: list[int],
) -> list[list[tuple[int, Paper]]]:
    """按主题把参考文献分组，让每一节都能取到对应主题的素材。

    每个元素是 (全局参考文献序号, 论文)，序号从 1 开始。
    必要性：正文里的 [n] 与逐句引用校验必须共用同一套编号体系，
    否则校验会把断言对到错误的论文上（详见 write_section 的说明）。
    """
    label_by_uid = {
        filtered[indices[position]].uid: int(outcome.labels[position])
        for position in range(len(indices))
    }
    grouped: dict[int, list[tuple[int, Paper]]] = defaultdict(list)
    for number, paper in enumerate(reference_papers, start=1):
        label = label_by_uid.get(paper.uid, -1)
        grouped[label].append((number, paper))

    groups = [grouped[label] for label in sorted(grouped) if label >= 0 and grouped[label]]
    if groups:
        return groups
    # 全部论文都未归入任何主题时，退化为单组，保证始终有素材可用
    return [[(number, paper) for number, paper in enumerate(reference_papers, start=1)]]


def _build_drafts(
    outcome, papers: list[Paper], keywords_map: dict
) -> list[TopicDraft]:
    from app.pipeline.cluster import top_papers_per_cluster

    representatives = top_papers_per_cluster(outcome.reduced, outcome.labels, top_k=4)
    drafts: list[TopicDraft] = []
    for cluster_id, size in outcome.sizes().items():
        if cluster_id < 0:
            continue
        member_indices = np.where(outcome.labels == cluster_id)[0]
        years = [papers[i].year for i in member_indices if papers[i].year]
        keywords = keywords_map.get(cluster_id)
        drafts.append(
            TopicDraft(
                cluster_id=cluster_id,
                keywords=keywords.keywords if keywords else [],
                size=size,
                titles=[papers[i].title for i in representatives.get(cluster_id, [])],
                year_from=min(years) if years else None,
                year_to=max(years) if years else None,
                trend_slope=trend_slope(year_trend([papers[i] for i in member_indices])),
            )
        )
    return drafts


def _parse_references(raw: str) -> list[dict]:
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
