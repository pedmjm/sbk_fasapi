"""
Async SQLAlchemy engine, declarative Base, session factory, and the
`create_db_and_tables()` / `get_db()` helpers used across the app.

Mirrors the structure of the uploaded `database.py` template but reads the
DATABASE_URL from the environment so it can be swapped between SQLite and
Postgres without touching code.
"""
from __future__ import annotations

import os
from pathlib import Path

# Load .env from the project root. We use `override=True` so the project's
# own settings take precedence over any globally-set environment variables
# (e.g. a DATABASE_URL exported in the shell that's pointing somewhere else).
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path, override=True)
    except ImportError:
        # Fallback: simple manual parser (no quotes / escaping support).
        for _line in _env_path.read_text().splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _, _v = _line.partition("=")
            os.environ[_k.strip()] = _v.strip().strip('"').strip("'")

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./app.db",
)

# `future=True` is implicit on the async engine. `echo=False` keeps logs clean.
engine = create_async_engine(DATABASE_URL, echo=False, future=True)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base shared by every model in `models.py`."""
    pass


async def create_db_and_tables() -> None:
    """Create all tables. Called from the FastAPI lifespan in `main.py`.

    For a real deployment prefer Alembic migrations over this — but for
    local dev / first boot it's convenient.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an async session."""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
