"""事件总线：驱动 SSE 实时进度推送。

每个分析任务对应一个独立队列，后台任务通过 emit 推送阶段进度与增量结果，
HTTP 层通过 SSE 消费。让"AI 正在做什么"对用户可见，是产品体验的关键，
也让长耗时任务不再表现为"卡住"。
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field

from app.schemas.analysis import ProgressEvent

_QUEUE_MAX = 1000

# (task_id, stage, message, percent) -> None
ProgressHook = Callable[[str, str, str, int], None]


@dataclass
class TaskChannel:
    task_id: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=_QUEUE_MAX))
    finished: bool = False

    def payload(self) -> dict:
        return {"task_id": self.task_id}


class EventBus:
    """任务事件通道管理。"""

    def __init__(self) -> None:
        self._channels: dict[str, TaskChannel] = {}
        self._progress_hook: ProgressHook | None = None

    def set_progress_hook(self, hook: ProgressHook | None) -> None:
        """注册进度回调，用于把阶段进度同步进任务记录（供非 SSE 查询）。"""
        self._progress_hook = hook

    def create(self, task_id: str) -> TaskChannel:
        channel = TaskChannel(task_id=task_id)
        self._channels[task_id] = channel
        return channel

    def get(self, task_id: str) -> TaskChannel | None:
        return self._channels.get(task_id)

    def discard(self, task_id: str) -> None:
        self._channels.pop(task_id, None)

    async def emit(self, task_id: str, event_type: str, payload: dict) -> None:
        """推送事件。队列满时丢弃最旧事件，保证后台任务不被阻塞。"""
        channel = self._channels.get(task_id)
        if channel is None:
            return
        message = (event_type, payload)
        try:
            channel.queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                channel.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                channel.queue.put_nowait(message)
            except asyncio.QueueFull:
                pass

    async def progress(
        self,
        task_id: str,
        stage: str,
        message: str,
        percent: int,
        *,
        source: str | None = None,
        count: int | None = None,
    ) -> None:
        if self._progress_hook is not None:
            self._progress_hook(task_id, stage, message, percent)
        event = ProgressEvent(
            stage=stage,  # type: ignore[arg-type]
            message=message,
            percent=percent,
            source=source,
            count=count,
        )
        await self.emit(task_id, "progress", event.model_dump())

    async def partial(self, task_id: str, kind: str, payload: dict) -> None:
        """增量结果推送，支持前端边算边渲染（过程可视化的核心）。"""
        await self.emit(task_id, "partial", {"type": kind, "payload": payload})

    async def finish(self, task_id: str, summary: dict) -> None:
        channel = self._channels.get(task_id)
        if channel is not None:
            channel.finished = True
        await self.emit(task_id, "done", summary)

    async def fail(self, task_id: str, message: str) -> None:
        channel = self._channels.get(task_id)
        if channel is not None:
            channel.finished = True
        await self.emit(task_id, "failed", {"message": message})

    @staticmethod
    def format_sse(event_type: str, payload: dict) -> str:
        """SSE 帧格式：前端 EventSource 直接消费。"""
        return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


bus = EventBus()
