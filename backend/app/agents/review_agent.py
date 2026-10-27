"""综述生成 Agent（M5）：大纲规划与分节撰写。

核心约束（决定整个模块的设计）：
综述里的每一句断言都必须能追溯到真实论文。因此生成流程不是
"给模型一堆摘要让它写"，而是**先定大纲 -> 每节召回证据 -> 基于证据撰写**，
再交给 verify 模块做逐句引用校验。

无 LLM 时退化为"结构化文献梳理"：按主题分节，每节列出代表论文与要点，
不生成自由行文，从而杜绝编造风险。
"""

import json
from dataclasses import dataclass, field

from app.agents.llm import LLMClient
from app.schemas.paper import Paper

OUTLINE_SYSTEM = """你是学术综述写作助手。基于给定的主题聚类与文献信息，规划综述大纲。

要求：
- 章节数量 3 到 6 个，覆盖该方向的主要脉络（可含技术演进、方法对比、挑战与展望）
- 每节给出 title（中文，20 字内）与 focus（该节要论述的核心问题，一句话）
- 章节顺序要符合逻辑递进，而不是简单并列
只输出 JSON：{"title":"综述标题","sections":[{"title":"...","focus":"..."}]}"""

SECTION_SYSTEM = """你是学术综述写作助手。基于给定的文献证据撰写一节综述正文。

严格要求（违反即视为失败）：
- 每一句涉及事实或结论的话，都必须以 [编号] 形式标注来源
- 编号是**全局参考文献序号**，必须原样使用给定文献前的方括号编号，禁止重新编号或自行顺延
- 只能使用给定文献中的信息，禁止补充任何外部知识或推测
- 如果给定文献不足以支撑某个论点，就不要写这个论点
- 输出中文正文，300 到 600 字，使用连贯段落而非罗列
- 只输出正文本身，不要标题、不要额外说明"""

MAX_SECTION_PAPERS = 12
MAX_SECTIONS = 6


@dataclass
class SectionDraft:
    title: str
    focus: str
    paper_indices: list[int] = field(default_factory=list)


@dataclass
class Outline:
    title: str
    sections: list[SectionDraft] = field(default_factory=list)


async def plan_outline(
    papers: list[Paper],
    topics: list[dict],
    llm: LLMClient,
    *,
    direction: str,
) -> Outline:
    """规划综述大纲。LLM 不可用时按主题簇生成结构化小节。"""
    if llm.available:
        outline = await _plan_with_llm(papers, topics, llm, direction)
        if outline is not None:
            return outline
    return _fallback_outline(papers, topics, direction)


async def _plan_with_llm(
    papers: list[Paper],
    topics: list[dict],
    llm: LLMClient,
    direction: str,
) -> Outline | None:
    topic_blocks = [
        f"- {topic.get('label')}（{topic.get('size')} 篇）"
        f"{'：' + str(topic.get('core_problem'))[:120] if topic.get('core_problem') else ''}"
        for topic in topics[:8]
    ]
    prompt = (
        f"研究方向：{direction}\n\n"
        f"该方向的主题聚类结果：\n" + "\n".join(topic_blocks) + "\n\n"
        "请规划一份综述大纲。"
    )
    payload = await llm.complete_json(
        prompt, system=OUTLINE_SYSTEM, model=llm.main_model, temperature=0.3
    )
    if not payload:
        return None

    sections_raw = payload.get("sections")
    if not isinstance(sections_raw, list) or not sections_raw:
        return None

    sections: list[SectionDraft] = []
    for item in sections_raw[:MAX_SECTIONS]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        sections.append(
            SectionDraft(title=title, focus=str(item.get("focus") or "").strip())
        )
    if not sections:
        return None
    return Outline(title=str(payload.get("title") or f"{direction} 研究综述"), sections=sections)


def _fallback_outline(papers: list[Paper], topics: list[dict], direction: str) -> Outline:
    """无 LLM 时按主题簇生成结构化大纲。"""
    sections: list[SectionDraft] = []
    for topic in topics[:MAX_SECTIONS]:
        label = str(topic.get("label") or "").strip()
        if not label:
            continue
        sections.append(
            SectionDraft(
                title=label[:30],
                focus=str(topic.get("core_problem") or "该主题的代表性工作与技术路线").strip(),
            )
        )
    if not sections:
        sections = [
            SectionDraft(title="代表性工作", focus="按时间梳理该方向的关键论文"),
            SectionDraft(title="方法对比", focus="比较不同技术路线的适用场景"),
            SectionDraft(title="挑战与展望", focus="总结现存局限与可能的研究方向"),
        ]
    return Outline(title=f"{direction} 研究综述", sections=sections)


