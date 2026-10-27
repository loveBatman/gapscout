"""主题命名与描述：c-TF-IDF 打底 + LLM 语义润色。

两级设计的原因：
1. c-TF-IDF 是确定性的，LLM 不可用时依然能产出可读标签，链路不中断
2. LLM 负责把关键词组合成学术语义准确的标签，并总结核心问题与主流方法

所有主题一次性提交给 LLM（而非逐簇调用），把 token 成本压到最低。
"""

from dataclasses import dataclass

from app.agents.llm import LLMClient
from app.pipeline.topic_naming import heuristic_label
from app.schemas.analysis import TopicOut

SYSTEM_PROMPT = """你是一名计算机领域的科研助手，擅长把文献聚类结果概括为准确的主题。
要求：
- label 用简洁中文术语，不超过 16 个字，避免"研究""分析""探讨"这类空泛词
- core_problem 说明该主题在解决什么学术问题，一到两句话
- methods 给出 3 到 5 个具体的技术或方法名称
- 只输出 JSON，不要任何额外解释"""


@dataclass
class TopicDraft:
    """主题草稿：聚类结果与关键词的中间载体。"""

    cluster_id: int
    keywords: list[str]
    size: int
    titles: list[str]
    year_from: int | None = None
    year_to: int | None = None
    trend_slope: float | None = None


async def name_topics(
    drafts: list[TopicDraft], llm: LLMClient, *, direction: str
) -> list[TopicOut]:
    if not drafts:
        return []
    if llm.available:
        named = await _name_with_llm(drafts, llm, direction)
        if named:
            return named
    return [_fallback(draft) for draft in drafts]


async def _name_with_llm(
    drafts: list[TopicDraft], llm: LLMClient, direction: str
) -> list[TopicOut] | None:
    blocks: list[str] = []
    for index, draft in enumerate(drafts):
        keywords = ", ".join(draft.keywords[:8]) or "（无）"
        titles = " | ".join(draft.titles[:4]) or "（无）"
        blocks.append(
            f"[{index}] 规模 {draft.size} 篇\n"
            f"    关键词: {keywords}\n"
            f"    代表论文: {titles}"
        )

    prompt = (
        f"研究方向：{direction}\n\n"
        f"以下是对该方向文献聚类得到的 {len(drafts)} 个主题，"
        f"请为每个主题生成中文标签、核心问题与主流方法。\n\n"
        + "\n".join(blocks)
        + "\n\n严格按此 JSON 结构输出："
        '{"topics":[{"index":0,"label":"...","core_problem":"...","methods":["...","..."]}]}'
    )

    payload = await llm.complete_json(
        prompt, system=SYSTEM_PROMPT, model=llm.cheap_model, temperature=0.3
    )
    if not payload:
        return None

    items = payload.get("topics")
    if not isinstance(items, list) or not items:
        return None

    named: dict[int, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < len(drafts):
            named[index] = item

    results: list[TopicOut] = []
    for index, draft in enumerate(drafts):
        info = named.get(index)
        if not info:
            results.append(_fallback(draft))
            continue
        methods = info.get("methods") or []
        results.append(
            TopicOut(
                id=draft.cluster_id,
                label=str(info.get("label") or heuristic_label(draft.keywords)),
                core_problem=_clean(info.get("core_problem")),
                keywords=draft.keywords[:8],
                methods=[str(m) for m in methods][:6],
                size=draft.size,
                trend_slope=draft.trend_slope,
                year_from=draft.year_from,
                year_to=draft.year_to,
            )
        )
    return results


def _fallback(draft: TopicDraft) -> TopicOut:
    return TopicOut(
        id=draft.cluster_id,
        label=heuristic_label(draft.keywords),
        keywords=draft.keywords[:8],
        size=draft.size,
        trend_slope=draft.trend_slope,
        year_from=draft.year_from,
        year_to=draft.year_to,
    )


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
