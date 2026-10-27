"""未来工作聚合（信号 A）：三路信号中证据强度最高的一路。

原理：论文作者会在 Limitation / Future Work 章节明确指出"什么还没解决"，
这是由领域专家自己标注的空白声明。把大量论文的此类陈述聚合聚类，
就能得到被反复提及但尚无对应工作的方向。

覆盖度判定（本模块的关键设计）：
把陈述簇的质心与全部论文的标题+摘要向量比对，取最高相似度作为"覆盖度"。
- 覆盖度高 → 已有工作在做这件事，不是空白
- 覆盖度低 → 现有工作没有触及，空白信号成立

这一步把"没人提过"与"提了但没人做"区分开，是信号 A 相对"直接问大模型"
的核心优势：结论来自可计算的证据，而不是模型的印象。
"""

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import numpy as np

from app.config import get_settings
from app.pipeline.cluster import cluster_topics
from app.pipeline.embed import Embedder, normalize_rows
from app.schemas.paper import Paper
from app.sources.base import FullText
from app.sources.fulltext import FullTextFetcher, pick_evidence_sections, split_sentences

ProgressCallback = Callable[[str, int, int], Awaitable[None]]

# 未来工作陈述的标记词：用于把"局限/展望"章节里的句子筛出来
FUTURE_MARKERS = (
    "future work", "future research", "future direction", "future study",
    "remains", "remain ", "still ", "should be", "should also", "could be",
    "need to", "needs to", "further ", "open problem", "open question",
    "unexplored", "not yet", "has not been", "have not been", "we leave",
    "promising direction", "would be interesting", "warrant", "deserve",
    "remains unclear", "remains challenging", "limitation", "limited to",
)

EVIDENCE_WEIGHT = {"L1": 1.0, "L2": 0.75, "L3": 0.35}
_MIN_STATEMENT_LEN = 40
_MAX_STATEMENTS_PER_PAPER = 8


@dataclass
class Statement:
    uid: str
    text: str
    level: str
    section: str


@dataclass
class FutureWorkSignals:
    papers_scanned: int = 0
    fulltext_levels: dict[str, int] = field(default_factory=dict)
    statements_total: int = 0
    coverage: float = 0.0  # 成功抽到陈述的论文占比
    clusters: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "papers_scanned": self.papers_scanned,
            "fulltext_levels": self.fulltext_levels,
            "statements_total": self.statements_total,
            "extraction_coverage": round(self.coverage, 3),
            "clusters": self.clusters,
            "errors": self.errors[:5],
        }


