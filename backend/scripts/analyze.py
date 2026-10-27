"""M1 领域探索链路完整自检：检索 -> 去重 -> 过滤 -> 嵌入 -> 聚类。

用途：在没有前端与数据库的情况下，验证核心分析链路是否成立，
并直观判断聚类质量（主题是否可解释、代表论文是否切题）。

用法：
    python scripts/analyze.py "multimodal large language model inference"
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.pipeline.cluster import cluster_topics, top_papers_per_cluster  # noqa: E402
from app.pipeline.embed import Embedder  # noqa: E402
from app.pipeline.filter import quality_filter, trend_slope, year_trend  # noqa: E402
from app.pipeline.normalize import dedup_papers  # noqa: E402
from app.schemas.paper import Query  # noqa: E402
from app.sources.registry import SourceRegistry  # noqa: E402


async def run(direction: str) -> None:
    settings = get_settings()
    query = Query(raw=direction, year_from=settings.min_year)
    registry = SourceRegistry()

    print("=" * 78)
    print(f"方向: {direction}")
    print("=" * 78)

    started = time.monotonic()
    papers, stats = await registry.search_all(
        query, settings.default_search_limit_per_source
    )
    print(f"[1] 检索   {len(papers):>4} 篇  {stats.per_source}  {stats.elapsed_seconds}s")

    deduped, report = dedup_papers(papers)
    print(f"[2] 去重   {len(deduped):>4} 篇  移除 {report.removed}（标题 {report.title_hits} / 键 {report.key_hits} / 模糊 {report.fuzzy_hits}）")

    filtered, dropped = quality_filter(deduped, query)
    print(f"[3] 过滤   {len(filtered):>4} 篇  丢弃 {dropped}")

    embedder = Embedder()
    embed_started = time.monotonic()
    result = await embedder.embed_papers(filtered)
    print(
        f"[4] 嵌入   {result.count:>4} 条  后端 {result.backend}  "
        f"维度 {result.dim}  {round(time.monotonic() - embed_started, 1)}s"
    )

    outcome = cluster_topics(result.vectors)
    print(
        f"[5] 聚类   {outcome.n_clusters} 个主题  噪声 {outcome.noise_count}  "
        f"降维 {outcome.reducer}  合并 {outcome.merged_count}  "
        f"回收 {outcome.reassigned_count}  {outcome.clusterer}"
    )

    trend = year_trend(filtered)
    print(f"[6] 趋势   斜率 {trend_slope(trend)}  年份 {trend[0]['year'] if trend else '-'}~{trend[-1]['year'] if trend else '-'}")

    print("\n" + "-" * 78)
    print("主题概览（按规模排序，展示每个主题的代表论文）")
    print("-" * 78)

    representatives = top_papers_per_cluster(result.vectors, outcome.labels, top_k=3)
    for label, size in outcome.sizes().items():
        if label < 0:
            print(f"\n[噪声] {size} 篇（未归入任何主题）")
            continue
        centroid = result.vectors[outcome.labels == label].mean(axis=0)
        norms = np.linalg.norm(result.vectors, axis=1) * np.linalg.norm(centroid)
        similarities = np.divide(
            result.vectors @ centroid, norms, out=np.zeros(len(filtered)), where=norms > 0
        )
        order = np.argsort(-similarities)
        years = [filtered[i].year for i in order[:size] if filtered[i].year]
        mean_similarity = float(similarities[order[:size]].mean())

        print(f"\n--- 主题 {label} | {size} 篇 | 年份中位 {int(np.median(years)) if years else '-'} | 内聚度 {mean_similarity:.3f}")
        for index in representatives.get(label, []):
            paper = filtered[index]
            citations = paper.citation_count if paper.citation_count is not None else "-"
            print(f"    · {paper.year} | 引用 {citations} | {paper.title[:64]}")
            print(f"      {paper.web_url()[:96]}")

    await registry.aclose()
    print(f"\n总耗时 {round(time.monotonic() - started, 1)}s")


if __name__ == "__main__":
    argument = (
        sys.argv[1] if len(sys.argv) > 1 else "multimodal large language model inference"
    )
    asyncio.run(run(argument))
