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
from datetime import datetime, date, timezone

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
    Consumible,
    TareaHerramientaEstado,
    tarea_herramienta,
    TareaConsumibleEstado,
    tarea_consumible,
    EstadoTarea,
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
    HerramientaEstadoOut,
    ConsumibleEstadoOut,
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
            "personal", "herramientas", "consumibles", 
            "pasos", "comentarios"
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
    consumible_ids: str = Form("[]"),
):
    if prioridad not in _VALID_PRIORIDADES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"prioridad must be one of {sorted(_VALID_PRIORIDADES)}",
        )

    cliente = (
        await db.execute(select(Cliente).where(Cliente.id == cliente_id))
    ).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cliente_id no existe")

    sucursal = (
        await db.execute(select(Sucursal).where(Sucursal.id == sucursal_id))
    ).scalar_one_or_none()
    if not sucursal:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="sucursal_id no existe")

    # Parse personal_ids (lista plana de UUIDs)
    try:
        p_ids = [uuid.UUID(str(x)) for x in json.loads(personal_ids)]
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"personal_ids no es JSON válido: {exc}")

    # ─── ✅ Parse herramienta_ids con cantidades ───────────────
    # Acepta ambos formatos:
    #   Old: ["uuid1", "uuid2"]              → cantidad=1
    #   New: [{"id":"uuid1","cantidad":2}]   → cantidad=2
    try:
        h_raw = json.loads(herramienta_ids)
        h_items = []
        for item in h_raw:
            if isinstance(item, str):
                h_items.append({"id": uuid.UUID(item), "cantidad": 1})
            elif isinstance(item, dict):
                h_items.append({
                    "id": uuid.UUID(str(item["id"])),
                    "cantidad": int(item.get("cantidad", 1)),
                })
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"herramienta_ids inválido: {exc}")

    # ─── ✅ Parse consumible_ids con cantidades ────────────────
    try:
        c_raw = json.loads(consumible_ids)
        c_items = []
        for item in c_raw:
            if isinstance(item, str):
                c_items.append({"id": uuid.UUID(item), "cantidad": 1})
            elif isinstance(item, dict):
                c_items.append({
                    "id": uuid.UUID(str(item["id"])),
                    "cantidad": int(item.get("cantidad", 1)),
                })
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"consumible_ids inválido: {exc}")

    try:
        pasos_data: list[dict] = json.loads(pasos)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"pasos no es JSON válido: {exc}")

    # Validate & fetch personal
    personales: list[Personal] = []
    if p_ids:
        personales = (
            await db.execute(select(Personal).where(Personal.id.in_(p_ids)))
        ).scalars().all()
        if len(personales) != len(set(p_ids)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="uno o mas personal_ids no existe.")

    # Validate herramientas
    h_uuids = [item["id"] for item in h_items]
    herramientas: list[Herramienta] = []
    if h_uuids:
        herramientas = (
            await db.execute(select(Herramienta).where(Herramienta.id.in_(h_uuids)))
        ).scalars().all()
        if len(herramientas) != len(set(h_uuids)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="uno o mas herramienta_ids no existe.")

    # Validate consumibles
    c_uuids = [item["id"] for item in c_items]
    consumibles: list[Consumible] = []
    if c_uuids:
        consumibles = (
            await db.execute(select(Consumible).where(Consumible.id.in_(c_uuids)))
        ).scalars().all()
        if len(consumibles) != len(set(c_uuids)):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="uno o mas consumible_ids no existe.")

    # ✅ Validar stock suficiente al asignar
    h_map = {h.id: h for h in herramientas}
    for item in h_items:
        h = h_map.get(item["id"])
        if h and h.stock_actual < item["cantidad"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Stock insuficiente para '{h.nombre}'. Disponible: {h.stock_actual}, Requerido: {item['cantidad']}"
            )

    c_map = {c.id: c for c in consumibles}
    for item in c_items:
        c = c_map.get(item["id"])
        if c and c.stock_actual < item["cantidad"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Stock insuficiente para '{c.nombre}'. Disponible: {c.stock_actual}, Requerido: {item['cantidad']}"
            )

    # ✅ Create tarea WITHOUT herramientas/consumibles via ORM
    # (insertamos manualmente después con cantidad correcta)
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
        # ❌ NO poner herramientas= ni consumibles= aquí
        estado=EstadoTarea.PENDIENTE,
    )
    db.add(tarea)
    await db.flush()

    # ─── ✅ Insertar en tarea_herramienta CON cantidad ─────────
    for item in h_items:
        await db.execute(
            tarea_herramienta.insert().values(
                tarea_id=tarea.id,
                herramienta_id=item["id"],
                cantidad=item["cantidad"],
            )
        )

    # ─── ✅ Insertar en tarea_consumible CON cantidad ────────────
    for item in c_items:
        await db.execute(
            tarea_consumible.insert().values(
                tarea_id=tarea.id,
                consumible_id=item["id"],
                cantidad=item["cantidad"],
            )
        )

    # Create pasos
    for paso_data in pasos_data:
        db.add(PasosTarea(
            tarea_id=tarea.id,
            actividad=paso_data.get("actividad", ""),
            metodo=paso_data.get("metodo"),
            requerimiento=paso_data.get("requerimiento"),
        ))

    # Upload evidence images
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

    # ─── ✅ Crear TareaHerramientaEstado con cantidad_asignada ─
    for item in h_items:
        estado_inicial = TareaHerramientaEstado(
            tarea_id=tarea.id,
            herramienta_id=item["id"],
            estado="asignada",
            cantidad_asignada=item["cantidad"],
            cantidad_devuelta=0,
        )
        db.add(estado_inicial)

    await db.commit()
    await db.refresh(tarea)
    await _load_tarea_relations(db, tarea)

    # Best-effort push notification
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
            selectinload(Tarea.consumibles),
            selectinload(Tarea.pasos),
            selectinload(Tarea.comentarios).selectinload(Comentario.autor),
        )
        .where(Tarea.id == tarea_id)
    )
    tarea = (await db.execute(stmt)).scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    
    await _load_tarea_relations(db, tarea)
    
    # Obtener estados de herramientas
    estados_herramientas = (
        await db.execute(
            select(TareaHerramientaEstado)
            .where(TareaHerramientaEstado.tarea_id == tarea_id)
        )
    ).scalars().all()
    
    # Obtener estados de consumibles
    estados_consumibles = (
        await db.execute(
            select(TareaConsumibleEstado)
            .where(TareaConsumibleEstado.tarea_id == tarea_id)
        )
    ).scalars().all()
    
    # Convertir a respuesta
    data = _serialize_tarea(tarea).model_dump(mode="json")
    data["herramientas_estado"] = [HerramientaEstadoOut.model_validate(e).model_dump() for e in estados_herramientas]
    data["consumibles_estado"] = [ConsumibleEstadoOut.model_validate(e).model_dump() for e in estados_consumibles]
    
    return Envelope(data=data)


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
            selectinload(Tarea.consumibles),
            selectinload(Tarea.pasos),
        )
        .where(Tarea.id == tarea_id)
    )
    tarea = (await db.execute(stmt)).scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    if tarea.estado in ("en_progreso", "completada", "cancelada"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tarea previamente iniciada")

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

    # ─── Extraer listas para sync ────────────────────────────
    p_ids = data.pop("personal_ids", None)
    h_items = data.pop("herramienta_ids", None)  # list[dict] con id+cantidad
    c_items = data.pop("consumible_ids", None)   # list[dict] con id+cantidad

    for k, v in data.items():
        setattr(tarea, k, v)

    # ─── Sync personal (lista plana de UUIDs) ────────────────
    if p_ids is not None:
        if p_ids:
            found = (await db.execute(select(Personal.id).where(Personal.id.in_(p_ids)))).scalars().all()
            if len(found) != len(set(p_ids)):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="One or more personal_ids do not exist.")
            personales = (await db.execute(select(Personal).where(Personal.id.in_(p_ids)))).scalars().all()
            tarea.personal = list(personales)
        else:
            tarea.personal = []

    # ─── ✅ Sync herramientas con cantidad ───────────────────
    if h_items is not None:
        # Limpiar ORM relationship
        tarea.herramientas = []
        await db.flush()

        # Borrar filas existentes en tarea_herramienta
        await db.execute(
            tarea_herramienta.delete().where(
                tarea_herramienta.c.tarea_id == tarea_id
            )
        )

        # Borrar TareaHerramientaEstado existentes
        estados_h = (
            await db.execute(
                select(TareaHerramientaEstado).where(
                    TareaHerramientaEstado.tarea_id == tarea_id
                )
            )
        ).scalars().all()
        for e in estados_h:
            await db.delete(e)
        await db.flush()

        if h_items:
            # Validar existencia
            h_uuids = [item["id"] for item in h_items]
            found = (await db.execute(select(Herramienta.id).where(Herramienta.id.in_(h_uuids)))).scalars().all()
            if len(found) != len(set(h_uuids)):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="One or more herramienta_ids do not exist.")

            # Insertar en tarea_herramienta CON cantidad
            for item in h_items:
                await db.execute(
                    tarea_herramienta.insert().values(
                        tarea_id=tarea_id,
                        herramienta_id=item["id"],
                        cantidad=item["cantidad"],
                    )
                )
                # Crear TareaHerramientaEstado con cantidad_asignada
                db.add(TareaHerramientaEstado(
                    tarea_id=tarea_id,
                    herramienta_id=item["id"],
                    estado="asignada",
                    cantidad_asignada=item["cantidad"],
                    cantidad_devuelta=0,
                ))

    # ─── ✅ Sync consumibles con cantidad ────────────────────
    if c_items is not None:
        # Limpiar ORM relationship
        tarea.consumibles = []
        await db.flush()

        # Borrar filas existentes en tarea_consumible
        await db.execute(
            tarea_consumible.delete().where(
                tarea_consumible.c.tarea_id == tarea_id
            )
        )

        if c_items:
            # Validar existencia
            c_uuids = [item["id"] for item in c_items]
            found = (await db.execute(select(Consumible.id).where(Consumible.id.in_(c_uuids)))).scalars().all()
            if len(found) != len(set(c_uuids)):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="One or more consumible_ids do not exist.")

            # Insertar en tarea_consumible CON cantidad
            for item in c_items:
                await db.execute(
                    tarea_consumible.insert().values(
                        tarea_id=tarea_id,
                        consumible_id=item["id"],
                        cantidad=item["cantidad"],
                    )
                )

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


