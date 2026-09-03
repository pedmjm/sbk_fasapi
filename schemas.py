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
from storage_helpers import build_public_url, delete_rel_path, save_upload

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field


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
    foto_perfil: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def foto_perfil_url(self) -> Optional[str]:
        """URL pública derivada de `foto_perfil` (path relativo en storage)."""
        return build_public_url(self.foto_perfil) if self.foto_perfil else None


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
    grupo: Optional[str] = None
    tipo: Optional[str] = None
    stock_minimo: Optional[int] = None
    stock_actual: Optional[int] = None
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


# ─── Comentario ────────────────────────────────────────────────────────────
# (Defined before Pasos because PasoOut nests ComentarioOut.)

class ComentarioOut(BaseModel):
    id: uuid.UUID
    tarea_id: uuid.UUID
    paso_id: Optional[uuid.UUID] = None
    autor_id: uuid.UUID
    texto: str
    created_at: datetime
    autor: Optional[UserOut] = None
    imagenes: list[ImagenOut] = Field(default_factory=list)

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
    comentarios: list[ComentarioOut] = Field(default_factory=list)

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
    """Tarea with all relations loaded — used by `/tareas` and `/tareas/{id}`.

    Comments are nested under each paso (`pasos[].comentarios`), not at
    the tarea level.
    """
    cliente: Optional[ClienteOut] = None
    sucursal: Optional[SucursalOut] = None
    creador: Optional[UserOut] = None
    personal: list[PersonalOut] = Field(default_factory=list)
    herramientas: list[HerramientaOut] = Field(default_factory=list)
    pasos: list[PasoOut] = Field(default_factory=list)
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
    foto_perfil: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def foto_perfil_url(self) -> Optional[str]:
        return build_public_url(self.foto_perfil) if self.foto_perfil else None

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


# ─── Informe Técnico ───────────────────────────────────────────────────────
# Nested exactly like the report JSON template. The DB stores flat prefixed
# columns (gen_/eq_/cond_/pr_*) — the routers map flat ↔ nested.

class InformeGeneralInformation(BaseModel):
    cliente: Optional[str] = None
    atencion: Optional[str] = None
    fecha_de_ejecucion: Optional[date] = None
    garantia: Optional[str] = None


class InformeIdentificacionEquipo(BaseModel):
    equipo: Optional[str] = None
    marca: Optional[str] = None
    voltaje: Optional[str] = None
    modelo: Optional[str] = None
    tipo: Optional[str] = None
    corriente: Optional[str] = None
    unidad_de_disparo: Optional[str] = None
    alimenta: Optional[str] = None
    categoria: Optional[str] = None


class InformeCondicionesEquipo(BaseModel):
    camaras_de_extincion_de_arco: Optional[str] = None
    mecanismo_de_apertura_y_cierre: Optional[str] = None
    conexiones_de_entrada_y_salida: Optional[str] = None
    frame_base: Optional[str] = None
    celda: Optional[str] = None
    contactos_fijos: Optional[str] = None
    pruebas_de_accionamiento_mecanico: Optional[str] = None
    leva_de_disparo: Optional[str] = None
    frame_tapa: Optional[str] = None
    barras: Optional[str] = None
    contactos_moviles: Optional[str] = None
    cuchillas_secundarias: Optional[str] = None
    tornilleria_en_general: Optional[str] = None
    accesorios: Optional[str] = None
    cables: Optional[str] = None


class InformeMeggerMediciones(BaseModel):
    a_vs_b: Optional[str] = None
    b_vs_c: Optional[str] = None
    c_vs_a: Optional[str] = None
    a_b_c_vs_tierra: Optional[str] = None
    entrada_vs_salida: Optional[str] = None
    salida_vs_entrada: Optional[str] = None


class InformeMeggerTest(BaseModel):
    """`pruebas_de_resistencia_de_aislamiento_megger_test`."""
    voltaje_vdc: Optional[str] = None
    mediciones: InformeMeggerMediciones = Field(default_factory=InformeMeggerMediciones)


class InformeValoresDisparo(BaseModel):
    valor_teorico_long_delay: Optional[str] = None
    valor_dejado: Optional[str] = None
    simulacion_del_disparo_por_corto_circuito_short_delay: Optional[str] = None
    tierra_ground: Optional[str] = None


class InformePruebasElectricas(BaseModel):
    pruebas_de_resistencia_de_aislamiento_megger_test: InformeMeggerTest = Field(
        default_factory=InformeMeggerTest
    )
    unidad_de_disparo_tipo: Optional[str] = None
    tipo_de_prueba: Optional[str] = None
    valores_de_disparo: InformeValoresDisparo = Field(default_factory=InformeValoresDisparo)


class InformeTecnicoBase(BaseModel):
    """Shared fields for create/update. Sections not sent are left null
    (on update: a section sent replaces it whole)."""
    titulo: Optional[str] = Field(None, max_length=255)
    fecha_de_emision: Optional[date] = None
    orden_de_compra: Optional[str] = Field(None, max_length=100)
    lugar: Optional[str] = Field(None, max_length=255)
    general_information: Optional[InformeGeneralInformation] = None
    identificacion_del_equipo: Optional[InformeIdentificacionEquipo] = None
    condiciones_del_equipo: Optional[InformeCondicionesEquipo] = None
    pruebas_electricas: Optional[InformePruebasElectricas] = None
    observaciones: Optional[str] = None
    recomendaciones: Optional[str] = None


