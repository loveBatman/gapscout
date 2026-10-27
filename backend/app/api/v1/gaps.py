"""研究空白识别接口（M2）。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.task_manager import manager

router = APIRouter()


class GapRequest(BaseModel):
    direction: str = Field(..., min_length=2, max_length=300, description="细分研究方向")


class GapResponse(BaseModel):
    task_id: str
    status: str
    stream_url: str


@router.post("/gaps", response_model=GapResponse)
async def create_gap_analysis(payload: GapRequest) -> GapResponse:
    direction = payload.direction.strip()
    if not direction:
        raise HTTPException(status_code=400, detail="研究方向不能为空")
    record = manager.create("gap", direction)
    manager.launch_gap(record.task_id)
    return GapResponse(
        task_id=record.task_id,
        status=record.status,
        stream_url=f"/api/v1/tasks/{record.task_id}/stream",
    )
