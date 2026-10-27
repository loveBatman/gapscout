"""OpenAlex 数据源适配器。

覆盖最广（2.5 亿+ 文献）且完全免费，提供开放获取链接与引用网络，
用于弥补 arXiv 只覆盖预印本的短板。

注意：OpenAlex 把摘要存成倒排索引（abstract_inverted_index），必须按位置还原。
"""

import re

from app.common.text import strip_html, truncate
from app.schemas.paper import Paper, Query
from app.sources.base import PaperSource

API_URL = "https://api.openalex.org/works"
# filter 语法用逗号分隔子句、冒号赋值，值内出现这些字符会破坏解析
_FILTER_UNSAFE_RE = re.compile(r"[,:]")
# OpenAlex 不提供 arxiv_id 字段，需从各类 URL 反解，用于 ar5iv 全文获取
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})")
# 合法的 OpenAlex work id 形如 W2741809807，用于剔除混入的其他来源 ID
_OPENALEX_ID_RE = re.compile(r"^W\d+$")


def sanitize_filter_value(text: str) -> str:
    return _FILTER_UNSAFE_RE.sub(" ", text or "").strip()


def build_search_texts(terms: list[str], raw: str) -> list[str]:
    """构造多路检索词。

    实测结论：把多个术语用空格连接时，OpenAlex 按 AND 匹配全部词，
    在交叉细分方向上召回极少——"diffusion model + multimodal large language
    model + efficient inference" 组合仅召回 5 篇。
    因此除组合查询外补充逐术语召回，召回量由上层按语义相似度重排与筛选。
    """
    cleaned_terms = [term for term in (sanitize_filter_value(t) for t in terms) if term][:2]
    if not cleaned_terms:
        return [sanitize_filter_value(raw or "machine learning")]

    texts = [" ".join(cleaned_terms)]
    for term in cleaned_terms:
        if term not in texts:
            texts.append(term)
    return texts
# OpenAlex field id 17 = Computer Science，把检索限定在已确认的学科范围内
CS_FIELD_ID = 17
PER_PAGE = 100


