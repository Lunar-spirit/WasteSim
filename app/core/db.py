from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)

# expire_on_commit=False: services return ORM objects that get serialised into
# response models *after* commit; without this SQLAlchemy would re-fetch every
# attribute on first access post-commit, needing another await inside sync code.
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

# A second engine, NullPool, for Celery worker tasks specifically — never
# imported by app/main.py or get_db(). Every `@celery_app.task` wrapper in
# app/workers/tasks_*.py runs its real logic via a fresh `asyncio.run(...)`
# call, which creates and destroys its own event loop *per task*. The
# default `engine` above pools physical connections across calls, so a
# worker process handling two tasks back to back hands the second task a
# connection whose asyncpg internals still reference the first task's
# already-closed loop — "Future attached to a different loop" (found live
# while wiring up a real Celery worker for the first time end-to-end).
# NullPool opens a brand-new physical connection per checkout and closes it
# on return, so nothing ever crosses a loop boundary — the same reasoning
# tests/conftest.py's own TestSessionLocal already uses NullPool for.
worker_engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
WorkerSessionLocal = async_sessionmaker(worker_engine, expire_on_commit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
