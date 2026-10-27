"""API v1 路由聚合。"""

from fastapi import APIRouter

from app.api.v1 import explore, feasibility, gaps, health, review, tasks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(explore.router, tags=["explore"])
api_router.include_router(gaps.router, tags=["gaps"])
api_router.include_router(feasibility.router, tags=["feasibility"])
api_router.include_router(review.router, tags=["review"])
api_router.include_router(tasks.router, tags=["tasks"])
