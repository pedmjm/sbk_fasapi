"""
Auth router — register / login / logout / me.

Mirrors the Laravel `AuthController` behaviour:

  * `POST /auth/register` — only succeeds if the supplied `cedula` already
    exists in the `personals` whitelist (the same pre-registration gate
    Laravel used).
  * `POST /auth/login` — email + password, returns a JWT.
  * `POST /auth/logout` — stateless JWT, so the client just discards the
    token. We expose the endpoint for API symmetry and return a 200.
  * `GET /auth/me` — returns the current user.

Bug fix vs. Laravel: the Laravel AuthController called `Hash::make()` on
the password AND the User model cast `password` as `hashed`, which
double-hashed and broke login. Here we hash exactly once, in `hash_password()`.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
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
from schemas import LoginRequest, Token, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # 1. Whitelist check: cédula must exist in `personals`.
    personal = (
        await db.execute(
            select(Personal).where(Personal.cedula == user_data.cedula)
        )
    ).scalar_one_or_none()
    if not personal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cédula ingresada no pertenece al personal autorizado.",
        )

    # 2. Uniqueness check on email + cédula against `users`.
    existing = (
        await db.execute(
            select(User).where(
                (User.email == user_data.email) | (User.cedula == user_data.cedula)
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email or cédula already registered.",
        )

    # 3. Create the user — hash exactly once (no double-hash bug).
    user = User(
        name=user_data.name,
        email=user_data.email,
        cedula=user_data.cedula,
        nivel=user_data.nivel if user_data.nivel is not None else (personal.tipo_usuario or 0),
        cargo=user_data.cargo or personal.cargo or "Técnico",
        telefono=user_data.telefono or personal.telefono,
        hashed_password=hash_password(user_data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(
        access_token=access_token,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """OAuth2 password flow — accepts `username` (treated as email) +
    `password` as form-data, returns a JWT.

    Also accepts a JSON body via the alternate `/auth/login/json` endpoint
    below for clients that prefer JSON.
    """
    user = (
        await db.execute(select(User).where(User.email == form_data.username))
    ).scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid login credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.disabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(
        access_token=access_token,
        user=UserOut.model_validate(user),
    )


@router.post("/login/json", response_model=Token)
async def login_json(
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """JSON-body alternative to `/auth/login` for clients that don't
    want to send form-data.
    """
    user = (
        await db.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid login credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.disabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(
        access_token=access_token,
        user=UserOut.model_validate(user),
    )


@router.post("/logout")
async def logout(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """JWT is stateless — the client just discards the token.
    This endpoint exists for API symmetry with the Laravel app.
    """
    return {"status": "success", "message": "Successfully logged out"}


@router.get("/me", response_model=UserOut)
async def me(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    return current_user
