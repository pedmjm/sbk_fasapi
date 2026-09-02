"""
Gestión de usuarios (admin) — promover niveles y activar/desactivar.

All endpoints require nivel >= 2 (admin). Extra rules:
  * Only a super admin (nivel 5) can modify another super or assign nivel 5.
  * You can't assign a nivel higher than your own.
  * You can't change your own nivel or deactivate yourself (lockout guard).

Deactivating a user:
  * `disabled = True` → login rejected (400 "Inactive user") and every
    authenticated request rejected.
  * `token_version` is bumped → ALL of the user's outstanding JWTs die
    instantly (the `ver` claim no longer matches).

Endpoints:
  GET    /usuarios                    list all users
  PATCH  /usuarios/{user_id}/nivel    body {"nivel": 0|1|2|5}
  PATCH  /usuarios/{user_id}/estado   body {"activo": true|false}
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_nivel
from database import get_db
from models import User
from schemas import Envelope, UsuarioAdminOut, UsuarioEstadoBody, UsuarioNivelBody

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

_VALID_NIVELES = {0, 1, 2, 5}


def _serialize_user(user: User) -> dict:
    data = UsuarioAdminOut.model_validate(user).model_dump(mode="json")
    return data


@router.get("", response_model=Envelope)
async def list_usuarios(
    db: Annotated[AsyncSession, Depends(get_db)],
    _admin: Annotated[User, Depends(require_nivel(2))],
):
    users = (
        await db.execute(select(User).order_by(User.created_at.desc()))
    ).scalars().all()
    return Envelope(data=[_serialize_user(u) for u in users])


@router.patch("/{user_id}/nivel", response_model=Envelope)
async def cambiar_nivel(
    user_id: uuid.UUID,
    body: UsuarioNivelBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(require_nivel(2))],
):
    if body.nivel not in _VALID_NIVELES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"nivel must be one of {sorted(_VALID_NIVELES)} (0 técnico, 1 moderador, 2 admin, 5 super)",
        )

    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes cambiar tu propio nivel.",
        )

    target = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    # Only a super touches a super, and only a super assigns nivel 5.
    if (target.nivel == 5 or body.nivel == 5) and admin.nivel < 5:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un super admin (nivel 5) puede gestionar nivel 5.",
        )
    # Can't grant a level higher than your own.
    if body.nivel > admin.nivel:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No puedes asignar un nivel mayor al tuyo ({admin.nivel}).",
        )

    target.nivel = body.nivel
    await db.commit()
    await db.refresh(target)
    return Envelope(
        message=f"Nivel actualizado a {body.nivel}",
        data=_serialize_user(target),
    )


@router.patch("/{user_id}/estado", response_model=Envelope)
async def cambiar_estado(
    user_id: uuid.UUID,
    body: UsuarioEstadoBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(require_nivel(2))],
):
    if user_id == admin.id and not body.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes desactivar tu propia cuenta.",
        )

    target = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    if target.nivel == 5 and admin.nivel < 5:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un super admin (nivel 5) puede desactivar a otro super admin.",
        )

    target.disabled = not body.activo
    # Invalidate ALL outstanding tokens: deactivation kicks every active
    # session; reactivation also starts a clean token epoch.
    target.token_version += 1

    await db.commit()
    await db.refresh(target)

    if body.activo:
        message = "Usuario activado (sesiones anteriores invalidadas)"
    else:
        message = "Usuario desactivado: no puede iniciar sesión y todas sus sesiones fueron cerradas"

    return Envelope(message=message, data=_serialize_user(target))
