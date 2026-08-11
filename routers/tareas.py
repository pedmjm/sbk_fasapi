"""
Tareas (tasks) CRUD router — the core of the app. Mirrors Laravel's
`TareaController` and adds the bug fixes flagged in the review:

  * `update()` validates the *correct* field name (`cliente_id`, not `cliente`)
    and re-validates `exists:` on `personal_ids.*` and `herramienta_ids.*`.
  * `destroy()` now deletes the tarea's own image files AND each comment's
    image files (the Laravel version left orphan comment photos on disk).
  * The polymorphic `imagenes.imageable_id` is a String, so Tarea UUIDs
    fit (Laravel used `numericMorphs` which truncated UUIDs).

Endpoints (all under `/tareas`, all require auth):
  GET    /tareas                  list all tareas (with relations)
  POST   /tareas                  create a tarea (multipart/form-data)
  GET    /tareas/{tarea_id}       full detail (relations + comments)
  PUT    /tareas/{tarea_id}       update (sync personal/herramientas)
  DELETE /tareas/{tarea_id}       delete + cleanup files
  POST   /tareas/{tarea_id}/pasos          add a step
  PUT    /tareas/{tarea_id}/pasos/{paso_id}  update a step (toggle completado, etc.)
  DELETE /tareas/{tarea_id}/pasos/{paso_id}  remove a step
  POST   /tareas/{tarea_id}/imagenes        attach evidence photos

Notifications: when a tarea is created with assigned `personal_ids`, a
push is sent to every User whose `cedula` matches one of those Personals.
"""
from __future__ import annotations

import json
import uuid
from typing import Annotated, Optional
from datetime import date

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
    Cliente,
    Comentario,
    Herramienta,
    Imagen,
    PasosTarea,
    Personal,
    Prioridad,
    Sucursal,
    Tarea,
    User,
)
from notifications import notify_users
from schemas import (
    Envelope,
    ImagenOut,
    PasoCreate,
    PasoOut,
    PasoUpdate,
    TareaCreate,
    TareaNested,
    TareaUpdate,
)
from storage_helpers import (
    build_public_url,
    delete_rel_path,
    delete_subdir,
    save_upload,
)

router = APIRouter(prefix="/tareas", tags=["tareas"])

_VALID_PRIORIDADES = {p.value for p in Prioridad}


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _load_tarea_relations(db: AsyncSession, tarea: Tarea) -> None:
    """Eagerly load everything the nested response needs. Avoids N+1."""
    await db.refresh(
        tarea,
        attribute_names=[
            "cliente", "sucursal", "creador",
            "personal", "herramientas", "pasos",
            "comentarios", "comentarios",
        ],
    )
    # Comentarios' imagenes + tarea's own imagenes — loaded via explicit
    # queries because the polymorphic relation is viewonly.
    tarea_imagenes = (
        await db.execute(
            select(Imagen)
            .where(Imagen.imageable_type == "Tarea", Imagen.imageable_id == str(tarea.id))
            .order_by(Imagen.created_at)
        )
    ).scalars().all()
    tarea.imagenes_proxy = tarea_imagenes  # type: ignore[attr-defined]

    for c in tarea.comentarios:
        c_imagenes = (
            await db.execute(
                select(Imagen)
                .where(Imagen.imageable_type == "Comentario", Imagen.imageable_id == str(c.id))
                .order_by(Imagen.created_at)
            )
        ).scalars().all()
        c.imagenes_proxy = c_imagenes  # type: ignore[attr-defined]


def _serialize_tarea(tarea: Tarea) -> TareaNested:
    """Build the nested response, attaching the polymorphic images."""
    data = TareaNested.model_validate(tarea).model_dump()
    # Replace the empty `imagenes` list (the relationship isn't auto-loaded
    # for Tarea because we don't have a SQLAlchemy `relationship()` on it)
    # with the explicitly-queried ones.
    tarea_imgs = getattr(tarea, "imagenes_proxy", [])
    data["imagenes"] = [
        ImagenOut.model_validate(img).model_dump() for img in tarea_imgs
    ]
    # Also patch comentarios' imagenes the same way.
    for c_data, c_obj in zip(data["comentarios"], tarea.comentarios):
        c_imgs = getattr(c_obj, "imagenes_proxy", [])
        c_data["imagenes"] = [
            ImagenOut.model_validate(img).model_dump() for img in c_imgs
        ]
    return TareaNested(**data)


