"""
Pasos (task steps) router — dedicated to the GUI's independent paso view.

Each paso of a tarea is accessed on its own screen, so routes are keyed by
`/pasos/{tarea_id}/{paso_id}` instead of nesting under `/tareas`.

Comments now belong to a **paso**, not to the tarea (moved from
`routers/comentarios.py`, which no longer exists). A comment may be:
  * text only
  * image(s) only
  * text + image(s)

Business rule: comments can only be added while the tarea is
`en_progreso` (started). Anything else returns 422.

Endpoints (all require auth):
  POST   /pasos/{tarea_id}                            add a step to a tarea
  GET    /pasos/{tarea_id}/{paso_id}                  full paso detail
                                                      (comentarios + tarea summary)
  PUT    /pasos/{tarea_id}/{paso_id}                  update a step
                                                      (toggle completado, etc.)
  DELETE /pasos/{tarea_id}/{paso_id}                  remove a step
                                                      (+ cleans its comments' files)
  GET    /pasos/{tarea_id}/{paso_id}/comentarios      list the paso's comments
                                                      (newest first)
  POST   /pasos/{tarea_id}/{paso_id}/comentarios      create a comment
                                                      (tarea must be en_progreso)
  DELETE /comentarios/{comentario_id}                 delete a comment + cleanup

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
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import get_current_active_user
from database import get_db
from models import (
    Comentario,
    EstadoTarea,
    Imagen,
    PasosTarea,
    Tarea,
    User,
)
from notifications import notify_users
from schemas import ComentarioOut, Envelope, ImagenOut, PasoCreate, PasoOut, PasoUpdate
from storage_helpers import (
    build_public_url,
    delete_rel_path,
    delete_subdir,
    save_upload,
)

router = APIRouter(tags=["pasos"])


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _fetch_paso(db: AsyncSession, tarea_id: uuid.UUID, paso_id: uuid.UUID) -> Optional[PasosTarea]:
    """Fetch a paso scoped to its tarea, with everything the responses need
    eagerly loaded (comentarios + autor, tarea + personal). Returns None if
    the paso doesn't exist or doesn't belong to that tarea.
    """
    stmt = (
        select(PasosTarea)
        .options(
            selectinload(PasosTarea.comentarios).selectinload(Comentario.autor),
            selectinload(PasosTarea.tarea).selectinload(Tarea.personal),
        )
        .where(PasosTarea.id == paso_id, PasosTarea.tarea_id == tarea_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _load_comentario_imagenes(db: AsyncSession, comentario: Comentario) -> list[Imagen]:
    """Load the comment's polymorphic Imagen rows and stash them on the
    instance so ComentarioOut's `imagenes` field can find them."""
    result = await db.execute(
        select(Imagen)
        .where(Imagen.imageable_type == "Comentario", Imagen.imageable_id == str(comentario.id))
        .order_by(Imagen.created_at)
    )
    imgs = result.scalars().all()
    comentario.imagenes_proxy = imgs  # type: ignore[attr-defined]
    return imgs


def _serialize_comentario(comentario: Comentario) -> dict:
    data = ComentarioOut.model_validate(comentario).model_dump(mode="json")
    imgs = getattr(comentario, "imagenes_proxy", [])
    data["imagenes"] = [ImagenOut.model_validate(img).model_dump(mode="json") for img in imgs]
    return data


def _serialize_paso(paso: PasosTarea) -> dict:
    """PasoOut dict with each comment's imagenes attached."""
    data = PasoOut.model_validate(paso).model_dump(mode="json")
    for c_data, c_obj in zip(data["comentarios"], paso.comentarios):
        c_data["imagenes"] = [
            ImagenOut.model_validate(img).model_dump(mode="json")
            for img in getattr(c_obj, "imagenes_proxy", [])
        ]
    return data


async def _hydrate_comentario_imagenes(db: AsyncSession, comentarios: list[Comentario]) -> None:
    for c in comentarios:
        await _load_comentario_imagenes(db, c)


# ─── Paso CRUD ──────────────────────────────────────────────────────────────

