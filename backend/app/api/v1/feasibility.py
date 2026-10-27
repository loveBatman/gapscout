"""选题可行性评估接口（M3）。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.task_manager import manager

router = APIRouter()


class FeasibilityRequest(BaseModel):
    idea: str = Field(..., min_length=4, max_length=1000, description="研究想法（自然语言）")


class FeasibilityResponse(BaseModel):
    task_id: str
    status: str
    stream_url: str


@router.post("/feasibility", response_model=FeasibilityResponse)
async def create_feasibility(payload: FeasibilityRequest) -> FeasibilityResponse:
    idea = payload.idea.strip()
    if not idea:
        raise HTTPException(status_code=400, detail="研究想法不能为空")
    record = manager.create("feasibility", idea)
    manager.launch_feasibility(record.task_id)
    return FeasibilityResponse(
        task_id=record.task_id,
        status=record.status,
        stream_url=f"/api/v1/tasks/{record.task_id}/stream",
    )
