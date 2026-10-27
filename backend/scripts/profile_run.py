"""性能诊断：实测各阶段耗时与 LLM 消耗，定位真正的瓶颈。

为什么需要这个脚本：
    「输入新关键词很慢」是一个感受，不是数据。优化之前必须知道时间花在哪里，
    否则很容易花力气去优化一个只占 5% 的环节，而放过真正的瓶颈。

    本脚本复用链路里已有的 stats.stages 与 stats.llm 埋点，不新增任何埋点，
    因此测量结果与生产路径（前端 SSE 请求）完全一致。

观测点：
    1. 各阶段耗时及其占比，按「网络 / 嵌入 / 本地计算 / 全文抓取 / LLM」分组汇总
    2. LLM 调用次数、token 消耗、按模型分布、失败次数
    3. 首次与二次执行同一方向的差异——量化缓存收益与模型重复加载开销
    4. 嵌入模型重复初始化的独立测量（假设验证，不依赖完整链路）

用法：
    python scripts/profile_run.py                                    # 默认方向，跑 M1 + M2
    python scripts/profile_run.py --module gap                       # 只跑 M2
    python scripts/profile_run.py "retrieval augmented generation"   # 指定方向
    python scripts/profile_run.py --repeat 2                         # 每个模块跑两次
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.cluster import warmup as warmup_cluster  # noqa: E402
from app.services.event_bus import bus  # noqa: E402
from app.services.explore_service import run_explore  # noqa: E402
from app.services.gap_service import run_gap_analysis  # noqa: E402

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports"

# 阶段归类：把后端各处推送的 stage 名归到"时间花在什么性质的事情上"
STAGE_GROUPS: dict[str, set[str]] = {
    "网络检索": {"retrieving", "retrieval", "references"},
    "语义嵌入": {"embedding"},
    "本地计算": {"dedup", "filtering", "clustering", "signal_bc"},
    "全文抓取与陈述": {"signal_a"},
    "LLM 调用": {"understanding", "naming", "critique"},
}

BAR_WIDTH = 28


async def drain(task_id: str) -> None:
    """消费事件队列。

    必须消费：EventBus 的队列有上限，无人读取时事件会堆积，
    与前端真实场景（SSE 持续读取）不一致。
    """
    channel = bus.get(task_id)
    if channel is None:
        return
    while True:
        try:
            event_type, _ = await asyncio.wait_for(channel.queue.get(), timeout=900)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return
        if event_type in ("done", "failed"):
            return


async def run_module(module: str, direction: str, task_id: str) -> dict:
    """执行单个模块，返回结果与墙钟耗时。"""
    bus.create(task_id)
    consumer = asyncio.create_task(drain(task_id))
    started = time.monotonic()

    if module == "gap":
        result = await run_gap_analysis(task_id, direction)
    else:
        result = await run_explore(task_id, direction)

    wall = round(time.monotonic() - started, 2)
    await asyncio.sleep(0.2)
    consumer.cancel()
    return {"result": result, "wall": wall}


def group_of(stage: str) -> str:
    for name, keys in STAGE_GROUPS.items():
        if stage in keys:
            return name
    return "其他"


def render_stages(stages: dict, total: float) -> tuple[list[str], dict]:
    """渲染阶段耗时明细，返回（输出行, 分组汇总）。"""
    if not stages:
        return ["  （无阶段数据）"], {}

    ordered = sorted(stages.items(), key=lambda item: -item[1])
    lines: list[str] = []
    groups: dict[str, float] = {}

    for stage, seconds in ordered:
        ratio = seconds / total if total > 0 else 0.0
        filled = max(1, int(ratio * BAR_WIDTH)) if seconds > 0 else 0
        bar = "█" * filled + "·" * (BAR_WIDTH - filled)
        lines.append(f"  {stage:<14} {seconds:>7.2f}s  {bar}  {ratio * 100:>5.1f}%")
        group = group_of(stage)
        groups[group] = round(groups.get(group, 0.0) + seconds, 2)

    return lines, groups


def render_llm(llm: dict) -> list[str]:
    if not llm or not llm.get("calls"):
        return ["  （未发生 LLM 调用：可能未配置 API key，或全部走了降级路径）"]

    lines = [
        f"  调用 {llm.get('calls')} 次 | "
        f"prompt {llm.get('prompt_tokens', 0)} + completion {llm.get('completion_tokens', 0)} "
        f"= {llm.get('total_tokens', 0)} tokens",
        f"  LLM 累计耗时 {llm.get('elapsed_seconds', 0)}s | 失败 {llm.get('failures', 0)} 次",
    ]
    per_model = llm.get("per_model") or {}
    if per_model:
        detail = " | ".join(f"{name} {count} 次" for name, count in per_model.items())
        lines.append(f"  按模型分布: {detail}")
    return lines


async def measure_embedder_load() -> dict:
    """独立测量嵌入模型的重复初始化开销。

    必要性：各 service 都是 `embedder = Embedder()` 新建实例，
    模型实例挂在实例属性上，因此每个任务都会重新初始化。
    这里连续构造两次 Embedder 并各自编码，即可量化该开销——
    不依赖完整链路，结论直接可用于判断"实例复用"的收益。
    """
    from app.pipeline.embed import Embedder

    samples = [
        "Retrieval-augmented generation for knowledge-intensive NLP tasks.",
        "Efficient inference of multimodal large language models via token compression.",
        "Graph neural networks for molecular property prediction.",
    ]

    timings: list[float] = []
    backend = ""
    for _ in range(2):
        embedder = Embedder()
        started = time.monotonic()
        await embedder.embed_texts(samples)
        timings.append(round(time.monotonic() - started, 2))
        backend = embedder.backend

    return {
        "backend": backend,
        "first_run_seconds": timings[0],
        "second_run_seconds": timings[1],
        "overhead_seconds": round(timings[0] - timings[1], 2),
    }


def summarize(entry: dict) -> dict:
    """从一次运行中提取关键指标，用于跨次对比与质量校验。"""
    result = entry["result"]
    stats = result.stats or {}
    return {
        "wall_seconds": entry["wall"],
        "elapsed_seconds": stats.get("elapsed_seconds"),
        "stages": stats.get("stages") or {},
        "llm": stats.get("llm") or {},
        "per_source": stats.get("per_source") or {},
        "dedup": stats.get("dedup") or {},
        "cluster": stats.get("cluster") or {},
        "corpus_size": stats.get("corpus_size") or len(getattr(result, "papers", []) or []),
        "gap_count": len(getattr(result, "gaps", []) or []),
        "topic_count": len(getattr(result, "topics", []) or []),
    }


async def profile(module: str, direction: str, repeat: int) -> list[dict]:
    label = "M2 研究空白识别" if module == "gap" else "M1 领域探索"
    print("\n" + "=" * 78)
    print(f"{label}  |  方向: {direction}")
    print("=" * 78)

    runs: list[dict] = []
    for index in range(repeat):
        entry = await run_module(module, direction, f"profile-{module}-{index}")
        summary = summarize(entry)
        runs.append(summary)

        cached = "cache" in summary["per_source"]
        print(f"\n[第 {index + 1} 次] 墙钟 {summary['wall_seconds']}s | "
              f"链路自计 {summary['elapsed_seconds']}s | "
              f"{'命中检索缓存' if cached else '实时检索'}")

        lines, groups = render_stages(summary["stages"], summary["wall_seconds"] or 1.0)
        print("  阶段耗时（按耗时降序）:")
        for line in lines:
            print(line)

        if groups:
            print("  分组汇总:")
            for name, seconds in sorted(groups.items(), key=lambda item: -item[1]):
                ratio = seconds / (summary["wall_seconds"] or 1.0) * 100
                print(f"    {name:<14} {seconds:>7.2f}s  {ratio:>5.1f}%")

        print("  LLM:")
        for line in render_llm(summary["llm"]):
            print(line)

        print(f"  数据源: {summary['per_source']} | 语料 {summary['corpus_size']} 篇 | "
              f"主题 {summary['topic_count']} 个 | 机会点 {summary['gap_count']} 个")

    if len(runs) > 1:
        first, second = runs[0], runs[1]
        delta = round(first["wall_seconds"] - second["wall_seconds"], 2)
        print(f"\n  两次对比: 第 1 次 {first['wall_seconds']}s -> "
              f"第 2 次 {second['wall_seconds']}s  （相差 {delta}s）")
        print("  说明: 差值同时包含「检索缓存命中」与「嵌入模型未重新加载」两部分收益。")

    return runs


async def main() -> None:
    parser = argparse.ArgumentParser(description="分析链路性能诊断")
    parser.add_argument("direction", nargs="?", default="multimodal large language model inference")
    parser.add_argument("--module", choices=["explore", "gap", "both"], default="both")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--skip-embed-probe", action="store_true")
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="先预热 UMAP，模拟服务启动时的预热行为（生产环境由 lifespan 完成）",
    )
    args = parser.parse_args()

    if args.warmup:
        print("\n预热 UMAP（模拟服务启动时的行为）...")
        warmup_cluster()

    modules = ["explore", "gap"] if args.module == "both" else [args.module]
    payload: dict = {"direction": args.direction, "modules": {}}

    if not args.skip_embed_probe:
        print("\n" + "=" * 78)
        print("嵌入模型初始化开销独立测量")
        print("=" * 78)
        probe = await measure_embedder_load()
        print(f"  后端 {probe['backend']}")
        print(f"  首次构造并编码 {probe['first_run_seconds']}s | "
              f"第二次 {probe['second_run_seconds']}s | "
              f"重复初始化开销约 {probe['overhead_seconds']}s")
        payload["embedder_probe"] = probe

    for module in modules:
        payload["modules"][module] = await profile(module, args.direction, args.repeat)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "profile_report.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n原始数据已写入 {out}")


if __name__ == "__main__":
    asyncio.run(main())