def is_future_statement(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(marker in lowered for marker in FUTURE_MARKERS)


def extract_statements(fulltext: FullText) -> list[Statement]:
    """从一篇论文的全文里抽取"未来工作 / 局限"陈述句。"""
    picked = pick_evidence_sections(fulltext)
    statements: list[Statement] = []
    for section_name, content in picked.items():
        for sentence in split_sentences(content, max_sentences=14):
            if len(sentence) < _MIN_STATEMENT_LEN or not is_future_statement(sentence):
                continue
            statements.append(
                Statement(
                    uid=fulltext.uid,
                    text=sentence,
                    level=fulltext.level,
                    section=section_name,
                )
            )
            if len(statements) >= _MAX_STATEMENTS_PER_PAPER:
                return statements
    return statements


async def collect_fulltexts(
    papers: list[Paper],
    *,
    max_papers: int = 40,
    concurrency: int | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[dict[str, FullText], Counter, list[str]]:
    """并发抓取全文，优先覆盖更可能拿到 HTML 的论文。

    并发度默认取配置值：实测全文抓取是 M2 的主要耗时来源之一，
    提高并发只影响速度，不改变抓取范围与最终结果。
    """
    limit = concurrency if concurrency is not None else get_settings().fulltext_concurrency
    candidates = sorted(
        papers,
        key=lambda paper: (
            1 if paper.arxiv_id else 0,
            1 if paper.pdf_url else 0,
            paper.citation_count or 0,
        ),
        reverse=True,
    )[:max_papers]

    fetcher = FullTextFetcher()
    semaphore = asyncio.Semaphore(max(1, limit))
    results: dict[str, FullText] = {}
    levels: Counter = Counter()
    errors: list[str] = []
    done = 0

    async def fetch_one(paper: Paper) -> None:
        nonlocal done
        async with semaphore:
            try:
                fulltext = await fetcher.fetch(paper)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{paper.uid}: {type(exc).__name__}: {exc}")
                return
        results[paper.uid] = fulltext
        levels[fulltext.level] += 1
        done += 1
        if on_progress is not None and done % 5 == 0:
            await on_progress("抓取全文", done, len(candidates))

    try:
        await asyncio.gather(*(fetch_one(paper) for paper in candidates))
    finally:
        await fetcher.aclose()

    return results, levels, errors


def _cluster_coverage(centroid: np.ndarray, paper_vectors: np.ndarray) -> tuple[float, int]:
    """计算陈述簇在现有工作中的最高相似度，返回（覆盖度, 最相似论文下标）。"""
    if paper_vectors.size == 0:
        return 0.0, -1
    similarities = paper_vectors @ centroid
    index = int(np.argmax(similarities))
    return float(similarities[index]), index


async def analyze_future_work(
    papers: list[Paper],
    paper_vectors: np.ndarray,
    embedder: Embedder,
    *,
    max_papers: int = 40,
    concurrency: int | None = None,
    min_cluster_size: int = 2,
    on_progress: ProgressCallback | None = None,
) -> FutureWorkSignals:
    """信号 A 完整流程：抓全文 -> 抽陈述 -> 聚类 -> 覆盖度判定。"""
    signals = FutureWorkSignals()
    if not papers:
        return signals

    fulltexts, levels, errors = await collect_fulltexts(
        papers, max_papers=max_papers, concurrency=concurrency, on_progress=on_progress
    )
    signals.papers_scanned = len(fulltexts)
    signals.fulltext_levels = dict(levels)
    signals.errors = errors

    statements: list[Statement] = []
    for fulltext in fulltexts.values():
        statements.extend(extract_statements(fulltext))
    signals.statements_total = len(statements)
    signals.coverage = len({s.uid for s in statements}) / len(papers) if papers else 0.0

    if len(statements) < min_cluster_size * 2:
        return signals

    if on_progress is not None:
        await on_progress("向量化陈述", len(statements), len(statements))

    embedding = await embedder.embed_texts([statement.text for statement in statements])
    outcome = cluster_topics(embedding.vectors, min_cluster_size=min_cluster_size)

    # 论文侧向量用于覆盖度比对（已 L2 归一化）
    paper_matrix = normalize_rows(paper_vectors) if paper_vectors.size else paper_vectors
    mapping = {paper.uid: index for index, paper in enumerate(papers)}

    clusters: list[dict] = []
    for label in sorted({int(x) for x in outcome.labels}):
        if label < 0:
            continue
        member_indices = np.where(outcome.labels == label)[0]
        if member_indices.size == 0:
            continue
        members = [statements[i] for i in member_indices]
        centroid = normalize_rows(embedding.vectors[member_indices].mean(axis=0, keepdims=True))[0]
        coverage, best_index = _cluster_coverage(centroid, paper_matrix)

        source_uids = sorted({member.uid for member in members})
        best_level = max(
            (member.level for member in members),
            key=lambda level: EVIDENCE_WEIGHT.get(level, 0.0),
        )
        representative = max(members, key=lambda member: len(member.text))

        clusters.append(
            {
                "label": representative.text[:120],
                "statements": [member.text[:300] for member in members[:5]],
                # 保留陈述与论文的对应关系，供证据溯源精确定位到来源论文
                "statement_items": [
                    {"uid": member.uid, "text": member.text[:300], "level": member.level}
                    for member in members[:8]
                ],
                "source_uids": source_uids,
                "source_count": len(source_uids),
                "mention_count": len(members),
                "coverage": round(coverage, 4),
                "gap_strength": round(max(0.0, 1.0 - coverage), 4),
                "level": best_level,
                "evidence_weight": EVIDENCE_WEIGHT.get(best_level, 0.0),
                "nearest_paper": _nearest_paper(papers, mapping, best_index),
            }
        )

    clusters.sort(key=lambda item: (-item["gap_strength"], -item["source_count"]))
    signals.clusters = clusters[:12]
    return signals


def _nearest_paper(
    papers: list[Paper], mapping: dict[str, int], index: int
) -> dict | None:
    if index < 0 or index >= len(papers):
        return None
    paper = papers[index]
    return {"uid": paper.uid, "title": paper.title, "year": paper.year, "url": paper.web_url()}


def summarize_levels(levels: dict[str, int]) -> str:
    """把全文覆盖情况转成可读文案，用于前端展示证据强度。"""
    if not levels:
        return "无全文证据"
    parts = [f"{level} {count} 篇" for level, count in sorted(levels.items())]
    return " / ".join(parts)
