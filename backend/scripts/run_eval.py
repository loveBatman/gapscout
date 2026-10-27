"""检索链路评测：客观量化多源聚合与各道过滤闸门的效果。

设计要点：
1. 用人工确认的核心论文作为召回率标准答案，指标客观可复现
2. 用跨领域噪声词检测术语歧义引入的污染（如 augmented → 增强现实）
3. 通过配置开关做消融实验，量化每道闸门的边际贡献
4. 全程不依赖 LLM，任何环境都能重复运行——这正是确定性管道的价值所在

用法：
    python scripts/run_eval.py               # 全量评测
    python scripts/run_eval.py --limit 3     # 只跑前 3 个方向（快速验证）
    python scripts/run_eval.py --configs multi_source,multi_source_term_gate
"""

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.filter import quality_filter  # noqa: E402
from app.pipeline.normalize import dedup_papers  # noqa: E402
from app.schemas.paper import Paper, Query  # noqa: E402
from app.sources.registry import SourceRegistry  # noqa: E402

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "eval_set.json"
REPORT_DIR = Path(__file__).resolve().parents[1] / "reports"
CACHE_DIR = REPORT_DIR / "cache"
PER_SOURCE_LIMIT = 150
# 并发过高会触发数据源限流（实测 OpenAlex 也会返回 429），
# 导致用例检索失败、评测结果失真，因此压到 2 并在配置之间留出间隔
CONCURRENCY = 2
CONFIG_PAUSE_SECONDS = 15
MATCH_THRESHOLD = 0.7

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SHORT_TOKEN_LEN = 2


@dataclass
class Config:
    name: str
    label: str
    sources: tuple[str, ...]
    term_coverage: float
    note: str


CONFIGS: dict[str, Config] = {
    "openalex_only": Config(
        name="openalex_only",
        label="单源（仅 OpenAlex）",
        sources=("openalex",),
        term_coverage=0.0,
        note="对比基线：不使用多源聚合与术语闸门",
    ),
    "multi_source": Config(
        name="multi_source",
        label="多源聚合",
        sources=("arxiv", "openalex", "s2"),
        term_coverage=0.0,
        note="验证多源聚合对召回的贡献",
    ),
    "multi_source_term_gate": Config(
        name="multi_source_term_gate",
        label="多源 + 术语覆盖闸门",
        sources=("arxiv", "openalex", "s2"),
        term_coverage=0.5,
        note="验证术语闸门对跨领域噪声的抑制效果",
    ),
}


@dataclass
class CaseResult:
    direction: str
    config: str
    fetched: int = 0
    deduped_count: int = 0
    kept: int = 0
    duplicates: int = 0
    must_hits: int = 0
    must_total: int = 0
    noise_hits: int = 0
    elapsed: float = 0.0
    per_source: dict[str, int] = field(default_factory=dict)
    missed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cache_hit: bool = False

    @property
    def recall(self) -> float:
        return self.must_hits / self.must_total if self.must_total else 0.0

    @property
    def noise_rate(self) -> float:
        return self.noise_hits / self.kept if self.kept else 0.0

    @property
    def valid(self) -> bool:
        """检索阶段无错误且拿到足够语料，该用例才计入有效样本。"""
        return not self.errors and self.fetched >= 30

    def as_dict(self) -> dict:
        return {
            "direction": self.direction,
            "config": self.config,
            "fetched": self.fetched,
            "deduped": self.deduped_count,
            "kept": self.kept,
            "duplicates": self.duplicates,
            "must_hits": self.must_hits,
            "must_total": self.must_total,
            "recall": round(self.recall, 4),
            "noise_hits": self.noise_hits,
            "noise_rate": round(self.noise_rate, 4),
            "elapsed": round(self.elapsed, 2),
            "per_source": self.per_source,
            "missed": self.missed,
            "errors": self.errors,
            "valid": self.valid,
            "cache_hit": self.cache_hit,
        }


def cache_path(direction: str, sources: tuple[str, ...]) -> Path:
    key = hashlib.sha256(
        f"{direction}|{','.join(sources)}|{PER_SOURCE_LIMIT}".encode("utf-8")
    ).hexdigest()[:16]
    return CACHE_DIR / f"{key}.json"


def read_cache(path: Path) -> list[Paper] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    try:
        return [Paper(**item) for item in payload]
    except (TypeError, ValueError):
        return None


def write_cache(path: Path, papers: list[Paper]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([paper.model_dump() for paper in papers], ensure_ascii=False),
        encoding="utf-8",
    )


def matches(title: str, target: str, threshold: float = MATCH_THRESHOLD) -> bool:
    """标题匹配：用词覆盖率而非完全相等，容忍预印本与正式版的标题差异。"""
    title_tokens = set(_TOKEN_RE.findall((title or "").lower()))
    target_tokens = [
        token
        for token in _TOKEN_RE.findall((target or "").lower())
        if len(token) > _SHORT_TOKEN_LEN
    ]
    if not target_tokens:
        return False
    hits = sum(1 for token in target_tokens if token in title_tokens)
    return hits / len(target_tokens) >= threshold


def count_noise(papers: list[Paper], markers: list[str]) -> int:
    if not markers:
        return 0
    count = 0
    for paper in papers:
        text = f"{paper.title} {paper.abstract_or_tldr or ''}".lower()
        if any(marker in text for marker in markers):
            count += 1
    return count