class InformeTecnicoCreate(InformeTecnicoBase):
    pass


class InformeTecnicoUpdate(InformeTecnicoBase):
    pass


class InformeTecnicoOut(BaseModel):
    """Nested like the report JSON template. `number` is the sequential int —
    the client zero-pads it for display (182 → "000182")."""
    id: uuid.UUID
    number: int
    visita_id: uuid.UUID
    titulo: Optional[str] = None
    fecha_de_emision: Optional[date] = None
    orden_de_compra: Optional[str] = None
    lugar: Optional[str] = None
    general_information: InformeGeneralInformation = Field(default_factory=InformeGeneralInformation)
    identificacion_del_equipo: InformeIdentificacionEquipo = Field(default_factory=InformeIdentificacionEquipo)
    condiciones_del_equipo: InformeCondicionesEquipo = Field(default_factory=InformeCondicionesEquipo)
    pruebas_electricas: InformePruebasElectricas = Field(default_factory=InformePruebasElectricas)
    observaciones: Optional[str] = None
    recomendaciones: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ─── Visita ────────────────────────────────────────────────────────────────

class VisitaCreate(BaseModel):
    cliente_id: uuid.UUID
    sucursal_id: Optional[uuid.UUID] = None
    personal_id: Optional[uuid.UUID] = None  # técnico asignado
    fecha: datetime
    ubicacion: Optional[str] = Field(None, max_length=255)
    descripcion: Optional[str] = None
    telefono_contacto: Optional[str] = Field(None, max_length=50)
    detalles_tecnicos: Optional[dict[str, Any]] = None


class VisitaUpdate(BaseModel):
    cliente_id: Optional[uuid.UUID] = None
    sucursal_id: Optional[uuid.UUID] = None
    personal_id: Optional[uuid.UUID] = None
    fecha: Optional[datetime] = None
    ubicacion: Optional[str] = Field(None, max_length=255)
    descripcion: Optional[str] = None
    telefono_contacto: Optional[str] = Field(None, max_length=50)
    detalles_tecnicos: Optional[dict[str, Any]] = None


class FinalizarVisitaBody(BaseModel):
    """Resultado de la inspección al finalizar la visita."""
    incidencias: Optional[str] = None
    observaciones: Optional[str] = None
    detalles_tecnicos: Optional[dict[str, Any]] = None


class VisitaOut(BaseModel):
    id: uuid.UUID
    cliente_id: uuid.UUID
    sucursal_id: Optional[uuid.UUID] = None
    personal_id: Optional[uuid.UUID] = None
    creador_id: uuid.UUID
    fecha: datetime
    ubicacion: Optional[str] = None
    descripcion: Optional[str] = None
    telefono_contacto: Optional[str] = None
    estado: str
    detalles_tecnicos: Optional[dict[str, Any]] = None
    incidencias: Optional[str] = None
    observaciones: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VisitaNested(VisitaOut):
    """Visita with relations loaded — used by `/visitas` list/detail."""
    cliente: Optional[ClienteOut] = None
    sucursal: Optional[SucursalOut] = None
    personal: Optional[PersonalOut] = None
    imagenes: list[ImagenOut] = Field(default_factory=list)
    informe: Optional[InformeTecnicoOut] = None


# ─── Gestión de usuarios + perfil ──────────────────────────────────────────

class UsuarioNivelBody(BaseModel):
    """Promover/degradar el nivel de un usuario (0 técnico, 1 moderador,
    2 admin, 5 super admin)."""
    nivel: int


class UsuarioEstadoBody(BaseModel):
    """Activar/desactivar un usuario. Desactivar impide el login e
    invalida todos sus tokens vigentes."""
    activo: bool


class UsuarioAdminOut(UserOut):
    """Vista de usuario para admins (incluye estado)."""
    activo: bool = True
    token_version: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PerfilUpdate(BaseModel):
    """Campos que el propio usuario puede editar de su perfil."""
    name: Optional[str] = Field(None, max_length=255)
    telefono: Optional[str] = Field(None, max_length=50)
    cargo: Optional[str] = Field(None, max_length=100)


class PasswordChange(BaseModel):
    actual: str
    nueva: str = Field(..., min_length=6)


# ─── Chat por tarea ────────────────────────────────────────────────────────

class MensajeChatOut(BaseModel):
    id: uuid.UUID
    tarea_id: uuid.UUID
    autor_id: uuid.UUID
    contenido: str
    created_at: datetime
    autor: Optional[UserOut] = None
    # Polymorphic images (imageable_type='ChatMensaje'); files under
    # storage/chat/{mensaje_id}/. Attached by the chat serializer.
    imagenes: list[ImagenOut] = Field(default_factory=list)
    # Deterministic bubble color: PALETA[autor_id.int % len(PALETA)].
    color: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)