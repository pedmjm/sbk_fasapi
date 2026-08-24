"""
Picking CRUD router.

Flujo:
  1. Creador (tipo_usuario > 0) crea el picking con referencia, motivo,
     personal asignado e ítems iniciales.
  2. Los técnicos asignados ven la lista y pueden:
     - Marcar ítems como "tomado", "no_disponible" o "innecesario".
     - Agregar ítems adicionales que consideren necesarios.
  3. El progreso se recalcula con cada cambio de estado de ítem.
  4. La respuesta incluye `signal` para futura integración con WebSocket.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_active_user, require_nivel
from database import get_db
from models import (
    Consumible,
    EstadoPicking,
    EstadoPickingItem,
    Herramienta,
    Picking,
    PickingItem,
    Personal,
    User,
)
from schemas import (
    Envelope,
    PickingCreate,
    PickingItemAddByTecnico,
    PickingItemEstadoUpdate,
    PickingItemOut,
    PickingListOut,
    PickingOut,
    PickingUpdate,
)

router = APIRouter(prefix="/picking", tags=["picking"])

_VALID_ESTADOS_PICKING = {e.value for e in EstadoPicking}
_VALID_ESTADOS_ITEM = {e.value for e in EstadoPickingItem}
_VALID_ITEM_TYPES = {"herramienta", "consumible"}


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _recalcular_progreso(db: AsyncSession, picking_id: uuid.UUID) -> int:
    """Recalcula y persiste el progreso del picking (0-100)."""
    total = (
        await db.execute(
            select(func.count(PickingItem.id)).where(
                PickingItem.picking_id == picking_id
            )
        )
    ).scalar() or 0
    
    if total == 0:
        progreso = 0
    else:
        completados = (
            await db.execute(
                select(func.count(PickingItem.id)).where(
                    PickingItem.picking_id == picking_id,
                    PickingItem.estado.in_([
                        EstadoPickingItem.TOMADO,
                        EstadoPickingItem.NO_DISPONIBLE,
                        EstadoPickingItem.INNECESARIO,
                    ]),
                )
            )
        ).scalar() or 0
        progreso = int((completados / total) * 100)
    
    await db.execute(
        Picking.__table__.update()
        .where(Picking.id == picking_id)
        .values(progreso=progreso)
    )
    await db.commit()
    return progreso


async def _emit_signal(
    picking_id: uuid.UUID,
    event_type: str,
    detail: dict | None = None,
) -> dict:
    """Genera la señal para futura integración WebSocket."""
    return {
        "type": "picking_update",
        "event": event_type,
        "picking_id": str(picking_id),
        "detail": detail or {},
    }


async def _get_picking_or_404(
    db: AsyncSession, picking_id: uuid.UUID
) -> Picking:
    p = (
        await db.execute(select(Picking).where(Picking.id == picking_id))
    ).scalar_one_or_none()
    if not p:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Picking no encontrado",
        )
    return p


async def _is_assigned_technician(
    db: AsyncSession, picking_id: uuid.UUID, user: User
) -> bool:
    """Verifica si el usuario actual está asignado al picking como técnico."""
    from models import picking_personal
    
    # 1. Buscar la entidad Personal que corresponde a la cédula del usuario
    personal = (
        await db.execute(
            select(Personal.id).where(Personal.cedula == user.cedula)
        )
    ).scalar_one_or_none()
    
    if not personal:
        return False
    
    # 2. Verificar la asignación usando personal.id (UUID)
    result = await db.execute(
        select(picking_personal.c.picking_id).where(
            picking_personal.c.picking_id == picking_id,
            picking_personal.c.personal_id == personal, # personal is already a UUID scalar
        )
    )
    return result.scalar_one_or_none() is not None

# ─── ENDPOINTS ──────────────────────────────────────────────────────────────

@router.get("", response_model=Envelope)
async def list_pickings(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    estado: Optional[str] = Query(None, description="Filtrar por estado"),
    asignado_a_mi: bool = Query(False, description="Solo asignados a mí"),
    search: Optional[str] = Query(None, description="Buscar por referencia/motivo"),
    utilizado: Optional[bool] = Query(None, description="Filtrar por utilizado"),
):
    """Lista pickings. Los técnicos solo ven los asignados a ellos."""
    query = select(Picking).order_by(Picking.created_at.desc())

    

    # Si es técnico (tipo_usuario == 0), solo ve los suyos
    if current_user.nivel == 0 or asignado_a_mi:
        from models import picking_personal
        
        my_personal = (
            await db.execute(
                select(Personal.id).where(Personal.cedula == current_user.cedula)
            )
        ).scalar_one_or_none()
        
        if my_personal:
            my_picking_ids = (
                await db.execute(
                    select(picking_personal.c.picking_id).where(
                        picking_personal.c.personal_id == my_personal.id
                    )
                )
            ).scalars().all()
            if my_picking_ids:
                query = query.where(Picking.id.in_(my_picking_ids))
            else:
                return Envelope(data=[])
        else:
            return Envelope(data=[])
    
    if estado and estado in _VALID_ESTADOS_PICKING:
        query = query.where(Picking.estado == estado)
    
    if search:
        query = query.where(
            (Picking.referencia.ilike(f"%{search}%"))
            | (Picking.motivo.ilike(f"%{search}%"))
        )
    if utilizado is not None:
        query = query.where(Picking.utilizado == utilizado)
    
    result = await db.execute(query)
    pickings = result.scalars().all()
    
        # Construir respuesta con conteos — sin tocar relaciones lazy
    from models import picking_personal as pp

    out = []
    for p in pickings:
        total_items = (
            await db.execute(
                select(func.count(PickingItem.id)).where(
                    PickingItem.picking_id == p.id
                )
            )
        ).scalar() or 0

        completados = (
            await db.execute(
                select(func.count(PickingItem.id)).where(
                    PickingItem.picking_id == p.id,
                    PickingItem.estado.in_([
                        EstadoPickingItem.TOMADO,
                        EstadoPickingItem.NO_DISPONIBLE,
                        EstadoPickingItem.INNECESARIO,
                    ]),
                )
            )
        ).scalar() or 0

        personal_rows = (
            await db.execute(
                select(Personal)
                .join(pp, pp.c.personal_id == Personal.id)
                .where(pp.c.picking_id == p.id)
            )
        ).scalars().all()

        out.append({
            "id": p.id,
            "referencia": p.referencia,
            "motivo": p.motivo,
            "estado": p.estado.value if hasattr(p.estado, "value") else p.estado,
            "creador_id": p.creador_id,
            "creador_nombre": "who de fuck",
            "progreso": p.progreso,
            "total_items": total_items,
            "items_completados": completados,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
            "personal_asignado": [
                {
                    "id": pr.id,
                    "nombre": pr.nombre,
                    "cedula": pr.cedula,
                    "cargo": pr.cargo,
                    "activo": pr.activo,
                }
                for pr in personal_rows
            ],
        })

    return Envelope(data=out)


@router.post("", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def create_picking(
    body: PickingCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_nivel(1))],
):
    """Crea un nuevo picking. Requiere tipo_usuario >= 1."""
    
    # Validar personal asignado
    if body.personal_ids:
        personales = (
            await db.execute(
                select(Personal).where(Personal.id.in_(body.personal_ids))
            )
        ).scalars().all()
        
        if len(personales) != len(body.personal_ids):
            found_ids = {p.id for p in personales}
            missing = set(body.personal_ids) - found_ids
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Personal no encontrado: {missing}",
            )
    
    # Validar ítems
    items_to_create = []
    for item_req in body.items:
        if item_req.item_type not in _VALID_ITEM_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"item_type debe ser uno de {_VALID_ITEM_TYPES}",
            )
        
        if item_req.item_type == "herramienta":
            original = (
                await db.execute(
                    select(Herramienta).where(Herramienta.id == item_req.item_id)
                )
            ).scalar_one_or_none()
            if not original:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Herramienta {item_req.item_id} no encontrada",
                )
            nombre = original.nombre
            detalle = f"{original.marca or ''} {original.serial or ''}".strip()
        else:  # consumible
            original = (
                await db.execute(
                    select(Consumible).where(Consumible.id == item_req.item_id)
                )
            ).scalar_one_or_none()
            if not original:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Consumible {item_req.item_id} no encontrado",
                )
            nombre = original.nombre
            detalle = original.descripcion
        
        items_to_create.append({
            "item_type": item_req.item_type,
            "item_id": item_req.item_id,
            "nombre": nombre,
            "detalle": detalle,
            "cantidad_solicitada": item_req.cantidad,
        })
    
    # Crear picking
    estado_inicial = (
        EstadoPicking.ASIGNADO if body.personal_ids else EstadoPicking.BORRADOR
    )
    picking = Picking(
        referencia=body.referencia,
        motivo=body.motivo,
        estado=estado_inicial,
        creador_id=current_user.id,
    )
    db.add(picking)
    await db.flush()  # Para obtener el ID
    
    # Asignar personal
    if body.personal_ids:
        from models import picking_personal
        
        for pid in body.personal_ids:
            await db.execute(
                picking_personal.insert().values(
                    picking_id=picking.id, personal_id=pid
                )
            )
    
    # Crear ítems
    for item_data in items_to_create:
        pi = PickingItem(picking_id=picking.id, **item_data)
        db.add(pi)
    
    await db.commit()
    await db.refresh(picking)
    
    signal = await _emit_signal(picking.id, "picking_created", {
        "referencia": picking.referencia,
        "total_items": len(items_to_create),
    })
    
    return Envelope(
        message="Picking creado correctamente",
        data=await _get_picking_full(db, picking.id),
        signal=signal,
    )


@router.get("/{picking_id}", response_model=Envelope)
async def get_picking(
    picking_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Obtiene un picking completo con todos sus ítems."""
    picking = await _get_picking_or_404(db, picking_id)
    
    # Verificar acceso: creador, asignado, o admin
    if (
        picking.creador_id != current_user.id
        and current_user.nivel == 0
        and not await _is_assigned_technician(db, picking_id, current_user)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este picking",
        )
    
    return Envelope(data=await _get_picking_full(db, picking_id))


