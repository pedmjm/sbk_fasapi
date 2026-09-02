"""
Visitas (technical visits) router.

Flow (mirrors the Flet app's visitas views):
    generar visita (programada) → se realiza y se marca finalizada →
    informe técnico opcional (see `routers/informes.py`).

Endpoints (all require auth):
  GET    /visitas                  list (filters: estado, cliente_id, personal_id)
  POST   /visitas                  create (estado = programada)
  GET    /visitas/{visita_id}      detail (cliente/sucursal/personal/imagenes/informe)
  PUT    /visitas/{visita_id}      update (422 si finalizada/cancelada)
  POST   /visitas/{visita_id}/finalizar   marca finalizada (+incidencias/observaciones/
                                          detalles_tecnicos de la inspección)
  POST   /visitas/{visita_id}/cancelar    marca cancelada
  POST   /visitas/{visita_id}/imagenes    attach evidencias fotográficas (multipart)
  DELETE /visitas/{visita_id}      delete + cleanup files

Evidence photos use the polymorphic `imagenes` table
(`imageable_type == "Visita"`), files under `storage/visitas/{id}/`.

Notifications: when a visita is created with an assigned `personal_id`
(técnico), a push is sent to the User whose cédula matches that Personal.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
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
    EstadoVisita,
    Imagen,
    Personal,
    Sucursal,
    User,
    Visita,
)
from notifications import notify_users
from routers.informes import informe_payload
from schemas import (
    ClienteOut,
    Envelope,
    FinalizarVisitaBody,
    ImagenOut,
    PersonalOut,
    SucursalOut,
    VisitaCreate,
    VisitaOut,
    VisitaUpdate,
)
from storage_helpers import (
    build_public_url,
    delete_rel_path,
    delete_subdir,
    save_upload,
)

router = APIRouter(prefix="/visitas", tags=["visitas"])

_VALID_ESTADOS = {e.value for e in EstadoVisita}


# ─── Helpers ────────────────────────────────────────────────────────────────

_EAGER = (
    selectinload(Visita.cliente),
    selectinload(Visita.sucursal),
    selectinload(Visita.personal),
    selectinload(Visita.informe),
)


def _serialize_visita(visita: Visita) -> dict:
    """Build the nested response dict (relations must be eager-loaded)."""
    data = VisitaOut.model_validate(visita).model_dump(mode="json")
    data["cliente"] = (
        ClienteOut.model_validate(visita.cliente).model_dump(mode="json")
        if visita.cliente else None
    )
    data["sucursal"] = (
        SucursalOut.model_validate(visita.sucursal).model_dump(mode="json")
        if visita.sucursal else None
    )
    data["personal"] = (
        PersonalOut.model_validate(visita.personal).model_dump(mode="json")
        if visita.personal else None
    )
    data["imagenes"] = [
        ImagenOut.model_validate(img).model_dump(mode="json")
        for img in getattr(visita, "imagenes_proxy", [])
    ]
    data["informe"] = informe_payload(visita.informe) if visita.informe else None
    return data


async def _load_visita_imagenes(db: AsyncSession, visita: Visita) -> list[Imagen]:
    """Load the visita's polymorphic Imagen rows and stash them on the
    instance so `_serialize_visita` can find them."""
    imgs = (
        await db.execute(
            select(Imagen)
            .where(Imagen.imageable_type == "Visita", Imagen.imageable_id == str(visita.id))
            .order_by(Imagen.created_at)
        )
    ).scalars().all()
    visita.imagenes_proxy = imgs  # type: ignore[attr-defined]
    return imgs


async def _fetch_visita(db: AsyncSession, visita_id: uuid.UUID) -> Optional[Visita]:
    stmt = select(Visita).options(*_EAGER).where(Visita.id == visita_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _personal_user_id(db: AsyncSession, personal_id: uuid.UUID) -> Optional[uuid.UUID]:
    """User linked to a Personal via cédula — whom to notify."""
    p = (await db.execute(select(Personal).where(Personal.id == personal_id))).scalar_one_or_none()
    if not p or not p.cedula:
        return None
    u = (await db.execute(select(User).where(User.cedula == p.cedula))).scalar_one_or_none()
    return u.id if u else None


# ─── CRUD ───────────────────────────────────────────────────────────────────

@router.get("", response_model=Envelope)
async def list_visitas(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    estado: Optional[str] = None,
    cliente_id: Optional[uuid.UUID] = None,
    personal_id: Optional[uuid.UUID] = None,
):
    stmt = select(Visita).options(*_EAGER).order_by(Visita.fecha.desc())
    if estado is not None:
        if estado not in _VALID_ESTADOS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"estado must be one of {sorted(_VALID_ESTADOS)}",
            )
        stmt = stmt.where(Visita.estado == EstadoVisita(estado))
    if cliente_id is not None:
        stmt = stmt.where(Visita.cliente_id == cliente_id)
    if personal_id is not None:
        stmt = stmt.where(Visita.personal_id == personal_id)

    visitas = (await db.execute(stmt)).scalars().unique().all()
    for v in visitas:
        await _load_visita_imagenes(db, v)
    return Envelope(data=[_serialize_visita(v) for v in visitas])


@router.post("", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def create_visita(
    body: VisitaCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    cliente = (
        await db.execute(select(Cliente).where(Cliente.id == body.cliente_id))
    ).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cliente_id no existe")

    if body.sucursal_id is not None:
        suc = (
            await db.execute(select(Sucursal).where(Sucursal.id == body.sucursal_id))
        ).scalar_one_or_none()
        if not suc or str(suc.cliente_id) != str(body.cliente_id):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="sucursal_id no existe o no pertenece al cliente")

    if body.personal_id is not None:
        per = (
            await db.execute(select(Personal).where(Personal.id == body.personal_id))
        ).scalar_one_or_none()
        if not per:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="personal_id no existe")

    visita = Visita(
        cliente_id=body.cliente_id,
        sucursal_id=body.sucursal_id,
        personal_id=body.personal_id,
        creador_id=current_user.id,
        fecha=body.fecha,
        ubicacion=body.ubicacion,
        descripcion=body.descripcion,
        telefono_contacto=body.telefono_contacto,
        detalles_tecnicos=body.detalles_tecnicos,
        estado=EstadoVisita.PROGRAMADA,
    )
    db.add(visita)
    await db.commit()

    visita = await _fetch_visita(db, visita.id)
    await _load_visita_imagenes(db, visita)

    # Best-effort push to the assigned técnico's linked User.
    if body.personal_id:
        user_id = await _personal_user_id(db, body.personal_id)
        if user_id and user_id != current_user.id:
            await notify_users(
                [user_id],
                title="Nueva visita programada",
                message=(
                    f"{cliente.razon_social}\n"
                    f"{visita.fecha.strftime('%d/%m/%Y %H:%M')}"
                    + (f"\n{visita.ubicacion}" if visita.ubicacion else "")
                ),
                subtitle="Visita técnica",
                data={"visita_id": str(visita.id), "action": "visita.created"},
                android_group="visitas",
                thread_id="visitas",
                collapse_id=f"visita:{visita.id}",
                name="visita.created",
            )

    return Envelope(
        message="Visita creada exitosamente",
        data=_serialize_visita(visita),
    )


@router.get("/{visita_id}", response_model=Envelope)
async def get_visita(
    visita_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")
    await _load_visita_imagenes(db, visita)
    return Envelope(data=_serialize_visita(visita))


@router.put("/{visita_id}", response_model=Envelope)
async def update_visita(
    visita_id: uuid.UUID,
    body: VisitaUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if visita.estado in (EstadoVisita.FINALIZADA, EstadoVisita.CANCELADA):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No se puede editar una visita {visita.estado.value}",
        )

    data = body.model_dump(exclude_unset=True)

    if "cliente_id" in data and data["cliente_id"] is not None:
        exists = (await db.execute(select(Cliente.id).where(Cliente.id == data["cliente_id"]))).scalar_one_or_none()
        if not exists:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cliente_id no existe")
    if "sucursal_id" in data and data["sucursal_id"] is not None:
        suc = (await db.execute(select(Sucursal).where(Sucursal.id == data["sucursal_id"]))).scalar_one_or_none()
        target_cliente = data.get("cliente_id", visita.cliente_id)
        if not suc or str(suc.cliente_id) != str(target_cliente):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="sucursal_id no existe o no pertenece al cliente")
    if "personal_id" in data and data["personal_id"] is not None:
        exists = (await db.execute(select(Personal.id).where(Personal.id == data["personal_id"]))).scalar_one_or_none()
        if not exists:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="personal_id no existe")

    for k, v in data.items():
        setattr(visita, k, v)

    await db.commit()
    visita = await _fetch_visita(db, visita_id)
    await _load_visita_imagenes(db, visita)
    return Envelope(message="Visita actualizada exitosamente", data=_serialize_visita(visita))


@router.post("/{visita_id}/finalizar", response_model=Envelope)
async def finalizar_visita(
    visita_id: uuid.UUID,
    body: FinalizarVisitaBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Marca la visita como finalizada, registrando el resultado de la
    inspección (incidencias, observaciones, detalles técnicos)."""
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if visita.estado == EstadoVisita.CANCELADA:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No se puede finalizar una visita cancelada")
    if visita.estado == EstadoVisita.FINALIZADA:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La visita ya está finalizada")

    visita.estado = EstadoVisita.FINALIZADA
    data = body.model_dump(exclude_unset=True)
    for k in ("incidencias", "observaciones", "detalles_tecnicos"):
        if k in data:
            setattr(visita, k, data[k])

    await db.commit()
    visita = await _fetch_visita(db, visita_id)
    await _load_visita_imagenes(db, visita)
    return Envelope(message="Visita finalizada", data=_serialize_visita(visita))


