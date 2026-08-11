"""Contacto CRUD router. Belongs to a Sucursal."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_active_user, require_admin
from database import get_db
from models import Contacto, Sucursal, User
from schemas import ContactoCreate, ContactoOut, ContactoUpdate, Envelope

router = APIRouter(prefix="/contactos", tags=["contactos"])


@router.post("", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def create_contacto(
    body: ContactoCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    sucursal = (
        await db.execute(select(Sucursal).where(Sucursal.id == body.sucursal_id))
    ).scalar_one_or_none()
    if not sucursal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sucursal no encontrada")

    contacto = Contacto(**body.model_dump())
    db.add(contacto)
    await db.commit()
    await db.refresh(contacto)
    return Envelope(message="Contacto creado exitosamente", data=ContactoOut.model_validate(contacto))


@router.put("/{contacto_id}", response_model=Envelope)
async def update_contacto(
    contacto_id: uuid.UUID,
    body: ContactoUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    contacto = (
        await db.execute(select(Contacto).where(Contacto.id == contacto_id))
    ).scalar_one_or_none()
    if not contacto:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contacto no encontrado")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(contacto, k, v)
    await db.commit()
    await db.refresh(contacto)
    return Envelope(message="Contacto actualizado exitosamente", data=ContactoOut.model_validate(contacto))


@router.delete("/{contacto_id}", response_model=Envelope)
async def delete_contacto(
    contacto_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    contacto = (
        await db.execute(select(Contacto).where(Contacto.id == contacto_id))
    ).scalar_one_or_none()
    if not contacto:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contacto no encontrado")
    await db.delete(contacto)
    await db.commit()
    return Envelope(message="Contacto eliminado correctamente")