@router.post("/pasos/{tarea_id}", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def add_paso(
    tarea_id: uuid.UUID,
    body: PasoCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    tarea = (
        await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    ).scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    paso = PasosTarea(tarea_id=tarea_id, **body.model_dump())
    db.add(paso)
    await db.commit()

    # Re-fetch with relations loaded (a fresh paso has no comments yet,
    # but this keeps the response shape identical to the other endpoints).
    paso = await _fetch_paso(db, tarea_id, paso.id)
    return Envelope(message="Paso agregado", data=PasoOut.model_validate(paso).model_dump(mode="json"))


@router.get("/pasos/{tarea_id}/{paso_id}", response_model=Envelope)
async def get_paso(
    tarea_id: uuid.UUID,
    paso_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Full paso detail for the independent paso view: the step, its
    comentarios (with autor + imagenes) and a summary of its tarea."""
    paso = await _fetch_paso(db, tarea_id, paso_id)
    if not paso:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paso no encontrado")

    await _hydrate_comentario_imagenes(db, paso.comentarios)
    data = _serialize_paso(paso)

    tarea = paso.tarea
    data["tarea"] = {
        "id": str(tarea.id),
        "titulo": tarea.titulo,
        "estado": tarea.estado.value,
        "cliente_id": str(tarea.cliente_id),
        "sucursal_id": str(tarea.sucursal_id),
        "fecha_limite": tarea.fecha_limite.isoformat() if tarea.fecha_limite else None,
    }
    return Envelope(data=data)


@router.put("/pasos/{tarea_id}/{paso_id}", response_model=Envelope)
async def update_paso(
    tarea_id: uuid.UUID,
    paso_id: uuid.UUID,
    body: PasoUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    paso = await _fetch_paso(db, tarea_id, paso_id)
    if not paso:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paso no encontrado")

    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(paso, k, v)
    await db.commit()

    # Re-fetch so relations survive the commit's expiry.
    paso = await _fetch_paso(db, tarea_id, paso_id)
    await _hydrate_comentario_imagenes(db, paso.comentarios)
    return Envelope(message="Paso actualizado", data=_serialize_paso(paso))


@router.delete("/pasos/{tarea_id}/{paso_id}", response_model=Envelope)
async def delete_paso(
    tarea_id: uuid.UUID,
    paso_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    paso = await _fetch_paso(db, tarea_id, paso_id)
    if not paso:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paso no encontrado")

    # Comments live on the paso now: delete their Imagen rows + physical
    # files before the cascade removes the rows (otherwise they orphan).
    for c in paso.comentarios:
        c_imgs = (
            await db.execute(
                select(Imagen).where(
                    Imagen.imageable_type == "Comentario",
                    Imagen.imageable_id == str(c.id),
                )
            )
        ).scalars().all()
        for img in c_imgs:
            delete_rel_path(img.path)
            await db.delete(img)
        delete_subdir("comentarios", str(c.id))

    await db.delete(paso)
    await db.commit()
    return Envelope(message="Paso eliminado")


# ─── Comentarios del paso ──────────────────────────────────────────────────

@router.get("/pasos/{tarea_id}/{paso_id}/comentarios", response_model=Envelope)
async def list_comentarios(
    tarea_id: uuid.UUID,
    paso_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    paso = (
        await db.execute(
            select(PasosTarea).where(PasosTarea.id == paso_id, PasosTarea.tarea_id == tarea_id)
        )
    ).scalar_one_or_none()
    if not paso:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paso no encontrado")

    comentarios = (
        await db.execute(
            select(Comentario)
            .options(selectinload(Comentario.autor))
            .where(Comentario.paso_id == paso_id)
            .order_by(Comentario.created_at.desc())
        )
    ).scalars().all()
    await _hydrate_comentario_imagenes(db, list(comentarios))
    return Envelope(data=[_serialize_comentario(c) for c in comentarios])


@router.post(
    "/pasos/{tarea_id}/{paso_id}/comentarios",
    response_model=Envelope,
    status_code=status.HTTP_201_CREATED,
)
async def create_comentario(
    tarea_id: uuid.UUID,
    paso_id: uuid.UUID,
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

    paso = await _fetch_paso(db, tarea_id, paso_id)
    if not paso:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paso no encontrado")

    tarea = paso.tarea
    # ─── ✅ Rule: comments only while the tarea is in progress ──
    if tarea.estado != EstadoTarea.EN_PROGRESO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No se puede comentar: la tarea está '{tarea.estado.value}' "
                "y debe estar 'en_progreso'."
            ),
        )

    comentario = Comentario(
        tarea_id=tarea_id,
        paso_id=paso_id,
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
                detail=str(exc),
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

    cedulas = [p.cedula for p in tarea.personal if p.cedula]
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
            title="Nuevo comentario en paso",
            message=f"{current_user.name}: {clean_texto[:80] if clean_texto else '(imagen)'}",
            data={
                "tarea_id": str(tarea_id),
                "paso_id": str(paso_id),
                "comentario_id": str(comentario.id),
                "action": "paso.comentario.created",
            },
        )

    return Envelope(
        message="Comentario registrado con éxito",
        data=_serialize_comentario(comentario),
    )


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

    # RBAC: author OR admin.
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
