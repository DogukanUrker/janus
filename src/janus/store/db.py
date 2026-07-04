from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from janus.settings import settings

engine = create_async_engine(settings.database_url)
async_session = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    async with async_session() as s, s.begin():
        yield s


async def init_db() -> None:
    from janus.store.schema import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
