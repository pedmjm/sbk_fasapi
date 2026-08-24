"""
Database seed script. Ports the Laravel seeders and adds Consumibles:

  * PersonalSeeder     — 10 real technicians (cédulas V-…)
  * HerramientaSeeder  — Herramientas clasificadas por Tipo y Grupo
  * ConsumibleSeeder   — Consumibles extraídos de insumos de taller/campo
  * ClienteSeeder      — 4 clientes (Mimesa, Heinz, Cofasa, Polar) con
                         sus sucursales + contactos

Run via:  python seed.py
"""
from __future__ import annotations

import asyncio
import enum
import logging

from sqlalchemy import select

from database import async_session, create_db_and_tables
from models import (
    Cliente,
    Contacto,
    Consumible,
    GrupoHerramienta,
    Herramienta,
    Personal,
    Sucursal,
    TipoConsumible,
    TipoHerramienta,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("seed")


# ─── Personal (técnicos) ────────────────────────────────────────────────────

PERSONALES = [
    {"nombre": "Giovanny Marquez",  "cedula": "V-7141260",   "cargo": "Supervisor"},
    {"nombre": "Jose Marquez",      "cedula": "V-6703391",   "cargo": "Supervisor"},
    {"nombre": "Joel Flores",       "cedula": "V-9926709",   "cargo": "Supervisor SHA"},
    {"nombre": "Alonzo Marrufo",    "cedula": "V-27927125",  "cargo": "Supervisor"},
    {"nombre": "Roland Carrillo",   "cedula": "V-12035269",  "cargo": "Asistente Tec."},
    {"nombre": "Ronald Salas",      "cedula": "V-15064320",  "cargo": "Asistente Tec."},
    {"nombre": "Jesus Almao",       "cedula": "V-17344513",  "cargo": "Asistente Tec."},
    {"nombre": "Isaac Mendoza",     "cedula": "V-27851969",  "cargo": "Asistente Tec."},
    {"nombre": "Gregory Carrillo",  "cedula": "V-10733887",  "cargo": "Asistente Tec."},
    {"nombre": "Pedro Jimenez",     "cedula": "V-24496413",  "cargo": "Asistente Tec."},
]


# ─── Herramientas ───────────────────────────────────────────────────────────

HERRAMIENTAS = [
    {
        "nombre": "Juego de Ratchet y Dados",
        "marca": "Craftsman",
        "tipo": TipoHerramienta.MANUAL,
        "grupo": GrupoHerramienta.MECANICA_LIGERA,
        "combustible": "N/A",
    },
    {
        "nombre": "Termo para Agua 20 Lts.",
        "marca": "Potamo",
        "tipo": TipoHerramienta.LOGISTICO,
        "grupo": GrupoHerramienta.LOGISTICA_ASEO,
        "combustible": "N/A",
    },
    {
        "nombre": "Segueta",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.MANUAL,
        "grupo": GrupoHerramienta.MECANICA_LIGERA,
        "combustible": "N/A",
    },
    {
        "nombre": "Llaves eléctricas de Impacto",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.INALAMBRICO,
        "grupo": GrupoHerramienta.POTENCIA_ELECTROPORTATIL,
        "combustible": "Batería",
    },
    {
        "nombre": 'Taladro 1/2" con mechas',
        "marca": "DeWalt",
        "tipo": TipoHerramienta.INALAMBRICO,
        "grupo": GrupoHerramienta.POTENCIA_ELECTROPORTATIL,
        "combustible": "Batería / Eléctrica",
    },
    {
        "nombre": "Detector de Voltaje con pértiga SALISBURY #4744",
        "marca": "Salisbury",
        "tipo": TipoHerramienta.MEDICION,
        "grupo": GrupoHerramienta.MEDICION_DIAGNOSTICO,
        "combustible": "Batería",
    },
    {
        "nombre": "Extensiones eléctricas",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.ELECTRICO,
        "grupo": GrupoHerramienta.INFRAESTRUCTURA_ELECTRICA,
        "combustible": "N/A",
    },
    {
        "nombre": "Cajas de Herramientas con ruedas CRAFTSMAN",
        "marca": "Craftsman",
        "tipo": TipoHerramienta.ALMACENAMIENTO,
        "grupo": GrupoHerramienta.ALMACENAMIENTO_CONSUMIBLES,
        "combustible": "N/A",
    },
    {
        "nombre": "Juegos de llaves Allen varias",
        "marca": "Toolmex",
        "tipo": TipoHerramienta.MANUAL,
        "grupo": GrupoHerramienta.MECANICA_LIGERA,
        "combustible": "N/A",
    },
    {
        "nombre": "Multímetro digital marca Greenlee",
        "marca": "Greenlee",
        "tipo": TipoHerramienta.MEDICION,
        "grupo": GrupoHerramienta.MEDICION_DIAGNOSTICO,
        "combustible": "Batería 9V",
    },
    {
        "nombre": 'Taladro de mano de 3/8" con Juego de mechas varias',
        "marca": "Craftsman",
        "tipo": TipoHerramienta.INALAMBRICO,
        "grupo": GrupoHerramienta.POTENCIA_ELECTROPORTATIL,
        "combustible": "Batería",
    },
    {
        "nombre": 'Esmeril de mano 4 1/2" inalámbrico',
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.INALAMBRICO,
        "grupo": GrupoHerramienta.POTENCIA_ELECTROPORTATIL,
        "combustible": "Batería",
    },
    {
        "nombre": 'Esmeril de mano 1/2" con enchufe',
        "marca": "Ryobi",
        "tipo": TipoHerramienta.ELECTRICO,
        "grupo": GrupoHerramienta.POTENCIA_ELECTROPORTATIL,
        "combustible": "Cable 110V/220V",
    },
    {
        "nombre": "Soplador Industrial",
        "marca": "Ryobi",
        "tipo": TipoHerramienta.ELECTRICO,
        "grupo": GrupoHerramienta.POTENCIA_ELECTROPORTATIL,
        "combustible": "Cable 110V/220V",
    },
    {
        "nombre": "Ratchet inalámbrico",
        "marca": "ACDelco",
        "tipo": TipoHerramienta.INALAMBRICO,
        "grupo": GrupoHerramienta.POTENCIA_ELECTROPORTATIL,
        "combustible": "Batería",
    },
    {
        "nombre": "Bolso con Herramientas",
        "marca": "Serbreka",
        "tipo": TipoHerramienta.ALMACENAMIENTO,
        "grupo": GrupoHerramienta.ALMACENAMIENTO_CONSUMIBLES,
        "combustible": "N/A",
    },
    {
        "nombre": "Cepillo de barrer con pala",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.LOGISTICO,
        "grupo": GrupoHerramienta.LOGISTICA_ASEO,
        "combustible": "N/A",
    },
    {
        "nombre": "Arnés de seguridad",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.SEGURIDAD,
        "grupo": GrupoHerramienta.SEGURIDAD_EPP,
        "combustible": "N/A",
    },
    {
        "nombre": "Contenedor plástico",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.ALMACENAMIENTO,
        "grupo": GrupoHerramienta.ALMACENAMIENTO_CONSUMIBLES,
        "combustible": "N/A",
    },
    {
        "nombre": "Careta para esmerilar",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.SEGURIDAD,
        "grupo": GrupoHerramienta.SEGURIDAD_EPP,
        "combustible": "N/A",
    },
    {
        "nombre": "Extintor de fuego CO2",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.SEGURIDAD,
        "grupo": GrupoHerramienta.SEGURIDAD_EPP,
        "combustible": "N/A",
    },
    {
        "nombre": "Reflectores con pedestal",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.ELECTRICO,
        "grupo": GrupoHerramienta.INFRAESTRUCTURA_ELECTRICA,
        "combustible": "Cable 110V/220V",
    },
    {
        "nombre": "Guantes de alta tensión",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.SEGURIDAD,
        "grupo": GrupoHerramienta.SEGURIDAD_EPP,
        "combustible": "N/A",
    },
    {
        "nombre": "Bolso de Herramientas varias",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.ALMACENAMIENTO,
        "grupo": GrupoHerramienta.ALMACENAMIENTO_CONSUMIBLES,
        "combustible": "N/A",
    },
    {
        "nombre": "Cinta Métrica",
        "marca": "Sin Marca",
        "tipo": TipoHerramienta.MEDICION,
        "grupo": GrupoHerramienta.MEDICION_DIAGNOSTICO,
        "combustible": "N/A",
    },
]


# ─── Consumibles ────────────────────────────────────────────────────────────

CONSUMIBLES = [
    {
        "nombre": "Teipe eléctrico",
        "descripcion": "Teipe/cinta aislante de alta calidad (3M)",
        "tipo": TipoConsumible.ELECTRICO,
        "unidad_medida": "rollo",
        "stock_actual": 20,
        "stock_minimo": 5,
    },
    {
        "nombre": "Lanilla de limpieza",
        "descripcion": "Lanilla/trapo industrial para limpieza de equipos",
        "tipo": TipoConsumible.LIMPIEZA,
        "unidad_medida": "kg",
        "stock_actual": 10,
        "stock_minimo": 2,
    },
    {
        "nombre": "Cremas limpiadoras / Desengrasantes",
        "descripcion": "Crema o desengrasante para limpieza de componentes",
        "tipo": TipoConsumible.LIMPIEZA,
        "unidad_medida": "unidad",
        "stock_actual": 8,
        "stock_minimo": 2,
    },
    {
        "nombre": "Desplazante de humedad / Lubricantes (WD-40)",
        "descripcion": "Spray desplazante de humedad y lubricante multipropósito",
        "tipo": TipoConsumible.MECANICO,
        "unidad_medida": "lata",
        "stock_actual": 12,
        "stock_minimo": 3,
    },
    {
        "nombre": "Amarres plásticos (Tirraps)",
        "descripcion": "Amarres plásticos de varios tamaños",
        "tipo": TipoConsumible.ELECTRICO,
        "unidad_medida": "paquete",
        "stock_actual": 15,
        "stock_minimo": 5,
    },
    {
        "nombre": "Tornillos varios",
        "descripcion": "Surtido de tornillos, tuercas y arandelas",
        "tipo": TipoConsumible.MECANICO,
        "unidad_medida": "caja",
        "stock_actual": 10,
        "stock_minimo": 3,
    },
]


# ─── Clientes + Sucursales + Contactos ─────────────────────────────────────

CLIENTES = [
    {
        "rif": "J-07032176-8", "razon_social": "MIMESA ALIMENTOS C.A.", "nombre_comercial": "Mimesa",
        "sucursales": [
            {"nombre_sucursal": "Planta Valencia", "codigo_interno": "PLT-VAL", "estado": "Carabobo", "ciudad": "Valencia"},
            {"nombre_sucursal": "Planta Catia La Mar", "codigo_interno": "PLT-CLM", "estado": "La Guaira", "ciudad": "Catia La Mar"},
            {"nombre_sucursal": "Planta La Encrucijada", "codigo_interno": "PLT-ENC", "estado": "Aragua", "ciudad": "Cagua"},
            {"nombre_sucursal": "Planta Maracaibo", "codigo_interno": "PLT-MAR", "estado": "Zulia", "ciudad": "Maracaibo"},
            {"nombre_sucursal": "PRODUSAL", "codigo_interno": "PLT-PRODUSAL", "estado": "", "ciudad": ""},
        ],
    },
    {
        "rif": "J-07586215-5", "razon_social": "ALIMENTOS HEINZ, C.A.", "nombre_comercial": "Heinz",
        "sucursales": [
            {"nombre_sucursal": "Sede Principal", "codigo_interno": "PLT-HNZ", "estado": "Carabobo", "ciudad": "San Joaquín"},
        ],
    },
    {
        "rif": "J-00087626-6", "razon_social": "LABORATORIO COFASA, S.A.", "nombre_comercial": "Laboratorio Cofasa",
        "sucursales": [
            {"nombre_sucursal": "Sede Principal", "codigo_interno": "PLT-COF", "estado": "", "ciudad": ""},
        ],
    },
    {
        "rif": "J-00006372-9", "razon_social": "ALIMENTOS POLAR, C.A.", "nombre_comercial": "Alimentos Polar",
        "sucursales": [
            {"nombre_sucursal": "Sede Principal", "codigo_interno": "PLT-POL", "estado": "", "ciudad": ""},
        ],
    },
]


# ─── Seed runner ────────────────────────────────────────────────────────────

async def seed_personales(session) -> int:
    count = 0
    for p_data in PERSONALES:
        existing = (
            await session.execute(select(Personal).where(Personal.cedula == p_data["cedula"]))
        ).scalar_one_or_none()
        if existing:
            continue
        session.add(Personal(**p_data, activo=True, tipo_usuario=0))
        count += 1
    return count


async def seed_herramientas(session) -> int:
    count = 0
    for h_data in HERRAMIENTAS:
        existing = (
            await session.execute(
                select(Herramienta).where(
                    Herramienta.nombre == h_data["nombre"],
                    Herramienta.marca == h_data["marca"],
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        session.add(Herramienta(
            nombre=h_data["nombre"],
            marca=h_data["marca"],
            tipo=h_data["tipo"],
            grupo=h_data["grupo"],
            combustible=h_data["combustible"],
            estado="Disponible",
        ))
        count += 1
    return count


async def seed_consumibles(session) -> int:
    count = 0
    for c_data in CONSUMIBLES:
        existing = (
            await session.execute(
                select(Consumible).where(
                    Consumible.nombre == c_data["nombre"],
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        session.add(Consumible(
            nombre=c_data["nombre"],
            descripcion=c_data["descripcion"],
            tipo=c_data["tipo"],
            unidad_medida=c_data["unidad_medida"],
            stock_actual=c_data["stock_actual"],
            stock_minimo=c_data["stock_minimo"],
            estado="Disponible",
        ))
        count += 1
    return count


async def seed_clientes(session) -> int:
    count = 0
    for c_data in CLIENTES:
        existing = (
            await session.execute(select(Cliente).where(Cliente.rif == c_data["rif"]))
        ).scalar_one_or_none()
        if existing:
            continue
        cliente = Cliente(
            rif=c_data["rif"],
            razon_social=c_data["razon_social"],
            nombre_comercial=c_data["nombre_comercial"],
            is_active=True,
        )
        session.add(cliente)
        await session.flush()

        for s_data in c_data["sucursales"]:
            sucursal = Sucursal(
                cliente_id=cliente.id,
                nombre_sucursal=s_data["nombre_sucursal"],
                codigo_interno=s_data["codigo_interno"],
                direccion="",
                estado=s_data["estado"],
                ciudad=s_data["ciudad"],
            )
            session.add(sucursal)
            await session.flush()
            session.add(Contacto(
                sucursal_id=sucursal.id,
                nombre_completo="",
                cargo="",
                telefono="",
                email="",
                is_primary=True,
            ))
        count += 1
    return count


async def main() -> None:
    log.info("Creating tables (if missing)…")
    await create_db_and_tables()

    async with async_session() as session:
        async with session.begin():
            n_p = await seed_personales(session)
            n_h = await seed_herramientas(session)
            n_con = await seed_consumibles(session)
            n_c = await seed_clientes(session)
        log.info(
            "Seeded: %d personales, %d herramientas, %d consumibles, %d clientes.",
            n_p, n_h, n_con, n_c
        )
        if n_p == 0 and n_h == 0 and n_con == 0 and n_c == 0:
            log.info("(Everything already present — nothing inserted.)")


if __name__ == "__main__":
    asyncio.run(main())