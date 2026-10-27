"""数据库会话管理：异步引擎 + 依赖注入 + 连接自检。"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.db_echo,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：提供一个自动关闭的异步会话。"""
    async with SessionLocal() as session:
        yield session


async def check_connection() -> bool:
    """启动自检：数据库不可用时不阻塞服务启动，仅打印告警。"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[db] 数据库连接失败，部分功能不可用: {exc}")
        return False


async def dispose_engine() -> None:
    await engine.dispose()
