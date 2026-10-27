"""M5 综述生成链路自检。

用法：
    python scripts/check_review.py "retrieval augmented generation"

除链路可用性外，本脚本还会校验增量事件（partial）的结构契约。
必要性：增量数据由前端按事件类型分流后**直接渲染**，若同一事件类型下混推异构载荷，
渲染层读到缺失字段即抛错——综述页曾因 outline 与 section 共用事件类型而整页白屏。
把契约固化成可自动检查的断言，能让这类问题在脚本阶段暴露。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows 控制台默认 GBK，输出对勾一类符号会抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.services.event_bus import bus  # noqa: E402
from app.services.review_service import run_review  # noqa: E402

TASK_ID = "local-review-test"

# 事件类型 -> 必须存在的字符串字段
PARTIAL_CONTRACT: dict[str, tuple[str, ...]] = {
    "outline": ("titles",),
    "section": ("title", "content"),
}


async def _drain_events() -> list[tuple[str, dict]]:
    """取出本次任务推送的全部事件。脚本不消费 SSE，事件仍留在队列中。"""
    channel = bus.get(TASK_ID)
    if channel is None:
        return []
    events: list[tuple[str, dict]] = []
    while not channel.queue.empty():
        events.append(channel.queue.get_nowait())
    return events


def _check_partial_contract(events: list[tuple[str, dict]]) -> list[str]:
    """校验增量事件的结构契约，返回问题清单（为空表示通过）。"""
    problems: list[str] = []
    counts: dict[str, int] = {}

    for event_type, payload in events:
        if event_type != "partial":
            continue
        kind = str(payload.get("type"))
        data = payload.get("payload")
        counts[kind] = counts.get(kind, 0) + 1

        if kind not in PARTIAL_CONTRACT:
            continue
        if not isinstance(data, dict):
            problems.append(f"partial({kind}) 的载荷不是对象")
            continue
        for field in PARTIAL_CONTRACT[kind]:
            value = data.get(field)
            if field == "titles":
                if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                    problems.append(f"partial(outline) 的 {field} 应为字符串数组")
            elif not isinstance(value, str):
                problems.append(f"partial(section) 缺少字符串字段 {field}")

    summary = " | ".join(f"{k} {v} 个" for k, v in sorted(counts.items()))
    print(f"\n增量事件: {summary or '无'}")
    return problems


async def main(direction: str) -> None:
    bus.create(TASK_ID)
    result = await run_review(TASK_ID, direction)

    print("=" * 78)
    print(f"综述题目: {result.title}")
    print("=" * 78)
    print(f"生成模式: {result.stats.get('generation_mode')} | "
          f"参考文献 {result.stats.get('reference_count')} 篇 | "
          f"主题 {result.stats.get('topics')} 个 | "
          f"耗时 {result.stats.get('elapsed_seconds')}s")

    verification = result.verification
    print(f"\n引用校验: 总句数 {verification.get('total_sentences')} | "
          f"带引用 {verification.get('cited_sentences')} | "
          f"已核查 {verification.get('checked')} | "
          f"通过 {verification.get('passed')} | "
          f"未通过 {verification.get('failed')}")
    print(f"通过率 {verification.get('pass_rate')} | "
          f"语义校验跳过: {verification.get('semantic_check_skipped')}")
    if verification.get("invalid_citations"):
        print(f"无效引用编号: {verification['invalid_citations']}")
    for item in (verification.get("missing_citation") or [])[:3]:
        print(f"  缺引用: {item['text'][:90]}")

    events = await _drain_events()
    problems = _check_partial_contract(events)
    if problems:
        print("[失败] 增量事件结构不符合契约:")
        for item in problems:
            print(f"  - {item}")
    else:
        print("  [通过] 增量事件结构全部符合契约")

    print("\n" + "-" * 78)
    for index, section in enumerate(result.sections, start=1):
        print(f"\n【第 {index} 节】{section.title}  （模式 {section.mode}）")
        print(section.content[:700])
        if len(section.content) > 700:
            print("    ……")

    print("\n" + "-" * 78)
    print("参考文献（前 5 条）:")
    for item in result.references[:5]:
        print(f"  [{item['index']}] {item['year']} | {item['title'][:64]}")
        print(f"       {item['url'][:94]}")

    print("\nBibTeX 片段:")
    print("\n".join(result.bibtex.splitlines()[:12]))


if __name__ == "__main__":
    argument = sys.argv[1] if len(sys.argv) > 1 else "retrieval augmented generation"
    asyncio.run(main(argument))
