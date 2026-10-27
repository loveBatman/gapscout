"""三源连通性与检索管道自检。

用途：
1. 验证 arXiv / OpenAlex / Semantic Scholar 三个数据源是否可用
2. 验证三级去重与质量过滤的实际效果（打印各阶段计数）
3. 产出真实的年份分布，用于判断领域是否适合做空白识别

用法：
    python scripts/check_sources.py "multimodal large language model inference"
    python scripts/check_sources.py "retrieval augmented generation"
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.pipeline.filter import quality_filter, year_trend  # noqa: E402
from app.pipeline.normalize import dedup_papers  # noqa: E402
from app.schemas.paper import Query  # noqa: E402
from app.sources.registry import SourceRegistry  # noqa: E402


async def run(direction: str) -> None:
    settings = get_settings()
    query = Query(raw=direction, year_from=settings.min_year)
    registry = SourceRegistry()

    print("=" * 72)
    print(f"方向: {direction}")
    print(f"数据源: {registry.names}")
    print("=" * 72)

    started = time.monotonic()
    counters: dict[str, int] = {}

    async def on_source_done(name: str, count: int) -> None:
        counters[name] = count
        print(f"  [完成] {name:<10} {count:>4} 篇")

    papers, stats = await registry.search_all(
        query,
        settings.default_search_limit_per_source,
        on_source_done=on_source_done,
    )

    print(f"\n原始召回: {len(papers)} 篇 | 各源: {counters} | 耗时 {stats.elapsed_seconds}s")
    for error in stats.errors:
        print(f"  [错误] {error}")

    deduped, report = dedup_papers(papers)
    print(f"去重结果: {report.as_dict()}")

    filtered, dropped = quality_filter(deduped, query)
    print(f"质量过滤: 保留 {len(filtered)} 篇，丢弃 {dropped} 篇")

    print("\n年份分布:")
    for item in year_trend(filtered):
        bar = "#" * min(60, item["count"])
        print(f"  {item['year']}  {item['count']:>4}  {bar}")

    print("\n质量分 Top 8:")
    for paper in filtered[:8]:
        citations = paper.citation_count if paper.citation_count is not None else "N/A"
        print(f"  - [{paper.source:<8}] {paper.year} | 引用 {citations:>5} | {paper.title[:66]}")
        print(f"      {paper.web_url()}")

    coverage = sum(1 for p in filtered if p.html_url) / len(filtered) if filtered else 0
    print(f"\nHTML 全文可尝试获取比例: {coverage:.0%}")
    print(f"总耗时: {round(time.monotonic() - started, 1)}s")

    await registry.aclose()


if __name__ == "__main__":
    argument = sys.argv[1] if len(sys.argv) > 1 else "multimodal large language model inference"
    asyncio.run(run(argument))
