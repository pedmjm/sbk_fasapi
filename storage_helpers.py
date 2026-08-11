"""
Shared storage helpers for image uploads.

Files are stored under `./storage/{subdir}/{parent_id}/{random_filename}`
and served by FastAPI's `StaticFiles` mount at `/storage` (see main.py).

The DB stores the *relative* path (e.g. `tareas/abc-123/xyz.png`); the
absolute URL is derived on read via `build_public_url()`. This fixes the
Laravel bug where the full URL (including host) was persisted at write
time, so changing `APP_URL` later broke every existing image.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Iterable

from fastapi import UploadFile

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./storage")).resolve()
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
APP_URL = os.getenv("APP_URL", "http://localhost:8000").rstrip("/")


def _ensure_storage_root() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)


async def save_upload(
    file: UploadFile,
    subdir: str,
    parent_id: str,
) -> str:
    """Save a single UploadFile to `storage/{subdir}/{parent_id}/{rand}.{ext}`
    and return the relative path (no leading slash, no host).
    """
    _ensure_storage_root()

    # Validate content type / extension.
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"Unsupported file type: {file.content_type}")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise ValueError(f"Unsupported file extension: {ext}")

    # Validate size without loading the whole thing into memory at once —
    # read in chunks and bail out if we exceed the limit.
    target_dir = STORAGE_DIR / subdir / parent_id
    target_dir.mkdir(parents=True, exist_ok=True)
    random_name = secrets.token_urlsafe(32) + ext
    target_path = target_dir / random_name
    rel_path = f"{subdir}/{parent_id}/{random_name}"

    written = 0
    with target_path.open("wb") as f:
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                f.close()
                target_path.unlink(missing_ok=True)
                raise ValueError(
                    f"File exceeds max upload size ({MAX_UPLOAD_BYTES} bytes)"
                )
            f.write(chunk)

    return rel_path


def build_public_url(rel_path: str) -> str:
    """Build the public URL for a stored file. Always derived from
    `APP_URL` at read time, never persisted.
    """
    return f"{APP_URL}/storage/{rel_path}"


def delete_rel_path(rel_path: str) -> None:
    """Delete a file by its relative path. Missing files are silently ignored."""
    abs_path = STORAGE_DIR / rel_path
    abs_path.unlink(missing_ok=True)


def delete_subdir(subdir: str, parent_id: str) -> None:
    """Recursively delete `storage/{subdir}/{parent_id}/`."""
    target = STORAGE_DIR / subdir / parent_id
    if target.exists():
        # Recursively delete; ignore errors.
        import shutil
        shutil.rmtree(target, ignore_errors=True)