@router.put("/{picking_id}", response_model=Envelope)
async def update_picking(
    picking_id: uuid.UUID,
    body: PickingUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_nivel(1))],
):
    """Actualiza un picking. Solo el creador o admin puede editar."""
    picking = await _get_picking_or_404(db, picking_id)
    
    if picking.creador_id != current_user.id and current_user.nivel < 2:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el creador o un admin puede editar el picking",
        )
    
    data = body.model_dump(exclude_unset=True)
    
    # No permitir cambiar estado a "completado" aquí (se hace vía endpoint específico)
    if "estado" in data and data["estado"] == EstadoPicking.COMPLETADO.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Use el endpoint específico para completar el picking",
        )
    
    if "estado" in data and data["estado"] not in _VALID_ESTADOS_PICKING:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"estado debe ser uno de {_VALID_ESTADOS_PICKING}",
        )
    
    # Actualizar campos simples
    for key in ["referencia", "motivo", "estado"]:
        if key in data:
            setattr(picking, key, data[key])
    
    # Actualizar personal asignado (reemplazo completo)
    if "personal_ids" in data and data["personal_ids"] is not None:
        from models import picking_personal
        
        # Eliminar asignaciones actuales
        await db.execute(
            picking_personal.delete().where(
                picking_personal.c.picking_id == picking_id
            )
        )
        
        # Agregar nuevas
        for pid in data["personal_ids"]:
            await db.execute(
                picking_personal.insert().values(
                    picking_id=picking_id, personal_id=pid
                )
            )
        
        # Actualizar estado si tenía personal
        if data["personal_ids"] and picking.estado == EstadoPicking.BORRADOR:
            picking.estado = EstadoPicking.ASIGNADO
    
    await db.commit()
    await db.refresh(picking)
    
    signal = await _emit_signal(picking_id, "picking_updated")
    
    return Envelope(
        message="Picking actualizado correctamente",
        data=await _get_picking_full(db, picking_id),
        signal=signal,
    )


