"""M2 研究空白识别链路自检。

直接调用服务层，实时打印各阶段进度与三路信号的实际产出，
用于在没有前端的情况下验证算法的有效性。

用法：
    python scripts/check_gaps.py "multimodal large language model inference"
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.event_bus import bus  # noqa: E402
from app.services.gap_service import run_gap_analysis  # noqa: E402

TASK_ID = "local-gap-test"


async def consume() -> None:
    channel = bus.get(TASK_ID)
    if channel is None:
        return
    while True:
        try:
            event_type, payload = await asyncio.wait_for(channel.queue.get(), timeout=600)
        except asyncio.TimeoutError:
            return
        if event_type == "progress":
            print(f"    [{payload['percent']:>3}%] {payload['stage']:<13} {payload['message']}")
        elif event_type in ("done", "failed"):
            return


async def main(direction: str) -> None:
    bus.create(TASK_ID)
    consumer = asyncio.create_task(consume())

    started = time.monotonic()
    result = await run_gap_analysis(TASK_ID, direction)
    await asyncio.sleep(0.3)
    consumer.cancel()

    stats = result.stats
    print("\n" + "=" * 78)
    print(f"方向: {direction}")
    print("=" * 78)
    print(f"语料规模: {stats.get('corpus_size')} 篇 | 总耗时: {stats.get('elapsed_seconds')}s")
    print(f"全文覆盖: {stats.get('fulltext_levels')}")
    print(f"候选 -> 确认: {stats.get('candidates')} -> {len(result.gaps)}")

    signals = result.signals
    fw = signals.get("future_work", {})
    matrix = signals.get("matrix", {})
    graph = signals.get("graph", {})

    print("\n--- 信号 A：未来工作聚合 ---")
    print(f"  抓取论文 {fw.get('papers_scanned')} 篇 | 陈述 {fw.get('statements_total')} 条 "
          f"| 覆盖率 {fw.get('extraction_coverage')}")
    for cluster in (fw.get("clusters") or [])[:4]:
        print(f"  [{cluster['level']}] {cluster['source_count']} 篇提及 | "
              f"覆盖度 {cluster['coverage']} | 空白强度 {cluster['gap_strength']}")
        print(f"      {cluster['label'][:110]}")
        nearest = cluster.get("nearest_paper") or {}
        if nearest:
            print(f"      最接近的已有工作: {str(nearest.get('title'))[:80]}")

    print("\n--- 信号 B：方法-任务矩阵 ---")
    print(f"  抽取覆盖率 {matrix.get('extraction_coverage')} | "
          f"任务 {len(matrix.get('tasks') or [])} 个 | 方法 {len(matrix.get('methods') or [])} 个")
    for cell in (matrix.get("gap_cells") or [])[:5]:
        print(f"  空格: {cell['task']} × {cell['method']} | "
              f"邻域活跃度 {cell['neighbor_score']}")

    print("\n--- 信号 C：引用图谱 ---")
    print(f"  节点 {graph.get('n_nodes')} | 边 {graph.get('n_edges')} | "
          f"社区 {graph.get('n_communities')} | 引用覆盖率 {graph.get('reference_coverage')}")
    for hole in (graph.get("structural_holes") or [])[:3]:
        print(f"  结构洞: 社区 {hole['community_a']}({hole['size_a']}) ↔ "
              f"社区 {hole['community_b']}({hole['size_b']}) | 边 {hole['edges']}")
    for item in (graph.get("emerging_communities") or [])[:3]:
        print(f"  新兴簇: 社区 {item['community']} | 规模 {item['size']} | 斜率 {item['slope']}")

    print("\n--- 机会点卡片 ---")
    for index, gap in enumerate(result.gaps, start=1):
        print(f"\n  [{index}] {gap.title}")
        print(f"      信号: {gap.signals} | 新颖度 {gap.novelty} | 置信度 {gap.confidence}")
        print(f"      {gap.description[:200]}")
        for evidence in gap.evidence[:2]:
            print(f"      证据 · {evidence.year} {evidence.title[:70]}")
            print(f"             {evidence.url[:96]}")

    print(f"\n真实总耗时: {round(time.monotonic() - started, 1)}s")


if __name__ == "__main__":
    argument = (
        sys.argv[1] if len(sys.argv) > 1 else "multimodal large language model inference"
    )
    asyncio.run(main(argument))
