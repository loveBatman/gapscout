"""任务管理：在后台执行分析并维护可查询的任务状态。

为什么需要独立任务层：
分析链路耗时数十秒到数分钟，不能阻塞 HTTP 请求；同时前端需要在
刷新或重连后仍能拿到进度与结果，因此任务状态必须独立于单次连接存在。
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.schemas.analysis import TaskStatus
from app.services.event_bus import bus
from app.services.explore_service import run_explore
from app.services.feasibility_service import run_feasibility
from app.services.gap_service import run_gap_analysis
from app.services.review_service import run_review

_MAX_KEPT = 50


@dataclass
class TaskRecord:
    task_id: str
    kind: str
    query: str
    status: str = "pending"
    stage: str | None = None
    progress: int = 0
    message: str | None = None
    error: str | None = None
    stats: dict = field(default_factory=dict)
    result: dict | None = None

    def to_status(self) -> TaskStatus:
        return TaskStatus(
            task_id=self.task_id,
            kind=self.kind,
            query=self.query,
            status=self.status,
            stage=self.stage,
            progress=self.progress,
            message=self.message,
            error=self.error,
            stats=self.stats,
            result=self.result,
        )


class TaskManager:
    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}
        self._order: list[str] = []
        self._runners: dict[str, asyncio.Task] = {}
        bus.set_progress_hook(self._sync_progress)

    # ---------- 查询 ----------
    def get(self, task_id: str) -> TaskRecord | None:
        return self._records.get(task_id)

    def list_recent(self, limit: int = 20) -> list[TaskRecord]:
        return [self._records[tid] for tid in reversed(self._order[-limit:]) if tid in self._records]

    # ---------- 创建与执行 ----------
    def create(self, kind: str, query: str) -> TaskRecord:
        task_id = str(uuid.uuid4())
        record = TaskRecord(task_id=task_id, kind=kind, query=query)
        self._records[task_id] = record
        self._order.append(task_id)
        self._evict()
        bus.create(task_id)
        return record

    def launch_explore(self, task_id: str) -> None:
        self._launch(
            task_id,
            run_explore,
            lambda result: {"topics": len(result.topics), "papers": len(result.papers)},
            failure_message="领域探索失败",
        )

    def launch_gap(self, task_id: str) -> None:
        self._launch(
            task_id,
            run_gap_analysis,
            lambda result: {"gaps": len(result.gaps)},
            failure_message="空白识别失败",
        )

    def launch_feasibility(self, task_id: str) -> None:
        self._launch(
            task_id,
            run_feasibility,
            lambda result: {
                "novelty_level": result.novelty_level,
                "similar_works": len(result.similar_works),
            },
            failure_message="可行性评估失败",
        )

    def launch_review(self, task_id: str) -> None:
        self._launch(
            task_id,
            run_review,
            lambda result: {
                "sections": len(result.sections),
                "references": len(result.references),
            },
            failure_message="综述生成失败",
        )

    def _launch(
        self,
        task_id: str,
        runner: Callable[[str, str], Awaitable[Any]],
        summarize: Callable[[Any], dict],
        *,
        failure_message: str,
    ) -> None:
        """统一的任务执行包装：状态流转、结果落库与事件收尾。

        三类分析（探索 / 空白 / 可行性）的收尾逻辑完全一致，
        集中在此实现可避免各服务各自处理状态而导致行为不一致。
        """

        async def execute() -> None:
            record = self._records[task_id]
            record.status = "running"
            try:
                result = await runner(task_id, record.query)
                record.status = "done"
                record.stage = "done"
                record.progress = 100
                record.result = result.model_dump()
                record.stats = getattr(result, "stats", None) or {}
                await bus.finish(
                    task_id,
                    {
                        "task_id": task_id,
                        "elapsed_seconds": record.stats.get("elapsed_seconds"),
                        **summarize(result),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                record.status = "failed"
                record.error = f"{type(exc).__name__}: {exc}"
                record.message = failure_message
                await bus.fail(task_id, record.error)

        asyncio.create_task(execute())

    # ---------- 内部 ----------
    def _sync_progress(self, task_id: str, stage: str, message: str, percent: int) -> None:
        record = self._records.get(task_id)
        if record is None:
            return
        record.stage = stage
        record.message = message
        record.progress = percent

    def _evict(self) -> None:
        """限制内存占用：超出上限时移除最旧的已结束任务。"""
        while len(self._order) > _MAX_KEPT:
            oldest = self._order[0]
            record = self._records.get(oldest)
            if record is not None and record.status in ("pending", "running"):
                break
            self._order.pop(0)
            self._records.pop(oldest, None)
            bus.discard(oldest)


manager = TaskManager()
