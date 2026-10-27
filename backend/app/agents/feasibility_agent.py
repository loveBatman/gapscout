"""选题可行性评估 Agent（M3）。

回答开题阶段最恐惧的问题："费半年做出来，会不会发现别人已经发过了？"

两段式设计：
1. 规则层：把想法解析为结构化表示，做定向检索与相似度计算，
   产出可量化的新颖性分布与撞车清单（确定性、可复现）
2. LLM 层：在规则层结果之上做差异点分析与切入角度建议（需要语义判断的部分）

没有 LLM 时规则层结论依然完整，只是缺少语言化的建议。
"""

from dataclasses import dataclass, field

from app.agents.llm import LLMClient
from app.schemas.analysis import SimilarWork

PARSE_SYSTEM = """你是科研选题分析助手。把用户的研究想法解析为结构化要素。
要求：
- task: 要解决的核心任务或问题（中文，15 字内）
- method: 拟采用的技术路线（中文，15 字内）
- scene: 应用场景或数据模态（中文，15 字内）
- english_terms: 3 到 6 个用于学术检索的英文关键词
- english_probe: 用一句话完整描述该研究想法（英文，25 词以内），
  要把方法、任务、场景组织成一个完整命题，而不是关键词堆砌
只输出 JSON：{"task":"...","method":"...","scene":"...","english_terms":["..."],"english_probe":"..."}"""

ANALYZE_SYSTEM = """你是资深科研评审，负责评估一个选题的可行性与撞车风险。

基于给定的已有工作清单，请给出：
- difference_hints: 对每篇最相似工作，用一句话说明它与用户想法的关键差异（数组，与输入顺序一致）
- suggestions: 2 到 4 条具体建议（如何调整范围以提升新颖性、可复现性等）
- risks: 2 到 4 条风险提示
- verdict: 一句话总结这个选题是否值得推进

只输出 JSON：{"difference_hints":["..."],"suggestions":["..."],"risks":["..."],"verdict":"..."}"""

# 相似度分档阈值。
# 标定依据：bge-small-en-v1.5 在"一句话想法 vs 论文摘要"这种长度与文体都不对等的
# 比较中，整体相似度尺度偏低（实测高度相关约 0.62-0.70，弱相关 0.45-0.55），
# 沿用 0.72 这类按等长文本设定的阈值会导致新颖性恒被高估。
HIGH_SIMILARITY = 0.66
MEDIUM_SIMILARITY = 0.57


@dataclass
class NoveltyAssessment:
    score: float | None
    level: str
    basis: str
    similar_count: int = 0
    recent_similar: int = 0
    details: dict = field(default_factory=dict)


def assess_novelty(
    similarities: list[float],
    years: list[int | None],
    current_year: int,
    *,
    probe_reliable: bool = True,
) -> NoveltyAssessment:
    """由相似度分布推导新颖性。

    设计依据一：单看"最高相似度"容易被一篇措辞接近但实质不同的论文误导，
    因此同时看高分论文的数量占比与近期占比。

    设计依据二（重要的方法论限制）：只有当 probe 是"完整意图描述"时，
    相似度才具备可比性。若 probe 由检索术语拼接而成，则构成循环论证——
    检索就是用这些术语做的，召回结果自然与该 probe 高相似（实测均值达 0.81）。
    因此降级模式下不给出评级，只提供相似工作清单供人工核对，
    避免用一个看似精确、实则不可靠的分数误导用户。
    """
    if not similarities:
        return NoveltyAssessment(
            score=None,
            level="unknown",
            basis="未检索到相关文献，可能是方向较新，也可能是检索词需要调整，建议更换表述重试",
        )

    if not probe_reliable:
        top = max(similarities)
        return NoveltyAssessment(
            score=None,
            level="unknown",
            basis=(
                f"已比对 {len(similarities)} 篇相关工作（最高相似度 {top:.3f}）。"
                "当前未配置语言模型，无法把中文想法转为完整的英文命题描述，"
                "相似度受检索术语影响存在系统性偏差，因此不给出评级，"
                "请以下方相似工作清单为准做人工核对。"
            ),
            details={"top_similarity": round(top, 4), "probe_degraded": True},
        )

    high = [index for index, value in enumerate(similarities) if value >= HIGH_SIMILARITY]
    medium = [
        index
        for index, value in enumerate(similarities)
        if MEDIUM_SIMILARITY <= value < HIGH_SIMILARITY
    ]
    recent_high = [
        index for index in high if (years[index] or 0) >= current_year - 2
    ]

    # 按占比折扣：1 篇占比 1% 与 20 篇占比 30% 的风险完全不同。
    # 中度相似论文也计入（权重较低）：它们是潜在的撞车对象，不能完全忽略。
    high_ratio = len(high) / len(similarities)
    medium_ratio = len(medium) / len(similarities)
    recent_ratio = len(recent_high) / len(similarities)
    penalty = min(0.75, high_ratio * 2.0 + medium_ratio * 0.9 + recent_ratio * 1.2)
    score = round(max(0.05, 1.0 - penalty), 3)

    if score >= 0.7:
        level = "high"
    elif score >= 0.45:
        level = "medium"
    else:
        level = "low"

    basis = (
        f"共比对 {len(similarities)} 篇相关工作：高度相似 {len(high)} 篇"
        f"（其中近两年 {len(recent_high)} 篇），中度相似 {len(medium)} 篇。"
    )
    return NoveltyAssessment(
        score=score,
        level=level,
        basis=basis,
        similar_count=len(high),
        recent_similar=len(recent_high),
        details={
            "high_similarity": len(high),
            "medium_similarity": len(medium),
            "recent_high": len(recent_high),
            "top_similarity": round(max(similarities), 4),
        },
    )