@router.delete("/{picking_id}", response_model=Envelope)
async def delete_picking(
    picking_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_nivel(2))],
):
    """Elimina un picking. Solo admin o superior."""
    picking = await _get_picking_or_404(db, picking_id)
    
    if picking.estado not in [
        EstadoPicking.BORRADOR,
        EstadoPicking.CANCELADO,
        EstadoPicking.COMPLETADO,
    ]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Solo se pueden eliminar pickings en borrador, cancelados o completados",
        )
    
    await db.delete(picking)
    await db.commit()
    
    signal = await _emit_signal(picking_id, "picking_deleted")
    
    return Envelope(
        message="Picking eliminado correctamente",
        signal=signal,
    )


# ─── ENDPOINTS DE ÍTEMS (para el técnico) ──────────────────────────────────

@router.patch(
    "/{picking_id}/items/{item_id}/estado",
    response_model=Envelope,
    summary="Técnico actualiza estado de ítem",
)
async def update_item_estado(
    picking_id: uuid.UUID,
    item_id: uuid.UUID,
    body: PickingItemEstadoUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """El técnico marca un ítem como tomado, no disponible o innecesario.
    
    Genera una señal para WebSocket indicando el avance.
    """
    if body.estado not in _VALID_ESTADOS_ITEM:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"estado debe ser uno de {_VALID_ESTADOS_ITEM}",
        )
    
    # Verificar que el técnico está asignado
    if not await _is_assigned_technician(db, picking_id, current_user):
        # Permitir si es creador o admin
        picking = await _get_picking_or_404(db, picking_id)
        if picking.creador_id != current_user.id and current_user.nivel < 1:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No estás asignado a este picking",
            )
    
    item = (
        await db.execute(
            select(PickingItem).where(
                PickingItem.id == item_id,
                PickingItem.picking_id == picking_id,
            )
        )
    ).scalar_one_or_none()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ítem no encontrado en este picking",
        )
    
    # Actualizar estado
    item.estado = EstadoPickingItem(body.estado)
    item.actualizado_por_id = current_user.id
    item.notas = body.notas if body.notas is not None else item.notas
    
    # Actualizar cantidad tomada
    if body.estado == EstadoPickingItem.TOMADO.value:
        item.cantidad_tomada = (
            body.cantidad_tomada
            if body.cantidad_tomada is not None
            else item.cantidad_solicitada
        )
    else:
        item.cantidad_tomada = 0
    
    # Si estaba en borrador, mover a en_progreso
    picking = await _get_picking_or_404(db, picking_id)
    if picking.estado == EstadoPicking.ASIGNADO:
        picking.estado = EstadoPicking.EN_PROGRESO
    
    await db.commit()
    await db.refresh(item)
    
    # Recalcular progreso
    nuevo_progreso = await _recalcular_progreso(db, picking_id)
    
    signal = await _emit_signal(
        picking_id,
        "item_estado_changed",
        {
            "item_id": str(item_id),
            "nuevo_estado": body.estado,
            "progreso": nuevo_progreso,
        },
    )
    
    return Envelope(
        message=f"Ítem marcado como '{body.estado}'",
        data=PickingItemOut.model_validate(item),
        signal=signal,
    )


