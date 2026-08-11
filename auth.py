"""
JWT + bcrypt auth, plus role-based access control dependencies.

Mirrors the uploaded `auth.py` template (bcrypt hashing, JWT encode/decode,
`OAuth2PasswordBearer`, `get_current_user`, `get_current_active_user`)
and adds:

  * `require_nivel(min_level)` — RBAC dependency factory that checks
    `current_user.nivel` against a minimum level. Closes the authorization
    gap flagged in the Laravel review (the Laravel app had `nivel` on User
    but no checks anywhere).
  * Configurable SECRET_KEY / ALGORITHM / ACCESS_TOKEN_EXPIRE_MINUTES
    via environment variables.

Role levels (matching the Laravel `tipo_usuario` convention):
    0 = Técnico
    1 = Moderador
    2 = Admin
    5 = Super Admin
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User

SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# Token-URL matches the OAuth2PasswordRequestForm endpoint defined in
# routers/auth.py — kept consistent with the uploaded template.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ─── Password hashing ──────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(pwd_bytes, hashed_bytes)


# ─── JWT ────────────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    # `sub` MUST be a string per the JWT spec.
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ─── Dependencies ───────────────────────────────────────────────────────────

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub: Optional[str] = payload.get("sub")
        if sub is None:
            raise credentials_exception
        user_id = uuid.UUID(sub)  # noqa: F821 — uuid imported below
    except (InvalidTokenError, ValueError) as exc:
        raise credentials_exception from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


# uuid is imported inside get_current_user to keep the top-level imports
# visually consistent with the template. Re-import here at module level
# for type-checkers / IDE support.
import uuid  # isort:skip  # noqa: E402


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if getattr(current_user, "disabled", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )
    return current_user


# ─── RBAC ───────────────────────────────────────────────────────────────────

def require_nivel(min_level: int):
    """Dependency factory: require `current_user.nivel >= min_level`.

    Usage:
        @router.post("/tecnicos", dependencies=[Depends(require_nivel(2))])
        def create_tecnico(...): ...

    Or as a function-level dependency:
        current_user: User = Depends(require_nivel(2))
    """
    async def _checker(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if current_user.nivel < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires nivel >= {min_level}",
            )
        return current_user
    return _checker


# Convenience aliases for the common role levels.
require_tecnico = require_nivel(0)   # any authenticated user
require_moderador = require_nivel(1)
require_admin = require_nivel(2)
require_super = require_nivel(5)