@router.get("/{tarea_id}/herramientas-estado", response_model=Envelope)
async def get_herramientas_estado(
    tarea_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Obtiene el estado actual de cada herramienta asignada a la tarea."""
    # Verificar que la tarea existe
    result_tarea = await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    tarea = result_tarea.scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    # Obtener los estados
    result_estados = await db.execute(
        select(TareaHerramientaEstado)
        .where(TareaHerramientaEstado.tarea_id == tarea_id)
    )
    estados = result_estados.scalars().all()

    # Si no hay registros, crear por defecto para cada herramienta asignada
    if not estados:
        # Obtener herramientas asignadas
        stmt_herramientas = (
            select(Herramienta)
            .join(tarea_herramienta, tarea_herramienta.c.herramienta_id == Herramienta.id)
            .where(tarea_herramienta.c.tarea_id == tarea_id)
        )
        result_herramientas = await db.execute(stmt_herramientas)
        herramientas = result_herramientas.scalars().all()

        # Crear registros de estado por defecto
        for h in herramientas:
            nuevo_estado = TareaHerramientaEstado(
                tarea_id=tarea_id,
                herramienta_id=h.id,
                estado="asignada"
            )
            db.add(nuevo_estado)
        await db.commit()

        # Recargar
        result_estados = await db.execute(
            select(TareaHerramientaEstado)
            .where(TareaHerramientaEstado.tarea_id == tarea_id)
        )
        estados = result_estados.scalars().all()

    return Envelope(data=[HerramientaEstadoOut.model_validate(e).model_dump(mode="json") for e in estados])


@router.patch("/{tarea_id}/herramientas/{herramienta_id}/estado", response_model=Envelope)
async def update_herramienta_estado(
    tarea_id: uuid.UUID,
    herramienta_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Cambia el estado de una herramienta específica en la tarea."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Invalid JSON body")
    
    estado = body.get('estado')
    if not estado or estado not in {"asignada", "en_uso", "devuelta", "parcialmente_devuelta"}:
        raise HTTPException(status_code=422, detail="estado must be one of: asignada, en_uso, devuelta, parcialmente_devuelta")
    
    personal_id = body.get('personal_id')
    observaciones = body.get('observaciones')
    cantidad_devuelta = body.get('cantidad_devuelta', 0)
    
    # Verificar tarea
    result_tarea = await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    tarea = result_tarea.scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    # Verificar herramienta
    result_herramienta = await db.execute(select(Herramienta).where(Herramienta.id == herramienta_id))
    herramienta = result_herramienta.scalar_one_or_none()
    if not herramienta:
        raise HTTPException(status_code=404, detail="Herramienta no encontrada")

    # ✅ CORRECCIÓN: Usar .first() para tablas asociativas (no ORM)
    result_asignacion = await db.execute(
        select(tarea_herramienta).where(
            tarea_herramienta.c.tarea_id == tarea_id,
            tarea_herramienta.c.herramienta_id == herramienta_id
        )
    )
    asignacion = result_asignacion.first()  # Retorna Row o None, NO un int
    
    # ✅ Acceder a la columna correctamente
    cantidad_asignada = asignacion.cantidad if asignacion else 1

    if not asignacion:
        await db.execute(
            tarea_herramienta.insert().values(
                tarea_id=tarea_id,
                herramienta_id=herramienta_id,
                cantidad=cantidad_asignada
            )
        )
        await db.flush()

    # Buscar o crear registro de estado
    result_estado = await db.execute(
        select(TareaHerramientaEstado)
        .where(
            TareaHerramientaEstado.tarea_id == tarea_id,
            TareaHerramientaEstado.herramienta_id == herramienta_id
        )
    )
    estado_reg = result_estado.scalar_one_or_none()

    if not estado_reg:
        estado_reg = TareaHerramientaEstado(
            tarea_id=tarea_id,
            herramienta_id=herramienta_id,
            estado=estado,
            personal_id=personal_id,
            observaciones=observaciones,
            cantidad_asignada=cantidad_asignada,
            cantidad_devuelta=cantidad_devuelta if estado in ("devuelta", "parcialmente_devuelta") else 0,
        )
        if estado == "en_uso":
            estado_reg.fecha_inicio = datetime.now()
        elif estado in ("devuelta", "parcialmente_devuelta"):
            estado_reg.fecha_fin = datetime.now()
        db.add(estado_reg)
    else:
        estado_reg.estado = estado
        if personal_id is not None:
            estado_reg.personal_id = personal_id
        if observaciones is not None:
            estado_reg.observaciones = observaciones
            
        # Manejar cant idades devueltas
        if estado in ("devuelta", "parcialmente_devuelta"):
            estado_reg.cantidad_devuelta = (
                estado_reg.cantidad_devuelta + cantidad_devuelta
            )
            if estado_reg.fecha_fin is None:
                estado_reg.fecha_fin = datetime.now()

            # ✅ NUEVO: Incrementar stock del inventario
            herramienta.stock_actual += cantidad_devuelta

            # Determinar si todo fue devuelto
            if estado_reg.cantidad_devuelta >= estado_reg.cantidad_asignada:
                estado_reg.estado = "devuelta"
                herramienta.estado = "Disponible"
            else:
                estado_reg.estado = "parcialmente_devuelta"
                herramienta.estado = "En Uso"
        elif estado == "en_uso":
            if estado_reg.fecha_inicio is None:
                estado_reg.fecha_inicio = datetime.now()
            herramienta.estado = "En Uso"

    await db.commit()
    await db.refresh(estado_reg)

    return Envelope(
        message=f"Estado de herramienta actualizado a '{estado_reg.estado}'",
        data=HerramientaEstadoOut.model_validate(estado_reg).model_dump()
    )

@router.post("/{tarea_id}/iniciar", response_model=Envelope)
async def iniciar_tarea(
    tarea_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Inicia la tarea: marca herramientas y consumibles como 'en_uso'
    y decrementa el stock del inventario."""
    result_tarea = await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    tarea = result_tarea.scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    if tarea.estado != EstadoTarea.PENDIENTE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No se puede iniciar una tarea en estado '{tarea.estado.value}'"
        )

    # ─── Herramientas: validar stock y decrementar ──────────
    stmt_h = (
        select(Herramienta, tarea_herramienta.c.cantidad)
        .join(tarea_herramienta, tarea_herramienta.c.herramienta_id == Herramienta.id)
        .where(tarea_herramienta.c.tarea_id == tarea_id)
    )
    result_h = await db.execute(stmt_h)
    herramientas_data = result_h.all()

    herramientas_actualizadas = 0
    for h, cantidad in herramientas_data:
        # ✅ Validar stock suficiente
        if h.stock_actual < cantidad:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Stock insuficiente para '{h.nombre}'. "
                       f"Disponible: {h.stock_actual}, Requerido: {cantidad}"
            )
        # ✅ Decrementar stock del inventario
        h.stock_actual -= cantidad
        h.estado = "En Uso"

        # Crear/actualizar registro de estado
        result_estado = await db.execute(
            select(TareaHerramientaEstado)
            .where(
                TareaHerramientaEstado.tarea_id == tarea_id,
                TareaHerramientaEstado.herramienta_id == h.id
            )
        )
        estado_reg = result_estado.scalar_one_or_none()

        if not estado_reg:
            estado_reg = TareaHerramientaEstado(
                tarea_id=tarea_id,
                herramienta_id=h.id,
                estado="en_uso",
                personal_id=current_user.id,
                cantidad_asignada=cantidad,
                cantidad_devuelta=0,
                fecha_inicio=datetime.now(),
            )
            db.add(estado_reg)
        else:
            estado_reg.estado = "en_uso"
            estado_reg.personal_id = current_user.id
            estado_reg.cantidad_asignada = cantidad
            if estado_reg.fecha_inicio is None:
                estado_reg.fecha_inicio = datetime.now()

        herramientas_actualizadas += 1

    # ─── Consumibles: validar stock y decrementar ───────────
    stmt_c = (
        select(Consumible, tarea_consumible.c.cantidad)
        .join(tarea_consumible, tarea_consumible.c.consumible_id == Consumible.id)
        .where(tarea_consumible.c.tarea_id == tarea_id)
    )
    result_c = await db.execute(stmt_c)
    consumibles_data = result_c.all()

    consumibles_actualizados = 0
    for c, cantidad in consumibles_data:
        # ✅ Validar stock suficiente
        if c.stock_actual < cantidad:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Stock insuficiente para '{c.nombre}'. "
                       f"Disponible: {c.stock_actual}, Requerido: {cantidad}"
            )
        # ✅ Decrementar stock del inventario
        c.stock_actual -= cantidad

        # Crear/actualizar registro de estado
        result_estado_c = await db.execute(
            select(TareaConsumibleEstado)
            .where(
                TareaConsumibleEstado.tarea_id == tarea_id,
                TareaConsumibleEstado.consumible_id == c.id
            )
        )
        estado_reg_c = result_estado_c.scalar_one_or_none()

        if not estado_reg_c:
            estado_reg_c = TareaConsumibleEstado(
                tarea_id=tarea_id,
                consumible_id=c.id,
                estado="en_uso",
                personal_id=current_user.id,
                cantidad_asignada=cantidad,
                cantidad_devuelta=0,
                fecha_inicio=datetime.now(),
            )
            db.add(estado_reg_c)
        else:
            estado_reg_c.estado = "en_uso"
            estado_reg_c.personal_id = current_user.id
            estado_reg_c.cantidad_asignada = cantidad
            if estado_reg_c.fecha_inicio is None:
                estado_reg_c.fecha_inicio = datetime.now()

        consumibles_actualizados += 1

    tarea.estado = EstadoTarea.EN_PROGRESO

    await db.commit()

    return Envelope(
        message=(
            f"Tarea iniciada. {herramientas_actualizadas} herramienta(s) "
            f"y {consumibles_actualizados} consumible(s) marcados como 'en_uso'"
        ),
        data={
            "herramientas_actualizadas": herramientas_actualizadas,
            "consumibles_actualizados": consumibles_actualizados,
        }
    )