@router.post(
    "/{picking_id}/items",
    response_model=Envelope,
    status_code=status.HTTP_201_CREATED,
    summary="Técnico agrega ítem faltante",
)
async def add_item_by_tecnico(
    picking_id: uuid.UUID,
    body: PickingItemAddByTecnico,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """El técnico agrega un ítem que considera necesario y no estaba en la lista."""
    
    # Verificar acceso
    if not await _is_assigned_technician(db, picking_id, current_user):
        picking = await _get_picking_or_404(db, picking_id)
        if picking.creador_id != current_user.id and current_user.nivel < 1:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No estás asignado a este picking",
            )
    
    if body.item_type not in _VALID_ITEM_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"item_type debe ser uno de {_VALID_ITEM_TYPES}",
        )
    
    # Si proporcionó item_id, validar que existe
    detalle = body.detalle
    if body.item_id:
        if body.item_type == "herramienta":
            original = (
                await db.execute(
                    select(Herramienta).where(Herramienta.id == body.item_id)
                )
            ).scalar_one_or_none()
            if not original:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Herramienta no encontrada",
                )
            if not body.nombre:
                body.nombre = original.nombre
            if not detalle:
                detalle = f"{original.marca or ''} {original.serial or ''}".strip()
        else:
            original = (
                await db.execute(
                    select(Consumible).where(Consumible.id == body.item_id)
                )
            ).scalar_one_or_none()
            if not original:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Consumible no encontrado",
                )
            if not body.nombre:
                body.nombre = original.nombre
            if not detalle:
                detalle = original.descripcion
    
    picking = await _get_picking_or_404(db, picking_id)
    if picking.estado == EstadoPicking.ASIGNADO:
        picking.estado = EstadoPicking.EN_PROGRESO
    
    item = PickingItem(
        picking_id=picking_id,
        item_type=body.item_type,
        item_id=body.item_id,
        nombre=body.nombre,
        detalle=detalle,
        estado=EstadoPickingItem.PENDIENTE,
        actualizado_por_id=current_user.id,
        cantidad_solicitada=body.cantidad,
        notas=body.notas,
        agregado_por_tecnico=True,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    
    # Recalcular progreso
    nuevo_progreso = await _recalcular_progreso(db, picking_id)
    
    signal = await _emit_signal(
        picking_id,
        "item_added_by_tecnico",
        {
            "item_id": str(item.id),
            "nombre": item.nombre,
            "agregado_por": current_user.name,
            "progreso": nuevo_progreso,
        },
    )
    
    return Envelope(
        message="Ítem agregado correctamente",
        data=PickingItemOut.model_validate(item),
        signal=signal,
    )


@router.delete(
    "/{picking_id}/items/{item_id}",
    response_model=Envelope,
    summary="Eliminar ítem del picking",
)
async def delete_picking_item(
    picking_id: uuid.UUID,
    item_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Elimina un ítem del picking. Solo si fue agregado por técnico o es creador."""
    picking = await _get_picking_or_404(db, picking_id)
    
    item = (
        await db.execute(
            select(PickingItem).where(
                PickingItem.id == item_id,
                PickingItem.picking_id == picking_id,
            )
        )
    ).scalar_one_or_none()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ítem no encontrado",
        )
    
    # Solo el creador puede eliminar ítems originales
    # El técnico solo puede eliminar los que él agregó
    if item.agregado_por_tecnico:
        if not await _is_assigned_technician(db, picking_id, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo el técnico que lo agregó puede eliminarlo",
            )
    else:
        if picking.creador_id != current_user.id and current_user.nivel < 2:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo el creador o admin puede eliminar ítems originales",
            )
    
    await db.delete(item)
    await db.commit()
    
    # Recalcular progreso
    nuevo_progreso = await _recalcular_progreso(db, picking_id)
    
    signal = await _emit_signal(
        picking_id,
        "item_deleted",
        {"item_id": str(item_id), "progreso": nuevo_progreso},
    )
    
    return Envelope(
        message="Ítem eliminado del picking",
        signal=signal,
    )


# ─── ENDPOINTS DE ESTADO DEL PICKING ───────────────────────────────────────

@router.post(
    "/{picking_id}/completar",
    response_model=Envelope,
    summary="Completar picking",
)
async def completar_picking(
    picking_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_nivel(1))],
):
    """Marca el picking como completado. Solo creador o admin."""
    picking = await _get_picking_or_404(db, picking_id)
    
    if picking.estado == EstadoPicking.COMPLETADO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El picking ya está completado",
        )
    
    if picking.estado == EstadoPicking.CANCELADO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se puede completar un picking cancelado",
        )
    
    picking.estado = EstadoPicking.COMPLETADO
    picking.progreso = 100
    await db.commit()
    await db.refresh(picking)
    
    signal = await _emit_signal(picking_id, "picking_completed", {
        "referencia": picking.referencia,
    })
    
    return Envelope(
        message="Picking marcado como completado",
        data=await _get_picking_full(db, picking_id),
        signal=signal,
    )


@router.post(
    "/{picking_id}/cancelar",
    response_model=Envelope,
    summary="Cancelar picking",
)
async def cancelar_picking(
    picking_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_nivel(1))],
):
    """Cancela un picking. Solo creador o admin."""
    picking = await _get_picking_or_404(db, picking_id)
    
    if picking.estado in [
        EstadoPicking.COMPLETADO,
        EstadoPicking.CANCELADO,
    ]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No se puede cancelar un picking completado o ya cancelado",
        )
    
    picking.estado = EstadoPicking.CANCELADO
    await db.commit()
    await db.refresh(picking)
    
    signal = await _emit_signal(picking_id, "picking_cancelled")
    
    return Envelope(
        message="Picking cancelado",
        data=await _get_picking_full(db, picking_id),
        signal=signal,
    )


# ─── ENDPOINT DE CATÁLOGO (para seleccionar items al crear) ────────────────

@router.get("/catalogo/buscar", response_model=Envelope)
async def buscar_catalogo(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    q: str = Query("", description="Término de búsqueda"),
    tipo: Optional[str] = Query(None, description="Filtrar: herramienta|consumible"),
):
    """Busca herramientas y consumibles para agregar al picking."""
    resultados = []
    
    if not tipo or tipo == "herramienta":
        herramientas = (
            await db.execute(
                select(Herramienta)
                .where(Herramienta.nombre.ilike(f"%{q}%"))
                .limit(20)
            )
        ).scalars().all()
        
        for h in herramientas:
            resultados.append({
                "type": "herramienta",
                "id": str(h.id),
                "nombre": h.nombre,
                "detalle": f"{h.marca or ''} {h.serial or ''}".strip(),
                "estado": h.estado,
                "tipo": h.tipo.value,
            })
    
    if not tipo or tipo == "consumible":
        consumibles = (
            await db.execute(
                select(Consumible)
                .where(Consumible.nombre.ilike(f"%{q}%"))
                .limit(20)
            )
        ).scalars().all()
        
        for c in consumibles:
            resultados.append({
                "type": "consumible",
                "id": str(c.id),
                "nombre": c.nombre,
                "detalle": c.descripcion,
                "estado": c.estado,
                "stock": c.stock_actual,
                "unidad": c.unidad_medida,
            })
    
    return Envelope(data=resultados)


# ─── Helper interno ─────────────────────────────────────────────────────────

async def _get_picking_full(db: AsyncSession, picking_id: uuid.UUID) -> dict:
    """Obtiene el picking completo sin tocar relaciones lazy."""
    from models import picking_personal
    picking = await _get_picking_or_404(db, picking_id)

    # Buscar el nombre del creador directamente por el UUID unificado
    creador_nombre = "Desconocido"
    if picking.creador_id:
        creador_row = (
            await db.execute(
                select(User.name).where(User.id == picking.creador_id)
            )
        ).scalar_one_or_none()
        
        if creador_row:
            creador_nombre = creador_row
        else:
            # Fallback a la tabla personal por si el creador fue un registro sin usuario activo
            personal_row = (
                await db.execute(
                    select(Personal.nombre).where(Personal.id == picking.creador_id)
                )
            ).scalar_one_or_none()
            if personal_row:
                creador_nombre = personal_row

    # Cargar personal asignado
    personal_rows = (
        await db.execute(
            select(Personal)
            .join(picking_personal, picking_personal.c.personal_id == Personal.id)
            .where(picking_personal.c.picking_id == picking_id)
        )
    ).scalars().all()

    # Cargar items
    items = (
        await db.execute(
            select(PickingItem)
            .where(PickingItem.picking_id == picking_id)
            .order_by(PickingItem.item_type, PickingItem.nombre)
        )
    ).scalars().all()

    return {
        "id": picking.id,
        "referencia": picking.referencia,
        "motivo": picking.motivo,
        "estado": picking.estado.value if hasattr(picking.estado, "value") else picking.estado,
        "creador_id": picking.creador_id,
        "creador_nombre": creador_nombre,
        "progreso": picking.progreso,
        "created_at": picking.created_at,
        "updated_at": picking.updated_at,
        "personal_asignado": [
            {
                "id": p.id,
                "nombre": p.nombre,
                "cedula": p.cedula,
                "cargo": p.cargo,
                "activo": p.activo,
            }
            for p in personal_rows
        ],
        "items": [
            {
                "id": i.id,
                "picking_id": i.picking_id,
                "item_type": i.item_type,
                "item_id": i.item_id,
                "nombre": i.nombre,
                "detalle": i.detalle,
                "estado": i.estado.value if hasattr(i.estado, "value") else i.estado,
                "actualizado_por_id": i.actualizado_por_id,
                "cantidad_solicitada": i.cantidad_solicitada,
                "cantidad_tomada": i.cantidad_tomada,
                "notas": i.notas,
                "agregado_por_tecnico": i.agregado_por_tecnico,
                "created_at": i.created_at,
                "updated_at": i.updated_at,
            }
            for i in items
        ],
    }


@router.patch("/{picking_id}/utilizado", response_model=Envelope)
async def marcar_picking_utilizado(
    picking_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Marca el picking como utilizado (no se podrá volver a importar)."""
    picking = await _get_picking_or_404(db, picking_id)
    if picking.creador_id != current_user.id and current_user.nivel < 1:
        raise HTTPException(status_code=403, detail="No tienes permisos")
    picking.utilizado = True
    await db.commit()
    return Envelope(message="Picking marcado como utilizado")