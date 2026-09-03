"""
Perfil (self-service) — el usuario gestiona su propia cuenta.

Endpoints (all require auth):
  GET   /perfil              mi perfil (+ foto_perfil_url)
  PUT   /perfil              editar name / telefono / cargo
  PUT   /perfil/password     {actual, nueva} → invalida todas las sesiones
                             y devuelve un access_token fresco
  POST   /perfil/imagen      subir/reemplazar foto de perfil (multipart)

Foto: file under `storage/perfil/{user_id}/`; DB stores the RELATIVE path
in `users.foto_perfil`; the public URL is derived at read time from APP_URL.
"""
from __future__ import annotations

from typing import Annotated

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

from auth import (
    create_access_token,
    get_current_active_user,
    hash_password,
    verify_password,
)
from database import get_db
from models import Personal, User
from schemas import (
    Envelope,
    PasswordChange,
    PerfilUpdate,
    Token,
    UserOut,
)
from storage_helpers import build_public_url, delete_rel_path, save_upload

router = APIRouter(prefix="/perfil", tags=["perfil"])


def _serialize_perfil(user: User) -> dict:
    data = UserOut.model_validate(user).model_dump(mode="json")
    data["foto_perfil_url"] = (
        build_public_url(user.foto_perfil) if user.foto_perfil else None
    )
    return data


@router.get("", response_model=Envelope)
async def get_perfil(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    return Envelope(data=_serialize_perfil(current_user))


@router.put("", response_model=Envelope)
async def update_perfil(
    body: PerfilUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(current_user, k, v)
    await db.commit()
    await db.refresh(current_user)
    return Envelope(message="Perfil actualizado", data=_serialize_perfil(current_user))


@router.put("/password", response_model=Token)
async def change_password(
    body: PasswordChange,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    if not verify_password(body.actual, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual es incorrecta.",
        )

    current_user.hashed_password = hash_password(body.nueva)
    # Invalidate every outstanding session, then hand the caller a fresh
    # token so they aren't kicked out of the current device.
    current_user.token_version += 1
    await db.commit()
    await db.refresh(current_user)

    access_token = create_access_token(
        data={"sub": str(current_user.id), "ver": current_user.token_version}
    )
    return Token(access_token=access_token, user=UserOut.model_validate(current_user))


@router.post("/imagen", response_model=Envelope)
async def upload_foto_perfil(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    imagen: UploadFile = File(...),
):
    try:
        rel = await save_upload(imagen, "perfil", str(current_user.id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Replace: remove the previous photo file (if any) — only when no other
    # row still points at it (the path is shared with personals.foto_perfil
    # and possibly comment/chat image copies).
    if current_user.foto_perfil:
        delete_rel_path(current_user.foto_perfil)

    current_user.foto_perfil = rel

    # ─── Write-through: mirror onto the linked Personal (User.id ==
    # Personal.id) so the técnico's photo shows in /tecnicos, tareas,
    # visitas y picking sin cargar la relación User en cada query.
    personal = (
        await db.execute(select(Personal).where(Personal.id == current_user.id))
    ).scalar_one_or_none()
    if personal:
        personal.foto_perfil = rel

    await db.commit()
    await db.refresh(current_user)

    return Envelope(
        message="Foto de perfil actualizada",
        data={
            "foto_perfil": rel,
            "foto_perfil_url": build_public_url(rel),
            "user": _serialize_perfil(current_user),
        },
    )