async def write_section(
    section: SectionDraft,
    material: list[tuple[int, Paper]],
    llm: LLMClient,
) -> dict:
    """撰写单节正文。返回 {title, content, citations, mode}。

    material 是 (全局参考文献序号, 论文) 的列表，携带**全局序号**而非本节内序号。
    必要性：正文里写的 [n] 最终要与参考文献列表的序号一致，而逐句引用校验
    正是按全局列表解析编号的。早期实现使用"本节素材内的局部编号"，两者错位后
    校验会把每条断言对到完全不相干的论文上（实测引用校验通过率恒为 0）。
    """
    selected = material[:MAX_SECTION_PAPERS]

    if not llm.available:
        return {
            "title": section.title,
            "content": _structured_summary(section, selected),
            "citations": [number for number, _ in selected],
            "mode": "structured",
        }

    blocks = [
        f"[{number}] {paper.title}（{paper.year or '年份未知'}，"
        f"{paper.display_venue}）\n    {paper.abstract_or_tldr[:400]}"
        for number, paper in selected
    ]
    prompt = (
        f"本节标题：{section.title}\n"
        f"论述重点：{section.focus}\n\n"
        f"可用文献：\n" + "\n".join(blocks) + "\n\n"
        "请撰写本节正文。"
    )
    content = await llm.complete(prompt, system=SECTION_SYSTEM, model=llm.main_model, temperature=0.4)
    if not content:
        return {
            "title": section.title,
            "content": _structured_summary(section, selected),
            "citations": [number for number, _ in selected],
            "mode": "structured",
        }
    return {
        "title": section.title,
        "content": content.strip(),
        "citations": [number for number, _ in selected],
        "mode": "generated",
    }


def _structured_summary(section: SectionDraft, material: list[tuple[int, Paper]]) -> str:
    """无 LLM 时的结构化小节：只罗列事实，不做任何推断。

    这是刻意的保守设计：宁可产出"不像是综述"的结构化清单，
    也不生成无法溯源的自由文本——后者对科研场景是负价值。
    """
    lines = [f"本节聚焦：{section.focus}。", ""]
    for number, paper in material:
        abstract = (paper.abstract_or_tldr or "").strip()
        summary = abstract[:220].rstrip()
        suffix = "……" if len(abstract) > 220 else ""
        lines.append(
            f"[{number}] {paper.title}（{paper.year or '年份未知'}，{paper.display_venue}）"
        )
        if summary:
            lines.append(f"{summary}{suffix}")
        lines.append("")
    lines.append("（本节为结构化文献梳理：未配置语言模型时不做自由行文，以保证每条例证均可溯源。）")
    return "\n".join(lines)


def build_bibtex(papers: list[Paper]) -> str:
    """生成 BibTeX 参考文献条目。"""
    entries: list[str] = []
    used_keys: set[str] = set()
    for index, paper in enumerate(papers, start=1):
        first_author = (paper.authors[0].split()[-1] if paper.authors else "unknown").lower()
        first_author = "".join(ch for ch in first_author if ch.isalnum()) or "unknown"
        base_key = f"{first_author}{paper.year or 'n'}"
        key = base_key
        suffix = 1
        while key in used_keys:
            suffix += 1
            key = f"{base_key}{suffix}"
        used_keys.add(key)

        entry_type = "article" if paper.doi else "misc"
        fields = [
            f"  title = {{{paper.title}}}",
            f"  author = {{{' and '.join(paper.authors[:10]) or 'Unknown'}}}",
        ]
        if paper.year:
            fields.append(f"  year = {{{paper.year}}}")
        if paper.venue:
            fields.append(f"  journal = {{{paper.venue}}}")
        if paper.doi:
            fields.append(f"  doi = {{{paper.doi}}}")
        fields.append(f"  url = {{{paper.web_url()}}}")
        fields.append(f"  note = {{参考文献序号 {index}}}")
        entries.append(f"@{entry_type}{{{key},\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(entries)


def build_citation_json(papers: list[Paper]) -> str:
    """生成便于前端渲染与二次处理的引用数据。"""
    payload = [
        {
            "index": index + 1,
            "uid": paper.uid,
            "title": paper.title,
            "year": paper.year,
            "venue": paper.display_venue,
            "doi": paper.doi,
            "url": paper.web_url(),
            "authors": paper.authors[:6],
        }
        for index, paper in enumerate(papers)
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)