@router.post("/{visita_id}/cancelar", response_model=Envelope)
async def cancelar_visita(
    visita_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if visita.estado == EstadoVisita.FINALIZADA:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No se puede cancelar una visita finalizada")

    visita.estado = EstadoVisita.CANCELADA
    await db.commit()
    return Envelope(message="Visita cancelada")


# ─── Evidencias fotográficas ────────────────────────────────────────────────

@router.post("/{visita_id}/imagenes", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def upload_visita_imagenes(
    visita_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    imagenes: list[UploadFile] = File(...),
):
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    saved: list[Imagen] = []
    for f in imagenes:
        try:
            rel = await save_upload(f, "visitas", str(visita_id))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        img = Imagen(
            path=rel,
            url=build_public_url(rel),
            imageable_type="Visita",
            imageable_id=str(visita_id),
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


@router.delete("/{visita_id}", response_model=Envelope)
async def delete_visita(
    visita_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    # 1. Delete every Imagen row referencing this Visita AND the physical
    #    files. (The informe cascades via FK and has no files.)
    imgs = (
        await db.execute(
            select(Imagen).where(Imagen.imageable_type == "Visita", Imagen.imageable_id == str(visita_id))
        )
    ).scalars().all()
    for img in imgs:
        delete_rel_path(img.path)
        await db.delete(img)
    delete_subdir("visitas", str(visita_id))

    # 2. Cascading FKs handle the informe.
    await db.delete(visita)
    await db.commit()
    return Envelope(message="Visita eliminada correctamente")
