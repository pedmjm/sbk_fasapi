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

from auth import get_current_active_user, require_nivel
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
    RevisionMotivoBody,
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


async def _revisores_ids(db: AsyncSession) -> list[uuid.UUID]:
    """User ids de los revisores (nivel >= 2, activos)."""
    rows = (
        await db.execute(
            select(User.id).where(User.nivel >= 2, User.disabled == False)  # noqa: E712
        )
    ).scalars().all()
    return list(rows)


async def _otros_admins_ids(db: AsyncSession, excepto_id: uuid.UUID) -> list[uuid.UUID]:
    """User ids de los demás admins activos (nivel >= 2)."""
    return [i for i in await _revisores_ids(db) if i != excepto_id]


async def _notificar_cierre_o_devolucion(
    db: AsyncSession, visita: Visita, titulo: str, mensaje: str, data: dict
) -> None:
    """Push al creador + técnico asignado (si tienen user vinculado)."""
    ids: set[uuid.UUID] = set()
    if visita.creador_id:
        ids.add(visita.creador_id)
    if visita.personal_id:
        uid = await _personal_user_id(db, visita.personal_id)
        if uid:
            ids.add(uid)
    if ids:
        await notify_users(ids, title=titulo, message=mensaje, data=data,
                           android_group="visitas", thread_id="visitas",
                           collapse_id=f"visita:{visita.id}")


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
    print("visita data:", body)
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if visita.estado in (EstadoVisita.EN_REVISION, EstadoVisita.FINALIZADA, EstadoVisita.CANCELADA):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No se puede editar una visita {visita.estado.value}"
            " (en revisión/finalizada/cancelada; pide que la devuelvan a en_progreso)",
        )

    data = body.model_dump(exclude_unset=True)
    print("visita data:", data)
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
    current_user: Annotated[User, Depends(require_nivel(1))],
):
    """Marca la visita como realizada → estado **en_revision** (nivel ≥ 1).
    Registra el resultado de la inspección (incidencias, observaciones,
    detalles técnicos). Un revisor (nivel >= 2) la cierra (`/cerrar`) o la
    devuelve (`/devolver`) a en_progreso."""
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if visita.estado == EstadoVisita.CANCELADA:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No se puede finalizar una visita cancelada")
    if visita.estado == EstadoVisita.EN_REVISION:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La visita ya está en revisión")
    if visita.estado == EstadoVisita.FINALIZADA:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="La visita ya está finalizada")

    visita.estado = EstadoVisita.EN_REVISION
    data = body.model_dump(exclude_unset=True)
    for k in ("incidencias", "observaciones", "detalles_tecnicos"):
        if k in data:
            setattr(visita, k, data[k])

    await db.commit()
    visita = await _fetch_visita(db, visita_id)
    await _load_visita_imagenes(db, visita)

    # Push a los revisores (nivel >= 2).
    revisores = await _revisores_ids(db)
    revisores = [r for r in revisores if r != current_user.id]
    if revisores:
        await notify_users(
            revisores,
            title="Visita enviada a revisión",
            message=f"{visita.cliente.razon_social if visita.cliente else 'Visita'} — esperando cierre",
            data={"visita_id": str(visita_id), "action": "visita.revision"},
            android_group="visitas",
            thread_id="visitas",
            collapse_id=f"visita:{visita_id}",
            name="visita.revision",
        )

    return Envelope(message="Visita enviada a revisión", data=_serialize_visita(visita))


@router.post("/{visita_id}/cerrar", response_model=Envelope)
async def cerrar_visita(
    visita_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _revisor: Annotated[User, Depends(require_nivel(2))],
):
    """Revisor (nivel >= 2): cierra la visita en revisión → finalizada."""
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if visita.estado != EstadoVisita.EN_REVISION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La visita está '{visita.estado.value}' — solo se cierra desde 'en_revision'",
        )

    visita.estado = EstadoVisita.FINALIZADA
    await db.commit()
    visita = await _fetch_visita(db, visita_id)
    await _load_visita_imagenes(db, visita)

    await _notificar_cierre_o_devolucion(
        db, visita,
        titulo="Visita aprobada",
        mensaje=f"'{visita.cliente.razon_social if visita.cliente else visita_id}' fue cerrada por revisión",
        data={"visita_id": str(visita_id), "action": "visita.cerrada"},
    )
    return Envelope(message="Visita cerrada (finalizada)", data=_serialize_visita(visita))


@router.post("/{visita_id}/devolver", response_model=Envelope)
async def devolver_visita(
    visita_id: uuid.UUID,
    body: RevisionMotivoBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    _revisor: Annotated[User, Depends(require_nivel(2))],
):
    """Revisor (nivel >= 2): devuelve la visita en revisión → en_progreso
    (editable de nuevo: imágenes, comentarios, edición, etc.)."""
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if visita.estado != EstadoVisita.EN_REVISION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La visita está '{visita.estado.value}' — solo se devuelve desde 'en_revision'",
        )

    visita.estado = EstadoVisita.EN_PROGRESO
    await db.commit()
    visita = await _fetch_visita(db, visita_id)
    await _load_visita_imagenes(db, visita)

    await _notificar_cierre_o_devolucion(
        db, visita,
        titulo="Visita devuelta",
        mensaje=(f"Devuelta a en_progreso: {body.motivo}" if body.motivo
                 else "Devuelta a en_progreso para correcciones"),
        data={"visita_id": str(visita_id), "action": "visita.devuelta"},
    )
    return Envelope(message="Visita devuelta a en_progreso", data=_serialize_visita(visita))


