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
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import secrets
import logging

from auth import (
    create_access_token,
    get_current_active_user,
    hash_password,
    verify_password,
)
from database import get_db
from models import Personal, User
from schemas import LoginRequest, Token, UserCreate, UserOut, Envelope, PasswordRecoveryRequest
# from notifications import send_email_via_onesignal
from email_smtp import send_email_smtp

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("sbk.pass_reset")

def _generate_password(length: int = 8) -> str:
    """Contraseña corta y legible: sin caracteres ambiguos (0/O, 1/l/I)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _build_recovery_email_html(name: str, password: str) -> str:
    return f"""
    <body style="font-family:'Helvetica Neue',Arial,sans-serif;font-size:16px;
                 color:#424d57;line-height:1.7;max-width:560px;margin:0 auto;padding:24px">
      <h2 style="color:#1a1a2e;margin:0 0 16px">Recuperación de contraseña</h2>
      <p>Hola <strong>{name}</strong>,</p>
      <p>Recibimos una solicitud para restablecer tu contraseña en <strong>SBK</strong>.</p>
      <p>Tu nueva contraseña temporal es:</p>
      <div style="background:#f4f6fa;border:1px solid #d8dee9;border-radius:8px;
                  padding:16px;text-align:center;margin:20px 0;
                  font-size:24px;letter-spacing:4px;
                  font-family:'Courier New',monospace;color:#1a1a2e;font-weight:bold; 
                  user-select: all; -webkit-user-select: all;">
          {password}
      </div>
      <p>Por seguridad, te recomendamos cambiar esta contraseña después de iniciar sesión.</p>
      <p style="color:#7a8699;font-size:13px;border-top:1px solid #e1e5eb;
                padding-top:16px;margin-top:24px">
        Si no solicitaste este cambio, contacta inmediatamente al administrador del sistema.
      </p>
    </body>
    """


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

    # 3. ✅ Sincronizar la tabla Personal con los datos del formulario
    personal.nombre = user_data.name
    personal.correo = user_data.email
    personal.telefono = user_data.telefono or personal.telefono
    personal.cargo = user_data.cargo or personal.cargo
    if user_data.nivel is not None:
        personal.tipo_usuario = user_data.nivel

    # 4. Create the user usando el mismo ID de personal
    user = User(
        id=personal.id,
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

    access_token = create_access_token(
        data={"sub": str(user.id), "ver": user.token_version}
    )
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

    access_token = create_access_token(
        data={"sub": str(user.id), "ver": user.token_version}
    )
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

    access_token = create_access_token(
        data={"sub": str(user.id), "ver": user.token_version}
    )
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


@router.post("/recover-password", response_model=Envelope)
async def recover_password(
    body: PasswordRecoveryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Envía una nueva contraseña temporal por correo.

    Reglas de seguridad:
      * Se verifica **email + cédula** (los dígitos, sin prefijo).
      * La respuesta es SIEMPRE la misma (no filtra si el usuario existe).
      * El correo se envía ANTES de persistir: si falla, no se cambia el hash.
      * Al persistir, se incrementa `token_version` → todas las sesiones
        activas del usuario quedan invalidadas.
    """
    generic_msg = (
        "Si los datos coinciden con un usuario registrado, "
        "recibirás tu nueva contraseña en el correo indicado."
    )

    # ── 1. Buscar usuario por email (case-insensitive) ─────────────
    email = body.email.strip().lower()
    user = (
        await db.execute(
            select(User).where(func.lower(User.email) == email)
        )
    ).scalar_one_or_none()

    # ── 2. Verificar cédula (solo dígitos, acepta V- / E- / etc.) ──
    if user:
        db_cedula = "".join(ch for ch in (user.cedula or "") if ch.isdigit())
        in_cedula = "".join(ch for ch in body.cedula.strip() if ch.isdigit())
        if not db_cedula or not in_cedula or db_cedula != in_cedula:
            user = None

    if not user or user.disabled:
        return Envelope(message=generic_msg)

    # ── 3. Generar contraseña temporal ─────────────────────────────
    new_password = _generate_password(8)

    # ── 4. Enviar email PRIMERO (con la contraseña en memoria) ─────
    try:
        await send_email_smtp(
            user.email,
            subject="Recuperación de contraseña - SBK",
            html_body=_build_recovery_email_html(user.name, new_password),
        )
    except Exception as exc:
        logger.error("Error enviando email de recuperación a %s: %s", user.email, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo enviar el correo. Intenta más tarde.",
        )

    # ── 5. Persistir (hash + invalidar tokens) ─────────────────────
    user.hashed_password = hash_password(new_password)
    user.token_version += 1
    await db.commit()

    return Envelope(message=generic_msg)