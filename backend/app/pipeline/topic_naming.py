"""主题命名：c-TF-IDF 关键词抽取。

为什么需要 c-TF-IDF：传统 TF-IDF 针对单篇文档，无法给出"簇级"标签。
c-TF-IDF（class-based TF-IDF，BERTopic 的核心机制）把每个簇视为一篇文档，
从而得到对簇最具区分度的关键词。

这条路不依赖 LLM，结果稳定、可复现、零成本，是主题命名的基础层；
LLM 只在其之上做语义化润色（见 agents/topic_naming.py）。
"""

from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer


@dataclass
class ClusterKeywords:
    label: int
    keywords: list[str]
    size: int


def ctfidf_keywords(
    documents: list[str],
    labels: np.ndarray,
    top_k: int = 8,
    ngram_range: tuple[int, int] = (1, 2),
) -> dict[int, ClusterKeywords]:
    """为每个簇抽取区分度最高的关键词。"""
    cluster_ids = sorted({int(x) for x in labels if x >= 0})
    if not cluster_ids or not documents:
        return {}

    class_docs: list[str] = []
    sizes: list[int] = []
    for cluster_id in cluster_ids:
        indices = np.where(labels == cluster_id)[0]
        class_docs.append(" ".join(documents[i] for i in indices))
        sizes.append(int(indices.size))

    vectorizer = CountVectorizer(
        stop_words="english",
        max_features=30000,
        ngram_range=ngram_range,
        min_df=1,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9\-\+]{2,}\b",
    )
    counts = vectorizer.fit_transform(class_docs)

    # 转稠密矩阵：簇数只有个位数、词汇量万级，规模完全可控（几百 KB），
    # 同时避开 scipy 稀疏矩阵不支持 keepdims 等 numpy 接口的问题
    matrix = np.asarray(counts.todense(), dtype=np.float32)

    # 类内词频：归一化为占比，避免大簇因文档多而占优
    term_freq = matrix / np.maximum(matrix.sum(axis=1, keepdims=True), 1.0)

    # 逆类频率：在该簇出现但对其他簇区分度低的词降权
    doc_freq = (matrix > 0).sum(axis=0)
    inverse_freq = np.log(1.0 + len(class_docs) / np.maximum(doc_freq, 1))

    scores = term_freq * inverse_freq
    vocabulary = vectorizer.get_feature_names_out()

    result: dict[int, ClusterKeywords] = {}
    for row, cluster_id in enumerate(cluster_ids):
        order = np.argsort(-scores[row])[: top_k * 3]
        picked: list[str] = []
        for index in order:
            if scores[row][index] <= 0:
                continue
            term = str(vocabulary[index])
            # 过滤被更长短语包含的短词，让标签更具体
            if any(term in existing for existing in picked):
                continue
            picked.append(term)
            if len(picked) >= top_k:
                break
        result[cluster_id] = ClusterKeywords(
            label=cluster_id, keywords=picked, size=sizes[row]
        )
    return result


def heuristic_label(keywords: list[str]) -> str:
    """无 LLM 时用关键词拼接出可读标签。"""
    if not keywords:
        return "未命名主题"
    head = [word for word in keywords[:3]]
    return " / ".join(word.title() for word in head)