async def parse_idea(idea: str, llm: LLMClient) -> dict:
    """把自然语言想法解析为结构化要素（用于检索与展示）。"""
    if llm.available:
        payload = await llm.complete_json(
            f"研究想法：{idea}", system=PARSE_SYSTEM, model=llm.cheap_model
        )
        if payload:
            terms = payload.get("english_terms")
            return {
                "task": _text(payload.get("task")),
                "method": _text(payload.get("method")),
                "scene": _text(payload.get("scene")),
                "english_terms": [str(t).strip() for t in terms if str(t).strip()][:6]
                if isinstance(terms, list)
                else [],
                "english_probe": _text(payload.get("english_probe")),
            }
    # 无 LLM 时保留原始想法作为检索依据，其余维度留空由前端展示为"未解析"
    return {"task": None, "method": None, "scene": None, "english_terms": [], "english_probe": None}


async def enrich_report(
    idea: str,
    similar_works: list[SimilarWork],
    competition: dict,
    llm: LLMClient,
) -> dict:
    """用 LLM 补充差异点分析与建议；不可用时返回规则层的通用提示。"""
    if not llm.available or not similar_works:
        return {
            "difference_hints": [],
            "suggestions": _rule_suggestions(competition),
            "risks": _rule_risks(competition),
            "verdict": None,
        }

    blocks = [
        f"[{index}] {work.year or '-'} | 相似度 {work.similarity:.3f} | {work.title}"
        for index, work in enumerate(similar_works)
    ]
    prompt = (
        f"用户的研究想法：{idea}\n\n"
        f"竞争态势：{competition}\n\n"
        f"最相似的已有工作：\n" + "\n".join(blocks)
    )
    payload = await llm.complete_json(
        prompt, system=ANALYZE_SYSTEM, model=llm.main_model, temperature=0.3
    )
    if not payload:
        return {
            "difference_hints": [],
            "suggestions": _rule_suggestions(competition),
            "risks": _rule_risks(competition),
            "verdict": None,
        }
    return {
        "difference_hints": _str_list(payload.get("difference_hints")),
        "suggestions": _str_list(payload.get("suggestions")) or _rule_suggestions(competition),
        "risks": _str_list(payload.get("risks")) or _rule_risks(competition),
        "verdict": _text(payload.get("verdict")),
    }


def _rule_suggestions(competition: dict) -> list[str]:
    suggestions: list[str] = []
    if competition.get("recent_works", 0) > 5:
        suggestions.append(
            "近两年同类工作较多，建议把范围收窄到具体场景或约束条件，"
            "例如限定特定数据模态、算力预算或评测指标。"
        )
    if competition.get("total", 0) < 20:
        suggestions.append("该方向公开文献较少，建议先确认是否有可用数据集与评测基准，避免无法验证。")
    suggestions.append("建议用上方的相似工作逐一比对，明确写出你与它们的差异点，作为开题的核心论证。")
    return suggestions


def _rule_risks(competition: dict) -> list[str]:
    risks: list[str] = []
    if competition.get("recent_works", 0) > 3:
        risks.append("近两年已有同类工作发表，存在撞车风险。")
    if competition.get("total", 0) < 20:
        risks.append("相关文献总量偏少，可能意味着该方向缺乏关注或已被证明不可行，需谨慎判断。")
    if not risks:
        risks.append("检索仅覆盖公开文献，未发表的在研工作无法被检测到。")
    return risks


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
