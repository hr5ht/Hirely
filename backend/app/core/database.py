"""Async database access: one connection pool for the whole app."""
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm.attributes import flag_modified

from app.core import config

# Requests share these connections instead of opening one each, so load doesn't exhaust Postgres's 100
engine = create_async_engine(config.DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
# expire_on_commit=False: objects stay readable after a commit, so code can commit (freeing the
# connection) before a slow AI call and keep using what it loaded
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as db:
        yield db


DB = Annotated[AsyncSession, Depends(get_db)]


async def save(db, obj, *fields):
    """Commit obj, marking JSON fields that were edited in place (SQLAlchemy can't see those)."""
    for field in fields:
        flag_modified(obj, field)
    await db.commit()


async def create_tables():
    # shortcut: create_all only adds missing tables and never alters existing ones; add Alembic before changing a column
    from app import models  # noqa: F401  (registers the tables)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
