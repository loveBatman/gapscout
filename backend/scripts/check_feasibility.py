"""M3 选题可行性评估链路自检。

用法：
    python scripts/check_feasibility.py
    python scripts/check_feasibility.py "用扩散模型做多模态大模型的推理加速"
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.event_bus import bus  # noqa: E402
from app.services.feasibility_service import run_feasibility  # noqa: E402

TASK_ID = "local-feasibility-test"
DEFAULT_IDEA = "用扩散模型做多模态大语言模型的高效推理加速"


async def main(idea: str) -> None:
    bus.create(TASK_ID)
    result = await run_feasibility(TASK_ID, idea)

    print("=" * 78)
    print(f"想法: {idea}")
    print("=" * 78)
    print(f"解析结果: {result.parsed}")
    print(f"新颖性评分: {result.novelty_score} ({result.novelty_level})")
    print(f"判定依据: {result.novelty_basis}")

    print("\n最相似的已有工作:")
    for work in result.similar_works[:8]:
        print(f"  [{work.similarity:.3f}] {work.year} | {work.title[:68]}")
        if work.difference_hint:
            print(f"        差异: {work.difference_hint}")
        print(f"        {work.url[:94]}")

    competition = result.competition
    print(
        f"\n竞争态势: 相关文献 {competition.get('total')} 篇 | "
        f"近一年 {competition.get('recent_works')} 篇 | "
        f"平均相似度 {competition.get('mean_similarity')}"
    )
    venues = [item["name"] for item in (competition.get("top_venues") or [])[:3]]
    print(f"主要发表渠道: {venues}")
    authors = [item["name"] for item in (competition.get("active_authors") or [])[:3]]
    print(f"活跃作者: {authors}")

    resources = result.resources
    print(
        f"\n资源线索: 数据集 {len(resources.get('datasets_found') or [])} 项 | "
        f"开源 {len(resources.get('open_source_found') or [])} 项 | "
        f"评测基准 {len(resources.get('benchmarks_found') or [])} 项"
    )
    for title in (resources.get("open_source_found") or [])[:3]:
        print(f"  - {title}")

    print("\n风险提示:")
    for risk in result.risks:
        print(f"  - {risk}")
    print("切入建议:")
    for suggestion in result.suggestions:
        print(f"  - {suggestion}")
    print(f"\n结论: {result.verdict}")


if __name__ == "__main__":
    argument = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IDEA
    asyncio.run(main(argument))
