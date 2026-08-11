"""
SQLAlchemy 2.0 models for the SBK TaskManager.

Ported from the Laravel app's Eloquent models. Schema-level bugs from the
original repo are fixed here:

  * `tareas` and `pasos_tarea` are defined exactly once (the Laravel repo
    had two `Schema::create` migrations for each).
  * `imagenes.imageable_id` is a String(36) so it can hold UUIDs from both
    `Tarea` and `Comentario` (Laravel used `numericMorphs` which truncated
    UUIDs).
  * `comentarios.autor_id` is a UUID FK → `users.id` (Laravel created it as
    UUID then re-pointed the FK at `users.id` BIGINT — type mismatch).
  * `tareas.creador_id` is consistently a UUID FK → `users.id`.

All UUID PKs are stored as native UUID (SQLAlchemy `Uuid(as_uuid=True)`),
which on SQLite is stored as CHAR(36) and on Postgres as native uuid.

Conventions:
  * `Mapped[...]` / `mapped_column(...)` (the modern SQLAlchemy 2.0 style
    used in the uploaded `models.py` template).
  * `relationship(..., back_populates=...)` is bidirectional where useful.
  * Polymorphic images are NOT modelled as a SQLAlchemy polymorphic
    inheritance — instead `Imagen.imageable_type` holds the class name
    ("Tarea" / "Comentario") and `Imagen.imageable_id` holds the str(UUID).
    This mirrors Laravel's `morphMany` and avoids cross-type FK headaches.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Column,
    Text,
    func,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from database import Base


# ─── Enums ───────────────────────────────────────────────────────────────────

class Prioridad(str, enum.Enum):
    BAJA = "Baja"
    MEDIA = "Media"
    ALTA = "Alta"
    URGENTE = "Urgente"


class TipoHerramienta(str, enum.Enum):
    INALAMBRICO = "Inalámbrico"
    GENERADOR = "Generador"
    ALMACENAMIENTO = "Almacenamiento"
    MEDICION = "Medición"
    SEGURIDAD = "Seguridad"
    ELECTRICO = "Eléctrico"
    LOGISTICO = "Logístico"
    MANUAL = "Manual"


# ─── Association tables (M:N) ────────────────────────────────────────────────

tarea_personal = Table(
    "tarea_personal",
    Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "tarea_id",
        Uuid(as_uuid=True),
        ForeignKey("tareas.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "personal_id",
        Uuid(as_uuid=True),
        ForeignKey("personals.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

tarea_herramienta = Table(
    "tarea_herramienta",
    Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "tarea_id",
        Uuid(as_uuid=True),
        ForeignKey("tareas.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "herramienta_id",
        Uuid(as_uuid=True),
        ForeignKey("herramientas.id", ondelete="CASCADE"),
        nullable=False,
    ),
)


# ─── Auth user ──────────────────────────────────────────────────────────────

class User(Base):
    """Auth user. Equivalent to Laravel's `User` model + Sanctum tokens.

    `cedula` is the bridge to `Personal` — when a user registers, their
    cédula must already exist in the `personals` whitelist (mirrors the
    Laravel AuthController behaviour).
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    cedula: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    nivel: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cargo: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    telefono: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    foto_perfil: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    tareas_creadas: Mapped[list["Tarea"]] = relationship(
        back_populates="creador",
        foreign_keys="Tarea.creador_id",
        cascade="all, delete-orphan",
    )
    comentarios: Mapped[list["Comentario"]] = relationship(
        back_populates="autor",
        cascade="all, delete-orphan",
    )


# ─── Personal (técnico whitelist) ───────────────────────────────────────────

class Personal(Base):
    """A technician. Equivalent to Laravel's `Personal` model.

    This is the pre-registration whitelist: a User can only register if
    their `cedula` matches a row here. Personal can also exist without
    a linked User (e.g. an inactive technician).
    """
    __tablename__ = "personals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    cedula: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    correo: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telefono: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cargo: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # 0 = Técnico, 1 = Moderador, 2 = Admin, 5 = Super Admin
    tipo_usuario: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # M:N with Tarea
    tareas: Mapped[list["Tarea"]] = relationship(
        secondary=tarea_personal, back_populates="personal"
    )


# ─── Cliente → Sucursal → Contacto hierarchy ────────────────────────────────

