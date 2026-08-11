"""Sucursal CRUD router. Belongs to a Cliente."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_active_user, require_admin
from database import get_db
from models import Cliente, Sucursal, User
from schemas import Envelope, SucursalCreate, SucursalOut, SucursalUpdate

router = APIRouter(prefix="/sucursales", tags=["sucursales"])


@router.post("", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def create_sucursal(
    body: SucursalCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    cliente = (
        await db.execute(select(Cliente).where(Cliente.id == body.cliente_id))
    ).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")

    sucursal = Sucursal(**body.model_dump())
    db.add(sucursal)
    await db.commit()
    await db.refresh(sucursal)
    return Envelope(message="Sucursal agregada exitosamente", data=SucursalOut.model_validate(sucursal))


@router.put("/{sucursal_id}", response_model=Envelope)
async def update_sucursal(
    sucursal_id: uuid.UUID,
    body: SucursalUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    sucursal = (
        await db.execute(select(Sucursal).where(Sucursal.id == sucursal_id))
    ).scalar_one_or_none()
    if not sucursal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sucursal no encontrada")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(sucursal, k, v)
    await db.commit()
    await db.refresh(sucursal)
    return Envelope(message="Sucursal actualizada exitosamente", data=SucursalOut.model_validate(sucursal))


@router.delete("/{sucursal_id}", response_model=Envelope)
async def delete_sucursal(
    sucursal_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    sucursal = (
        await db.execute(select(Sucursal).where(Sucursal.id == sucursal_id))
    ).scalar_one_or_none()
    if not sucursal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sucursal no encontrada")
    await db.delete(sucursal)
    await db.commit()
    return Envelope(message="Sucursal eliminada correctamente")
