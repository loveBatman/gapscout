"""引用图谱分析（信号 C）。

从论文的引用关系构建有向图，用社区发现定位研究群落，再通过三个指标寻找机会：

1. 结构洞 —— 两个活跃社区之间缺乏连接，代表跨领域融合机会
2. 新兴簇 —— 近期论文量增长最快的社区，代表正在升温的方向
3. 潜在转折点 —— 引用密度异常高的年轻论文，可能开启新范式

设计取舍：千级节点用 NetworkX 内存计算足够，无需引入 Neo4j，
避免了额外的部署与运维成本（小团队的规模约束）。
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import networkx as nx

from app.schemas.paper import Paper

MIN_COMMUNITY_SIZE = 4
# 社区间边密度低于该值视为"缺乏连接"
MAX_HOLE_DENSITY = 0.02


@dataclass
class GraphSignals:
    n_nodes: int = 0
    n_edges: int = 0
    n_communities: int = 0
    community_sizes: dict[int, int] = field(default_factory=dict)
    structural_holes: list[dict] = field(default_factory=list)
    emerging_communities: list[dict] = field(default_factory=list)
    turning_points: list[dict] = field(default_factory=list)
    coverage: float = 0.0  # 有引用数据的论文占比

    def as_dict(self) -> dict:
        return {
            "n_nodes": self.n_nodes,
            "n_edges": self.n_edges,
            "n_communities": self.n_communities,
            "community_sizes": self.community_sizes,
            "structural_holes": self.structural_holes,
            "emerging_communities": self.emerging_communities,
            "turning_points": self.turning_points,
            "reference_coverage": round(self.coverage, 3),
        }


def build_citation_graph(papers: list[Paper]) -> nx.DiGraph:
    """构建引用图。

    被引论文可能不在本次检索集合内，因此只保留两端都在集合中的边，
    这样社区结构才反映"当前领域的内部连接"。
    """
    alias: dict[str, str] = {}
    for paper in papers:
        for key in (paper.doi, paper.arxiv_id, paper.source_id):
            if key:
                alias[str(key).strip().lower()] = paper.citation_key

    graph = nx.DiGraph()
    graph.add_nodes_from(paper.citation_key for paper in papers)

    for paper in papers:
        for reference in paper.references:
            target = alias.get(str(reference).strip().lower())
            if target and target != paper.citation_key:
                graph.add_edge(paper.citation_key, target)
    return graph


def analyze_graph(
    papers: list[Paper], community_labels: dict[str, int] | None = None
) -> GraphSignals:
    """完整的引用图谱分析入口。

    community_labels 允许复用语义聚类的主题划分作为社区。
    必要性（实测结论）：检索结果通常跨越多个子领域，子领域之间本就少有互引，
    163 篇论文间可能只有个位数引用边。此时 Louvain 会把图切成上百个碎片社区，
    导致结构洞恒为空。改用语义主题作为社区，结构洞才有实际含义：
    "两个活跃研究方向之间缺乏交叉"。
    """
    if not papers:
        return GraphSignals()

    with_refs = sum(1 for paper in papers if paper.references)
    signals = GraphSignals(coverage=with_refs / len(papers))

    graph = build_citation_graph(papers)
    signals.n_nodes = graph.number_of_nodes()
    signals.n_edges = graph.number_of_edges()

    if signals.n_edges == 0:
        # 无引用数据时退化为"潜在转折点"单指标，保证信号 C 仍有输出
        signals.turning_points = _turning_points(papers, {})
        return signals

    communities = community_labels or _detect_communities(graph)
    if not communities:
        signals.turning_points = _turning_points(papers, {})
        return signals

    sizes = Counter(communities.values())
    signals.community_sizes = dict(sizes)
    signals.n_communities = len(sizes)
    signals.structural_holes = _structural_holes(graph, communities, sizes)
    signals.emerging_communities = _emerging_communities(papers, communities)
    signals.turning_points = _turning_points(papers, communities)
    return signals


def _detect_communities(graph: nx.DiGraph) -> dict[str, int]:
    undirected = graph.to_undirected()
    if undirected.number_of_edges() == 0:
        return {}
    try:
        groups = nx.community.louvain_communities(undirected, seed=42)
    except Exception as exc:  # noqa: BLE001
        print(f"[graph] 社区检测失败（{type(exc).__name__}: {exc}）")
        return {}
    return {
        node: index
        for index, group in enumerate(sorted(groups, key=len, reverse=True))
        for node in group
    }


def _structural_holes(
    graph: nx.DiGraph, communities: dict[str, int], sizes: Counter
) -> list[dict]:
    """结构洞：两侧社区都活跃，但彼此几乎不互相引用。

    注意密度阈值：主题级社区的理论最大边数 = size_a × size_b，实际观测到的
    引用边往往只有个位数，因此密度天然极低。这里对"完全无连接"与"连接稀少"
    同等看待，并按 potential（规模乘积）排序，让大主题之间的空白优先浮现。
    """
    active = [cid for cid, size in sizes.items() if size >= MIN_COMMUNITY_SIZE]
    if len(active) < 2:
        return []

    pair_edges: Counter = Counter()
    for source, target in graph.to_undirected().edges():
        left, right = communities.get(source), communities.get(target)
        if left is None or right is None or left == right:
            continue
        pair_edges[(min(left, right), max(left, right))] += 1

    holes: list[dict] = []
    for index, left in enumerate(active):
        for right in active[index + 1 :]:
            possible = sizes[left] * sizes[right]
            if possible == 0:
                continue
            actual = pair_edges.get((min(left, right), max(left, right)), 0)
            density = actual / possible
            if density <= MAX_HOLE_DENSITY:
                holes.append(
                    {
                        "community_a": left,
                        "community_b": right,
                        "size_a": sizes[left],
                        "size_b": sizes[right],
                        "edges": actual,
                        "density": round(density, 5),
                        "potential": sizes[left] * sizes[right],
                    }
                )
    holes.sort(key=lambda item: -item["potential"])
    return holes[:5]


def _emerging_communities(papers: list[Paper], communities: dict[str, int]) -> list[dict]:
    """新兴簇：近期论文占比高、增长斜率大的社区。"""
    from app.pipeline.filter import trend_slope, year_trend

    grouped: dict[int, list[Paper]] = defaultdict(list)
    for paper in papers:
        community = communities.get(paper.citation_key)
        if community is not None:
            grouped[community].append(paper)

    results: list[dict] = []
    for community, members in grouped.items():
        if len(members) < MIN_COMMUNITY_SIZE:
            continue
        trend = year_trend(members)
        slope = trend_slope(trend)
        years = [paper.year for paper in members if paper.year]
        recent = sum(1 for year in years if year >= 2024)
        results.append(
            {
                "community": community,
                "size": len(members),
                "slope": slope,
                "recent_ratio": round(recent / len(years), 3) if years else 0.0,
                "year_from": min(years) if years else None,
                "year_to": max(years) if years else None,
            }
        )
    results.sort(key=lambda item: (-item["slope"], -item["recent_ratio"]))
    return results[:5]


def _turning_points(papers: list[Paper], communities: dict[str, int]) -> list[dict]:
    """潜在转折点：年轻但引用密度远超同龄论文的工作。"""
    current_year = max((paper.year or 0) for paper in papers) or 2026
    by_year: dict[int, list[Paper]] = defaultdict(list)
    for paper in papers:
        if paper.year and paper.citation_count is not None:
            by_year[paper.year].append(paper)

    results: list[dict] = []
    for year, members in by_year.items():
        if len(members) < 3:
            continue
        counts = sorted(paper.citation_count or 0 for paper in members)
        threshold = counts[int(len(counts) * 0.9)] if counts else 0
        for paper in members:
            citations = paper.citation_count or 0
            if citations >= threshold and citations > 0 and (current_year - year) <= 3:
                results.append(
                    {
                        "uid": paper.uid,
                        "title": paper.title,
                        "year": paper.year,
                        "citations": citations,
                        "community": communities.get(paper.citation_key),
                        "url": paper.web_url(),
                    }
                )
    results.sort(key=lambda item: (-(item["citations"] or 0)))
    return results[:5]
