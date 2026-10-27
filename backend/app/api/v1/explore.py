"""领域探索接口。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.task_manager import manager

router = APIRouter()


class ExploreRequest(BaseModel):
    direction: str = Field(..., min_length=2, max_length=300, description="细分研究方向")
    # 预留：后续可透传年份、引用数下限等约束
    year_from: int | None = None
    min_citations: int | None = None


class ExploreResponse(BaseModel):
    task_id: str
    status: str
    stream_url: str


@router.post("/explore", response_model=ExploreResponse)
async def create_explore(payload: ExploreRequest) -> ExploreResponse:
    direction = payload.direction.strip()
    if not direction:
        raise HTTPException(status_code=400, detail="研究方向不能为空")
    record = manager.create("explore", direction)
    manager.launch_explore(record.task_id)
    return ExploreResponse(
        task_id=record.task_id,
        status=record.status,
        stream_url=f"/api/v1/tasks/{record.task_id}/stream",
    )
