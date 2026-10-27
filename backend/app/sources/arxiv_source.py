"""arXiv 数据源适配器。

arXiv 是计算机/AI 领域预印本覆盖最全、且提供全文的来源，是检索的主力。
官方礼貌策略要求请求间隔，由基类 RateLimiter 保证。
"""

import re
import xml.etree.ElementTree as ET

from app.common.text import extract_keywords, sanitize_query_term, strip_html, truncate
from app.schemas.paper import Paper, Query
from app.sources.base import PaperSource

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
API_URL = "https://export.arxiv.org/api/query"

_ARXIV_ID_RE = re.compile(r"abs/([0-9]{4}\.[0-9]{4,5}|[a-z\-]+/[0-9]{7})")
_VENUE_HINT_RE = re.compile(
    r"(accept|published|proceedings|conference|journal|workshop|neurips|icml|iclr|acl|emnlp|cvpr|kdd|aaai|ijcai)",
    re.IGNORECASE,
)

# 计算机/AI 相关分类，用于把检索限定在本学科范围内（学科范围已确定为计算机/AI）
AI_CATEGORIES = (
    "cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.IR", "cs.SE",
    "cs.DB", "cs.DC", "cs.MA", "cs.NE", "cs.RO", "cs.HC", "cs.CR",
)


class ArxivSource(PaperSource):
    name = "arxiv"
    min_interval = 3.0

    def get_min_interval(self) -> float:
        return self._settings.arxiv_min_interval

    def _build_search_query(self, query: Query) -> str:
        """构造 arXiv 查询表达式。

        实测结论（见 scripts/probe_queries.py）：
        - 整句短语 all:"<整句>" 召回极低，必须拆为关键词并用 AND 组合
        - arXiv 不支持 cat:cs.* 通配符，必须列出具体分类
        - 布尔表达式必须整体加括号，否则解析器报 syntax error
        """
        terms = query.terms or extract_keywords(query.raw, limit=5)
        cleaned = [t for t in (sanitize_query_term(t) for t in terms) if len(t) >= 3]
        if not cleaned:
            cleaned = ["machine", "learning"]
        clause = " AND ".join(f"all:{term}" for term in cleaned[:5])
        categories = query.categories or list(AI_CATEGORIES)
        cat_expr = " OR ".join(f"cat:{cat}" for cat in categories)
        return f"({clause}) AND ({cat_expr})"

    async def search(self, query: Query, limit: int) -> list[Paper]:
        """单页请求：arXiv 限流严格（实测密集请求会触发 429 并进入冷却期），
        因此不做分页追取，把 arXiv 定位为补充源，主力召回交给 OpenAlex。"""
        params = {
            "search_query": self._build_search_query(query),
            "start": 0,
            "max_results": max(1, min(limit, 200)),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        raw = await self.get_text(API_URL, params, max_attempts=1)
        if not raw or "Rate exceeded" in raw[:200]:
            return []
        return self.parse_feed(raw)

    def parse_feed(self, raw_xml: str) -> list[Paper]:
        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as exc:
            print(f"[arxiv] Atom 解析失败: {exc}")
            return []
        papers: list[Paper] = []
        for entry in root.findall(f"{ATOM}entry"):
            paper = self._parse_entry(entry)
            if paper is not None:
                papers.append(paper)
        return papers

    def _parse_entry(self, entry: ET.Element) -> Paper | None:
        raw_id = entry.findtext(f"{ATOM}id", "") or ""
        if not raw_id:
            return None
        source_id = self._extract_id(raw_id)
        title = strip_html(entry.findtext(f"{ATOM}title", ""))
        if not title:
            return None
        abstract = strip_html(entry.findtext(f"{ATOM}summary", ""))
        published = entry.findtext(f"{ATOM}published", "") or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [
            name for node in entry.findall(f"{ATOM}author")
            if (name := strip_html(node.findtext(f"{ATOM}name")))
        ]
        doi = (entry.findtext(f"{ARXIV_NS}doi") or "").strip() or None
        journal_ref = strip_html(entry.findtext(f"{ARXIV_NS}journal_ref"))
        comment = strip_html(entry.findtext(f"{ARXIV_NS}comment"))
        primary = entry.find(f"{ARXIV_NS}primary_category")
        category = primary.get("term") if primary is not None else None

        return Paper(
            source="arxiv",
            source_id=source_id,
            doi=doi,
            title=title,
            abstract=truncate(abstract, 4000) or None,
            authors=authors,
            year=year,
            venue=self._pick_venue(journal_ref, comment),
            citation_count=None,
            html_url=f"https://ar5iv.labs.arxiv.org/html/{source_id}",
            pdf_url=f"https://arxiv.org/pdf/{source_id}",
            concepts=[category] if category else [],
        )

    @staticmethod
    def _pick_venue(journal_ref: str, comment: str) -> str | None:
        """从 journal_ref 或作者备注中提取发表信息。"""
        if journal_ref:
            return truncate(journal_ref, 200)
        if comment and _VENUE_HINT_RE.search(comment):
            return truncate(comment, 200)
        return None

    @staticmethod
    def _extract_id(raw_id: str) -> str:
        match = _ARXIV_ID_RE.search(raw_id)
        if match:
            return match.group(1)
        tail = raw_id.rsplit("/", 1)[-1]
        return tail.split("v")[0] if tail else raw_id

    async def fetch_references(self, paper: Paper) -> list[str]:
        """arXiv Atom 不提供结构化引用列表，引用关系由 Semantic Scholar 补充。"""
        return []
