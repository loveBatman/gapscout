"""Semantic Scholar 数据源适配器。

提供两项 arXiv / OpenAlex 难以替代的能力：
1. TLDR 摘要 —— 快速判断论文贡献，用于机会点证据的精简呈现
2. 结构化引用关系 —— 信号 C 引用图谱的主要来源
"""

from app.common.text import strip_html, truncate
from app.schemas.paper import Paper, Query
from app.sources.base import PaperSource

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper"

SEARCH_FIELDS = ",".join(
    [
        "paperId",
        "title",
        "abstract",
        "year",
        "citationCount",
        "venue",
        "externalIds",
        "tldr",
        "authors",
        "openAccessPdf",
    ]
)
REFERENCE_FIELDS = "paperId,title,externalIds,year"


class SemanticScholarSource(PaperSource):
    name = "s2"
    min_interval = 1.0

    def get_min_interval(self) -> float:
        """无 API key 时 S2 使用共享池，极易 429，因此放慢并减少重试。"""
        if self._settings.s2_api_key:
            return self._settings.s2_min_interval
        return max(self._settings.s2_min_interval, 3.0)

    @property
    def max_attempts(self) -> int:
        return 2 if self._settings.s2_api_key else 1

    def _headers(self) -> dict[str, str]:
        if self._settings.s2_api_key:
            return {"x-api-key": self._settings.s2_api_key}
        return {}

    async def search(self, query: Query, limit: int) -> list[Paper]:
        papers: list[Paper] = []
        seen: set[str] = set()
        for term in query.all_terms()[:2]:
            params: dict = {
                "query": term,
                "limit": max(1, min(limit, 100)),
                "fields": SEARCH_FIELDS,
            }
            if query.year_from:
                params["year"] = f"{query.year_from}-"
            response = await self.request(
                SEARCH_URL, params, headers=self._headers(), max_attempts=self.max_attempts
            )
            if response is None:
                continue
            try:
                payload = response.json()
            except Exception as exc:  # noqa: BLE001
                print(f"[s2] 响应解析失败: {exc}")
                continue
            for item in payload.get("data") or []:
                paper = self._parse_item(item)
                if paper is None or paper.uid in seen:
                    continue
                seen.add(paper.uid)
                papers.append(paper)
        return papers

    def _parse_item(self, item: dict) -> Paper | None:
        paper_id = item.get("paperId")
        title = strip_html(item.get("title") or "")
        if not paper_id or not title:
            return None

        external = item.get("externalIds") or {}
        doi = external.get("DOI")
        arxiv_id = external.get("ArXiv")
        tldr_field = item.get("tldr")
        tldr = tldr_field.get("text") if isinstance(tldr_field, dict) else None
        open_pdf = item.get("openAccessPdf") or {}
        authors = [a.get("name", "") for a in (item.get("authors") or []) if a.get("name")]

        return Paper(
            source="s2",
            source_id=paper_id,
            doi=doi,
            arxiv_id=arxiv_id,
            title=title,
            abstract=truncate(strip_html(item.get("abstract") or ""), 4000) or None,
            authors=authors,
            year=item.get("year"),
            venue=(item.get("venue") or "").strip() or None,
            citation_count=item.get("citationCount"),
            html_url=None,
            pdf_url=open_pdf.get("url"),
            tldr=tldr,
        )

    async def fetch_references(self, paper: Paper) -> list[str]:
        """获取被引文献键（优先 DOI，其次 arXiv ID），用于构建引用图谱。"""
        for prefix, value in (("DOI", paper.doi), ("ARXIV", paper.arxiv_id)):
            if not value:
                continue
            url = f"{PAPER_URL}/{prefix}:{value}/references"
            response = await self.request(
                url,
                {"fields": REFERENCE_FIELDS, "limit": 100},
                headers=self._headers(),
                max_attempts=self.max_attempts,
            )
            if response is None:
                continue
            try:
                payload = response.json()
            except Exception as exc:  # noqa: BLE001
                print(f"[s2] 引用解析失败: {exc}")
                continue
            keys: list[str] = []
            for entry in payload.get("data") or []:
                cited = entry.get("citedPaper") or {}
                if not cited:
                    continue
                ext = cited.get("externalIds") or {}
                key = ext.get("DOI") or ext.get("ArXiv") or cited.get("paperId")
                if key:
                    keys.append(str(key))
            if keys:
                return keys
        return []
