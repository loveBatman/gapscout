"""FastAPI 应用入口。"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import api_router
from app.config import get_settings
from app.db.session import check_connection, dispose_engine
from app.pipeline.cluster import warmup as warmup_cluster

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 数据库不可用时不阻塞启动，仅告警，便于前端先行联调
    await check_connection()
    # UMAP 的 numba 编译很慢（实测 22.7s），放到后台线程预热：
    # 既不阻塞服务启动，又能把这段一次性开销从第一个用户任务里移走。
    asyncio.create_task(asyncio.to_thread(warmup_cluster))
    yield
    await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="输入细分研究方向，检索真实文献并产出可溯源的研究空白与综述",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

def _resolve_frontend_dist() -> Path | None:
    """定位前端构建产物。

    支持两种目录布局，便于不同部署方式：
    1. backend/web_dist  —— 单目录部署（只上传 backend 时使用）
    2. frontend/dist     —— 仓库内构建后的默认位置
    """
    candidates = (
        Path(__file__).resolve().parents[1] / "web_dist",
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


# 前端构建产物由后端一并托管：单端口即可完成部署，无需额外的反向代理配置。
# 仅在产物存在时挂载，因此本地前后端分离开发不受影响。
_frontend_dist = _resolve_frontend_dist()

if _frontend_dist is not None:
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
else:

    @app.get("/")
    async def root() -> dict:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "hint": "前端构建产物未找到，请先在 frontend 目录执行 npm run build",
        }