class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    rif: Mapped[str] = mapped_column(String(15), unique=True, nullable=False, index=True)
    razon_social: Mapped[str] = mapped_column(String(150), nullable=False)
    nombre_comercial: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sucursales: Mapped[list["Sucursal"]] = relationship(
        back_populates="cliente",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Sucursal(Base):
    __tablename__ = "sucursals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cliente_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clientes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nombre_sucursal: Mapped[str] = mapped_column(String(100), nullable=False)
    codigo_interno: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    direccion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    estado: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ciudad: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    cliente: Mapped[Cliente] = relationship(back_populates="sucursales")
    contactos: Mapped[list["Contacto"]] = relationship(
        back_populates="sucursal",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Contacto(Base):
    __tablename__ = "contactos"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sucursal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sucursals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nombre_completo: Mapped[str] = mapped_column(String(150), nullable=False)
    cargo: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    telefono: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sucursal: Mapped[Sucursal] = relationship(back_populates="contactos")


# ─── Herramienta ────────────────────────────────────────────────────────────

class Herramienta(Base):
    __tablename__ = "herramientas"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    marca: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    serial: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tipo: Mapped[TipoHerramienta] = mapped_column(
        Enum(TipoHerramienta, name="tipo_herramienta"),
        default=TipoHerramienta.MANUAL,
        nullable=False,
    )
    combustible: Mapped[str] = mapped_column(String(100), default="N/A", nullable=False)
    estado: Mapped[str] = mapped_column(String(50), default="Disponible", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tareas: Mapped[list["Tarea"]] = relationship(
        secondary=tarea_herramienta, back_populates="herramientas"
    )


# ─── Tarea + Pasos + Comentarios + Imagenes ─────────────────────────────────

class Tarea(Base):
    __tablename__ = "tareas"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cliente_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clientes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sucursal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sucursals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    titulo: Mapped[str] = mapped_column(String(255), nullable=False)
    descripcion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prioridad: Mapped[Prioridad] = mapped_column(
        Enum(Prioridad, name="prioridad"),
        default=Prioridad.MEDIA,
        nullable=False,
    )
    fecha_programada: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    fecha_limite: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    creador_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    cliente: Mapped[Cliente] = relationship()
    sucursal: Mapped[Sucursal] = relationship()
    creador: Mapped[User] = relationship(
        back_populates="tareas_creadas", foreign_keys=[creador_id]
    )
    personal: Mapped[list[Personal]] = relationship(
        secondary=tarea_personal, back_populates="tareas"
    )
    herramientas: Mapped[list[Herramienta]] = relationship(
        secondary=tarea_herramienta, back_populates="tareas"
    )
    pasos: Mapped[list["PasosTarea"]] = relationship(
        back_populates="tarea",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PasosTarea.created_at",
    )
    comentarios: Mapped[list["Comentario"]] = relationship(
        back_populates="tarea",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Comentario.created_at.desc()",
    )


class PasosTarea(Base):
    """A single checklist step inside a Tarea."""
    __tablename__ = "pasos_tarea"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tarea_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tareas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actividad: Mapped[str] = mapped_column(Text, nullable=False)
    metodo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requerimiento: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tarea: Mapped[Tarea] = relationship(back_populates="pasos")


class Comentario(Base):
    """A comment on a Tarea. May contain text, image(s), or both."""
    __tablename__ = "comentarios"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tarea_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tareas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    autor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    texto: Mapped[str] = mapped_column(Text, default="", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tarea: Mapped[Tarea] = relationship(back_populates="comentarios")
    autor: Mapped[User] = relationship(back_populates="comentarios")
    # NOTE: Imagen rows for this Comentario are loaded explicitly in
    # `routers/comentarios.py` via a `select(Imagen).where(
    # Imagen.imageable_type=='Comentario', Imagen.imageable_id==str(c.id))`
    # and stashed on the instance as `comentario.imagenes_proxy`.
    # We do NOT define a polymorphic SQLAlchemy relationship here because
    # `Comentario.id` is a UUID and `Imagen.imageable_id` is a String(36),
    # which makes the join condition awkward and adds no real value
    # (the relation would be viewonly anyway).


class Imagen(Base):
    """Polymorphic image. Belongs to a Tarea or a Comentario.

    `imageable_id` is a String(36) so it can hold UUIDs from either parent
    table — the bug in the Laravel repo (`numericMorphs`) is fixed here.
    """
    __tablename__ = "imagenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    imageable_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    imageable_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Convenience helper for the response schema.
    @property
    def parent_kind(self) -> str:
        return self.imageable_type
