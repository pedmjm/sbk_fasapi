"""Cliente CRUD router. Includes the sucursal-count aggregate that
Laravel exposed via `Cliente::$appends = ['total_sucursales']`."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_active_user, require_admin
from database import get_db
from models import Cliente, Sucursal, User
from schemas import ClienteCreate, ClienteNested, ClienteOut, ClienteUpdate, Envelope

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.get("", response_model=Envelope)
async def list_clientes(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    # Avoid N+1: count sucursales in a single subquery rather than per-row.
    count_sq = (
        select(Sucursal.cliente_id, func.count(Sucursal.id).label("total"))
        .group_by(Sucursal.cliente_id)
        .subquery()
    )
    stmt = (
        select(Cliente, func.coalesce(count_sq.c.total, 0))
        .outerjoin(count_sq, count_sq.c.cliente_id == Cliente.id)
        .order_by(Cliente.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    out = []
    for cliente, total in rows:
        d = ClienteOut.model_validate(cliente).model_dump()
        d["total_sucursales"] = int(total)
        out.append(d)
    return Envelope(data=out)


@router.post("", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def create_cliente(
    body: ClienteCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    cliente = Cliente(**body.model_dump())
    db.add(cliente)
    await db.commit()
    await db.refresh(cliente)
    return Envelope(message="Cliente creado exitosamente", data=ClienteOut.model_validate(cliente))


@router.get("/{cliente_id}", response_model=Envelope)
async def get_cliente(
    cliente_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    cliente = (
        await db.execute(
            select(Cliente).where(Cliente.id == cliente_id)
        )
    ).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    # Eager-load sucursales + contactos for the detail view.
    await db.refresh(cliente, attribute_names=["sucursales"])
    for suc in cliente.sucursales:
        await db.refresh(suc, attribute_names=["contactos"])
    return Envelope(data=ClienteNested.model_validate(cliente).model_dump(mode="json"))


@router.put("/{cliente_id}", response_model=Envelope)
async def update_cliente(
    cliente_id: uuid.UUID,
    body: ClienteUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    cliente = (
        await db.execute(select(Cliente).where(Cliente.id == cliente_id))
    ).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(cliente, k, v)
    await db.commit()
    await db.refresh(cliente)
    return Envelope(message="Cliente actualizado exitosamente", data=ClienteOut.model_validate(cliente))


@router.delete("/{cliente_id}", response_model=Envelope)
async def delete_cliente(
    cliente_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    cliente = (
        await db.execute(select(Cliente).where(Cliente.id == cliente_id))
    ).scalar_one_or_none()
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    await db.delete(cliente)
    await db.commit()
    return Envelope(message="Cliente eliminado correctamente")
