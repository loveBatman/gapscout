"""研究空白识别服务（M2）：三路信号交叉验证。

链路：
    语料构建（检索 -> 去重 -> 过滤 -> 嵌入 -> 聚类）
    -> 引用关系抓取
    -> 信号 A：未来工作陈述聚合 + 覆盖度判定
    -> 信号 B：方法-任务矩阵空格
    -> 信号 C：引用图谱结构洞 / 新兴簇 / 转折点
    -> 融合 + LLM 价值批判
    -> 机会点卡片

三路信号各自独立产出候选，再交叉验证。单独依赖任何一路都容易得出
不可靠的结论：只靠 A 会漏掉尚无人提及的迁移机会，只靠 B 会误判
"没价值所以没人做"的组合，只靠 C 则过于抽象无法落地。
"""

import asyncio
import time

import numpy as np

from app.agents.gap_agent import build_candidates, build_gap_cards
from app.agents.llm import LLMClient
from app.agents.topic_naming import TopicDraft, name_topics
from app.config import get_settings
from app.pipeline.cluster import ClusterOutcome, cluster_topics
from app.pipeline.embed import Embedder
from app.pipeline.filter import filter_by_relevance, quality_filter, trend_slope, year_trend
from app.pipeline.future_work import analyze_future_work
from app.pipeline.graph import analyze_graph
from app.pipeline.method_task import analyze_matrix
from app.pipeline.normalize import dedup_papers
from app.pipeline.topic_naming import ClusterKeywords, ctfidf_keywords
from app.schemas.analysis import GapResult, MatrixView
from app.schemas.paper import Paper, Query
from app.services.event_bus import bus
from app.services.explore_service import understand_query
from app.sources.registry import SourceRegistry

FULLTEXT_PAPER_LIMIT = 40
REFERENCE_PAPER_LIMIT = 100


