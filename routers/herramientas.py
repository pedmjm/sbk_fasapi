"""
Herramientas (tools / inventory) CRUD router. Mirrors Laravel's
`HerramientaController`. Bug fix vs. Laravel: the controller's enum
validation only allowed 4 of the 8 enum values that the DB accepted
(so seeding a herramienta of tipo "Medición" worked but updating it
would 422). Here we accept all 8 enum values consistently.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_active_user, require_admin
from database import get_db
from models import Herramienta, TipoHerramienta, User
from schemas import Envelope, HerramientaCreate, HerramientaOut, HerramientaUpdate

router = APIRouter(prefix="/herramientas", tags=["herramientas"])

_VALID_TIPOS = {t.value for t in TipoHerramienta}


@router.get("", response_model=Envelope)
async def list_herramientas(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    result = await db.execute(select(Herramienta).order_by(Herramienta.nombre.asc()))
    # print([HerramientaOut.model_validate(h) for h in result.scalars().all()])
    return Envelope(data=[HerramientaOut.model_validate(h) for h in result.scalars().all()])


@router.post("", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def create_herramienta(
    body: HerramientaCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    if body.tipo and body.tipo not in _VALID_TIPOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"tipo must be one of {sorted(_VALID_TIPOS)}",
        )
    herramienta = Herramienta(**body.model_dump())
    db.add(herramienta)
    await db.commit()
    await db.refresh(herramienta)
    return Envelope(message="Herramienta guardada correctamente", data=HerramientaOut.model_validate(herramienta))


@router.get("/{herramienta_id}", response_model=Envelope)
async def get_herramienta(
    herramienta_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    h = (
        await db.execute(select(Herramienta).where(Herramienta.id == herramienta_id))
    ).scalar_one_or_none()
    if not h:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Herramienta no encontrada")
    return Envelope(data=HerramientaOut.model_validate(h))


@router.put("/{herramienta_id}", response_model=Envelope)
async def update_herramienta(
    herramienta_id: uuid.UUID,
    body: HerramientaUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    h = (
        await db.execute(select(Herramienta).where(Herramienta.id == herramienta_id))
    ).scalar_one_or_none()
    if not h:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Herramienta no encontrada")

    data = body.model_dump(exclude_unset=True)
    if "tipo" in data and data["tipo"] is not None and data["tipo"] not in _VALID_TIPOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"tipo must be one of {sorted(_VALID_TIPOS)}",
        )
    for k, v in data.items():
        setattr(h, k, v)
    await db.commit()
    await db.refresh(h)
    return Envelope(message="Herramienta actualizada correctamente", data=HerramientaOut.model_validate(h))


@router.delete("/{herramienta_id}", response_model=Envelope)
async def delete_herramienta(
    herramienta_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    h = (
        await db.execute(select(Herramienta).where(Herramienta.id == herramienta_id))
    ).scalar_one_or_none()
    if not h:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Herramienta no encontrada")
    await db.delete(h)
    await db.commit()
    return Envelope(message="Herramienta eliminada correctamente")
