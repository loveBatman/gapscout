"""方法-任务矩阵（信号 B）。

抽取每篇论文的 (任务, 方法族, 数据模态) 三元组，构建组合矩阵，
定位"尚未被验证的组合"——尤其关注**空格但邻域活跃**的格子，
这类空白具备可迁移性，比纯粹的无人区更可能是真机会。

抽取策略：受控词表匹配（确定性、可解释、零成本）。
有 LLM 时可用 agents 层做结构化抽取并回填到同一词表，
两条路径产出同一结构，便于对比评测。
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from app.schemas.paper import Paper

# 受控词表：每个方法族对应一组可识别的表述
METHOD_FAMILIES: dict[str, tuple[str, ...]] = {
    "Transformer": ("transformer", "self-attention", "attention mechanism"),
    "CNN": ("convolutional", "convnet", "resnet", "cnn"),
    "GNN": ("graph neural", "gnn", "message passing"),
    "Diffusion": ("diffusion model", "denoising diffusion", "ddpm", "stable diffusion"),
    "MoE": ("mixture of experts", "mixture-of-experts", "moe"),
    "LoRA": ("lora", "low-rank adaptation", "peft"),
    "RLHF": ("rlhf", "reinforcement learning from human feedback"),
    "Prompt": ("prompt tuning", "prompt engineering", "in-context learning", "prefix tuning"),
    "RAG": ("retrieval-augmented", "retrieval augmented", "rag"),
    "Distillation": ("distillation", "teacher-student"),
    "Quantization": ("quantization", "int8", "int4", "low-bit"),
    "Pruning": ("pruning", "sparsity", "sparse"),
    "TokenCompression": ("token compression", "token pruning", "visual token", "token reduction"),
    "CoT": ("chain-of-thought", "chain of thought", "step-by-step reasoning"),
    "Contrastive": ("contrastive learning", "clip", "contrastive"),
    "Federated": ("federated learning", "federated"),
    "MetaLearning": ("meta-learning", "few-shot learning", "meta learning"),
    "GAN": ("generative adversarial", "gan"),
    "StateSpace": ("state space model", "mamba", "ssm"),
    "Reinforcement": ("reinforcement learning", "policy gradient", "ppo", "dpo"),
}

TASK_TYPES: dict[str, tuple[str, ...]] = {
    "分类": ("classification", "classifier", "categorization"),
    "检测": ("detection", "detector", "localization"),
    "分割": ("segmentation", "segment"),
    "生成": ("generation", "generative", "synthesis"),
    "推理": ("reasoning", "inference chain", "logical"),
    "检索": ("retrieval", "search", "ranking"),
    "压缩加速": ("compression", "acceleration", "efficiency", "latency", "throughput"),
    "问答": ("question answering", "qa", "vqa"),
    "翻译": ("translation", "multilingual"),
    "摘要": ("summarization", "summarisation"),
    "推荐": ("recommendation", "recommender"),
    "代码生成": ("code generation", "program synthesis", "code completion"),
    "对齐": ("alignment", "safety", "helpful", "harmless"),
    "评测": ("benchmark", "evaluation", "evaluate"),
    "理解": ("understanding", "comprehension", "grounding"),
}

MODALITIES: dict[str, tuple[str, ...]] = {
    "文本": ("text", "language", "nlp", "linguistic"),
    "图像": ("image", "vision", "visual", "pixel"),
    "视频": ("video", "temporal", "frame"),
    "音频": ("audio", "speech", "acoustic"),
    "图结构": ("graph", "node", "edge", "molecular"),
    "三维": ("3d", "point cloud", "mesh"),
}

_TOP_PER_DIMENSION = 3


@dataclass
class MatrixSignals:
    tasks: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    matrix: list[list[int]] = field(default_factory=list)
    gap_cells: list[dict] = field(default_factory=list)
    coverage: float = 0.0  # 被成功抽取三元组的论文占比
    top_pairs: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "tasks": self.tasks,
            "methods": self.methods,
            "matrix": self.matrix,
            "gap_cells": self.gap_cells,
            "extraction_coverage": round(self.coverage, 3),
            "top_pairs": self.top_pairs,
        }


def extract_dimensions(paper: Paper) -> dict[str, list[str]]:
    """从标题与摘要中抽取任务、方法、模态。"""
    text = f"{paper.title or ''} {paper.abstract_or_tldr or ''}".lower()
    return {
        "tasks": _match(text, TASK_TYPES),
        "methods": _match(text, METHOD_FAMILIES),
        "modalities": _match(text, MODALITIES),
    }


def _match(text: str, vocabulary: dict[str, tuple[str, ...]]) -> list[str]:
    hits: list[tuple[str, int]] = []
    for label, patterns in vocabulary.items():
        score = sum(1 for pattern in patterns if pattern in text)
        if score > 0:
            hits.append((label, score))
    hits.sort(key=lambda item: -item[1])
    return [label for label, _ in hits[: _TOP_PER_DIMENSION]]


def analyze_matrix(papers: list[Paper], min_neighbors: int = 3) -> MatrixSignals:
    """构建任务×方法矩阵并定位空格。"""
    signals = MatrixSignals()
    if not papers:
        return signals

    pair_counter: Counter = Counter()
    task_counter: Counter = Counter()
    method_counter: Counter = Counter()
    pair_papers: dict[tuple[str, str], list[Paper]] = defaultdict(list)
    extracted = 0

    for paper in papers:
        dims = extract_dimensions(paper)
        if not dims["tasks"] or not dims["methods"]:
            continue
        extracted += 1
        for task in dims["tasks"]:
            task_counter[task] += 1
            for method in dims["methods"]:
                pair_counter[(task, method)] += 1
                pair_papers[(task, method)].append(paper)
        for method in dims["methods"]:
            method_counter[method] += 1

    signals.coverage = extracted / len(papers)

    # 只保留出现频次足够的任务与方法，避免长尾把矩阵撑得过稀
    tasks = [name for name, count in task_counter.most_common(10) if count >= 3]
    methods = [name for name, count in method_counter.most_common(10) if count >= 3]
    if not tasks or not methods:
        return signals

    signals.tasks = tasks
    signals.methods = methods
    matrix = [[pair_counter.get((task, method), 0) for method in methods] for task in tasks]
    signals.matrix = matrix

    signals.top_pairs = [
        {"task": task, "method": method, "count": count}
        for (task, method), count in pair_counter.most_common(8)
    ]
    signals.gap_cells = _gap_cells(matrix, tasks, methods, pair_papers, min_neighbors)
    return signals


def _gap_cells(
    matrix: list[list[int]],
    tasks: list[str],
    methods: list[str],
    pair_papers: dict[tuple[str, str], list[Paper]],
    min_neighbors: int,
) -> list[dict]:
    """空格 + 邻域活跃 = 有迁移价值的空白。

    邻域活跃度取该格子同行与同列的均值：如果某个任务在其他方法上很热，
    或某个方法在其他任务上很热，那么它们的交叉点空缺就更值得关注。
    """
    array = np.asarray(matrix, dtype=np.float32)
    row_mean = array.mean(axis=1)
    column_mean = array.mean(axis=0)

    cells: list[dict] = []
    for row, task in enumerate(tasks):
        for column, method in enumerate(methods):
            if array[row][column] > 0:
                continue
            neighbor_score = float((row_mean[row] + column_mean[column]) / 2)
            if neighbor_score < min_neighbors:
                continue
            cells.append(
                {
                    "task": task,
                    "method": method,
                    "neighbor_score": round(neighbor_score, 2),
                    "task_activity": round(float(row_mean[row]), 2),
                    "method_activity": round(float(column_mean[column]), 2),
                    "active_papers": len(pair_papers.get((task, method), [])),
                }
            )

    cells.sort(key=lambda item: -item["neighbor_score"])
    return cells[:8]