async def run_gap_analysis(task_id: str, raw_direction: str) -> GapResult:
    started = time.monotonic()
    settings = get_settings()
    llm = LLMClient()
    stages: dict[str, float] = {}

    # ---------- 语料构建 ----------
    await bus.progress(task_id, "understanding", "解析研究方向", 3)
    mark = time.monotonic()
    query = await understand_query(raw_direction, llm)
    stages["understanding"] = round(time.monotonic() - mark, 2)

    await bus.progress(task_id, "retrieving", "并发检索真实文献", 7)
    mark = time.monotonic()

    registry = SourceRegistry()
    try:
        papers, search_stats = await registry.search_all(
            query, settings.default_search_limit_per_source
        )
        deduped, dedup_report = dedup_papers(papers)
        filtered, filter_dropped = quality_filter(deduped, query)
        stages["retrieval"] = round(time.monotonic() - mark, 2)

        if not filtered:
            return _empty_result(task_id, raw_direction, query, stages)

        # ---------- 嵌入与相关性闸门 ----------
        await bus.progress(task_id, "embedding", f"向量化 {len(filtered)} 篇文献", 16)
        mark = time.monotonic()
        embedder = Embedder()
        embedding = await embedder.embed_papers(filtered)
        probe = f"{raw_direction} {' '.join(query.terms)}"
        query_vector = await embedder.embed_one(probe)
        similarities = embedding.vectors @ query_vector
        filtered, indices, relevance_dropped = filter_by_relevance(filtered, similarities)
        vectors = embedding.vectors[indices]
        stages["embedding"] = round(time.monotonic() - mark, 2)

        # ---------- 聚类与主题命名 ----------
        await bus.progress(task_id, "clustering", "主题聚类", 28)
        mark = time.monotonic()
        outcome = cluster_topics(vectors)
        documents = [Embedder.paper_text(paper) for paper in filtered]
        keywords_map = ctfidf_keywords(documents, outcome.labels)
        topics = await name_topics(
            _build_drafts(outcome, filtered, keywords_map), llm, direction=raw_direction
        )
        stages["clustering"] = round(time.monotonic() - mark, 2)
        await bus.progress(
            task_id, "clustering", f"识别出 {outcome.n_clusters} 个主题簇", 38
        )

        # ---------- 引用关系（信号 C 输入）与全文抓取并行 ----------
        # 两者互不依赖（引用来自 OpenAlex，全文来自 ar5iv），
        # 串行执行只会让两段网络等待简单叠加，这里改为并发。
        await bus.progress(task_id, "extracting", "并行抓取引用关系与论文全文", 42)
        openalex = registry.get("openalex")
        references_task = (
            asyncio.create_task(
                openalex.fetch_references_batch(filtered[:REFERENCE_PAPER_LIMIT])
            )
            if openalex is not None
            else None
        )

        # ---------- 信号 A ----------

        async def on_fulltext(label: str, done: int, total: int) -> None:
            percent = 50 + int(24 * done / max(1, total))
            await bus.progress(task_id, "extracting", f"{label} {done}/{total}", percent)

        mark = time.monotonic()
        future_work = await analyze_future_work(
            filtered,
            vectors,
            embedder,
            max_papers=FULLTEXT_PAPER_LIMIT,
            on_progress=on_fulltext,
        )
        stages["signal_a"] = round(time.monotonic() - mark, 2)

        # 引用抓取此时通常已完成，这里的耗时是并行之后的剩余等待时间
        mark = time.monotonic()
        if references_task is not None:
            _apply_references(filtered, await references_task)
        stages["references"] = round(time.monotonic() - mark, 2)
        await bus.progress(
            task_id,
            "analyzing",
            f"信号 A：从 {future_work.statements_total} 条陈述中聚出 "
            f"{len(future_work.clusters)} 个方向簇",
            76,
        )

        # ---------- 信号 B / C ----------
        mark = time.monotonic()
        matrix = analyze_matrix(filtered)
        # 复用语义主题作为引用图谱的社区划分（稀疏引用图下 Louvain 会完全碎片化）
        community_labels = {
            paper.citation_key: int(outcome.labels[index])
            for index, paper in enumerate(filtered)
            if int(outcome.labels[index]) >= 0
        }
        graph = analyze_graph(filtered, community_labels)
        stages["signal_bc"] = round(time.monotonic() - mark, 2)
        await bus.progress(
            task_id,
            "analyzing",
            f"信号 B：{len(matrix.gap_cells)} 个矩阵空格；"
            f"信号 C：{len(graph.structural_holes)} 个结构洞",
            82,
        )

        # ---------- 融合与批判 ----------
        await bus.progress(task_id, "criticizing", "融合三路信号并做价值批判", 86)
        mark = time.monotonic()
        candidates = build_candidates(future_work, matrix, graph, filtered)
        gaps = await build_gap_cards(
            candidates, llm, direction=raw_direction, topic_labels=[t.label for t in topics]
        )
        stages["critique"] = round(time.monotonic() - mark, 2)
        await bus.progress(
            task_id,
            "criticizing",
            f"从 {len(candidates)} 个候选中确认 {len(gaps)} 个机会点",
            94,
        )

        for gap in gaps:
            await bus.partial(task_id, "opportunity", gap.model_dump())

        return GapResult(
            task_id=task_id,
            query=raw_direction,
            terms=query.terms,
            topics=topics,
            gaps=gaps,
            signals={
                "future_work": future_work.as_dict(),
                "matrix": matrix.as_dict(),
                "graph": graph.as_dict(),
            },
            matrix=MatrixView(
                tasks=matrix.tasks,
                methods=matrix.methods,
                matrix=matrix.matrix,
                gap_cells=matrix.gap_cells,
            ),
            stats={
                "stages": stages,
                "per_source": search_stats.per_source,
                "search_errors": search_stats.errors,
                "dedup": dedup_report.as_dict(),
                "filter_dropped": filter_dropped,
                "relevance_dropped": relevance_dropped,
                "embed_backend": embedding.backend,
                "corpus_size": len(filtered),
                "fulltext_levels": future_work.fulltext_levels,
                "candidates": len(candidates),
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "llm": llm.usage.as_dict(),
            },
        )
    finally:
        await registry.aclose()


def _apply_references(papers: list[Paper], references: dict[str, list[str]]) -> None:
    for paper in papers:
        refs = references.get(paper.source_id)
        if refs:
            paper.references = refs


def _build_drafts(
    outcome: ClusterOutcome,
    papers: list[Paper],
    keywords_map: dict[int, ClusterKeywords],
) -> list[TopicDraft]:
    drafts: list[TopicDraft] = []
    from app.pipeline.cluster import top_papers_per_cluster

    representatives = top_papers_per_cluster(outcome.reduced, outcome.labels, top_k=4)
    for cluster_id, size in outcome.sizes().items():
        if cluster_id < 0:
            continue
        indices = np.where(outcome.labels == cluster_id)[0]
        years = [papers[i].year for i in indices if papers[i].year]
        cluster_trend = year_trend([papers[i] for i in indices])
        keywords = keywords_map.get(cluster_id)
        drafts.append(
            TopicDraft(
                cluster_id=cluster_id,
                keywords=keywords.keywords if keywords else [],
                size=size,
                titles=[papers[i].title for i in representatives.get(cluster_id, [])],
                year_from=min(years) if years else None,
                year_to=max(years) if years else None,
                trend_slope=trend_slope(cluster_trend),
            )
        )
    return drafts


def _empty_result(
    task_id: str, direction: str, query: Query, stages: dict[str, float]
) -> GapResult:
    return GapResult(
        task_id=task_id,
        query=direction,
        terms=query.terms,
        stats={"stages": stages, "message": "未检索到满足条件的文献"},
    )
