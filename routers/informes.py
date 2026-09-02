"""
Informes Técnicos router — reports generated from finalized Visitas.

The informe is anchored 1:1 to its visita (`informes_tecnicos.visita_id`
is UNIQUE). Flow:
    visita programada → finalizada → (opcional) POST .../informe

The DB stores flat prefixed columns (gen_/eq_/cond_/pr_*); the API exposes
them nested exactly like the report JSON template (see schemas:
InformeTecnicoCreate/Out). `number` is an auto-sequential Integer
(max+1, NO zero-padding — the client pads for display, e.g. 182 → "000182").

Endpoints (all require auth):
  POST   /visitas/{visita_id}/informe   generar (visita debe estar finalizada;
                                        409 si ya tiene informe)
  GET    /visitas/{visita_id}/informe   el informe de la visita
  PUT    /visitas/{visita_id}/informe   edición parcial (secciones se
                                        reemplazan completas)
  DELETE /visitas/{visita_id}/informe   eliminar
  GET    /informes                      lista global (con resumen de visita)
  GET    /informes/{number}             lookup por número secuencial
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import get_current_active_user
from database import get_db
from models import EstadoVisita, InformeTecnico, User, Visita
from schemas import Envelope, InformeTecnicoBase, InformeTecnicoCreate, InformeTecnicoUpdate
from datetime import date as date_type

router = APIRouter(tags=["informes"])


# ─── Flat columns ↔ nested JSON mapping ─────────────────────────────────────

_SECTION_MAPS: dict[str, dict[str, str]] = {
    "general_information": {
        "cliente": "gen_cliente",
        "atencion": "gen_atencion",
        "fecha_de_ejecucion": "gen_fecha_de_ejecucion",
        "garantia": "gen_garantia",
    },
    "identificacion_del_equipo": {
        "equipo": "eq_equipo",
        "marca": "eq_marca",
        "voltaje": "eq_voltaje",
        "modelo": "eq_modelo",
        "tipo": "eq_tipo",
        "corriente": "eq_corriente",
        "unidad_de_disparo": "eq_unidad_de_disparo",
        "alimenta": "eq_alimenta",
        "categoria": "eq_categoria",
    },
    "condiciones_del_equipo": {
        "camaras_de_extincion_de_arco": "cond_camaras_de_extincion_de_arco",
        "mecanismo_de_apertura_y_cierre": "cond_mecanismo_de_apertura_y_cierre",
        "conexiones_de_entrada_y_salida": "cond_conexiones_de_entrada_y_salida",
        "frame_base": "cond_frame_base",
        "celda": "cond_celda",
        "contactos_fijos": "cond_contactos_fijos",
        "pruebas_de_accionamiento_mecanico": "cond_pruebas_de_accionamiento_mecanico",
        "leva_de_disparo": "cond_leva_de_disparo",
        "frame_tapa": "cond_frame_tapa",
        "barras": "cond_barras",
        "contactos_moviles": "cond_contactos_moviles",
        "cuchillas_secundarias": "cond_cuchillas_secundarias",
        "tornilleria_en_general": "cond_tornilleria_en_general",
        "accesorios": "cond_accesorios",
        "cables": "cond_cables",
    },
}

_MEGGER_MAP = {
    "a_vs_b": "pr_a_vs_b",
    "b_vs_c": "pr_b_vs_c",
    "c_vs_a": "pr_c_vs_a",
    "a_b_c_vs_tierra": "pr_abc_vs_tierra",
    "entrada_vs_salida": "pr_entrada_vs_salida",
    "salida_vs_entrada": "pr_salida_vs_entrada",
}

_VALORES_MAP = {
    "valor_teorico_long_delay": "pr_valor_teorico_long_delay",
    "valor_dejado": "pr_valor_dejado",
    "simulacion_del_disparo_por_corto_circuito_short_delay": "pr_simulacion_disparo_corto",
    "tierra_ground": "pr_tierra_ground",
}

_SCALAR_KEYS = (
    "titulo", "fecha_de_emision", "orden_de_compra", "lugar",
    "observaciones", "recomendaciones",
)


def apply_informe_body(informe: InformeTecnico, body: InformeTecnicoBase) -> None:
    """Copy the (nested) body fields onto the flat ORM columns.

    Uses `exclude_unset` so a PUT only touches what the client sent; a
    section present in the payload replaces that section whole.
    """
    data = body.model_dump(exclude_unset=True)

    for k in _SCALAR_KEYS:
        if k in data:
            setattr(informe, k, data[k])

    for section, mapping in _SECTION_MAPS.items():
        if data.get(section) is not None:
            for field, col in mapping.items():
                if field in data[section]:
                    setattr(informe, col, data[section][field])

    pe = data.get("pruebas_electricas")
    if pe is not None:
        meg = pe.get("pruebas_de_resistencia_de_aislamiento_megger_test")
        if meg:
            if "voltaje_vdc" in meg:
                setattr(informe, "pr_voltaje_vdc", meg["voltaje_vdc"])
            med = meg.get("mediciones") or {}
            for field, col in _MEGGER_MAP.items():
                if field in med:
                    setattr(informe, col, med[field])
        if "unidad_de_disparo_tipo" in pe:
            setattr(informe, "pr_unidad_de_disparo_tipo", pe["unidad_de_disparo_tipo"])
        if "tipo_de_prueba" in pe:
            setattr(informe, "pr_tipo_de_prueba", pe["tipo_de_prueba"])
        vd = pe.get("valores_de_disparo") or {}
        for field, col in _VALORES_MAP.items():
            if field in vd:
                setattr(informe, col, vd[field])


def informe_payload(informe: InformeTecnico) -> dict:
    """ORM → nested dict exactly like the report JSON template."""
    return {
        "id": str(informe.id),
        "number": informe.number,
        "visita_id": str(informe.visita_id),
        "titulo": informe.titulo,
        "fecha_de_emision": informe.fecha_de_emision.isoformat() if informe.fecha_de_emision else None,
        "orden_de_compra": informe.orden_de_compra,
        "lugar": informe.lugar,
        "general_information": {
            "cliente": informe.gen_cliente,
            "atencion": informe.gen_atencion,
            "fecha_de_ejecucion": informe.gen_fecha_de_ejecucion.isoformat() if informe.gen_fecha_de_ejecucion else None,
            "garantia": informe.gen_garantia,
        },
        "identificacion_del_equipo": {
            "equipo": informe.eq_equipo,
            "marca": informe.eq_marca,
            "voltaje": informe.eq_voltaje,
            "modelo": informe.eq_modelo,
            "tipo": informe.eq_tipo,
            "corriente": informe.eq_corriente,
            "unidad_de_disparo": informe.eq_unidad_de_disparo,
            "alimenta": informe.eq_alimenta,
            "categoria": informe.eq_categoria,
        },
        "condiciones_del_equipo": {
            "camaras_de_extincion_de_arco": informe.cond_camaras_de_extincion_de_arco,
            "mecanismo_de_apertura_y_cierre": informe.cond_mecanismo_de_apertura_y_cierre,
            "conexiones_de_entrada_y_salida": informe.cond_conexiones_de_entrada_y_salida,
            "frame_base": informe.cond_frame_base,
            "celda": informe.cond_celda,
            "contactos_fijos": informe.cond_contactos_fijos,
            "pruebas_de_accionamiento_mecanico": informe.cond_pruebas_de_accionamiento_mecanico,
            "leva_de_disparo": informe.cond_leva_de_disparo,
            "frame_tapa": informe.cond_frame_tapa,
            "barras": informe.cond_barras,
            "contactos_moviles": informe.cond_contactos_moviles,
            "cuchillas_secundarias": informe.cond_cuchillas_secundarias,
            "tornilleria_en_general": informe.cond_tornilleria_en_general,
            "accesorios": informe.cond_accesorios,
            "cables": informe.cond_cables,
        },
        "pruebas_electricas": {
            "pruebas_de_resistencia_de_aislamiento_megger_test": {
                "voltaje_vdc": informe.pr_voltaje_vdc,
                "mediciones": {
                    "a_vs_b": informe.pr_a_vs_b,
                    "b_vs_c": informe.pr_b_vs_c,
                    "c_vs_a": informe.pr_c_vs_a,
                    "a_b_c_vs_tierra": informe.pr_abc_vs_tierra,
                    "entrada_vs_salida": informe.pr_entrada_vs_salida,
                    "salida_vs_entrada": informe.pr_salida_vs_entrada,
                },
            },
            "unidad_de_disparo_tipo": informe.pr_unidad_de_disparo_tipo,
            "tipo_de_prueba": informe.pr_tipo_de_prueba,
            "valores_de_disparo": {
                "valor_teorico_long_delay": informe.pr_valor_teorico_long_delay,
                "valor_dejado": informe.pr_valor_dejado,
                "simulacion_del_disparo_por_corto_circuito_short_delay": informe.pr_simulacion_disparo_corto,
                "tierra_ground": informe.pr_tierra_ground,
            },
        },
        "observaciones": informe.observaciones,
        "recomendaciones": informe.recomendaciones,
        "created_at": informe.created_at.isoformat() if informe.created_at else None,
        "updated_at": informe.updated_at.isoformat() if informe.updated_at else None,
    }


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _fetch_informe(db: AsyncSession, visita_id: uuid.UUID) -> Optional[InformeTecnico]:
    stmt = (
        select(InformeTecnico)
        .options(selectinload(InformeTecnico.visita).selectinload(Visita.cliente))
        .where(InformeTecnico.visita_id == visita_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _visita_summary(informe: InformeTecnico) -> dict:
    v = informe.visita
    return {
        "id": str(v.id),
        "fecha": v.fecha.isoformat() if v.fecha else None,
        "estado": v.estado.value if v.estado else None,
        "ubicacion": v.ubicacion,
        "cliente": v.cliente.razon_social if v.cliente else None,
    }


# ─── Informe de una visita (anidado) ────────────────────────────────────────

@router.post("/visitas/{visita_id}/informe", response_model=Envelope, status_code=status.HTTP_201_CREATED)
async def generar_informe(
    visita_id: uuid.UUID,
    body: InformeTecnicoCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Genera el informe técnico de una visita FINALIZADA (opcional en el
    flujo). Auto-asigna `number = max+1` (sin padding) y auto-completa
    desde la visita: general_information.cliente, fecha_de_ejecucion y lugar."""
    visita = (
        await db.execute(
            select(Visita)
            .options(selectinload(Visita.cliente))
            .where(Visita.id == visita_id)
        )
    ).scalar_one_or_none()
    if not visita:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")

    if visita.estado != EstadoVisita.FINALIZADA:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No se puede generar el informe: la visita está "
                f"'{visita.estado.value}' y debe estar 'finalizada'."
            ),
        )

    existing = await _fetch_informe(db, visita_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta visita ya tiene un informe técnico.",
        )

    # Auto-sequential number (no padding — the client pads for display).
    max_num = (await db.execute(select(func.max(InformeTecnico.number)))).scalar()
    next_number = (max_num or 0) + 1

    informe = InformeTecnico(visita_id=visita_id, number=next_number)
    apply_informe_body(informe, body)

    # ─── Auto-fill desde la visita (solo lo que el cliente no envió) ──
    if informe.gen_cliente is None and visita.cliente:
        informe.gen_cliente = visita.cliente.razon_social
    if informe.gen_fecha_de_ejecucion is None:
        informe.gen_fecha_de_ejecucion = visita.fecha.date() if visita.fecha else None
    if informe.lugar is None:
        informe.lugar = visita.ubicacion
    if informe.fecha_de_emision is None:
        informe.fecha_de_emision = date_type.today()

    db.add(informe)
    await db.commit()

    informe = await _fetch_informe(db, visita_id)
    data = informe_payload(informe)
    data["visita"] = _visita_summary(informe)
    return Envelope(message="Informe técnico generado", data=data)