class OpenAlexSource(PaperSource):
    name = "openalex"
    min_interval = 0.15

    def get_min_interval(self) -> float:
        return self._settings.openalex_min_interval

    def _build_filter(self, query: Query) -> str:
        clauses = [f"primary_topic.field.id:{CS_FIELD_ID}"]
        if query.year_from:
            clauses.append(f"from_publication_date:{query.year_from}-01-01")
        if query.min_citations:
            clauses.append(f"cited_by_count:>{query.min_citations}")
        if query.open_access_only:
            clauses.append("is_oa:true")
        return ",".join(clauses)

    def _base_params(self) -> dict:
        return {"mailto": self._settings.contact_email}

    async def search(self, query: Query, limit: int) -> list[Paper]:
        papers: list[Paper] = []
        seen: set[str] = set()
        # 优先使用查询理解产出的英文术语：raw 可能是中文，
        # 而 OpenAlex 对中文表述的召回极低（实测整句中文只召回 1 篇）
        search_texts = build_search_texts(query.terms, query.raw)
        per_query = max(20, limit // max(1, len(search_texts)))
        base_filter = self._build_filter(query)

        for search_text in search_texts:
            cursor = "*"
            fetched = 0
            while fetched < per_query and cursor:
                params = {
                    **self._base_params(),
                    # 实测结论：顶层 search 是全文检索，会引入病理学、机器人等跨学科噪声；
                    # 放进 filter 的 title_and_abstract.search 相关性显著更高，且支持游标分页
                    "filter": f"{base_filter},title_and_abstract.search:{search_text}",
                    "per-page": min(PER_PAGE, max(1, per_query - fetched)),
                    "cursor": cursor,
                }
                payload = await self.get_json(API_URL, params)
                if not payload:
                    break
                results = payload.get("results") or []
                fetched += len(results)
                for item in results:
                    paper = self._parse_item(item)
                    if paper is None or paper.uid in seen:
                        continue
                    seen.add(paper.uid)
                    papers.append(paper)
                cursor = (payload.get("meta") or {}).get("next_cursor")
            if len(papers) >= limit:
                break

        return papers[:limit]

    def _parse_item(self, item: dict) -> Paper | None:
        openalex_id = (item.get("id") or "").rsplit("/", 1)[-1]
        title = strip_html(item.get("title") or item.get("display_name") or "")
        if not openalex_id or not title:
            return None

        authors = [
            name
            for authorship in item.get("authorships") or []
            if (name := (authorship.get("author") or {}).get("display_name"))
        ]
        topics = item.get("topics") or []
        concepts = [t["display_name"] for t in topics[:5] if t.get("display_name")]

        primary = item.get("primary_location") or {}
        source_info = primary.get("source") or {}
        best_oa = item.get("best_oa_location") or {}

        doi = (item.get("doi") or "").replace("https://doi.org/", "").strip() or None

        return Paper(
            source="openalex",
            source_id=openalex_id,
            doi=doi,
            arxiv_id=self._extract_arxiv_id(item, best_oa, primary),
            title=title,
            abstract=self._restore_abstract(item.get("abstract_inverted_index")),
            authors=authors,
            year=item.get("publication_year"),
            venue=(source_info.get("display_name") or "").strip() or None,
            citation_count=item.get("cited_by_count"),
            html_url=best_oa.get("landing_page_url") or primary.get("landing_page_url"),
            pdf_url=best_oa.get("pdf_url"),
            concepts=concepts,
        )

    @staticmethod
    def _extract_arxiv_id(item: dict, *locations: dict | None) -> str | None:
        """从位置 URL 中反解 arXiv ID。

        这一步让 OpenAlex 单独就能支撑全文抓取（ar5iv HTML），
        从而在 arXiv API 限流或 S2 缺少 key 时系统依然可用。
        """
        candidates: list[str] = []
        for location in locations:
            if not location:
                continue
            for key in ("landing_page_url", "pdf_url"):
                value = location.get(key)
                if value:
                    candidates.append(str(value))
        for value in (item.get("ids") or {}).values():
            candidates.append(str(value))
        for candidate in candidates:
            match = _ARXIV_URL_RE.search(candidate)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _restore_abstract(inverted: dict | None) -> str | None:
        """把倒排索引还原为可读摘要。"""
        if not inverted:
            return None
        positioned: list[tuple[int, str]] = []
        for word, positions in inverted.items():
            for position in positions or []:
                positioned.append((position, word))
        if not positioned:
            return None
        positioned.sort(key=lambda pair: pair[0])
        text = " ".join(word for _, word in positioned)
        return truncate(strip_html(text), 4000) or None

    async def fetch_references(self, paper: Paper) -> list[str]:
        """通过 referenced_works 字段获取被引文献 OpenAlex ID。"""
        payload = await self.get_json(
            f"{API_URL}/{paper.source_id}",
            {**self._base_params(), "select": "id,referenced_works"},
        )
        if not payload:
            return []
        return [
            ref.rsplit("/", 1)[-1]
            for ref in payload.get("referenced_works") or []
            if ref
        ]

    async def fetch_references_batch(
        self, papers: list[Paper], chunk_size: int = 50
    ) -> dict[str, list[str]]:
        """批量获取引用关系。

        用 openalex_id 过滤器一次取多篇（`|` 分隔），相比逐篇请求
        把网络往返从 N 次压到 N/50 次——引用图谱是信号 C 的输入，
        抓取效率直接决定 M2 的整体耗时。
        """
        # 只查询 OpenAlex 来源的论文：其他来源（如 arXiv）的 source_id
        # 形如 2401.12345，拼进 openalex_id 过滤器即构成非法值，
        # 实测会让整个请求返回 400，导致引用图谱完全拿不到数据。
        # 该缺陷在 arXiv 被限流（返回 0 篇）时不会暴露，只在 arXiv 正常工作时触发。
        ids = [
            paper.source_id
            for paper in papers
            if paper.source_id and _OPENALEX_ID_RE.match(paper.source_id)
        ]
        result: dict[str, list[str]] = {}

        for start in range(0, len(ids), chunk_size):
            chunk = ids[start : start + chunk_size]
            payload = await self.get_json(
                API_URL,
                {
                    **self._base_params(),
                    "filter": f"openalex_id:{'|'.join(chunk)}",
                    "select": "id,referenced_works",
                    "per-page": chunk_size,
                },
            )
            if not payload:
                continue
            for item in payload.get("results") or []:
                key = (item.get("id") or "").rsplit("/", 1)[-1]
                if not key:
                    continue
                result[key] = [
                    ref.rsplit("/", 1)[-1]
                    for ref in item.get("referenced_works") or []
                    if ref
                ]
        return result