async def run_case(case: dict, config: Config, semaphore: asyncio.Semaphore) -> CaseResult:
    direction = case["direction"]
    result = CaseResult(direction=direction, config=config.name)
    result.must_total = len(case.get("must_hit") or [])

    async with semaphore:
        started = time.monotonic()
        query = Query(raw=direction, terms=[direction], year_from=2020)
        path = cache_path(direction, config.sources)

        # 优先复用已抓取的原始检索结果：固定输入后，不同过滤策略的对比才是
        # 公平的（控制变量），同时避免重复请求触发数据源限流
        papers = read_cache(path)
        if papers is not None:
            result.per_source = {"cache": len(papers)}
            result.cache_hit = True
        else:
            registry = SourceRegistry(config.sources)
            try:
                papers, stats = await registry.search_all(query, PER_SOURCE_LIMIT)
                result.per_source = dict(stats.per_source)
                result.errors = list(stats.errors)
                write_cache(path, papers)
            finally:
                await registry.aclose()

        result.fetched = len(papers)
        deduped, dedup_report = dedup_papers(papers)
        result.deduped_count = len(deduped)
        result.duplicates = dedup_report.removed

        filtered, _ = quality_filter(deduped, query, min_term_coverage=config.term_coverage)
        result.kept = len(filtered)
        result.elapsed = round(time.monotonic() - started, 2)

    for target in case.get("must_hit") or []:
        if any(matches(paper.title, target) for paper in filtered):
            result.must_hits += 1
        else:
            result.missed.append(target)
    result.noise_hits = count_noise(filtered, case.get("noise_markers") or [])
    return result


def summarize(results: list[CaseResult], config: Config) -> dict:
    """汇总时剔除检索失败的用例：限流导致的空结果不代表配置优劣。"""
    valid = [item for item in results if item.valid]
    skipped = len(results) - len(valid)
    if not valid:
        return {
            "config": config.name,
            "label": config.label,
            "note": config.note,
            "cases": 0,
            "skipped": skipped,
            "avg_recall": 0.0,
            "avg_kept": 0.0,
            "avg_fetched": 0.0,
            "avg_elapsed": 0.0,
            "total_noise": 0,
            "noise_rate": 0.0,
            "perfect_recall_cases": 0,
        }

    count = len(valid)
    return {
        "config": config.name,
        "label": config.label,
        "note": config.note,
        "cases": count,
        "skipped": skipped,
        "avg_recall": round(sum(item.recall for item in valid) / count, 4),
        "avg_kept": round(sum(item.kept for item in valid) / count, 1),
        "avg_fetched": round(sum(item.fetched for item in valid) / count, 1),
        "avg_elapsed": round(sum(item.elapsed for item in valid) / count, 2),
        "total_noise": sum(item.noise_hits for item in valid),
        "noise_rate": round(
            sum(item.noise_hits for item in valid) / max(1, sum(item.kept for item in valid)),
            4,
        ),
        "perfect_recall_cases": sum(1 for item in valid if item.recall >= 1.0),
    }


async def main(limit: int | None, config_names: list[str]) -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    cases = payload.get("cases") or []
    if limit:
        cases = cases[:limit]

    chosen = [CONFIGS[name] for name in config_names if name in CONFIGS]
    if not chosen:
        print(f"无效的配置名，可选：{list(CONFIGS)}")
        return

    print("=" * 82)
    print(f"检索链路评测：{len(cases)} 个方向 × {len(chosen)} 种配置")
    print("=" * 82)

    all_results: list[CaseResult] = []
    summaries: list[dict] = []
    semaphore = asyncio.Semaphore(CONCURRENCY)

    for position, config in enumerate(chosen):
        if position > 0:
            # 配置之间留出间隔，避免连续请求触发数据源限流
            print(f"\n（等待 {CONFIG_PAUSE_SECONDS}s 以规避数据源限流）")
            await asyncio.sleep(CONFIG_PAUSE_SECONDS)
        print(f"\n>>> 配置：{config.label}（{config.note}）")
        started = time.monotonic()
        tasks = [run_case(case, config, semaphore) for case in cases]
        results: list[CaseResult] = []
        for coro in asyncio.as_completed(tasks):
            item = await coro
            results.append(item)
            flag = "" if item.valid else "  [限流跳过]"
            print(
                f"    {item.direction[:40]:<42} "
                f"召回 {item.must_hits}/{item.must_total} | "
                f"保留 {item.kept:>4} 篇 | 噪声 {item.noise_hits:>2} | "
                f"{item.elapsed:>5.1f}s{flag}"
            )
        all_results.extend(results)
        summary = summarize(results, config)
        summaries.append(summary)
        print(
            f"    小计：有效用例 {summary['cases']}/{len(results)} | "
            f"平均召回率 {summary['avg_recall']:.1%} | "
            f"平均保留 {summary['avg_kept']} 篇 | "
            f"噪声率 {summary['noise_rate']:.2%} | "
            f"耗时 {round(time.monotonic() - started, 1)}s"
        )

    publish(summaries, all_results)

    print("\n" + "=" * 82)
    print("汇总对比")
    print("=" * 82)
    header = f"{'配置':<26}{'平均召回率':<12}{'平均保留':<10}{'噪声率':<10}{'平均耗时':<10}"
    print(header)
    for summary in summaries:
        print(
            f"{summary['label']:<24}"
            f"{summary['avg_recall']:<12.1%}"
            f"{summary['avg_kept']:<10}"
            f"{summary['noise_rate']:<10.2%}"
            f"{summary['avg_elapsed']:<10}"
        )


def publish(summaries: list[dict], results: list[CaseResult]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summaries": summaries,
        "details": [item.as_dict() for item in results],
    }
    path = REPORT_DIR / "eval_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入 {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="检索链路评测")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 个方向")
    parser.add_argument(
        "--configs",
        type=str,
        default="openalex_only,multi_source,multi_source_term_gate",
        help="逗号分隔的配置名",
    )
    args = parser.parse_args()
    asyncio.run(main(args.limit, [name.strip() for name in args.configs.split(",")]))
