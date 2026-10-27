"""多源并发注册与聚合。

设计要点：
- 三源并发执行，单源失败不影响整体（错误进入 stats.errors，前端可见）
- 每完成一个数据源即回调一次，驱动 SSE 实时进度（过程可视化的关键）
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence

from app.config import get_settings
from app.pipeline.cache import make_key, read_cache, write_cache
from app.schemas.paper import Paper, Query, SearchStats
from app.sources.arxiv_source import ArxivSource
from app.sources.base import PaperSource
from app.sources.openalex_source import OpenAlexSource
from app.sources.s2_source import SemanticScholarSource

SourceCallback = Callable[[str, int], Awaitable[None]]

CACHE_KIND = "search"


class SourceRegistry:
    """数据源注册表：负责创建、并发检索与释放。"""

    def __init__(self, names: Sequence[str] = ("arxiv", "openalex", "s2")) -> None:
        self._sources: dict[str, PaperSource] = {}
        settings = get_settings()
        for name in names:
            if name == "s2" and not settings.s2_api_key:
                # 无 API key 时 S2 走共享池，实测必然返回 429，
                # 每次都白白等一轮超时（约 5s）。直接跳过，不做无意义等待。
                print("[registry] 未配置 S2 API key，跳过 Semantic Scholar")
                continue
            source = self._create(name)
            if source is not None:
                self._sources[name] = source

    @staticmethod
    def _create(name: str) -> PaperSource | None:
        factories = {
            "arxiv": ArxivSource,
            "openalex": OpenAlexSource,
            "s2": SemanticScholarSource,
        }
        factory = factories.get(name)
        return factory() if factory is not None else None

    @property
    def names(self) -> list[str]:
        return list(self._sources)

    def get(self, name: str) -> PaperSource | None:
        return self._sources.get(name)

    async def search_all(
        self,
        query: Query,
        limit_per_source: int,
        on_source_done: SourceCallback | None = None,
        *,
        use_cache: bool = True,
    ) -> tuple[list[Paper], SearchStats]:
        """并发检索。命中缓存时直接返回，避免重复请求与限流风险。

        缓存是容错设计的落地：预热过的方向即使网络抖动，
        也能立即给出结果，而不是因为数据源 429 导致整个分析空转。
        """
        # 缓存键必须基于**用户输入的原始方向**，而不是查询理解生成的术语：
        # 术语由大模型生成，同一方向两次可能不同，实测会导致缓存命中不稳定；
        # 更严重的是让同一方向的两次分析得到不同结果
        # （诊断中出现过 6 个主题与 2 个主题的差异）。
        seed = (query.raw or "").strip().lower() or "|".join(query.all_terms()).lower()
        key = make_key(
            CACHE_KIND,
            {"q": seed, "limit": limit_per_source, "sources": self.names},
        )
        if use_cache:
            cached = read_cache(CACHE_KIND, key)
            if cached and cached.get("papers"):
                stats = SearchStats()
                stats.fetched = len(cached["papers"])
                stats.per_source = {"cache": stats.fetched}
                stats.elapsed_seconds = 0.0
                papers = [Paper(**item) for item in cached["papers"]]
                if on_source_done is not None:
                    await on_source_done("cache", len(papers))
                return papers, stats

        started = time.monotonic()
        stats = SearchStats()

        async def run(
            name: str, source: PaperSource
        ) -> tuple[str, list[Paper], str | None]:
            try:
                papers = await source.search(query, limit_per_source)
                return name, papers, None
            except Exception as exc:  # noqa: BLE001
                return name, [], f"{type(exc).__name__}: {exc}"

        results = await asyncio.gather(
            *(run(name, source) for name, source in self._sources.items())
        )

        merged: list[Paper] = []
        for name, papers, error in results:
            stats.per_source[name] = len(papers)
            stats.fetched += len(papers)
            if error:
                stats.errors.append(f"{name}: {error}")
            merged.extend(papers)
            if on_source_done is not None:
                await on_source_done(name, len(papers))

        stats.elapsed_seconds = round(time.monotonic() - started, 2)

        # 仅在拿到足量结果时写缓存：避免把限流导致的空结果缓存下来，
        # 否则半小时内该方向都会持续返回空数据
        if use_cache and len(merged) >= 20:
            write_cache(
                CACHE_KIND, key, {"papers": [paper.model_dump() for paper in merged]}
            )

        return merged, stats

    async def aclose(self) -> None:
        await asyncio.gather(
            *(source.aclose() for source in self._sources.values()),
            return_exceptions=True,
        )
