"""
Consumibles CRUD router.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_active_user, require_admin
from database import get_db
from models import Consumible, TipoConsumible, User
from schemas import (
    Envelope,
    ConsumibleCreate,
    ConsumibleOut,
    ConsumibleUpdate,
)

router = APIRouter(prefix="/consumibles", tags=["consumibles"])

_VALID_TIPOS = {t.value for t in TipoConsumible}


@router.get("", response_model=Envelope)
async def list_consumibles(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    tipo: str | None = Query(None, description="Filtrar por tipo"),
    estado: str | None = Query(None, description="Filtrar por estado"),
    low_stock: bool = Query(False, description="Solo stock bajo"),
    search: str | None = Query(None, description="Buscar por nombre"),
):
    """Lista consumibles con filtros opcionales."""
    query = select(Consumible).order_by(Consumible.nombre.asc())
    
    if tipo and tipo in _VALID_TIPOS:
        query = query.where(Consumible.tipo == tipo)
    if estado:
        query = query.where(Consumible.estado == estado)
    if low_stock:
        query = query.where(Consumible.stock_actual <= Consumible.stock_minimo)
    if search:
        query = query.where(Consumible.nombre.ilike(f"%{search}%"))
    
    result = await db.execute(query)
    return Envelope(data=[ConsumibleOut.model_validate(c) for c in result.scalars().all()])


@router.post("", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def create_consumible(
    body: ConsumibleCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    if body.tipo and body.tipo not in _VALID_TIPOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"tipo must be one of {sorted(_VALID_TIPOS)}",
        )
    consumible = Consumible(**body.model_dump())
    db.add(consumible)
    await db.commit()
    await db.refresh(consumible)
    return Envelope(
        message="Consumible guardado correctamente",
        data=ConsumibleOut.model_validate(consumible),
    )


@router.get("/stats", response_model=Envelope)
async def consumible_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Estadísticas de consumibles."""
    total = (await db.execute(select(func.count(Consumible.id)))).scalar() or 0
    low_stock = (
        await db.execute(
            select(func.count(Consumible.id)).where(
                Consumible.stock_actual <= Consumible.stock_minimo
            )
        )
    ).scalar() or 0
    by_type = (
        await db.execute(
            select(Consumible.tipo, func.count(Consumible.id))
            .group_by(Consumible.tipo)
        )
    ).all()
    
    return Envelope(
        data={
            "total": total,
            "low_stock": low_stock,
            "by_type": {t: c for t, c in by_type},
        }
    )


@router.get("/{consumible_id}", response_model=Envelope)
async def get_consumible(
    consumible_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    c = (
        await db.execute(select(Consumible).where(Consumible.id == consumible_id))
    ).scalar_one_or_none()
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consumible no encontrado",
        )
    return Envelope(data=ConsumibleOut.model_validate(c))


@router.put("/{consumible_id}", response_model=Envelope)
async def update_consumible(
    consumible_id: uuid.UUID,
    body: ConsumibleUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    c = (
        await db.execute(select(Consumible).where(Consumible.id == consumible_id))
    ).scalar_one_or_none()
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consumible no encontrado",
        )

    data = body.model_dump(exclude_unset=True)
    if "tipo" in data and data["tipo"] is not None and data["tipo"] not in _VALID_TIPOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"tipo must be one of {sorted(_VALID_TIPOS)}",
        )
    for k, v in data.items():
        setattr(c, k, v)
    await db.commit()
    await db.refresh(c)
    return Envelope(
        message="Consumible actualizado correctamente",
        data=ConsumibleOut.model_validate(c),
    )


@router.patch(
    "/{consumible_id}/stock", response_model=Envelope, summary="Ajustar stock"
)
async def adjust_stock(
    consumible_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    cantidad: int = Query(..., description="Cantidad a sumar (negativo para restar)"),
    _current_user: Annotated[User, Depends(require_admin)] = None,
):
    """Ajusta el stock de un consumible sumando o restando cantidad."""
    c = (
        await db.execute(select(Consumible).where(Consumible.id == consumible_id))
    ).scalar_one_or_none()
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consumible no encontrado",
        )
    new_stock = c.stock_actual + cantidad
    if new_stock < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stock no puede ser negativo",
        )
    c.stock_actual = new_stock
    await db.commit()
    await db.refresh(c)
    
    # Señal para notificar stock bajo (futuro websocket)
    signal = None
    if c.stock_actual <= c.stock_minimo:
        signal = {"type": "low_stock", "consumible_id": str(c.id), "stock": c.stock_actual}
    
    return Envelope(
        message=f"Stock actualizado a {c.stock_actual}",
        data=ConsumibleOut.model_validate(c),
        signal=signal,
    )


@router.delete("/{consumible_id}", response_model=Envelope)
async def delete_consumible(
    consumible_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    c = (
        await db.execute(select(Consumible).where(Consumible.id == consumible_id))
    ).scalar_one_or_none()
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consumible no encontrado",
        )
    await db.delete(c)
    await db.commit()
    return Envelope(message="Consumible eliminado correctamente")