@router.get("/visitas/{visita_id}/informe", response_model=Envelope)
async def get_informe_de_visita(
    visita_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    informe = await _fetch_informe(db, visita_id)
    if not informe:
        # Distinguish "visita no existe" from "visita sin informe".
        visita_exists = (
            await db.execute(select(Visita.id).where(Visita.id == visita_id))
        ).scalar_one_or_none()
        if not visita_exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visita no encontrada")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Esta visita no tiene informe técnico")

    data = informe_payload(informe)
    data["visita"] = _visita_summary(informe)
    return Envelope(data=data)


@router.put("/visitas/{visita_id}/informe", response_model=Envelope)
async def update_informe(
    visita_id: uuid.UUID,
    body: InformeTecnicoUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    informe = await _fetch_informe(db, visita_id)
    if not informe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Esta visita no tiene informe técnico")

    apply_informe_body(informe, body)
    await db.commit()

    informe = await _fetch_informe(db, visita_id)
    data = informe_payload(informe)
    data["visita"] = _visita_summary(informe)
    return Envelope(message="Informe técnico actualizado", data=data)


@router.delete("/visitas/{visita_id}/informe", response_model=Envelope)
async def delete_informe(
    visita_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    informe = await _fetch_informe(db, visita_id)
    if not informe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Esta visita no tiene informe técnico")

    await db.delete(informe)
    await db.commit()
    return Envelope(message="Informe técnico eliminado")


# ─── Listado global ─────────────────────────────────────────────────────────

@router.get("/informes", response_model=Envelope)
async def list_informes(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    informes = (
        await db.execute(
            select(InformeTecnico)
            .options(selectinload(InformeTecnico.visita).selectinload(Visita.cliente))
            .order_by(InformeTecnico.number.desc())
        )
    ).scalars().all()

    out = []
    for inf in informes:
        d = informe_payload(inf)
        d["visita"] = _visita_summary(inf)
        out.append(d)
    return Envelope(data=out)


@router.get("/informes/{number}", response_model=Envelope)
async def get_informe_by_number(
    number: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Lookup por número secuencial (sin padding: 182, no "000182")."""
    informe = (
        await db.execute(
            select(InformeTecnico)
            .options(selectinload(InformeTecnico.visita).selectinload(Visita.cliente))
            .where(InformeTecnico.number == number)
        )
    ).scalar_one_or_none()
    if not informe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Informe número {number} no encontrado")

    data = informe_payload(informe)
    data["visita"] = _visita_summary(informe)
    return Envelope(data=data)
