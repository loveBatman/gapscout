"""中文到英文的领域术语映射：无 LLM 时支撑中文方向检索。

定位说明（重要）：
这不是通用翻译器，而是覆盖计算机 / AI 领域高频术语的映射表。
存在意义是让未配置 LLM 的用户也能用中文输入——否则只能得到"请改用英文"
这种把问题推回给用户的提示。

实测背景：直接拿中文去检索 OpenAlex 时，整句只召回 1 篇文献；
换成由本表映射出的英文术语后，可召回上百篇相关论文。
配置 LLM 后会改走语义翻译，覆盖范围更广。
"""

ZH_EN_TERMS: dict[str, str] = {
    # 模型与架构
    "多模态大语言模型": "multimodal large language model",
    "多模态大模型": "multimodal large language model",
    "大语言模型": "large language model",
    "语言模型": "language model",
    "视觉语言模型": "vision language model",
    "扩散模型": "diffusion model",
    "图神经网络": "graph neural network",
    "状态空间模型": "state space model",
    "专家混合": "mixture of experts",
    "变换器": "transformer",
    "注意力机制": "attention mechanism",
    "智能体": "agent",
    # 任务
    "推理加速": "inference acceleration",
    "推理效率": "inference efficiency",
    "高效推理": "efficient inference",
    "推理": "inference",
    "加速": "acceleration",
    "压缩": "compression",
    "量化": "quantization",
    "剪枝": "pruning",
    "蒸馏": "distillation",
    "检索增强生成": "retrieval augmented generation",
    "检索增强": "retrieval augmented generation",
    "检索": "retrieval",
    "对齐": "alignment",
    "微调": "fine-tuning",
    "提示学习": "prompt learning",
    "生成": "generation",
    "分割": "segmentation",
    "检测": "detection",
    "分类": "classification",
    "问答": "question answering",
    "摘要": "summarization",
    "翻译": "translation",
    "推荐": "recommendation",
    "代码生成": "code generation",
    "评测": "evaluation",
    "基准": "benchmark",
    "数据集": "dataset",
    # 模态
    "多模态": "multimodal",
    "视觉": "vision",
    "图像": "image",
    "视频": "video",
    "语音": "speech",
    "音频": "audio",
    "文本": "text",
    "三维点云": "point cloud",
    "表格": "tabular",
    # 领域与方法
    "强化学习": "reinforcement learning",
    "联邦学习": "federated learning",
    "元学习": "meta learning",
    "对比学习": "contrastive learning",
    "知识图谱": "knowledge graph",
    "长上下文": "long context",
    "幻觉": "hallucination",
    "思维链": "chain of thought",
    "参数高效": "parameter efficient",
    "低秩适配": "low-rank adaptation",
    "注意力稀疏": "sparse attention",
    "键值缓存": "kv cache",
    "视觉令牌": "visual token",
    "令牌压缩": "token compression",
    "稀疏": "sparse",
    "显存": "memory footprint",
    "吞吐": "throughput",
    "延迟": "latency",
    "边缘部署": "edge deployment",
    "端侧": "on-device",
    "轻量化": "lightweight",
    "高效": "efficient",
    # 应用场景
    "医疗": "medical",
    "健康": "health",
    "教育": "education",
    "具身智能": "embodied intelligence",
    "机器人": "robotics",
    "自动驾驶": "autonomous driving",
    "遥感": "remote sensing",
    "安全": "safety",
    "隐私": "privacy",
    "鲁棒性": "robustness",
    "公平性": "fairness",
    "可解释": "explainability",
    "误导": "misinformation",
    "合规": "compliance",
}


def translate_zh_terms(text: str, limit: int = 6) -> list[str]:
    """从中文文本抽取英文检索术语。

    实现要点：按词条长度降序匹配并记录已占用区间，
    避免"大语言模型"被"语言模型"提前截断而产生语义偏移。
    """
    if not text:
        return []

    found: list[tuple[int, str]] = []
    occupied: list[tuple[int, int]] = []

    for zh in sorted(ZH_EN_TERMS, key=len, reverse=True):
        start = 0
        while True:
            index = text.find(zh, start)
            if index < 0:
                break
            end = index + len(zh)
            start = end
            if any(left < end and index < right for left, right in occupied):
                continue
            occupied.append((index, end))
            found.append((index, ZH_EN_TERMS[zh]))

    found.sort(key=lambda item: item[0])
    unique: list[str] = []
    for _, term in found:
        if term not in unique:
            unique.append(term)
    return unique[:limit]
