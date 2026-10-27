"""任务查询与 SSE 进度流。"""

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.analysis import TaskStatus
from app.services.event_bus import bus
from app.services.task_manager import manager

router = APIRouter()

# SSE 心跳间隔：避免中间代理因长时间无数据而断开连接
_HEARTBEAT_SECONDS = 15.0
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.get("/tasks", response_model=list[TaskStatus])
async def list_tasks(limit: int = 20) -> list[TaskStatus]:
    return [record.to_status() for record in manager.list_recent(limit)]


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task(task_id: str) -> TaskStatus:
    record = manager.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="任务不存在或已被清理")
    return record.to_status()


@router.get("/tasks/{task_id}/stream")
async def stream_task(task_id: str) -> StreamingResponse:
    record = manager.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="任务不存在或已被清理")

    channel = bus.get(task_id)
    if channel is None:
        channel = bus.create(task_id)

    async def event_source():
        # 先补发当前状态，让中途接入或刷新后的连接立即可见进度
        yield bus.format_sse(
            "progress",
            {
                "stage": record.stage or "queued",
                "message": record.message or "任务已创建",
                "percent": record.progress,
            },
        )
        if record.status in ("done", "failed"):
            event = "done" if record.status == "done" else "failed"
            yield bus.format_sse(event, {"task_id": task_id, "cached": True})
            return

        while True:
            try:
                event_type, payload = await asyncio.wait_for(
                    channel.queue.get(), timeout=_HEARTBEAT_SECONDS
                )
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield bus.format_sse(event_type, payload)
            if event_type in ("done", "failed"):
                break

    return StreamingResponse(
        event_source(), media_type="text/event-stream", headers=_SSE_HEADERS
    )
