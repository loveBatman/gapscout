"""全文获取：三级降级策略。

M2 信号 A（Future Work 段落聚合）依赖全文，但全文覆盖率天然有限，
因此设计三级降级并显式标注证据等级，避免用低质量证据冒充高置信结论：

    L1  arXiv HTML / ar5iv  ->  按 <section> 抽取结构化章节（置信度最高）
    L2  PDF 文本层          ->  按标题行切分章节
    L3  摘要 + TLDR         ->  仅做语义级判断，不参与置信度加权
"""

import io
import re

import httpx
from bs4 import BeautifulSoup

from app.common.text import strip_html
from app.config import get_settings
from app.schemas.paper import Paper
from app.sources.base import FullText, RateLimiter

AR5IV_URL = "https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
ARXIV_HTML_URL = "https://arxiv.org/html/{arxiv_id}"
PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"

LIMITATION_KEYWORDS = ("limitation", "limitations", "discussion", "局限", "不足")
FUTURE_KEYWORDS = (
    "future work",
    "future direction",
    "future research",
    "conclusion",
    "outlook",
    "展望",
    "未来",
)

_MIN_SECTION_LEN = 60
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_MAX_PDF_PAGES = 40
_PDF_SECTION_CHARS = 6000

# 只保留与"局限 / 展望"相关的章节，其余章节对信号 A 无贡献且会放大计算量
_SECTION_HEADING_RE = re.compile(
    r"^\s*(?:\d+\.?\s*)?"
    r"(limitation|limitations|future work|future direction|future research|"
    r"conclusion|conclusions|discussion|outlook)\b",
    re.IGNORECASE | re.MULTILINE,
)


class FullTextFetcher:
    """全文抓取器：独立限流 + 三级降级。

    为什么独立于数据源适配器的限流：ar5iv 与 arXiv API 是两个不同服务。
    arXiv API 要求 3-5 秒的礼貌间隔，而 ar5iv 是静态 HTML 站点，
    沿用 API 的间隔会让几十篇论文的抓取耗时膨胀到数分钟而不可用。
    这里改用独立且更宽松的间隔，同时保持基本的站点礼貌。
    """

    def __init__(self, min_interval: float | None = None) -> None:
        self._settings = get_settings()
        interval = (
            min_interval
            if min_interval is not None
            else self._settings.fulltext_min_interval
        )
        self._limiter = RateLimiter(interval)
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._settings.http_timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": f"GapScout/0.1 (mailto:{self._settings.contact_email})"
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def fetch(self, paper: Paper) -> FullText:
        arxiv_id = paper.arxiv_id or (paper.source_id if paper.source == "arxiv" else None)
        if arxiv_id:
            result = await self._try_html(arxiv_id, paper)
            if result is not None:
                return result
        result = await self._try_pdf(paper)
        if result is not None:
            return result
        return self._abstract_level(paper)

    async def _get(self, url: str) -> httpx.Response | None:
        await self._limiter.acquire()
        try:
            response = await self.client.get(url)
            if response.status_code == 429:
                # 触发限流：动态放慢后续请求。
                # 这是"放宽初始间隔"能够成立的前提——被拒后会自动退让；
                # 否则一旦触发限流就会持续被拒，反而比保守间隔更慢。
                self._limiter.slow_down()
                print("[fulltext] 触发限流(429)，已自动放慢抓取间隔")
                return None
            return response if response.status_code == 200 else None
        except Exception as exc:  # noqa: BLE001
            print(f"[fulltext] 抓取失败 {type(exc).__name__}: {exc}")
            return None

    async def _try_html(self, arxiv_id: str, paper: Paper) -> FullText | None:
        for template in (AR5IV_URL, ARXIV_HTML_URL):
            url = template.format(arxiv_id=arxiv_id)
            response = await self._get(url)
            if response is None:
                continue
            sections = parse_html_sections(response.text)
            if sections:
                return FullText(
                    uid=paper.uid,
                    text="\n\n".join(sections.values()),
                    sections=sections,
                    level="L1",
                    source_url=url,
                )
        return None

    async def _try_pdf(self, paper: Paper) -> FullText | None:
        url = paper.pdf_url
        if not url and paper.arxiv_id:
            url = PDF_URL.format(arxiv_id=paper.arxiv_id)
        if not url:
            return None
        response = await self._get(url)
        if response is None or not response.content:
            return None
        text = extract_pdf_text(response.content)
        if len(text) < _MIN_SECTION_LEN:
            return None
        return FullText(
            uid=paper.uid,
            text=text,
            sections=split_pdf_sections(text),
            level="L2",
            source_url=url,
        )

    @staticmethod
    def _abstract_level(paper: Paper) -> FullText:
        text = paper.abstract_or_tldr
        sections = {"abstract": text} if text else {}
        return FullText(uid=paper.uid, text=text, sections=sections, level="L3")


