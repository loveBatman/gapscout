"""质量过滤：把"检索到的一堆论文"收敛为"对该领域有代表性的论文集合"。

两个关键设计：
1. 用"年均引用密度"而非绝对引用数排序，避免老论文天然占优
2. 按年份分层保留，保证前沿动态不被高引老论文挤掉（对研究空白分析至关重要）
"""

import math
import re
from collections import defaultdict
from datetime import datetime

import numpy as np

from app.schemas.paper import Paper, Query

# 超出时间范围但引用极高，视为经典文献保留
CLASSIC_CITATION_THRESHOLD = 150
DEFAULT_MAX_KEEP = 400
MIN_YEAR_FALLBACK = 2019

# 论文需覆盖的检索术语比例上限
DEFAULT_MIN_TERM_COVERAGE = 0.5
# 高引经典工作豁免术语闸门：奠基性论文的表述常与当代检索词不同
CLASSIC_EXEMPT_CITATIONS = 300
# 前缀匹配长度：容忍同一概念的词形变化
STEM_LENGTH = 5
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-]{2,}")


def _prefix_present(text: str, word: str, stem_length: int = STEM_LENGTH) -> bool:
    stem = word[:stem_length]
    if len(stem) < 3:
        return word in text
    return re.search(rf"\b{re.escape(stem)}", text) is not None


def term_coverage(text: str, terms: list[str]) -> float:
    """计算文本对检索术语的覆盖比例（前缀匹配，容忍词形变化）。

    必要性（实测问题一）：OpenAlex 的 title_and_abstract.search 是宽松匹配而非
    严格 AND，查询 "retrieval augmented generation" 会召回大量
    "Augmented Reality" 论文——"augmented" 一词的歧义把整个 AR 领域带了进来，
    聚类结果因此被污染成两个互不相干的主题。

    必要性（实测问题二）：精确词匹配会误杀奠基工作。
    "Distilling the Knowledge in a Neural Network" 与检索词 "distillation"
    词形不同，精确匹配下覆盖率判定为 0 而被丢弃，导致评测召回率不升反降。
    改用前缀匹配后 distillation/distilling/distill 可互相命中。
    """
    if not terms:
        return 1.0
    words: list[str] = []
    for term in terms:
        words.extend(match.group(0).lower() for match in _WORD_RE.finditer(term))
    unique = list(dict.fromkeys(words))
    if not unique:
        return 1.0
    lowered = (text or "").lower()
    hits = sum(1 for word in unique if _prefix_present(lowered, word))
    return hits / len(unique)


def rank_score(paper: Paper, current_year: int) -> float:
    """综合排序分：年均引用密度 × 新近度 × 数据完整度。"""
    year = paper.year or (current_year - 5)
    age = max(1, current_year - year + 1)
    citations = paper.citation_count or 0
    density = citations / age
    recency = 1.0 + max(0.0, 3 - (current_year - year)) * 0.35
    completeness = 1.0
    if paper.abstract:
        completeness += 0.15
    if paper.doi:
        completeness += 0.05
    return (math.log1p(density) + 0.5) * recency * completeness


