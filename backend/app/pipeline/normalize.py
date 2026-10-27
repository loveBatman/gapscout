"""三级去重：标题精确匹配 -> DOI/arXiv ID 交叉映射 -> MinHash-LSH 模糊匹配。

复杂度：n≈2000 时朴素两两比较是 4×10^6 次，经 LSH 分桶后实际比较降到 O(n) 量级。
去重准确率本身也是评测指标之一。
"""

import re
from dataclasses import dataclass

from datasketch import MinHash, MinHashLSH

from app.common.text import normalize_title
from app.schemas.paper import Paper

_SHINGLE_SIZE = 3
_LSH_THRESHOLD = 0.78
_LSH_PERMUTATIONS = 64
_VERSION_SUFFIX_RE = re.compile(r"v\d+$")


@dataclass
class DedupReport:
    input_count: int = 0
    output_count: int = 0
    title_hits: int = 0
    key_hits: int = 0
    fuzzy_hits: int = 0

    @property
    def removed(self) -> int:
        return self.input_count - self.output_count

    def as_dict(self) -> dict:
        return {
            "input": self.input_count,
            "output": self.output_count,
            "removed": self.removed,
            "title_hits": self.title_hits,
            "key_hits": self.key_hits,
            "fuzzy_hits": self.fuzzy_hits,
        }


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower()
    cleaned = cleaned.replace("https://doi.org/", "").replace("http://doi.org/", "")
    cleaned = cleaned.replace("doi:", "").strip()
    return cleaned or None


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower().replace("arxiv:", "")
    cleaned = cleaned.rsplit("/", 1)[-1] if cleaned.startswith("http") else cleaned
    cleaned = _VERSION_SUFFIX_RE.sub("", cleaned)
    return cleaned or None


def dedup_papers(papers: list[Paper]) -> tuple[list[Paper], DedupReport]:
    """三级去重入口。保留信息更完整的记录（有 DOI / 摘要 / 更高引用）。"""
    report = DedupReport(input_count=len(papers))
    stage_one, title_hits, key_hits = _dedup_by_key(papers)
    report.title_hits = title_hits
    report.key_hits = key_hits

    final, fuzzy_hits = _dedup_fuzzy(stage_one)
    report.fuzzy_hits = fuzzy_hits
    report.output_count = len(final)
    return final, report


def _dedup_by_key(papers: list[Paper]) -> tuple[list[Paper], int, int]:
    unique: list[Paper] = []
    by_title: dict[str, int] = {}
    by_doi: dict[str, int] = {}
    by_arxiv: dict[str, int] = {}
    title_hits = 0
    key_hits = 0

    for paper in papers:
        title_key = paper.normalized_title or normalize_title(paper.title)
        if not title_key:
            continue

        target: int | None = None
        if title_key in by_title:
            target = by_title[title_key]
            title_hits += 1
        else:
            doi = normalize_doi(paper.doi)
            arxiv = normalize_arxiv_id(paper.arxiv_id)
            if doi and doi in by_doi:
                target = by_doi[doi]
                key_hits += 1
            elif arxiv and arxiv in by_arxiv:
                target = by_arxiv[arxiv]
                key_hits += 1

        if target is not None:
            _merge(unique[target], paper)
            _register(by_doi, by_arxiv, unique[target], target)
            continue

        unique.append(paper)
        index = len(unique) - 1
        by_title[title_key] = index
        _register(by_doi, by_arxiv, paper, index)

    return unique, title_hits, key_hits


def _register(
    by_doi: dict[str, int], by_arxiv: dict[str, int], paper: Paper, index: int
) -> None:
    doi = normalize_doi(paper.doi)
    if doi:
        by_doi.setdefault(doi, index)
    arxiv = normalize_arxiv_id(paper.arxiv_id)
    if arxiv:
        by_arxiv.setdefault(arxiv, index)


def _dedup_fuzzy(papers: list[Paper]) -> tuple[list[Paper], int]:
    """模糊去重：处理"同一论文标题在预印本与正式版间轻微不一致"的情况。"""
    if len(papers) < 2:
        return papers, 0

    lsh = MinHashLSH(threshold=_LSH_THRESHOLD, num_perm=_LSH_PERMUTATIONS)
    signatures: list[MinHash] = []
    for index, paper in enumerate(papers):
        signature = _build_minhash(paper.normalized_title or normalize_title(paper.title))
        signatures.append(signature)
        lsh.insert(str(index), signature)

    dropped: set[int] = set()
    for index, signature in enumerate(signatures):
        if index in dropped:
            continue
        for candidate in lsh.query(signature):
            other = int(candidate)
            if other == index or other in dropped:
                continue
            if other < index:
                # 已在前序轮次处理过，跳过避免重复合并
                continue
            _merge(papers[index], papers[other])
            dropped.add(other)

    kept = [paper for index, paper in enumerate(papers) if index not in dropped]
    return kept, len(dropped)


def _build_minhash(text: str) -> MinHash:
    signature = MinHash(num_perm=_LSH_PERMUTATIONS)
    tokens = text.split()
    if not tokens:
        signature.update(b"")
        return signature
    span = min(_SHINGLE_SIZE, len(tokens))
    for start in range(len(tokens) - span + 1):
        shingle = " ".join(tokens[start : start + span])
        signature.update(shingle.encode("utf-8"))
    return signature


def _merge(target: Paper, incoming: Paper) -> None:
    """把 incoming 的补充信息合并进 target，保证不丢失任何来源的字段。"""
    if not target.doi and incoming.doi:
        target.doi = incoming.doi
    if not target.arxiv_id and incoming.arxiv_id:
        target.arxiv_id = incoming.arxiv_id
    if not target.abstract and incoming.abstract:
        target.abstract = incoming.abstract
    if not target.tldr and incoming.tldr:
        target.tldr = incoming.tldr
    if not target.html_url and incoming.html_url:
        target.html_url = incoming.html_url
    if not target.pdf_url and incoming.pdf_url:
        target.pdf_url = incoming.pdf_url
    if not target.venue and incoming.venue:
        target.venue = incoming.venue
    if not target.year and incoming.year:
        target.year = incoming.year
    if (incoming.citation_count or 0) > (target.citation_count or 0):
        target.citation_count = incoming.citation_count
    target.concepts = list(dict.fromkeys([*target.concepts, *incoming.concepts]))
    target.references = list(dict.fromkeys([*target.references, *incoming.references]))
