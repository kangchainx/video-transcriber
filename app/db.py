"""数据库连接与会话管理，使用 SQLAlchemy 异步引擎连接 Postgres。"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

settings = get_settings()


def _build_engine() -> AsyncEngine:
    """创建异步引擎。"""

    return create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True, future=True)


engine: AsyncEngine = _build_engine()
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, autocommit=False)


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """通用会话上下文，可用于依赖或内部调用。"""

    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：提供一次请求的数据库会话。"""

    async with session_scope() as session:
        yield session