# ─── Estados de Consumibles en Tarea ─────────────────────────────

@router.get("/{tarea_id}/consumibles-estado", response_model=Envelope)
async def get_consumibles_estado(
    tarea_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Obtiene el estado actual de cada consumible asignado a la tarea."""
    # Verificar que la tarea existe
    result_tarea = await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    tarea = result_tarea.scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    # Obtener los estados
    result_estados = await db.execute(
        select(TareaConsumibleEstado)
        .where(TareaConsumibleEstado.tarea_id == tarea_id)
    )
    estados = result_estados.scalars().all()

    # Si no hay registros, crear por defecto para cada consumible asignado
    if not estados:
        stmt_consumibles = (
            select(Consumible)
            .join(tarea_consumible, tarea_consumible.c.consumible_id == Consumible.id)
            .where(tarea_consumible.c.tarea_id == tarea_id)
        )
        result_consumibles = await db.execute(stmt_consumibles)
        consumibles = result_consumibles.scalars().all()

        for c in consumibles:
            nuevo_estado = TareaConsumibleEstado(
                tarea_id=tarea_id,
                consumible_id=c.id,
                estado="asignado"
            )
            db.add(nuevo_estado)
        await db.commit()

        result_estados = await db.execute(
            select(TareaConsumibleEstado)
            .where(TareaConsumibleEstado.tarea_id == tarea_id)
        )
        estados = result_estados.scalars().all()

    return Envelope(data=[ConsumibleEstadoOut.model_validate(e).model_dump(mode="json") for e in estados])


@router.patch("/{tarea_id}/consumibles/{consumible_id}/estado", response_model=Envelope)
async def update_consumible_estado(
    tarea_id: uuid.UUID,
    consumible_id: uuid.UUID,
    request: Request,  # ✅ Cambiado de TareaConsumibleEstadoUpdate a Request
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Cambia el estado de un consumible específico en la tarea."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Invalid JSON body")

    estado = body.get('estado')
    if not estado or estado not in {"asignado", "en_uso", "consumido", "parcialmente_consumido"}:
        raise HTTPException(
            status_code=422,
            detail="estado must be one of: asignado, en_uso, consumido, parcialmente_consumido"
        )

    personal_id = body.get('personal_id')
    observaciones = body.get('observaciones')
    cantidad_devuelta = body.get('cantidad_devuelta', 0)

    # Verificar tarea
    result_tarea = await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    tarea = result_tarea.scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    # Verificar consumible
    result_consumible = await db.execute(
        select(Consumible).where(Consumible.id == consumible_id)
    )
    consumible = result_consumible.scalar_one_or_none()
    if not consumible:
        raise HTTPException(status_code=404, detail="Consumible no encontrado")

    # Buscar o crear registro de estado
    result_estado = await db.execute(
        select(TareaConsumibleEstado)
        .where(
            TareaConsumibleEstado.tarea_id == tarea_id,
            TareaConsumibleEstado.consumible_id == consumible_id
        )
    )
    estado_reg = result_estado.scalar_one_or_none()

    if not estado_reg:
        estado_reg = TareaConsumibleEstado(
            tarea_id=tarea_id,
            consumible_id=consumible_id,
            estado=estado,
            personal_id=personal_id,
            observaciones=observaciones,
            cantidad_asignada=1,
            cantidad_devuelta=0,
        )
        if estado == "en_uso":
            estado_reg.fecha_inicio = datetime.now()
        db.add(estado_reg)
    else:
        estado_reg.estado = estado
        if personal_id is not None:
            estado_reg.personal_id = personal_id
        if observaciones is not None:
            estado_reg.observaciones = observaciones

        # Manejar cantidades consumidas
        if estado in ("consumido", "parcialmente_consumido"):
            estado_reg.cantidad_devuelta += cantidad_devuelta
            if estado_reg.fecha_fin is None:
                estado_reg.fecha_fin = datetime.now()

            if estado_reg.cantidad_devuelta >= estado_reg.cantidad_asignada:
                estado_reg.estado = "consumido"
            else:
                estado_reg.estado = "parcialmente_consumido"
        elif estado == "en_uso":
            if estado_reg.fecha_inicio is None:
                estado_reg.fecha_inicio = datetime.now()

    await db.commit()
    await db.refresh(estado_reg)

    return Envelope(
        message=f"Estado de consumible actualizado a '{estado_reg.estado}'",
        data=ConsumibleEstadoOut.model_validate(estado_reg).model_dump()
    )

@router.post("/{tarea_id}/completar", response_model=Envelope)
async def completar_tarea(
    tarea_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_nivel(1))],
):
    """Marca la tarea como completada."""
    result = await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    tarea = result.scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    
    tarea.estado = EstadoTarea.COMPLETADA
    await db.commit()
    return Envelope(message="Tarea marcada como completada")


@router.post("/{tarea_id}/cancelar", response_model=Envelope)
async def cancelar_tarea(
    tarea_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_nivel(1))],
):
    # similar
    tarea.estado = EstadoTarea.CANCELADA
    await db.commit()
    return Envelope(message="Tarea cancelada")


@router.post("/{tarea_id}/herramientas/agregar", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def agregar_herramienta_tarea_iniciada(
    tarea_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Agrega una herramienta a una tarea ya iniciada (con cantidad).
    Soporta re-agregar herramientas previamente devueltas."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Invalid JSON body")

    herramienta_id = body.get('herramienta_id')
    cantidad = body.get('cantidad', 1)

    if not herramienta_id:
        raise HTTPException(status_code=422, detail="herramienta_id es requerido")

    try:
        herramienta_uuid = uuid.UUID(str(herramienta_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="herramienta_id inválido")

    # Verificar tarea existe y está en progreso
    result_tarea = await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    tarea = result_tarea.scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    if tarea.estado != EstadoTarea.EN_PROGRESO:
        raise HTTPException(
            status_code=422,
            detail="Solo se pueden agregar herramientas a tareas en progreso"
        )

        # Verificar herramienta existe
    result_herramienta = await db.execute(
        select(Herramienta).where(Herramienta.id == herramienta_uuid)
    )
    herramienta = result_herramienta.scalar_one_or_none()
    if not herramienta:
        raise HTTPException(status_code=404, detail="Herramienta no encontrada")

    # ✅ NUEVO: Validar stock suficiente
    if herramienta.stock_actual < cantidad:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Stock insuficiente para '{herramienta.nombre}'. "
                   f"Disponible: {herramienta.stock_actual}, Requerido: {cantidad}"
        )

    # ✅ NUEVO: Decrementar stock del inventario
    herramienta.stock_actual -= cantidad
    herramienta.estado = "En Uso"

    # ✅ FIX 1: Usar .first() (retorna Row), no .scalar_one_or_none()
    result_asignacion = await db.execute(
        select(tarea_herramienta).where(
            tarea_herramienta.c.tarea_id == tarea_id,
            tarea_herramienta.c.herramienta_id == herramienta_uuid
        )
    )
    asignacion = result_asignacion.first()

    if asignacion:
        # Ya existe en la tabla pivote → sumar cantidad
        await db.execute(
            tarea_herramienta.update()
            .where(
                tarea_herramienta.c.tarea_id == tarea_id,
                tarea_herramienta.c.herramienta_id == herramienta_uuid
            )
            .values(cantidad=asignacion.cantidad + cantidad)
        )
    else:
        # Crear nueva asignación en la tabla pivote
        await db.execute(
            tarea_herramienta.insert().values(
                tarea_id=tarea_id,
                herramienta_id=herramienta_uuid,
                cantidad=cantidad
            )
        )

    # ✅ FIX 2: Buscar registro de estado existente
    # (puede estar en estado 'devuelta' si fue re-agregada)
    result_estado = await db.execute(
        select(TareaHerramientaEstado)
        .where(
            TareaHerramientaEstado.tarea_id == tarea_id,
            TareaHerramientaEstado.herramienta_id == herramienta_uuid
        )
    )
    estado_reg = result_estado.scalar_one_or_none()

    if estado_reg:
        # ✅ Actualizar registro existente (re-agregando una devuelta)
        estado_reg.cantidad_asignada = (estado_reg.cantidad_asignada or 0) + cantidad
        estado_reg.estado = "en_uso"
        estado_reg.personal_id = current_user.id
        # Reset fecha_fin, vuelve a estar en uso
        estado_reg.fecha_fin = None
        if estado_reg.fecha_inicio is None:
            estado_reg.fecha_inicio = datetime.now()
        # cantidad_devuelta se MANTIENE (preserva historial de devoluciones)
        # restante = cantidad_asignada - cantidad_devuelta > 0 gracias al aumento
    else:
        # Crear nuevo registro de estado
        estado_reg = TareaHerramientaEstado(
            tarea_id=tarea_id,
            herramienta_id=herramienta_uuid,
            estado="en_uso",
            personal_id=current_user.id,
            cantidad_asignada=cantidad,
            cantidad_devuelta=0,
            fecha_inicio=datetime.now(),
        )
        db.add(estado_reg)

    # Marcar herramienta como en uso
    herramienta.estado = "En Uso"

    await db.commit()
    await db.refresh(estado_reg)

    return Envelope(
        message=f"Herramienta '{herramienta.nombre}' agregada (cantidad: {cantidad})",
        data=HerramientaEstadoOut.model_validate(estado_reg).model_dump()
    )


@router.post("/{tarea_id}/consumibles/agregar", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def agregar_consumible_tarea_iniciada(
    tarea_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Agrega un consumible a una tarea ya iniciada (con cantidad)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Invalid JSON body")

    consumible_id = body.get('consumible_id')
    cantidad = body.get('cantidad', 1)

    if not consumible_id:
        raise HTTPException(status_code=422, detail="consumible_id es requerido")

    try:
        consumible_uuid = uuid.UUID(str(consumible_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="consumible_id inválido")

    # Verificar tarea existe y está en progreso
    result_tarea = await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    tarea = result_tarea.scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")

    if tarea.estado != EstadoTarea.EN_PROGRESO:
        raise HTTPException(
            status_code=422,
            detail="Solo se pueden agregar consumibles a tareas en progreso"
        )

        # Verificar consumible existe
    result_consumible = await db.execute(
        select(Consumible).where(Consumible.id == consumible_uuid)
    )
    consumible = result_consumible.scalar_one_or_none()
    if not consumible:
        raise HTTPException(status_code=404, detail="Consumible no encontrado")

    # ✅ NUEVO: Validar stock suficiente
    if consumible.stock_actual < cantidad:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Stock insuficiente para '{consumible.nombre}'. "
                   f"Disponible: {consumible.stock_actual}, Requerido: {cantidad}"
        )

    # ✅ NUEVO: Decrementar stock del inventario
    consumible.stock_actual -= cantidad

    # Verificar si ya está asignado
    result_asignacion = await db.execute(
        select(tarea_consumible).where(
            tarea_consumible.c.tarea_id == tarea_id,
            tarea_consumible.c.consumible_id == consumible_uuid
        )
    )
    asignacion = result_asignacion.first()

    if asignacion:
        # Actualizar cantidad si ya existe
        await db.execute(
            tarea_consumible.update()
            .where(
                tarea_consumible.c.tarea_id == tarea_id,
                tarea_consumible.c.consumible_id == consumible_uuid
            )
            .values(cantidad=asignacion.cantidad + cantidad)
        )
    else:
        # Crear nueva asignación
        await db.execute(
            tarea_consumible.insert().values(
                tarea_id=tarea_id,
                consumible_id=consumible_uuid,
                cantidad=cantidad
            )
        )

    # Crear/actualizar registro de estado como "en_uso"
    result_estado = await db.execute(
        select(TareaConsumibleEstado)
        .where(
            TareaConsumibleEstado.tarea_id == tarea_id,
            TareaConsumibleEstado.consumible_id == consumible_uuid
        )
    )
    estado_reg = result_estado.scalar_one_or_none()

    if not estado_reg:
        estado_reg = TareaConsumibleEstado(
            tarea_id=tarea_id,
            consumible_id=consumible_uuid,
            estado="en_uso",
            personal_id=current_user.id,
            cantidad_asignada=cantidad,
            cantidad_devuelta=0,
            fecha_inicio=datetime.now(),
        )
        db.add(estado_reg)
    else:
        estado_reg.cantidad_asignada += cantidad
        estado_reg.estado = "en_uso"

    await db.commit()
    await db.refresh(estado_reg)

    return Envelope(
        message=f"Consumible '{consumible.nombre}' agregado (cantidad: {cantidad})",
        data=ConsumibleEstadoOut.model_validate(estado_reg).model_dump()
    )