"""选题可行性评估服务（M3）。

流程：想法解析 -> 定向检索 -> 语义相似度分布 -> 新颖性评估
      -> 竞争态势与资源分析 -> LLM 差异点分析 -> 开题决策报告

与 M1/M2 的关系：复用同一套检索与嵌入组件，但目标不同——
M1 回答"这个领域有什么"，M2 回答"哪里没人做"，
M3 回答"我想到的这个点，别人做过没有、能不能做"。
"""

import time
from collections import Counter
from datetime import datetime

import numpy as np

from app.agents.feasibility_agent import assess_novelty, enrich_report, parse_idea
from app.agents.llm import LLMClient
from app.common.text import extract_keywords
from app.config import get_settings
from app.pipeline.embed import Embedder
from app.pipeline.filter import quality_filter, year_trend
from app.pipeline.normalize import dedup_papers
from app.schemas.analysis import FeasibilityResult, SimilarWork
from app.schemas.paper import Paper, Query
from app.services.event_bus import bus
from app.sources.registry import SourceRegistry

SIMILAR_WORK_LIMIT = 20
ANALYSIS_POOL = 60


async def run_feasibility(task_id: str, idea: str) -> FeasibilityResult:
    started = time.monotonic()
    settings = get_settings()
    llm = LLMClient()
    current_year = datetime.now().year

    # ---------- 1. 想法解析 ----------
    await bus.progress(task_id, "understanding", "解析研究想法", 6)
    parsed = await parse_idea(idea, llm)
    await bus.partial(task_id, "terms", {"parsed": parsed})

    # ---------- 2. 定向检索 ----------
    await bus.progress(task_id, "retrieving", "检索相关文献", 14)
    # 中文想法无法直接检索英文学术库：
    # 有 LLM 时用语义翻译的术语，否则走领域术语映射（app/common/zh_terms.py）
    terms = parsed.get("english_terms") or extract_keywords(idea, limit=5)
    # raw 保留用户的原始想法：它被用作检索缓存的键，必须是稳定输入，
    # 而 terms 由大模型生成，同一想法两次可能得到不同术语。
    query = Query(raw=idea, terms=terms, year_from=settings.min_year)

    registry = SourceRegistry()
    try:
        papers, search_stats = await registry.search_all(
            query, settings.default_search_limit_per_source
        )
        deduped, dedup_report = dedup_papers(papers)
        filtered, filter_dropped = quality_filter(deduped, query)
        await bus.progress(
            task_id, "retrieving", f"获取 {len(filtered)} 篇候选对比文献", 34
        )

        if not filtered:
            return FeasibilityResult(
                task_id=task_id,
                idea=idea,
                parsed=parsed,
                novelty_level="unknown",
                novelty_basis="未检索到相关文献，请调整描述或补充英文关键词后重试",
                stats={"message": "检索结果为空"},
            )

        # ---------- 3. 语义相似度 ----------
        await bus.progress(task_id, "embedding", "计算与已有工作的语义相似度", 46)
        embedder = Embedder()
        embedding = await embedder.embed_papers(filtered)
        # 关键：用英文命题描述而非中文原文生成想法向量。
        # 中途踩过的两个坑：
        #   1. 直接嵌入中文原文 —— 默认嵌入模型是英文模型，跨语言相似度被系统性压低
        #   2. 用检索术语拼接 —— 构成循环论证，召回结果与 probe 必然高相似（均值 0.81）
        # 正确做法是让 LLM 生成一句完整的英文命题（含方法、任务、场景），
        # 降级时用术语拼接但不给出评级（见 assess_novelty 的 probe_reliable 参数）
        english_probe = parsed.get("english_probe")
        probe_text = english_probe or (" ".join(terms[:5]) if terms else idea)
        idea_vector = await embedder.embed_one(probe_text)
        similarities = embedding.vectors @ idea_vector
        order = np.argsort(-similarities)
        pool = order[:ANALYSIS_POOL]

        similar_works = [
            SimilarWork(
                uid=filtered[index].uid,
                title=filtered[index].title,
                year=filtered[index].year,
                venue=filtered[index].display_venue,
                url=filtered[index].web_url(),
                similarity=round(float(similarities[index]), 4),
            )
            for index in order[:SIMILAR_WORK_LIMIT]
        ]

        # ---------- 4. 新颖性评估 ----------
        await bus.progress(task_id, "analyzing", "评估新颖性与撞车风险", 64)
        assessment = assess_novelty(
            [float(similarities[index]) for index in pool],
            [filtered[index].year for index in pool],
            current_year,
            probe_reliable=bool(english_probe),
        )

        competition = _competition(filtered, pool, similarities, current_year)
        resources = _resources(filtered, order[:10])

        # ---------- 5. 差异点与建议 ----------
        await bus.progress(task_id, "generating", "分析差异点并生成建议", 82)
        enrichment = await enrich_report(idea, similar_works[:5], competition, llm)
        for index, hint in enumerate(enrichment["difference_hints"][: len(similar_works)]):
            similar_works[index].difference_hint = hint

        await bus.progress(task_id, "generating", "开题决策报告已生成", 96)

        return FeasibilityResult(
            task_id=task_id,
            idea=idea,
            parsed=parsed,
            novelty_score=assessment.score,
            novelty_level=assessment.level,
            novelty_basis=assessment.basis,
            similar_works=similar_works,
            competition=competition,
            resources=resources,
            risks=enrichment["risks"],
            suggestions=enrichment["suggestions"],
            verdict=enrichment["verdict"] or _default_verdict(assessment.level),
            stats={
                "per_source": search_stats.per_source,
                "search_errors": search_stats.errors,
                "dedup": dedup_report.as_dict(),
                "filter_dropped": filter_dropped,
                "embed_backend": embedding.backend,
                "pool_size": len(pool),
                "probe_text": probe_text,
                "probe_source": "llm" if english_probe else "degraded",
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "llm": llm.usage.as_dict(),
                "novelty_details": assessment.details,
            },
        )
    finally:
        await registry.aclose()


