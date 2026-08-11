"""
Personal (técnicos) CRUD router. Mirrors Laravel's `PersonalController`,
mapped to `/api/tecnicos` in the original. RBAC: list is open to any
authenticated user; create/update/delete require nivel >= 2 (admin).
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_active_user, require_admin
from database import get_db
from models import Personal, User
from schemas import Envelope, PersonalCreate, PersonalOut, PersonalUpdate

router = APIRouter(prefix="/tecnicos", tags=["personal"])


@router.get("", response_model=Envelope)
async def list_tecnicos(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    activo: bool | None = Query(None, description="Filter by `activo` flag"),
):
    stmt = select(Personal).order_by(Personal.nombre.asc())
    if activo is not None:
        stmt = stmt.where(Personal.activo == activo)
    result = await db.execute(stmt)
    return Envelope(data=[PersonalOut.model_validate(p) for p in result.scalars().all()])


@router.post("", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def create_tecnico(
    body: PersonalCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    # Uniqueness check (cedula + correo) — gives a friendlier error than
    # the DB IntegrityError.
    existing = (
        await db.execute(
            select(Personal).where(
                (Personal.cedula == body.cedula)
                | (Personal.correo == body.correo if body.correo else False)
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cédula or correo already exists.",
        )

    personal = Personal(**body.model_dump())
    db.add(personal)
    await db.commit()
    await db.refresh(personal)
    return Envelope(message="Técnico registrado correctamente", data=PersonalOut.model_validate(personal))


@router.get("/{tecnico_id}", response_model=Envelope)
async def get_tecnico(
    tecnico_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    personal = (
        await db.execute(select(Personal).where(Personal.id == tecnico_id))
    ).scalar_one_or_none()
    if not personal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Técnico no encontrado")
    return Envelope(data=PersonalOut.model_validate(personal))


@router.put("/{tecnico_id}", response_model=Envelope)
async def update_tecnico(
    tecnico_id: uuid.UUID,
    body: PersonalUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    personal = (
        await db.execute(select(Personal).where(Personal.id == tecnico_id))
    ).scalar_one_or_none()
    if not personal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Técnico no encontrado")

    data = body.model_dump(exclude_unset=True)
    # Re-check uniqueness on changed fields.
    if "cedula" in data and data["cedula"] != personal.cedula:
        clash = (
            await db.execute(select(Personal).where(Personal.cedula == data["cedula"]))
        ).scalar_one_or_none()
        if clash:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cédula already in use.")
    if "correo" in data and data["correo"]:
        clash = (
            await db.execute(select(Personal).where(Personal.correo == data["correo"]))
        ).scalar_one_or_none()
        if clash and clash.id != personal.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Correo already in use.")

    for k, v in data.items():
        setattr(personal, k, v)
    await db.commit()
    await db.refresh(personal)
    return Envelope(message="Técnico actualizado correctamente", data=PersonalOut.model_validate(personal))


@router.delete("/{tecnico_id}", response_model=Envelope)
async def delete_tecnico(
    tecnico_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
):
    personal = (
        await db.execute(select(Personal).where(Personal.id == tecnico_id))
    ).scalar_one_or_none()
    if not personal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Técnico no encontrado")
    await db.delete(personal)
    await db.commit()
    return Envelope(message="Técnico eliminado correctamente")
