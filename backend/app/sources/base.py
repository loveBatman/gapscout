"""数据源适配基类。

设计要点：
- 限流在基类统一实现，子类只需声明最小请求间隔，天然遵守各源礼貌策略
- 失败重试对 429/5xx 生效，保证偶发的网络抖动不致命
- 新增数据源只需实现 search / fetch_references 并注册，满足开闭原则
"""

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from app.config import get_settings
from app.schemas.paper import Paper, Query

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# 429 的退避序列（秒）：逐级拉长，给数据源恢复的时间
RATE_LIMIT_BACKOFF = (5.0, 15.0, 30.0, 45.0)


@dataclass
class FullText:
    """论文全文：三级降级策略（ar5iv HTML -> PDF -> 摘要）的产出。"""

    uid: str
    text: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    level: str = "L3"  # L1=HTML 结构化 / L2=PDF 文本层 / L3=摘要级
    source_url: str | None = None

    @property
    def has_sections(self) -> bool:
        return bool(self.sections)

    def section(self, keywords: tuple[str, ...]) -> str:
        """按标题关键词查找章节，用于定位 Limitation / Future Work 段落。"""
        for name, content in self.sections.items():
            lowered = name.lower()
            if any(kw in lowered for kw in keywords):
                return content
        return ""


class RateLimiter:
    """最小间隔限流：串行化请求以满足数据源礼貌策略。"""

    def __init__(self, min_interval: float) -> None:
        self._min_interval = max(min_interval, 0.0)
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    def slow_down(self, factor: float = 2.0, ceiling: float = 5.0) -> None:
        """遇到限流时动态放慢后续请求。

        必要性：放宽抓取间隔的前提是"被拒之后能自动退让"。
        否则一旦调快触发 429 就会持续被拒，反而比保守间隔更慢。
        """
        self._min_interval = min(self._min_interval * factor, ceiling)


class PaperSource(ABC):
    name: str = "base"
    min_interval: float = 1.0

    def __init__(self) -> None:
        self._settings = get_settings()
        self._limiter = RateLimiter(self.get_min_interval())
        self._client: httpx.AsyncClient | None = None

    def get_min_interval(self) -> float:
        return self.min_interval

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._settings.http_timeout,
                follow_redirects=True,
                headers={"User-Agent": self.user_agent()},
            )
        return self._client

    def user_agent(self) -> str:
        return f"GapScout/0.1 (mailto:{self._settings.contact_email})"

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def request(
        self,
        url: str,
        params: dict | None = None,
        *,
        headers: dict | None = None,
        max_attempts: int = 3,
    ) -> httpx.Response | None:
        """带限流与退避重试的 GET 请求。

        max_attempts 可调：对限流严格且非必需的数据源（如无 key 的 S2），
        降低重试次数可避免拖慢整体链路。
        """
        last_error: Exception | None = None
        for attempt in range(max(1, max_attempts)):
            await self._limiter.acquire()
            try:
                response = await self.client.get(url, params=params, headers=headers)
                if response.status_code == 200:
                    return response
                if response.status_code in RETRYABLE_STATUS:
                    # 429 需要更长的退避：短退避在持续限流下只是徒劳重试，
                    # 实测 OpenAlex 在密集请求后会连续返回 429，
                    # 给到秒级到十几秒的等待才有机会恢复
                    if response.status_code == 429:
                        backoff = RATE_LIMIT_BACKOFF[min(attempt, len(RATE_LIMIT_BACKOFF) - 1)]
                        print(
                            f"[{self.name}] 触发限流(429)，"
                            f"第 {attempt + 1}/{max_attempts} 次尝试，等待 {backoff:.0f}s"
                        )
                        await asyncio.sleep(backoff)
                        continue
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                print(f"[{self.name}] HTTP {response.status_code} -> {url}")
                return None
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                await asyncio.sleep(1.5 * (attempt + 1))
        if last_error is not None:
            print(f"[{self.name}] 请求异常: {type(last_error).__name__}: {last_error!r}")
        return None

    async def get_json(self, url: str, params: dict | None = None) -> dict | None:
        response = await self.request(url, params)
        if response is None:
            return None
        try:
            return response.json()
        except Exception as exc:  # noqa: BLE001
            print(f"[{self.name}] JSON 解析失败: {exc}")
            return None

    async def get_text(
        self, url: str, params: dict | None = None, *, max_attempts: int = 3
    ) -> str | None:
        response = await self.request(url, params, max_attempts=max_attempts)
        return response.text if response is not None else None

    @abstractmethod
    async def search(self, query: Query, limit: int) -> list[Paper]:
        """按查询检索论文。"""

    @abstractmethod
    async def fetch_references(self, paper: Paper) -> list[str]:
        """获取该论文的被引文献键，用于构建引用图谱。"""