async def _resolve_personal_users(
    db: AsyncSession, personal_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Given a list of Personal IDs, find the User IDs linked to them
    via cédula match. Used to know whom to notify.
    """
    if not personal_ids:
        return []
    personales = (
        await db.execute(select(Personal).where(Personal.id.in_(personal_ids)))
    ).scalars().all()
    cedulas = [p.cedula for p in personales if p.cedula]
    if not cedulas:
        return []
    users = (
        await db.execute(select(User).where(User.cedula.in_(cedulas)))
    ).scalars().all()
    return [u.id for u in users]


# ─── Tarea CRUD ─────────────────────────────────────────────────────────────

@router.get("", response_model=Envelope)
async def list_tareas(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    stmt = (
        select(Tarea)
        .options(
            selectinload(Tarea.cliente),
            selectinload(Tarea.sucursal),
            selectinload(Tarea.creador),
            selectinload(Tarea.personal),
            selectinload(Tarea.herramientas),
            selectinload(Tarea.pasos),
            selectinload(Tarea.comentarios).selectinload(Comentario.autor),
        )
        .order_by(Tarea.created_at.desc())
    )
    result = await db.execute(stmt)
    tareas = result.scalars().unique().all()
    for t in tareas:
        await _load_tarea_relations(db, t)
    return Envelope(data=[_serialize_tarea(t).model_dump(mode="json") for t in tareas])


@router.post("", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def create_tarea(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    cliente_id: uuid.UUID = Form(...),
    sucursal_id: uuid.UUID = Form(...),
    titulo: str = Form(...),
    descripcion: Optional[str] = Form(None),
    prioridad: str = Form("Media"),
    fecha_programada: Optional[date] = Form(None),
    fecha_limite: Optional[date] = Form(None),
    personal_ids: str = Form("[]"),
    herramienta_ids: str = Form("[]"),
    pasos: str = Form("[]"),
    imagenes: list[UploadFile] = File(default=[]),
):
    # Validate prioridad.
    if prioridad not in _VALID_PRIORIDADES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"prioridad must be one of {sorted(_VALID_PRIORIDADES)}",
        )

    # Validate FK existence.
    cliente = (
        await db.execute(select(Cliente).where(Cliente.id == cliente_id))
    ).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cliente_id does not exist")
    
    sucursal = (
        await db.execute(select(Sucursal).where(Sucursal.id == sucursal_id))
    ).scalar_one_or_none()
    if not sucursal:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="sucursal_id does not exist")

    # Parse JSON-encoded list fields.
    try:
        p_ids = [uuid.UUID(str(x)) for x in json.loads(personal_ids)]
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"personal_ids is not a valid JSON list of UUIDs: {exc}")
    try:
        h_ids = [uuid.UUID(str(x)) for x in json.loads(herramienta_ids)]
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"herramienta_ids is not a valid JSON list of UUIDs: {exc}")
    try:
        pasos_data: list[dict] = json.loads(pasos)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"pasos is not valid JSON: {exc}")

    # Validate & fetch M:N entities upfront.
    personales: list[Personal] = []
    if p_ids:
        personales = (
            await db.execute(select(Personal).where(Personal.id.in_(p_ids)))
        ).scalars().all()
        if len(personales) != len(set(p_ids)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="One or more personal_ids do not exist.")

    herramientas: list[Herramienta] = []
    if h_ids:
        herramientas = (
            await db.execute(select(Herramienta).where(Herramienta.id.in_(h_ids)))
        ).scalars().all()
        if len(herramientas) != len(set(h_ids)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="One or more herramienta_ids do not exist.")

    # Create the tarea with relationships pre-populated in memory.
    tarea = Tarea(
        cliente_id=cliente_id,
        sucursal_id=sucursal_id,
        titulo=titulo,
        descripcion=descripcion,
        prioridad=Prioridad(prioridad),
        fecha_programada=fecha_programada,
        fecha_limite=fecha_limite,
        creador_id=current_user.id,
        personal=list(personales),
        herramientas=list(herramientas),
    )
    db.add(tarea)
    await db.flush()  # Generates tarea.id and links association table entries cleanly

    # Create pasos.
    for paso_data in pasos_data:
        db.add(PasosTarea(
            tarea_id=tarea.id,
            actividad=paso_data.get("actividad", ""),
            metodo=paso_data.get("metodo"),
            requerimiento=paso_data.get("requerimiento"),
        ))

    # Upload evidence images.
    saved_images: list[Imagen] = []
    for f in imagenes:
        try:
            rel = await save_upload(f, "tareas", str(tarea.id))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        img = Imagen(
            path=rel,
            url=build_public_url(rel),
            imageable_type="Tarea",
            imageable_id=str(tarea.id),
        )
        db.add(img)
        saved_images.append(img)

    await db.commit()
    await db.refresh(tarea)
    await _load_tarea_relations(db, tarea)

    # Best-effort push notification.
    user_ids = await _resolve_personal_users(db, p_ids)
    if user_ids:
        await notify_users(
            user_ids,
            title="Nueva tarea asignada",
            message=f"{titulo} — prioridad {prioridad}",
            data={"tarea_id": str(tarea.id), "action": "tarea.created"},
        )

    return Envelope(
        message="Tarea creada exitosamente",
        data=_serialize_tarea(tarea).model_dump(mode="json"),
    )

@router.get("/{tarea_id}", response_model=Envelope)
async def get_tarea(
    tarea_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    stmt = (
        select(Tarea)
        .options(
            selectinload(Tarea.cliente),
            selectinload(Tarea.sucursal),
            selectinload(Tarea.creador),
            selectinload(Tarea.personal),
            selectinload(Tarea.herramientas),
            selectinload(Tarea.pasos),
            selectinload(Tarea.comentarios).selectinload(Comentario.autor),
        )
        .where(Tarea.id == tarea_id)
    )
    tarea = (await db.execute(stmt)).scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    await _load_tarea_relations(db, tarea)
    return Envelope(data=_serialize_tarea(tarea).model_dump(mode="json"))


@router.put("/{tarea_id}", response_model=Envelope)
async def update_tarea(
    tarea_id: uuid.UUID,
    body: TareaUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    stmt = (
        select(Tarea)
        .options(
            selectinload(Tarea.personal),
            selectinload(Tarea.herramientas),
            selectinload(Tarea.pasos),
        )
        .where(Tarea.id == tarea_id)
    )
    tarea = (await db.execute(stmt)).scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    data = body.model_dump(exclude_unset=True)

    # Validate prioridad if present.
    if "prioridad" in data and data["prioridad"] is not None:
        if data["prioridad"] not in _VALID_PRIORIDADES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"prioridad must be one of {sorted(_VALID_PRIORIDADES)}",
            )
        data["prioridad"] = Prioridad(data["prioridad"])

    # Validate FK existence if changed.
    if "cliente_id" in data and data["cliente_id"] is not None:
        exists = (await db.execute(select(Cliente.id).where(Cliente.id == data["cliente_id"]))).scalar_one_or_none()
        if not exists:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cliente_id does not exist")
    if "sucursal_id" in data and data["sucursal_id"] is not None:
        exists = (await db.execute(select(Sucursal.id).where(Sucursal.id == data["sucursal_id"]))).scalar_one_or_none()
        if not exists:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="sucursal_id does not exist")

    # Sync M:N — Laravel used `sync()` which replaces; we match that semantics.
    p_ids = data.pop("personal_ids", None)
    h_ids = data.pop("herramienta_ids", None)

    for k, v in data.items():
        setattr(tarea, k, v)

    if p_ids is not None:
        if p_ids:
            found = (await db.execute(select(Personal.id).where(Personal.id.in_(p_ids)))).scalars().all()
            if len(found) != len(set(p_ids)):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="One or more personal_ids do not exist.")
            personales = (await db.execute(select(Personal).where(Personal.id.in_(p_ids)))).scalars().all()
            tarea.personal = list(personales)
        else:
            tarea.personal = []

    if h_ids is not None:
        if h_ids:
            found = (await db.execute(select(Herramienta.id).where(Herramienta.id.in_(h_ids)))).scalars().all()
            if len(found) != len(set(h_ids)):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="One or more herramienta_ids do not exist.")
            herramientas = (await db.execute(select(Herramienta).where(Herramienta.id.in_(h_ids)))).scalars().all()
            tarea.herramientas = list(herramientas)
        else:
            tarea.herramientas = []

    await db.commit()
    await db.refresh(tarea)
    await _load_tarea_relations(db, tarea)
    return Envelope(message="Tarea actualizada exitosamente", data=_serialize_tarea(tarea).model_dump(mode="json"))


@router.delete("/{tarea_id}", response_model=Envelope)
async def delete_tarea(
    tarea_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    tarea = (
        await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    ).scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    # 1. Delete every Imagen row referencing this Tarea or its Comentarios,
    #    AND delete the physical files. (Laravel missed the comment-image
    #    cleanup — leaving orphans on disk.)
    tarea_imgs = (
        await db.execute(
            select(Imagen).where(Imagen.imageable_type == "Tarea", Imagen.imageable_id == str(tarea_id))
        )
    ).scalars().all()
    for img in tarea_imgs:
        delete_rel_path(img.path)
        await db.delete(img)

    comentarios = (
        await db.execute(select(Comentario).where(Comentario.tarea_id == tarea_id))
    ).scalars().all()
    for c in comentarios:
        c_imgs = (
            await db.execute(
                select(Imagen).where(Imagen.imageable_type == "Comentario", Imagen.imageable_id == str(c.id))
            )
        ).scalars().all()
        for img in c_imgs:
            delete_rel_path(img.path)
            await db.delete(img)
        delete_subdir("comentarios", str(c.id))

    delete_subdir("tareas", str(tarea_id))

    # 2. Cascading FKs handle comentarios, pasos, pivots.
    await db.delete(tarea)
    await db.commit()
    return Envelope(message="Tarea eliminada correctamente")


# ─── Pasos sub-resource ─────────────────────────────────────────────────────

@router.post("/{tarea_id}/pasos", response_model=Envelope, status_code=status.HTTP_201_CREATED)
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
    await db.refresh(paso)
    return Envelope(message="Paso agregado", data=PasoOut.model_validate(paso))


@router.put("/{tarea_id}/pasos/{paso_id}", response_model=Envelope)
async def update_paso(
    tarea_id: uuid.UUID,
    paso_id: uuid.UUID,
    body: PasoUpdate,
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
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(paso, k, v)
    await db.commit()
    await db.refresh(paso)
    return Envelope(message="Paso actualizado", data=PasoOut.model_validate(paso))


@router.delete("/{tarea_id}/pasos/{paso_id}", response_model=Envelope)
async def delete_paso(
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
    await db.delete(paso)
    await db.commit()
    return Envelope(message="Paso eliminado")


# ─── Evidence image upload ─────────────────────────────────────────────────

@router.post("/{tarea_id}/imagenes", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def upload_tarea_imagenes(
    tarea_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    imagenes: list[UploadFile] = File(...),
):
    tarea = (
        await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    ).scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    saved: list[Imagen] = []
    for f in imagenes:
        try:
            rel = await save_upload(f, "tareas", str(tarea_id))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        img = Imagen(
            path=rel,
            url=build_public_url(rel),
            imageable_type="Tarea",
            imageable_id=str(tarea_id),
        )
        db.add(img)
        saved.append(img)
    await db.commit()
    for img in saved:
        await db.refresh(img)
    return Envelope(
        message=f"{len(saved)} imagen(es) adjuntada(s)",
        data=[ImagenOut.model_validate(img).model_dump(mode="json") for img in saved],
    )