def extract_pdf_text(content: bytes) -> str:
    """用 pypdf 提取 PDF 文本层（不依赖需要编译的二进制库）。"""
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001
        print(f"[fulltext] PDF 解析失败: {type(exc).__name__}: {exc}")
        return ""

    chunks: list[str] = []
    for page in reader.pages[:_MAX_PDF_PAGES]:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(chunks)


def split_pdf_sections(text: str) -> dict[str, str]:
    """按标题行切分 PDF 文本，只保留局限 / 展望相关章节。"""
    if not text:
        return {}
    matches = list(_SECTION_HEADING_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else min(len(text), start + _PDF_SECTION_CHARS)
        )
        name = match.group(1).lower()
        body = strip_html(text[start:end])
        if len(body) >= _MIN_SECTION_LEN:
            sections.setdefault(name, body)
    return sections


def parse_html_sections(html: str) -> dict[str, str]:
    """从 arXiv HTML 抽取章节：优先 <section> 结构，退化为标题标签切分。"""
    soup = BeautifulSoup(html, "lxml")
    sections: dict[str, str] = {}

    top_sections = [
        node for node in soup.find_all("section") if node.find_parent("section") is None
    ]
    for node in top_sections:
        heading = node.find(_HEADING_TAGS)
        if heading is None:
            continue
        name = strip_html(heading.get_text(" ", strip=True))
        body = strip_html(node.get_text(" ", strip=True))
        if name and len(body) >= _MIN_SECTION_LEN:
            sections[name] = body

    if not sections:
        sections = _parse_by_heading(soup)
    return sections


def _parse_by_heading(soup: BeautifulSoup) -> dict[str, str]:
    """退化路径：按 h2/h3 标题切分同级内容。"""
    sections: dict[str, str] = {}
    for heading in soup.find_all(["h2", "h3"]):
        name = strip_html(heading.get_text(" ", strip=True))
        if not name:
            continue
        chunks: list[str] = []
        for sibling in heading.find_next_siblings():
            if sibling.name in {"h1", "h2", "h3"}:
                break
            chunks.append(sibling.get_text(" ", strip=True))
        body = strip_html(" ".join(chunks))
        if len(body) >= _MIN_SECTION_LEN:
            sections[name] = body
    return sections


def pick_evidence_sections(fulltext: FullText) -> dict[str, str]:
    """定位局限与未来工作章节，作为信号 A 的输入。

    返回键为 limitation / future，缺失则不含该键，调用方据此判断证据等级。
    """
    picked: dict[str, str] = {}
    for name, content in fulltext.sections.items():
        lowered = name.lower()
        if "limitation" not in picked and any(kw in lowered for kw in LIMITATION_KEYWORDS):
            picked["limitation"] = content
        if "future" not in picked and any(kw in lowered for kw in FUTURE_KEYWORDS):
            picked["future"] = content
    return picked


def split_sentences(text: str, max_sentences: int = 12) -> list[str]:
    """把章节正文切成句子，用于未来工作陈述的聚类。"""
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", normalized)
    sentences = [p.strip() for p in parts if len(p.strip()) >= 30]
    return sentences[:max_sentences]
