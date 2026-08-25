"""
Pydantic v2 schemas for request/response validation.

Conventions:
  * `*Create`  — payload accepted by POST endpoints
  * `*Update`  — payload accepted by PUT/PATCH endpoints (all fields optional)
  * `*Out`     — response shape (with `model_config = ConfigDict(from_attributes=True)`
                 so we can build them directly from SQLAlchemy ORM instances)
  * `*Nested`  — a `*Out` variant that includes child relations (used by `show` endpoints)

The envelope shape is consistent across the API:
    {"status": "success", "message": "...", "data": ...}
except for auth endpoints which return the auth template's `Token` shape
(access_token / token_type / user) to match the uploaded `schemas.py`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ─── Auth ───────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    cedula: str = Field(..., min_length=1, max_length=20)
    password: str = Field(..., min_length=6)
    telefono: Optional[str] = None
    cargo: Optional[str] = None
    nivel: Optional[int] = None


class UserOut(BaseModel):
    id: uuid.UUID
    name: str
    email: EmailStr
    cedula: str
    nivel: int
    cargo: Optional[str] = None
    telefono: Optional[str] = None
    foto_perfil: Optional[str] = None
    disabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ─── Personal ───────────────────────────────────────────────────────────────

class PersonalCreate(BaseModel):
    nombre: str = Field(..., max_length=255)
    cedula: str = Field(..., max_length=20)
    correo: Optional[EmailStr] = None
    telefono: Optional[str] = Field(None, max_length=50)
    cargo: Optional[str] = Field(None, max_length=100)
    tipo_usuario: int = Field(0, ge=0, le=5)
    activo: bool = True


class PersonalUpdate(BaseModel):
    nombre: Optional[str] = Field(None, max_length=255)
    cedula: Optional[str] = Field(None, max_length=20)
    correo: Optional[EmailStr] = None
    telefono: Optional[str] = Field(None, max_length=50)
    cargo: Optional[str] = Field(None, max_length=100)
    tipo_usuario: Optional[int] = Field(None, ge=0, le=5)
    activo: Optional[bool] = None


class PersonalOut(BaseModel):
    id: uuid.UUID
    nombre: str
    cedula: str
    correo: Optional[str] = None
    telefono: Optional[str] = None
    cargo: Optional[str] = None
    tipo_usuario: int
    activo: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── Cliente ────────────────────────────────────────────────────────────────

class ClienteCreate(BaseModel):
    rif: str = Field(..., max_length=15)
    razon_social: str = Field(..., max_length=150)
    nombre_comercial: Optional[str] = Field(None, max_length=100)
    is_active: bool = True


class ClienteUpdate(BaseModel):
    rif: Optional[str] = Field(None, max_length=15)
    razon_social: Optional[str] = Field(None, max_length=150)
    nombre_comercial: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None


class ClienteOut(BaseModel):
    id: uuid.UUID
    rif: str
    razon_social: str
    nombre_comercial: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClienteNested(ClienteOut):
    """Cliente with sucursales (and their contactos) loaded."""
    sucursales: list["SucursalNested"] = Field(default_factory=list)


# ─── Sucursal ───────────────────────────────────────────────────────────────

class SucursalCreate(BaseModel):
    cliente_id: uuid.UUID
    nombre_sucursal: str = Field(..., max_length=100)
    codigo_interno: Optional[str] = Field(None, max_length=50)
    direccion: Optional[str] = None
    estado: Optional[str] = Field(None, max_length=50)
    ciudad: Optional[str] = Field(None, max_length=50)


class SucursalUpdate(BaseModel):
    nombre_sucursal: Optional[str] = Field(None, max_length=100)
    codigo_interno: Optional[str] = Field(None, max_length=50)
    direccion: Optional[str] = None
    estado: Optional[str] = Field(None, max_length=50)
    ciudad: Optional[str] = Field(None, max_length=50)


class SucursalOut(BaseModel):
    id: uuid.UUID
    cliente_id: uuid.UUID
    nombre_sucursal: str
    codigo_interno: Optional[str] = None
    direccion: Optional[str] = None
    estado: Optional[str] = None
    ciudad: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SucursalNested(SucursalOut):
    contactos: list[ContactoOut] = Field(default_factory=list)
    
# ─── Contacto ───────────────────────────────────────────────────────────────

class ContactoCreate(BaseModel):
    sucursal_id: uuid.UUID
    nombre_completo: str = Field(..., max_length=150)
    cargo: Optional[str] = Field(None, max_length=100)
    telefono: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None
    is_primary: bool = False


class ContactoUpdate(BaseModel):
    nombre_completo: Optional[str] = Field(None, max_length=150)
    cargo: Optional[str] = Field(None, max_length=100)
    telefono: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = None
    is_primary: Optional[bool] = None


class ContactoOut(BaseModel):
    id: uuid.UUID
    sucursal_id: uuid.UUID
    nombre_completo: str
    cargo: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    is_primary: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── Herramienta ────────────────────────────────────────────────────────────

class HerramientaCreate(BaseModel):
    nombre: str = Field(..., max_length=255)
    marca: Optional[str] = Field(None, max_length=255)
    serial: Optional[str] = None
    tipo: Optional[str] = None  # validated against enum in router
    combustible: Optional[str] = Field("N/A", max_length=100)
    estado: Optional[str] = Field("Disponible", max_length=50)


class HerramientaUpdate(BaseModel):
    nombre: Optional[str] = Field(None, max_length=255)
    marca: Optional[str] = Field(None, max_length=255)
    serial: Optional[str] = None
    grupo: Optional[str] = None
    tipo: Optional[str] = None
    stock_minimo: Optional[int] = None
    stock_actual: Optional[int] = None
    combustible: Optional[str] = Field(None, max_length=100)
    estado: Optional[str] = Field(None, max_length=50)


class HerramientaOut(BaseModel):
    id: uuid.UUID
    nombre: str
    marca: Optional[str] = None
    grupo: Optional[str] = None
    serial: Optional[str] = None
    stock_minimo: int
    stock_actual: int
    tipo: str
    combustible: str
    estado: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── Pasos ─────────────────────────────────────────────────────────────────

class PasoCreate(BaseModel):
    actividad: str
    metodo: Optional[str] = None
    requerimiento: Optional[str] = None


class PasoUpdate(BaseModel):
    actividad: Optional[str] = None
    metodo: Optional[str] = None
    requerimiento: Optional[str] = None
    completado: Optional[bool] = None


class PasoOut(BaseModel):
    id: uuid.UUID
    tarea_id: uuid.UUID
    actividad: str
    metodo: Optional[str] = None
    requerimiento: Optional[str] = None
    completado: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── Imagen ─────────────────────────────────────────────────────────────────

class ImagenOut(BaseModel):
    id: int
    path: str
    url: Optional[str] = None
    imageable_type: str
    imageable_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── Comentario ────────────────────────────────────────────────────────────

class ComentarioOut(BaseModel):
    id: uuid.UUID
    tarea_id: uuid.UUID
    autor_id: uuid.UUID
    texto: str
    created_at: datetime
    autor: Optional[UserOut] = None
    imagenes: list[ImagenOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


# ─── Tarea ─────────────────────────────────────────────────────────────────

class TareaCreate(BaseModel):
    cliente_id: uuid.UUID
    sucursal_id: uuid.UUID
    titulo: str = Field(..., max_length=255)
    descripcion: Optional[str] = None
    prioridad: Optional[str] = "Media"
    fecha_programada: Optional[date] = None
    fecha_limite: Optional[date] = None
    personal_ids: list[uuid.UUID] = Field(default_factory=list)
    herramienta_ids: list[uuid.UUID] = Field(default_factory=list)
    pasos: list[PasoCreate] = Field(default_factory=list)
    consumible_ids: list[uuid.UUID] = Field(default_factory=list)


class ItemWithCantidad(BaseModel):
    """Item con cantidad para asignar a una tarea."""
    id: uuid.UUID
    cantidad: int = 1


class TareaUpdate(BaseModel):
    cliente_id: Optional[uuid.UUID] = None
    sucursal_id: Optional[uuid.UUID] = None
    titulo: Optional[str] = Field(None, max_length=255)
    descripcion: Optional[str] = None
    prioridad: Optional[str] = None
    fecha_programada: Optional[date] = None
    fecha_limite: Optional[date] = None
    personal_ids: Optional[list[uuid.UUID]] = None
    # ✅ Cambiado: ahora acepta items con cantidad
    herramienta_ids: Optional[list[ItemWithCantidad]] = None
    consumible_ids: Optional[list[ItemWithCantidad]] = None


class TareaOut(BaseModel):
    id: uuid.UUID
    cliente_id: uuid.UUID
    sucursal_id: uuid.UUID
    titulo: str
    descripcion: Optional[str] = None
    prioridad: str
    fecha_programada: Optional[date] = None
    fecha_limite: Optional[date] = None
    creador_id: uuid.UUID
    created_at: datetime
    estado: str

    model_config = ConfigDict(from_attributes=True)


class TareaNested(TareaOut):
    """Tarea with all relations loaded — used by `/tareas` and `/tareas/{id}`."""
    cliente: Optional[ClienteOut] = None
    sucursal: Optional[SucursalOut] = None
    creador: Optional[UserOut] = None
    personal: list[PersonalOut] = Field(default_factory=list)
    herramientas: list[HerramientaOut] = Field(default_factory=list)
    pasos: list[PasoOut] = Field(default_factory=list)
    comentarios: list[ComentarioOut] = Field(default_factory=list)
    imagenes: list[ImagenOut] = Field(default_factory=list)
    consumibles: list[ConsumibleOut] = Field(default_factory=list)


# ─── Generic envelope + notification schemas ────────────────────────────────

class Envelope(BaseModel):
    """Generic success envelope."""
    status: str = "success"
    message: Optional[str] = None
    data: Optional[Any] = None


class NotificationRequest(BaseModel):
    user_id: uuid.UUID
    title: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


# Resolve forward references (ClienteNested references SucursalNested
# which is defined later in this file).
ClienteNested.model_rebuild()
SucursalNested.model_rebuild()


# ─── Consumible Schemas ─────────────────────────────────────────────────────

class ConsumibleCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    tipo: Optional[str] = None
    unidad_medida: str = "unidad"
    stock_actual: int = 0
    stock_minimo: int = 5
    estado: str = "Disponible"

class ConsumibleUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    tipo: Optional[str] = None
    unidad_medida: Optional[str] = None
    stock_actual: Optional[int] = None
    stock_minimo: Optional[int] = None
    estado: Optional[str] = None

class ConsumibleOut(BaseModel):
    id: uuid.UUID
    nombre: str
    descripcion: Optional[str] = None
    tipo: str
    unidad_medida: str
    stock_actual: int
    stock_minimo: int
    estado: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── Picking Schemas ────────────────────────────────────────────────────────

class PickingItemCreate(BaseModel):
    """Ítem que el creador agrega al picking."""
    item_type: str  # "herramienta" | "consumible"
    item_id: uuid.UUID
    cantidad: int = 1

class PickingItemOut(BaseModel):
    id: uuid.UUID
    picking_id: uuid.UUID
    item_type: str
    item_id: Optional[uuid.UUID] = None
    nombre: str
    detalle: Optional[str] = None
    estado: str
    actualizado_por_id: Optional[uuid.UUID] = None
    cantidad_solicitada: int
    cantidad_tomada: int
    notas: Optional[str] = None
    agregado_por_tecnico: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PickingCreate(BaseModel):
    """Cuerpo para crear un picking."""
    referencia: str
    motivo: str
    personal_ids: list[uuid.UUID] = []  # IDs del personal asignado
    items: list[PickingItemCreate] = []  # Herramientas y consumibles iniciales

class PickingUpdate(BaseModel):
    """Actualización parcial del picking (solo campos editables por creador)."""
    referencia: Optional[str] = None
    motivo: Optional[str] = None
    estado: Optional[str] = None  # Solo para cancelar desde creador
    personal_ids: Optional[list[uuid.UUID]] = None  # Reemplaza la lista completa

class PickingItemEstadoUpdate(BaseModel):
    """El técnico actualiza el estado de un ítem."""
    estado: str  # "tomado" | "no_disponible" | "innecesario"
    cantidad_tomada: Optional[int] = None
    notas: Optional[str] = None

class PickingItemAddByTecnico(BaseModel):
    """El técnico agrega un ítem que no estaba en la lista original."""
    item_type: str  # "herramienta" | "consumible"
    nombre: Optional[str] = None
    detalle: Optional[str] = None
    item_id: Optional[uuid.UUID] = None  # Si existe en el catálogo
    cantidad: int = 1
    notas: Optional[str] = None

class PersonalAsignadoOut(BaseModel):
    id: uuid.UUID
    nombre: str
    cedula: str
    cargo: Optional[str] = None
    activo: bool

    model_config = ConfigDict(from_attributes=True)

class PickingOut(BaseModel):
    id: uuid.UUID
    referencia: str
    motivo: str
    estado: str
    creador_id: uuid.UUID
    progreso: int
    created_at: datetime
    updated_at: datetime
    # Relaciones
    personal_asignado: list[PersonalAsignadoOut] = []
    items: list[PickingItemOut] = []
    utilizado: bool = False

    model_config = ConfigDict(from_attributes=True)

class PickingListOut(BaseModel):
    """Versión ligera para listados."""
    id: uuid.UUID
    referencia: str
    motivo: str
    estado: str
    creador_id: uuid.UUID
    progreso: int
    total_items: int = 0
    items_completados: int = 0
    created_at: datetime
    updated_at: datetime
    personal_asignado: list[PersonalAsignadoOut] = []
    utilizado: bool = False

    model_config = ConfigDict(from_attributes=True)

class PickingCloneData(BaseModel):
    referencia: str
    motivo: str
    personal_ids: list[uuid.UUID]
    items: list[PickingItemCreate]

class TareaHerramientaEstadoUpdate(BaseModel):
    estado: str  # "asignada", "en_uso", "devuelta"
    personal_id: Optional[uuid.UUID] = None
    observaciones: Optional[str] = None

class TareaConsumibleEstadoUpdate(BaseModel):
    estado: str  # "asignado", "en_uso", "consumido"
    personal_id: Optional[uuid.UUID] = None
    observaciones: Optional[str] = None

class HerramientaEstadoOut(BaseModel):
    id: uuid.UUID
    tarea_id: uuid.UUID
    herramienta_id: uuid.UUID
    cantidad_asignada: int = 1
    cantidad_devuelta: int = 0
    estado: str
    fecha_inicio: datetime
    fecha_fin: Optional[datetime] = None
    observaciones: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ConsumibleEstadoOut(BaseModel):
    id: uuid.UUID
    tarea_id: uuid.UUID
    consumible_id: uuid.UUID
    cantidad_asignada: int = 1
    cantidad_devuelta: int = 0
    estado: str
    fecha_inicio: datetime
    fecha_fin: Optional[datetime] = None
    observaciones: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)