def _competition(
    papers: list[Paper],
    pool: np.ndarray,
    similarities: np.ndarray,
    current_year: int,
) -> dict:
    """竞争态势：规模、近期活跃度、主要发表渠道与活跃团队。"""
    subset = [papers[int(index)] for index in pool]
    years = [paper.year for paper in subset if paper.year]
    recent = sum(1 for year in years if year >= current_year - 1)

    venue_counter: Counter = Counter(
        paper.venue for paper in subset if paper.venue
    )
    author_counter: Counter = Counter()
    for paper in subset:
        for author in paper.authors[:3]:
            if author:
                author_counter[author] += 1

    similarity_values = [float(similarities[int(index)]) for index in pool]
    return {
        "total": len(papers),
        "analyzed": len(subset),
        "recent_works": recent,
        "year_from": min(years) if years else None,
        "year_to": max(years) if years else None,
        "year_trend": year_trend(subset),
        "top_venues": [
            {"name": name, "count": count} for name, count in venue_counter.most_common(5)
        ],
        "active_authors": [
            {"name": name, "count": count} for name, count in author_counter.most_common(5)
        ],
        "mean_similarity": round(float(np.mean(similarity_values)), 4)
        if similarity_values
        else 0.0,
    }


def _resources(papers: list[Paper], indices: np.ndarray) -> dict:
    """资源评估：从最相关论文中识别可复用的公开资源。

    用关键词匹配而非让模型推测：数据集与代码是否公开是客观事实，
    匹配不到就是找不到，比模型给出似是而非的答案更可靠。
    """
    datasets: list[str] = []
    code: list[str] = []
    benchmarks: list[str] = []

    for index in indices:
        paper = papers[int(index)]
        text = f"{paper.title} {paper.abstract_or_tldr or ''}".lower()
        if "dataset" in text or "corpus" in text:
            datasets.append(paper.title[:90])
        if "github" in text or "open-source" in text or "code is available" in text or "open source" in text:
            code.append(paper.title[:90])
        if "benchmark" in text:
            benchmarks.append(paper.title[:90])

    return {
        "datasets_found": datasets[:5],
        "open_source_found": code[:5],
        "benchmarks_found": benchmarks[:5],
        "note": "以上为依据摘要关键词识别的资源线索，建议人工核实可得性。",
    }


def _default_verdict(level: str) -> str:
    if level == "high":
        return "未发现显著相似工作，选题新颖性较高，建议进一步确认数据集与评测基准是否可得。"
    if level == "medium":
        return "存在部分相似工作，建议收窄研究范围或更换切入角度以形成明确差异。"
    if level == "low":
        return "已有较多高度相似工作，直接推进的撞车风险较高，建议重新设计问题设定。"
    return "检索结果不足以给出可靠判断，建议补充英文关键词后重新评估。"
