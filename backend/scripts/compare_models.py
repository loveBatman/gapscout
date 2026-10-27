"""主力 / 廉价模型档位对比实验（价值批判环节）。

背景（实测驱动）：
    M2 的「价值批判」是唯一走推理模型 deepseek-reasoner 的环节，
    实测单次耗时 24.7s ~ 48.1s（波动大），占 M2 总耗时的 33% ~ 40%，
    是目前最大的单点耗时。
    但该环节直接决定机会点的取舍（判断一个候选空白是真机会还是伪机会），
    属于质量敏感环节——因此**不能直接替换模型，必须先做对比实验**。

公平性保证：
    两次对比使用**同一批候选**（同一次分析产出），只有模型档位不同，
    其余输入完全一致，因此差异只可能来自模型本身。

用法：
    python scripts/compare_models.py                       # 默认方向
    python scripts/compare_models.py "retrieval augmented generation"
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.gap_agent import build_candidates, build_gap_cards  # noqa: E402
from app.agents.llm import LLMClient  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.pipeline.cluster import cluster_topics  # noqa: E402
from app.pipeline.embed import Embedder  # noqa: E402
from app.pipeline.filter import filter_by_relevance, quality_filter  # noqa: E402
from app.pipeline.future_work import analyze_future_work  # noqa: E402
from app.pipeline.graph import analyze_graph  # noqa: E402
from app.pipeline.method_task import analyze_matrix  # noqa: E402
from app.pipeline.normalize import dedup_papers  # noqa: E402
from app.services.explore_service import understand_query  # noqa: E402
from app.sources.registry import SourceRegistry  # noqa: E402

REPORT_DIR = Path(__file__).resolve().parents[1] / "reports"
REFERENCE_LIMIT = 100
FULLTEXT_LIMIT = 40


async def build_candidates_for(direction: str):
    """重现 M2 的前半段，产出候选空白列表（供两次批判共用）。"""
    settings = get_settings()
    llm = LLMClient()
    query = await understand_query(direction, llm)

    registry = SourceRegistry()
    try:
        papers, _ = await registry.search_all(query, settings.default_search_limit_per_source)
        deduped, _ = dedup_papers(papers)
        filtered, _ = quality_filter(deduped, query)

        embedder = Embedder()
        embedding = await embedder.embed_papers(filtered)
        probe = f"{direction} {' '.join(query.terms)}"
        query_vector = await embedder.embed_one(probe)
        filtered, indices, _ = filter_by_relevance(filtered, embedding.vectors @ query_vector)
        vectors = embedding.vectors[indices]

        outcome = cluster_topics(vectors)

        openalex = registry.get("openalex")
        if openalex is not None:
            references = await openalex.fetch_references_batch(filtered[:REFERENCE_LIMIT])
            for paper in filtered:
                if references.get(paper.source_id):
                    paper.references = references[paper.source_id]

        future_work = await analyze_future_work(
            filtered, vectors, embedder, max_papers=FULLTEXT_LIMIT
        )
        matrix = analyze_matrix(filtered)
        community = {
            paper.citation_key: int(outcome.labels[index])
            for index, paper in enumerate(filtered)
            if int(outcome.labels[index]) >= 0
        }
        graph = analyze_graph(filtered, community)

        candidates = build_candidates(future_work, matrix, graph, filtered)
        topic_labels = [f"主题 {cid}" for cid in outcome.sizes() if cid >= 0]
        print(f"语料 {len(filtered)} 篇 | 候选空白 {len(candidates)} 个 | 主题 {len(topic_labels)} 个")
        return candidates, topic_labels
    finally:
        await registry.aclose()


async def critique_with(candidates, topic_labels, direction: str, model: str) -> dict:
    """用指定模型执行一次价值批判。"""
    settings = get_settings()
    original = settings.llm_model_main
    settings.llm_model_main = model
    try:
        llm = LLMClient()
        started = time.monotonic()
        cards = await build_gap_cards(
            candidates, llm, direction=direction, topic_labels=topic_labels
        )
        elapsed = round(time.monotonic() - started, 2)
        usage = llm.usage.as_dict()
    finally:
        settings.llm_model_main = original

    return {
        "model": model,
        "elapsed_seconds": elapsed,
        "kept": len(cards),
        "kept_ratio": round(len(cards) / max(1, len(candidates)), 3),
        "tokens": usage.get("total_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "failures": usage.get("failures", 0),
        "titles": [card.title for card in cards],
        "with_value_note": sum(1 for card in cards if card.value_note),
        "with_risk": sum(1 for card in cards if card.risk),
        "avg_desc_len": round(
            sum(len(card.description) for card in cards) / max(1, len(cards)), 1
        ),
    }


async def main(direction: str) -> None:
    settings = get_settings()
    print("=" * 78)
    print(f"模型档位对比 | 方向: {direction}")
    print(f"主力档 {settings.llm_model_main}  vs  廉价档 {settings.llm_model_cheap}")
    print("=" * 78)

    candidates, topic_labels = await build_candidates_for(direction)
    if not candidates:
        print("未产出候选空白，无法对比")
        return

    payload = {"direction": direction, "candidate_count": len(candidates), "runs": []}
    for model in (settings.llm_model_main, settings.llm_model_cheap):
        print(f"\n--- 使用 {model} 执行价值批判 ---")
        outcome = await critique_with(candidates, topic_labels, direction, model)
        payload["runs"].append(outcome)
        print(f"  耗时 {outcome['elapsed_seconds']}s | token {outcome['tokens']}"
              f"（completion {outcome['completion_tokens']}）| 失败 {outcome['failures']}")
        print(f"  保留 {outcome['kept']}/{len(candidates)} 个（{outcome['kept_ratio']:.0%}）"
              f" | 含价值说明 {outcome['with_value_note']}"
              f" | 含风险说明 {outcome['with_risk']}"
              f" | 平均描述长度 {outcome['avg_desc_len']}")
        for index, title in enumerate(outcome["titles"], start=1):
            print(f"    [{index}] {title}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "model_compare.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if len(payload["runs"]) == 2:
        main_run, cheap_run = payload["runs"]
        speedup = (
            round(main_run["elapsed_seconds"] / cheap_run["elapsed_seconds"], 2)
            if cheap_run["elapsed_seconds"]
            else 0
        )
        print("\n" + "=" * 78)
        print("对比结论")
        print("=" * 78)
        print(f"  省时: {main_run['elapsed_seconds']}s -> {cheap_run['elapsed_seconds']}s（{speedup}x）")
        print(f"  token: {main_run['tokens']} -> {cheap_run['tokens']}")
        print(f"  保留数: {main_run['kept']} -> {cheap_run['kept']}"
              f"（候选共 {len(candidates)} 个）")
        print("  质量判断需要人工核对上方标题列表：")
        print("    - 廉价档若保留了明显空洞/不可执行的伪机会，则不应替换")
        print("    - 两档保留集合一致且标题具体度接近时，替换是安全的")
    print(f"\n原始数据已写入 {out}")


if __name__ == "__main__":
    argument = sys.argv[1] if len(sys.argv) > 1 else "multimodal large language model inference"
    asyncio.run(main(argument))
