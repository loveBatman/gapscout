"""机会点识别 Agent：三路信号融合 + LLM 批判 + 卡片生成。

融合策略：
三路信号先各自转为候选机会点并计算先验分（完全由规则计算，可解释、可复现），
再统一交给 LLM 做价值批判。

为什么必须先有规则层的先验分：直接让大模型"想几个没人做的点"是本项目
明确要避免的做法。规则层保证每个候选都有可追溯的证据来源与量化依据，
LLM 只负责判断价值与可行性，不负责"发明"空白。
"""

import math
import re
from dataclasses import dataclass, field

from app.agents.llm import LLMClient
from app.pipeline.future_work import FutureWorkSignals
from app.pipeline.graph import GraphSignals
from app.pipeline.method_task import MatrixSignals
from app.schemas.analysis import EvidenceRef, GapOut
from app.schemas.paper import Paper

MAX_CANDIDATES = 12
MIN_PRIOR_SCORE = 0.8
# 信号 A 的最小共同提及数：单篇论文的自述证据强度不足，不作为独立机会点
MIN_FUTURE_WORK_SOURCES = 2

SYSTEM_PROMPT = """你是资深科研选题顾问，负责判断一个"研究空白"是否真的值得投入。

判断为伪机会的情况（务必剔除）：
- 已被其他工作间接解决，只是措辞不同
- 缺乏可用数据或评测基准，做出来无法验证
- 属于领域内公认的死胡同（理论不可行或无实际价值）
- 描述过于宽泛，不构成可执行的研究问题

输出要求：
- title 用具体中文，25 字以内，指明问题而非泛泛的方向
- description 说明这个空白是什么，2 到 3 句
- value_note 说明为什么值得做
- feasibility 说明需要什么资源、门槛如何
- risk 说明主要风险或此前无人做成的可能原因
- confidence 为 0 到 1 的置信度

只输出 JSON，不要任何解释：
{"items":[{"index":0,"keep":true,"title":"...","description":"...","value_note":"...","feasibility":"...","risk":"...","confidence":0.7}]}"""

SOURCE_LABELS = {"A": "文献自述", "B": "方法迁移", "C": "图谱结构"}


@dataclass
class Candidate:
    """候选机会点：由规则层产出，携带可追溯的证据。"""

    source: str
    title: str
    description: str
    prior_score: float
    evidence: list[EvidenceRef] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def build_candidates(
    future_work: FutureWorkSignals,
    matrix: MatrixSignals,
    graph: GraphSignals,
    papers: list[Paper],
) -> list[Candidate]:
    """把三路信号统一转为候选机会点，并按先验分排序。"""
    by_uid = {paper.uid: paper for paper in papers}
    candidates: list[Candidate] = []

    # ---------- 信号 A：论文自述的未解决问题 ----------
    for cluster in future_work.clusters:
        # 多篇论文独立提及同一问题，才构成"共同指出"的强证据
        if cluster["source_count"] < MIN_FUTURE_WORK_SOURCES:
            continue
        # 证据按论文去重：同一篇论文可能对该簇贡献多条陈述，重复列出会误导"支持篇数"
        seen: set[str] = set()
        evidence: list[EvidenceRef] = []
        for item in _statement_items(cluster):
            uid = item["uid"]
            if uid in seen or uid not in by_uid:
                continue
            seen.add(uid)
            evidence.append(
                _evidence(
                    by_uid[uid],
                    quote=item["text"],
                    signal="A",
                    level=item.get("level", cluster["level"]),
                )
            )
            if len(evidence) >= 4:
                break
        if not evidence:
            continue
        candidates.append(
            Candidate(
                source="A",
                title=_compact_title(cluster["label"]),
                description=(
                    f"{cluster['source_count']} 篇论文独立指出同一未解决问题："
                    f"{cluster['label']}"
                ),
                prior_score=round(
                    cluster["source_count"]
                    * cluster["evidence_weight"]
                    * (0.5 + cluster["gap_strength"]),
                    3,
                ),
                evidence=evidence,
                raw=cluster,
            )
        )

    # ---------- 信号 B：方法-任务矩阵空格 ----------
    for cell in matrix.gap_cells:
        candidates.append(
            Candidate(
                source="B",
                title=f"{cell['method']} 尚未用于{cell['task']}",
                description=(
                    f"矩阵显示「{cell['task']}」×「{cell['method']}」的组合为空，"
                    f"但该任务与该方法各自的平均活跃度达 {cell['task_activity']} 与 "
                    f"{cell['method_activity']}，说明两端都在发展而交叉点尚未被占据。"
                ),
                prior_score=round(math.log1p(cell["neighbor_score"]) * 1.6, 3),
                raw=cell,
            )
        )

    # ---------- 信号 C：引用图谱结构洞 ----------
    for hole in graph.structural_holes:
        candidates.append(
            Candidate(
                source="C",
                title=f"研究群落 {hole['community_a']} 与 {hole['community_b']} 之间缺乏交叉",
                description=(
                    f"两个群落规模分别为 {hole['size_a']} 与 {hole['size_b']} 篇，"
                    f"但相互引用仅 {hole['edges']} 条（密度 {hole['density']}），"
                    f"存在跨领域方法融合的空间。"
                ),
                prior_score=round(math.log1p(hole["potential"]) * 1.1, 3),
                raw=hole,
            )
        )

    candidates = [item for item in candidates if item.prior_score >= MIN_PRIOR_SCORE]
    candidates.sort(key=lambda item: -item.prior_score)
    return candidates[:MAX_CANDIDATES]


