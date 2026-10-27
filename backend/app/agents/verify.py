"""引用一致性校验（M5 的防幻觉闸门）。

三道检查，从硬到软：
1. 编号白名单 —— 正文引用的编号必须真实存在于文献列表，拦截模型编造的引用
2. 引用覆盖 —— 实质性断言必须带出处，拦截图谱里"看起来像综述"的无源陈述
3. 语义蕴含 —— 判断被引论文是否真的支持该论断，拦截张冠李戴（LLM 可用时）

无 LLM 时只执行前两道（纯规则），并在报告中明确标注语义检查未执行，
避免把"只做了格式检查"包装成"引用已验证"。
"""

import re
from dataclasses import dataclass, field

from app.agents.llm import LLMClient
from app.schemas.paper import Paper

CITATION_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；!?;])\s*")
_MIN_SENTENCE_LEN = 16
MAX_CHECKS_PER_CALL = 20

# 不含这些特征的句子视为过渡句，不要求引用（如"本节首先介绍…"）
_TRANSITION_HINTS = (
    "本节", "下文", "下面", "如下", "接下来", "首先", "其次", "再次", "最后",
    "综上", "总体而言", "总而言之", "如前所述", "以上", "由此可见",
)

JUDGE_SYSTEM = """你是学术引用核查员。判断每条断言是否被其引用的论文所支持。

判断标准：
- supported=true：论文的标题或摘要明确包含支持该断言的信息
- supported=false：论文与断言无关，或信息不足以支撑
- 无法判断时一律判为 false（宁可误报也不要放过）

只输出 JSON：{"items":[{"index":0,"supported":true,"reason":"依据简述"}]}"""


@dataclass
class SentenceCheck:
    text: str
    citations: list[int]
    status: str  # ok / unsupported / missing_citation / invalid_citation / unresolved
    reason: str | None = None
    section: str | None = None


@dataclass
class VerifyReport:
    total_sentences: int = 0
    cited_sentences: int = 0
    missing_citation: list[SentenceCheck] = field(default_factory=list)
    invalid_citations: list[int] = field(default_factory=list)
    checked: int = 0
    passed: int = 0
    failed: int = 0
    unresolved: list[SentenceCheck] = field(default_factory=list)
    semantic_check_skipped: bool = False

    @property
    def pass_rate(self) -> float:
        if self.checked == 0:
            return 0.0
        return round(self.passed / self.checked, 4)

    def as_dict(self) -> dict:
        return {
            "total_sentences": self.total_sentences,
            "cited_sentences": self.cited_sentences,
            "checked": self.checked,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "missing_citation": [
                {"text": item.text[:200], "section": item.section}
                for item in self.missing_citation[:10]
            ],
            "invalid_citations": sorted(set(self.invalid_citations)),
            "unresolved": [
                {"text": item.text[:200], "citations": item.citations, "reason": item.reason}
                for item in self.unresolved[:10]
            ],
            "semantic_check_skipped": self.semantic_check_skipped,
        }


def split_sentences(text: str) -> list[str]:
    return [chunk.strip() for chunk in _SENTENCE_SPLIT_RE.split(text or "") if chunk.strip()]


def parse_citations(sentence: str) -> list[int]:
    """解析句子中的引用编号。

    去重是必要的：模型偶尔会输出 [1][1] 或 [1,1] 这类重复标注，
    不去重会让引用计数虚高，也会让同一条断言被重复核查。
    """
    found: list[int] = []
    for match in CITATION_RE.finditer(sentence):
        for piece in match.group(1).split(","):
            piece = piece.strip()
            if piece.isdigit():
                number = int(piece)
                if number not in found:
                    found.append(number)
    return found


def is_transition_sentence(sentence: str) -> bool:
    return any(hint in sentence for hint in _TRANSITION_HINTS)


async def verify_review(
    sections: list[dict],
    papers: list[Paper],
    llm: LLMClient,
    *,
    max_checks: int = 60,
) -> VerifyReport:
    """执行三道引用检查。"""
    report = VerifyReport()
    valid_range = range(1, len(papers) + 1)
    candidates: list[SentenceCheck] = []

    for section in sections:
        title = str(section.get("title") or "")
        for sentence in split_sentences(str(section.get("content") or "")):
            report.total_sentences += 1
            citations = parse_citations(sentence)
            if not citations:
                # 括号内的说明文字与过渡句不算实质断言
                if len(sentence) >= _MIN_SENTENCE_LEN and not is_transition_sentence(sentence):
                    report.missing_citation.append(
                        SentenceCheck(text=sentence, citations=[], status="missing_citation", section=title)
                    )
                continue

            report.cited_sentences += 1
            invalid = [number for number in citations if number not in valid_range]
            if invalid:
                report.invalid_citations.extend(invalid)
                continue
            candidates.append(
                SentenceCheck(text=sentence, citations=citations, status="unresolved", section=title)
            )

    if not candidates:
        return report

    if not llm.available:
        # 只做了编号与覆盖检查：如实标注，不冒充"引用已通过语义验证"
        report.semantic_check_skipped = True
        report.unresolved = candidates[: max_checks]
        return report

    report.checked = min(len(candidates), max_checks)
    for start in range(0, report.checked, MAX_CHECKS_PER_CALL):
        batch = candidates[start : start + MAX_CHECKS_PER_CALL]
        results = await _judge_batch(batch, papers, llm, offset=start)
        for index, check in enumerate(batch):
            verdict = results.get(start + index)
            if verdict is None:
                report.unresolved.append(check)
                continue
            if verdict.get("supported"):
                report.passed += 1
            else:
                report.failed += 1
                check.status = "unsupported"
                check.reason = str(verdict.get("reason") or "").strip() or None
                report.unresolved.append(check)

    if len(candidates) > report.checked:
        report.unresolved.extend(candidates[report.checked :])
    return report


async def _judge_batch(
    batch: list[SentenceCheck], papers: list[Paper], llm: LLMClient, offset: int = 0
) -> dict[int, dict]:
    blocks: list[str] = []
    for index, check in enumerate(batch):
        # 摘要截断长度必须与撰写时（write_section 用 400 字）保持一致：
        # 若校验时给的摘要更短，撰写阶段依据的那部分内容就会被判成"无依据"，
        # 造成系统性的误报（实测这会让通过率凭空掉一大截）。
        evidence = "\n".join(
            f"    [论文 {number}] {papers[number - 1].title}"
            f"（{papers[number - 1].year or '年份未知'}）："
            f"{(papers[number - 1].abstract_or_tldr or '')[:400]}"
            for number in check.citations
            if 1 <= number <= len(papers)
        )
        blocks.append(f"[{index}] 断言：{check.text[:300]}\n  被引论文：\n{evidence}")

    payload = await llm.complete_json(
        "请逐条核查下列断言的引用是否成立：\n\n" + "\n\n".join(blocks),
        system=JUDGE_SYSTEM,
        model=llm.cheap_model,
        temperature=0.0,
    )
    if not payload or not isinstance(payload.get("items"), list):
        return {}
    # 模型返回的是**批内下标**，加上 offset 才是全局下标。
    # 调用方按全局下标查找，缺了 offset 会让第 2 批及之后的判定全部丢失
    # （实测表现为"20 条判定凭空消失、全部落到未决"）。
    return {
        int(item["index"]) + offset: item
        for item in payload["items"]
        if isinstance(item, dict) and isinstance(item.get("index"), int)
    }
