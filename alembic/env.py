"""
Alembic env.py — Async SQLAlchemy + SQLite UUID fix.
"""
from __future__ import annotations

import os
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# ─── Load .env ──────────────────────────────────────────────────────────────

_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path, override=True)
    except ImportError:
        for _line in _env_path.read_text().splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _, _v = _line.partition("=")
            os.environ[_k.strip()] = _v.strip().strip('"').strip("'")

# ─── Alembic Config ─────────────────────────────────────────────────────────

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ─── Import ALL models ──────────────────────────────────────────────────────

from database import Base
import models
from models import (
    User, Personal, Cliente, Sucursal, Contacto,
    Herramienta, Consumible, Tarea, PasosTarea,
    Comentario, Imagen, Picking, PickingItem,
)

target_metadata = Base.metadata

# ─── DATABASE_URL ───────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./app.db")
# DATABASE_URL=postgresql+asyncpg://mi_usuario:mi_contraseña_segura@localhost:5432/mi_base_datos
config.set_main_option("sqlalchemy.url", DATABASE_URL)

IS_SQLITE = "sqlite" in DATABASE_URL.lower()


# ─── Filter: remove false UUID type changes on SQLite ───────────────────────

def _strip_uuid_type_changes_on_sqlite(context, revision, directives):
    """
    SQLite stores Uuid as CHAR(36). Alembic detects a type mismatch
    and generates ALTER COLUMN TYPE which SQLite can't run.
    This removes those ops before the migration file is written.
    """
    if not IS_SQLITE:
        return

    from alembic.operations.ops import ModifyTableOps, AlterColumnOp

    for directive in directives:
        if not isinstance(directive, ModifyTableOps):
            continue
        # Build a new list without UUID type-change alter_columns
        new_ops = []
        for op in directive.ops:
            if isinstance(op, AlterColumnOp):
                # Check if it's a type-only change (no other modifications)
                if (
                    op.existing_type is not None
                    and op.type_impl is not None
                    and op.nullable is None
                    and op.server_default is None
                    and op.autoincrement is None
                    and op.comment is None
                ):
                    # It's a type-only change — check if UUID-related
                    existing = str(op.existing_type).upper()
                    new = str(op.type_impl).upper()
                    uuid_words = {"UUID", "CHAR(32)", "CHAR(36)", "VARCHAR(36)"}
                    if existing in uuid_words and new in uuid_words:
                        # Skip this op entirely
                        continue
            new_ops.append(op)
        directive.ops = new_ops


# ─── Migration runners ──────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_server_default=True,
        process_revision_directives=_strip_uuid_type_changes_on_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_server_default=True,
        include_schemas=True,
        process_revision_directives=_strip_uuid_type_changes_on_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    import asyncio
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_async_migrations())


# ─── Entry point ────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()