async def build_gap_cards(
    candidates: list[Candidate],
    llm: LLMClient,
    *,
    direction: str,
    topic_labels: list[str],
) -> list[GapOut]:
    """生成机会点卡片：有 LLM 时做价值批判，否则用规则层结果直出。"""
    if not candidates:
        return []
    if llm.available:
        critiqued = await _critique(candidates, llm, direction, topic_labels)
        if critiqued:
            return critiqued
    return [_fallback(candidate) for candidate in candidates]


async def _critique(
    candidates: list[Candidate],
    llm: LLMClient,
    direction: str,
    topic_labels: list[str],
) -> list[GapOut] | None:
    blocks: list[str] = []
    for index, candidate in enumerate(candidates):
        evidence_text = " | ".join(item.title[:70] for item in candidate.evidence[:3]) or "无直接证据"
        blocks.append(
            f"[{index}] 信号来源: {SOURCE_LABELS.get(candidate.source, candidate.source)}\n"
            f"    候选描述: {candidate.description[:280]}\n"
            f"    支撑论文: {evidence_text}"
        )

    prompt = (
        f"研究方向：{direction}\n"
        f"该方向已识别出的主题：{'、'.join(topic_labels[:8]) or '无'}\n\n"
        f"以下是 {len(candidates)} 个候选研究空白，请逐个判断是否值得做。\n\n"
        + "\n".join(blocks)
    )

    payload = await llm.complete_json(
        prompt, system=SYSTEM_PROMPT, model=llm.main_model, temperature=0.3
    )
    if not payload:
        return None

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None

    decisions: dict[int, dict] = {
        int(item["index"]): item
        for item in items
        if isinstance(item, dict) and isinstance(item.get("index"), int)
    }

    cards: list[GapOut] = []
    for index, candidate in enumerate(candidates):
        decision = decisions.get(index)
        if decision is None:
            cards.append(_fallback(candidate))
            continue
        if decision.get("keep") is False:
            # LLM 判定为伪机会：直接剔除，宁缺勿滥
            continue
        cards.append(
            GapOut(
                title=_text(decision.get("title")) or candidate.title,
                description=_text(decision.get("description")) or candidate.description,
                signals=[candidate.source],
                evidence=candidate.evidence,
                value_note=_text(decision.get("value_note")),
                feasibility=_text(decision.get("feasibility")),
                risk=_text(decision.get("risk")),
                novelty=round(float(candidate.prior_score), 3),
                confidence=_confidence(decision.get("confidence")),
            )
        )
    return cards or None


def _fallback(candidate: Candidate) -> GapOut:
    return GapOut(
        title=candidate.title,
        description=candidate.description,
        signals=[candidate.source],
        evidence=candidate.evidence,
        novelty=round(candidate.prior_score, 3),
        confidence=round(min(0.85, 0.35 + candidate.prior_score / 12), 3),
    )


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _confidence(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(1.0, number)), 3)


def _evidence(
    paper: Paper, *, quote: str | None, signal: str, level: str
) -> EvidenceRef:
    return EvidenceRef(
        uid=paper.uid,
        title=paper.title,
        year=paper.year,
        venue=paper.display_venue,
        url=paper.web_url(),
        quote=quote,
        level=level,
        signal=signal,
    )


def _statement_items(cluster: dict) -> list[dict]:
    """取出陈述与其来源论文的对应关系，保证引用能精确指回出处。"""
    items = cluster.get("statement_items")
    if isinstance(items, list) and items:
        return [item for item in items if isinstance(item, dict) and item.get("uid")]
    # 兼容旧结构：只有文本时退化为不带出处的引用
    return [
        {"uid": uid, "text": "", "level": cluster.get("level")}
        for uid in cluster.get("source_uids", [])
    ]


def _compact_title(text: str, limit: int = 46) -> str:
    """把长篇陈述压成可读标题。

    无 LLM 时标题直接取自论文原文，虽然不如人工命名精炼，
    但保证"标题即证据"，不会出现模型编造的概念。
    """
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    cleaned = cleaned.strip(" .,;:-")
    if not cleaned:
        return "未标注的未解决问题"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "…"
