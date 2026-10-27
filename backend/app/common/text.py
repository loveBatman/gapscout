"""文本工具：标题归一化、内容 hash、HTML 清洗。

这些函数被数据源适配、去重管道、缓存层共同使用，因此独立于 schemas 与 pipeline。
"""

import hashlib
import re
import unicodedata

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]+\s*")
_MATH_INLINE_RE = re.compile(r"\$[^$]{0,240}\$")
_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9\-\+\.]*")
_QUERY_UNSAFE_RE = re.compile(r'["()\[\]:]')

# 仅过滤语法功能词，保留 method / model 这类可能携带信息的实词
STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "for", "and", "or", "to", "in", "on", "with",
        "via", "using", "based", "towards", "toward", "from", "by", "at", "as",
        "is", "are", "be", "been", "was", "were", "we", "our", "its", "it",
        "this", "that", "these", "those", "their", "than", "then", "into",
        "over", "under", "between", "how", "what", "which", "when", "where",
    }
)


def normalize_title(title: str) -> str:
    """标题归一化，作为三级去重中的一级键。

    处理：Unicode 归一化 -> 小写 -> 去公式与 LaTeX 命令 -> 去标点 -> 压缩空白。
    """
    if not title:
        return ""
    text = unicodedata.normalize("NFKC", title).lower()
    text = _MATH_INLINE_RE.sub(" ", text)
    text = _LATEX_CMD_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def sha256_text(*parts: str) -> str:
    """内容级缓存键：相同输入必然命中相同缓存，保证重复分析零成本。"""
    digest = hashlib.sha256()
    for part in parts:
        digest.update((part or "").encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def strip_html(raw: str | None) -> str:
    """清洗 HTML 片段，用于 arXiv / OpenAlex 摘要字段。"""
    if not raw:
        return ""
    text = _HTML_TAG_RE.sub(" ", raw)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return _SPACE_RE.sub(" ", text).strip()


def truncate(text: str, limit: int) -> str:
    if not text or len(text) <= limit:
        return text or ""
    return text[:limit].rstrip() + "..."


def contains_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")


def extract_keywords(text: str, limit: int = 6) -> list[str]:
    """抽取英文实词关键词，用于构造检索表达式。

    实测依据一：arXiv 用整句短语（all:"整句"）检索召回极低，
    必须拆为关键词并用 AND 组合才能获得合理召回量。

    实测依据二：直接用中文检索 OpenAlex 只召回 1 篇文献，
    因此中文输入会先经领域术语映射转为英文（见 app/common/zh_terms.py）。
    配置 LLM 后由查询理解节点做更准确的语义翻译。
    """
    if contains_chinese(text):
        from app.common.zh_terms import translate_zh_terms

        translated = translate_zh_terms(text, limit=limit)
        if translated:
            return translated

    tokens = _TOKEN_RE.findall((text or "").lower())
    picked: list[str] = []
    for token in tokens:
        cleaned = token.strip("-+.")
        if len(cleaned) < 3 or cleaned in STOPWORDS:
            continue
        if cleaned not in picked:
            picked.append(cleaned)
    return picked[:limit]


def sanitize_query_term(term: str) -> str:
    """清洗检索词中的查询语法保留字符，避免破坏 arXiv 查询表达式。"""
    return _SPACE_RE.sub(" ", _QUERY_UNSAFE_RE.sub(" ", term or "")).strip()
