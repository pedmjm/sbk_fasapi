"""
FastAPI app entry point. Wires together:

  * The lifespan that creates DB tables on first boot
  * All routers (auth, personal, herramientas, clientes, sucursales,
    contactos, tareas, comentarios, notifications)
  * The `/storage` static-file mount for uploaded images
  * A request-logging middleware that REDACTS the Authorization header
    and password fields (fixes the security issue in Laravel's
    LogApiRequests middleware, which logged bearer tokens in plaintext)
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from database import create_db_and_tables
from routers import (
    auth,
    comentarios,
    clientes,
    contactos,
    herramientas,
    notifications,
    personal,
    sucursales,
    tareas,
    consumibles,
    picking,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("sbk")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on first boot. For real deployments, prefer Alembic.
    logger.info("Creating DB tables (if missing)…")
    await create_db_and_tables()

    # Ensure the storage directory exists.
    storage_dir = Path(os.getenv("STORAGE_DIR", "./storage")).resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Storage directory: %s", storage_dir)

    yield


app = FastAPI(
    title="SBK TaskManager API",
    description=(
        "FastAPI port of the sbk_laravel_app task manager. "
        "JWT auth, role-based access control, polymorphic image evidence, "
        "and OneSignal push notifications."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ─── Routers ────────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(personal.router)
app.include_router(herramientas.router)
app.include_router(clientes.router)
app.include_router(sucursales.router)
app.include_router(contactos.router)
app.include_router(tareas.router)
app.include_router(comentarios.router)
app.include_router(notifications.router)
app.include_router(consumibles.router)
app.include_router(picking.router)


# ─── Static files (uploaded evidence) ───────────────────────────────────────

# Served at /storage/<subdir>/<parent_id>/<filename>  — matches what
# `storage_helpers.build_public_url()` produces.
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./storage")).resolve()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount(
    "/storage",
    StaticFiles(directory=str(STORAGE_DIR)),
    name="storage",
)


# ─── Redacted request-logging middleware ────────────────────────────────────

_REDACTED_HEADERS = {"authorization", "cookie"}
_REDACTED_BODY_FIELDS = {"password", "hashed_password", "foto_perfil"}


def _redact_headers(headers) -> dict:
    return {
        k: ("***REDACTED***" if k.lower() in _REDACTED_HEADERS else v)
        for k, v in headers.items()
    }


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every request + response, with sensitive fields redacted.

    Fixes the security issue in Laravel's LogApiRequests middleware,
    which logged the full Authorization header (plaintext bearer token)
    and the password field on /login + /register.
    """
    start = time.perf_counter()

    # Don't log static-file requests — they're noisy and irrelevant.
    path = request.url.path
    if path.startswith("/storage"):
        return await call_next(request)

    logger.info(
        "→ %s %s  headers=%s",
        request.method,
        path,
        _redact_headers(dict(request.headers)),
    )

    response: Response = await call_next(request)

    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("← %s %s  %d  %.1fms", request.method, path, response.status_code, elapsed_ms)
    return response


# ─── Root health-check ──────────────────────────────────────────────────────

@app.get("/", tags=["meta"])
async def root():
    return {
        "name": "SBK TaskManager API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/up",
    }


@app.get("/up", tags=["meta"])
async def health():
    return {"status": "ok"}