def quality_filter(
    papers: list[Paper],
    query: Query,
    *,
    min_year: int | None = None,
    max_keep: int = DEFAULT_MAX_KEEP,
    min_term_coverage: float = DEFAULT_MIN_TERM_COVERAGE,
) -> tuple[list[Paper], int]:
    """返回（过滤并排序后的论文, 被丢弃的数量）。"""
    current_year = datetime.now().year
    year_floor = min_year or query.year_from or MIN_YEAR_FALLBACK
    terms = query.terms or []

    eligible: list[Paper] = []
    for paper in papers:
        year = paper.year or year_floor
        citations = paper.citation_count or 0

        if year < year_floor and citations < CLASSIC_CITATION_THRESHOLD:
            continue
        if query.min_citations and citations < query.min_citations:
            continue
        if query.open_access_only and not (paper.pdf_url or paper.html_url):
            continue
        # 无摘要的论文无法参与语义聚类与证据生成，直接排除
        if not paper.abstract_or_tldr:
            continue
        # 术语覆盖闸门：拦截因术语歧义引入的跨领域论文。
        # 高引经典工作豁免——奠基论文的用词可能与本领域当代检索词不一致，
        # 用覆盖率硬卡会把它们误杀，反而损害检索质量
        if (
            terms
            and citations < CLASSIC_EXEMPT_CITATIONS
            and term_coverage(f"{paper.title} {paper.abstract_or_tldr}", terms)
            < min_term_coverage
        ):
            continue

        eligible.append(paper)

    eligible.sort(key=lambda p: rank_score(p, current_year), reverse=True)
    trimmed = _stratified_trim(eligible, max_keep)
    return trimmed, len(papers) - len(trimmed)


def _stratified_trim(papers: list[Paper], max_keep: int) -> list[Paper]:
    """按年份分层截断，确保每个年份都有代表论文，保留领域演化全貌。"""
    if len(papers) <= max_keep:
        return papers

    by_year: dict[int, list[Paper]] = defaultdict(list)
    for paper in papers:
        by_year[paper.year or 0].append(paper)

    quota = max(3, max_keep // max(1, len(by_year)))
    selected: list[Paper] = []
    for year in sorted(by_year, reverse=True):
        selected.extend(by_year[year][:quota])

    if len(selected) < max_keep:
        chosen = {id(paper) for paper in selected}
        remaining = [paper for paper in papers if id(paper) not in chosen]
        selected.extend(remaining[: max_keep - len(selected)])

    return selected[:max_keep]


def filter_by_relevance(
    papers: list[Paper],
    similarities: np.ndarray,
    *,
    threshold: float = 0.32,
    min_keep: int = 40,
) -> tuple[list[Paper], list[int], int]:
    """用查询语义向量做相关性闸门，剔除跨学科噪声。

    必要性：OpenAlex 的关键词匹配是词袋级别的，实测在查询
    "multimodal large language model inference" 时会返回
    "Computational toxicology in drug discovery" 这类不相关论文。
    仅靠引用数排序无法剔除它们，只能用语义相似度兜底。

    返回（保留的论文, 保留论文在入参中的下标, 被剔除数量）。
    """
    if not papers or similarities.size != len(papers):
        return papers, list(range(len(papers))), 0

    order = np.argsort(-similarities)
    keep = [int(index) for index in order if float(similarities[index]) >= threshold]
    if len(keep) < min_keep:
        # 阈值过严时至少保住相关性最高的一批，避免结果过少无法分析
        keep = [int(index) for index in order[: min(min_keep, len(papers))]]

    keep_set = set(keep)
    kept_papers = [papers[index] for index in sorted(keep_set)]
    return kept_papers, sorted(keep_set), len(papers) - len(kept_papers)


def year_trend(papers: list[Paper]) -> list[dict]:
    """按年份统计论文量，用于前端热度趋势曲线与新兴簇判定。"""
    counter: dict[int, int] = defaultdict(int)
    for paper in papers:
        if paper.year:
            counter[paper.year] += 1
    return [{"year": year, "count": counter[year]} for year in sorted(counter)]


def trend_slope(years: list[dict]) -> float:
    """用最近若干年计数做最小二乘斜率，衡量主题升温速度（信号 C 新兴簇依据）。"""
    points = [(item["year"], item["count"]) for item in years if item.get("count")]
    if len(points) < 3:
        return 0.0
    recent = points[-5:]
    n = len(recent)
    mean_x = sum(x for x, _ in recent) / n
    mean_y = sum(y for _, y in recent) / n
    denominator = sum((x - mean_x) ** 2 for x, _ in recent)
    if denominator == 0:
        return 0.0
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in recent)
    return round(numerator / denominator, 4)
