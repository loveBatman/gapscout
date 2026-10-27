"""综述生成接口（M5）。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.task_manager import manager

router = APIRouter()


class ReviewRequest(BaseModel):
    direction: str = Field(..., min_length=2, max_length=300, description="综述主题方向")


class ReviewResponse(BaseModel):
    task_id: str
    status: str
    stream_url: str


@router.post("/review", response_model=ReviewResponse)
async def create_review(payload: ReviewRequest) -> ReviewResponse:
    direction = payload.direction.strip()
    if not direction:
        raise HTTPException(status_code=400, detail="综述方向不能为空")
    record = manager.create("review", direction)
    manager.launch_review(record.task_id)
    return ReviewResponse(
        task_id=record.task_id,
        status=record.status,
        stream_url=f"/api/v1/tasks/{record.task_id}/stream",
    )