@router.post("/{visita_id}/reabrir", response_model=Envelope)
async def reabrir_visita(
    visita_id: uuid.UUID,
    body: RevisionMotivoBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    _revisor: Annotated[User, Depends(require_nivel(2))],
):
    """Revisor (nivel >= 2): devuelve una visita FINALIZADA a en_revision,
    para luego decidir con /devolver (abrir) o /cerrar (cerrar). El
    informe (si existe) permanece anclado a la visita."""
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if visita.estado != EstadoVisita.FINALIZADA:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La visita está '{visita.estado.value}' — solo se reabre desde 'finalizada'",
        )

    visita.estado = EstadoVisita.EN_REVISION
    await db.commit()
    visita = await _fetch_visita(db, visita_id)
    await _load_visita_imagenes(db, visita)

    await _notificar_cierre_o_devolucion(
        db, visita,
        titulo="Visita reabierta a revisión",
        mensaje=(f"{body.motivo}" if body.motivo
                 else "Reabierta a revisión para reevaluación"),
        data={"visita_id": str(visita_id), "action": "visita.reabierta"},
    )
    return Envelope(message="Visita reabierta a revisión", data=_serialize_visita(visita))


@router.post("/{visita_id}/marcar-eliminar", response_model=Envelope)
async def marcar_eliminar_visita(
    visita_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_nivel(2))],
):
    """Admin (nivel >= 2): marca la visita para eliminar (cualquier
    estado). La eliminación real la confirma OTRO admin vía DELETE —
    quien marcó no puede eliminarla (principio de 4 ojos)."""
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    visita.eliminar_marcada = True
    visita.eliminar_marcada_por_id = current_user.id
    await db.commit()

    otros = await _otros_admins_ids(db, current_user.id)
    if otros:
        await notify_users(
            otros,
            title="Visita marcada para eliminar",
            message=f"{visita.cliente.razon_social if visita.cliente else 'Visita'} — requiere confirmación de otro administrador",
            data={"visita_id": str(visita_id), "action": "visita.eliminar_marcada"},
            android_group="visitas",
            thread_id="visitas",
            name="visita.eliminar_marcada",
        )

    return Envelope(
        message="Visita marcada para eliminar — otro administrador debe confirmar",
        data={"id": str(visita_id), "eliminar_marcada": True,
              "eliminar_marcada_por_id": str(current_user.id)},
    )


@router.post("/{visita_id}/desmarcar-eliminar", response_model=Envelope)
async def desmarcar_eliminar_visita(
    visita_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[User, Depends(require_nivel(2))],
):
    """Admin (nivel >= 2): cancela la solicitud de eliminación."""
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if not visita.eliminar_marcada:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La visita no está marcada para eliminar",
        )

    visita.eliminar_marcada = False
    visita.eliminar_marcada_por_id = None
    await db.commit()
    return Envelope(
        message="Solicitud de eliminación cancelada",
        data={"id": str(visita_id), "eliminar_marcada": False,
              "eliminar_marcada_por_id": None},
    )


@router.post("/{visita_id}/cancelar", response_model=Envelope)
async def cancelar_visita(
    visita_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if visita.estado == EstadoVisita.FINALIZADA:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No se puede cancelar una visita finalizada")
    if visita.estado == EstadoVisita.EN_REVISION and current_user.nivel < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La visita está en revisión: solo un revisor (nivel >= 2) puede cancelarla",
        )

    visita.estado = EstadoVisita.CANCELADA
    await db.commit()
    return Envelope(message="Visita cancelada")


# ─── Evidencias fotográficas (solo con la visita ABIERTA) ──────────────────

# Estados donde aún se puede subir/eliminar imágenes.
_ESTADOS_ABIERTOS = (EstadoVisita.PROGRAMADA, EstadoVisita.EN_PROGRESO)


def _check_visita_abierta(visita: Visita) -> None:
    """Subir y eliminar imágenes solo es posible mientras la visita esté
    abierta (programada / en_progreso). En revisión, finalizada o
    cancelada → 422 (pide que la devuelvan a en_progreso)."""
    if visita.estado not in _ESTADOS_ABIERTOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"La visita está '{visita.estado.value}': solo se pueden gestionar "
                "imágenes mientras esté abierta (programada/en_progreso)"
            ),
        )


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
    _check_visita_abierta(visita)

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


@router.delete("/{visita_id}/imagenes/{imagen_id}", response_model=Envelope)
async def delete_visita_imagen(
    visita_id: uuid.UUID,
    imagen_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Elimina una evidencia fotográfica de la visita (fila + archivo
    físico). Solo con la visita abierta."""
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")
    _check_visita_abierta(visita)

    img = (
        await db.execute(
            select(Imagen).where(
                Imagen.id == imagen_id,
                Imagen.imageable_type == "Visita",
                Imagen.imageable_id == str(visita_id),
            )
        )
    ).scalar_one_or_none()
    if not img:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Imagen no encontrada en esta visita",
        )

    delete_rel_path(img.path)
    await db.delete(img)
    await db.commit()
    return Envelope(message="Imagen eliminada")


@router.delete("/{visita_id}", response_model=Envelope)
async def delete_visita(
    visita_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_nivel(2))],
):
    """Elimina la visita — eliminación en DOS PASOS (4 ojos):
    1) un admin la marcó (`/marcar-eliminar`),
    2) OTRO admin distinto confirma aquí."""
    visita = await _fetch_visita(db, visita_id)
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if not visita.eliminar_marcada:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La visita debe estar marcada para eliminar antes (POST /visitas/{id}/marcar-eliminar)",
        )
    if visita.eliminar_marcada_por_id is not None and str(visita.eliminar_marcada_por_id) == str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El administrador que marcó la visita no puede eliminarla — requiere confirmación de otro administrador",
        )

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
