"""健康检查：用于部署自检与运行时环境确认。"""

from fastapi import APIRouter

from app.config import get_settings
from app.db.session import check_connection

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    db_ok = await check_connection()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "database": "up" if db_ok else "down",
        "llm_configured": settings.has_llm,
    }
