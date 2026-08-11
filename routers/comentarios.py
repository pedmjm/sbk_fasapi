"""
Comentarios (comments) router — nested under a Tarea.

Mirrors Laravel's `ComentarioController`. A comment may be:
  * text only
  * image(s) only
  * text + image(s)

Endpoints (all require auth):
  GET    /tareas/{tarea_id}/comentarios         list comments (newest first)
  POST   /tareas/{tarea_id}/comentarios         create (multipart: texto + imagenes[])
  DELETE /comentarios/{comentario_id}           delete + cleanup files

Notifications: when a comment is added, push goes to the tarea's creator
AND every User linked to the assigned Personal — except the comment's own
author (no self-notification).
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
    Request
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import get_current_active_user
from database import get_db
from models import Comentario, Imagen, Personal, Tarea, User
from notifications import notify_users
from schemas import ComentarioOut, Envelope, ImagenOut
from storage_helpers import build_public_url, delete_rel_path, delete_subdir, save_upload

router = APIRouter(tags=["comentarios"])


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _load_comentario_imagenes(db: AsyncSession, comentario: Comentario) -> list[Imagen]:
    result = await db.execute(
        select(Imagen)
        .where(Imagen.imageable_type == "Comentario", Imagen.imageable_id == str(comentario.id))
        .order_by(Imagen.created_at)
    )
    imgs = result.scalars().all()
    # Stash on the instance so ComentarioOut's `imagenes` field can find them.
    comentario.imagenes_proxy = imgs  # type: ignore[attr-defined]
    return imgs


def _serialize_comentario(comentario: Comentario) -> dict:
    data = ComentarioOut.model_validate(comentario).model_dump(mode="json")
    imgs = getattr(comentario, "imagenes_proxy", [])
    data["imagenes"] = [ImagenOut.model_validate(img).model_dump(mode="json") for img in imgs]
    return data


# ─── List ──────────────────────────────────────────────────────────────────

@router.get("/tareas/{tarea_id}/comentarios", response_model=Envelope)
async def list_comentarios(
    tarea_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    tarea = (
        await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    ).scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    result = await db.execute(
        select(Comentario)
        .options(selectinload(Comentario.autor))
        .where(Comentario.tarea_id == tarea_id)
        .order_by(Comentario.created_at.desc())
    )
    comentarios = result.scalars().all()
    for c in comentarios:
        await _load_comentario_imagenes(db, c)
    return Envelope(data=[_serialize_comentario(c) for c in comentarios])


# ─── Create ────────────────────────────────────────────────────────────────


@router.post(
    "/tareas/{tarea_id}/comentarios",
    response_model=Envelope,
    status_code=status.HTTP_201_CREATED,
)
async def create_comentario(
    tarea_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    texto: Optional[str] = Form(default=None),
    imagenes: list[UploadFile] = File(default=[]),
):
    clean_texto = texto.strip() if texto and texto.strip() else None

    # Filter invalid empty fields
    valid_images = [f for f in imagenes if f.filename]

    if not clean_texto and not valid_images:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debes enviar al menos un texto o una imagen.",
        )

    tarea = (
        await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    ).scalar_one_or_none()
    if not tarea:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Tarea no encontrada"
        )

    comentario = Comentario(
        tarea_id=tarea_id,
        autor_id=current_user.id,
        texto=clean_texto or "",
    )
    db.add(comentario)
    await db.flush()

    saved_images: list[Imagen] = []
    for f in valid_images:
        try:
            rel = await save_upload(f, "comentarios", str(comentario.id))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, 
                detail=str(exc)
            )
        img = Imagen(
            path=rel,
            url=build_public_url(rel),
            imageable_type="Comentario",
            imageable_id=str(comentario.id),
        )
        db.add(img)
        saved_images.append(img)

    await db.commit()
    await db.refresh(comentario)
    await db.refresh(comentario, attribute_names=["autor"])
    await _load_comentario_imagenes(db, comentario)

    # Push notification: tarea creator + assigned Personals' linked Users,
    # minus the comment author.
    notify_ids: set[uuid.UUID] = set()
    if tarea.creador_id and tarea.creador_id != current_user.id:
        notify_ids.add(tarea.creador_id)
    # Find assigned Personal -> linked Users via cédula.
    personales = (
        await db.execute(
            select(Personal).join(Tarea, Tarea.id == tarea_id).where(Personal.id == Tarea.personal.any())  # noqa
        )
    ).scalars().all() if False else []  # placeholder — replaced below

    # Simpler: load tarea.personal explicitly.
    tarea_with_personal = (
        await db.execute(
            select(Tarea).options(selectinload(Tarea.personal)).where(Tarea.id == tarea_id)
        )
    ).scalar_one()
    cedulas = [p.cedula for p in tarea_with_personal.personal if p.cedula]
    if cedulas:
        linked_users = (
            await db.execute(select(User).where(User.cedula.in_(cedulas)))
        ).scalars().all()
        for u in linked_users:
            if u.id != current_user.id:
                notify_ids.add(u.id)

    if notify_ids:
        await notify_users(
            notify_ids,
            title="Nuevo comentario en tarea",
            message=f"{current_user.name}: {texto[:80] if texto else '(imagen)'}",
            data={
                "tarea_id": str(tarea_id),
                "comentario_id": str(comentario.id),
                "action": "comentario.created",
            },
        )


    return Envelope(
        message="Comentario registrado con éxito",
        data=_serialize_comentario(comentario),
    )


# ─── Delete ────────────────────────────────────────────────────────────────

@router.delete("/comentarios/{comentario_id}", response_model=Envelope)
async def delete_comentario(
    comentario_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    comentario = (
        await db.execute(select(Comentario).where(Comentario.id == comentario_id))
    ).scalar_one_or_none()
    if not comentario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El comentario no existe o ya fue eliminado.",
        )

    # RBAC: author OR admin (the Laravel check was commented out — fixing).
    if comentario.autor_id != current_user.id and current_user.nivel < 2:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado para eliminar este comentario.",
        )

    # 1. Delete physical files + Imagen rows.
    imgs = (
        await db.execute(
            select(Imagen).where(
                Imagen.imageable_type == "Comentario",
                Imagen.imageable_id == str(comentario_id),
            )
        )
    ).scalars().all()
    for img in imgs:
        delete_rel_path(img.path)
        await db.delete(img)
    delete_subdir("comentarios", str(comentario_id))

    # 2. Delete the comentario row.
    await db.delete(comentario)
    await db.commit()
    return Envelope(message="Comentario eliminado correctamente")
