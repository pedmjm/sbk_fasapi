"""
Database seed script. Ports the three Laravel seeders:

  * PersonalSeeder     — 10 real technicians (cédulas V-…)
  * HerramientaSeeder  — ~25 tools (Craftsman, DeWalt, Salisbury, ...)
  * ClienteSeeder      — 4 clientes (Mimesa, Heinz, Cofasa, Polar) with
                         their sucursales + contactos

Run via:  python seed.py
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from database import async_session, create_db_and_tables
from models import Cliente, Contacto, Herramienta, Personal, Sucursal, TipoHerramienta

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
    {"nombre": "Juego de Ratchet y Dados", "marca": "Craftsman", "tipo": "Manual", "combustible": "N/A"},
    {"nombre": "Termo para Agua 20 Lts.", "marca": "Potamo", "tipo": "Logístico", "combustible": "N/A"},
    {"nombre": "Segueta", "marca": "Sin Marca", "tipo": "Manual", "combustible": "N/A"},
    {"nombre": "Llaves eléctricas de Impacto", "marca": "Sin Marca", "tipo": "Inalámbrico", "combustible": "Batería"},
    {"nombre": 'Taladro 1/2" con mechas', "marca": "DeWalt", "tipo": "Inalámbrico", "combustible": "Batería / Eléctrica"},
    {"nombre": "Detector de Voltaje con pértiga SALISBURY #4744", "marca": "Salisbury", "tipo": "Medición", "combustible": "Batería"},
    {"nombre": "Extensiones eléctricas", "marca": "Sin Marca", "tipo": "Eléctrico", "combustible": "N/A"},
    {"nombre": "Cajas de Herramientas con ruedas CRAFTSMAN", "marca": "Craftsman", "tipo": "Almacenamiento", "combustible": "N/A"},
    {"nombre": "Juegos de llaves Allen varias", "marca": "Toolmex", "tipo": "Manual", "combustible": "N/A"},
    {"nombre": "Multímetro digital marca Greenlee", "marca": "Greenlee", "tipo": "Medición", "combustible": "Batería 9V"},
    {"nombre": "Cajas con consumibles (Teipe, lanilla, cremas limpiadoras, desplazante de humedad, lubricantes, amarres)", "marca": "3M", "tipo": "Almacenamiento", "combustible": "N/A"},
    {"nombre": 'Taladro de mano de 3/8" con Juego de mechas varias', "marca": "Craftsman", "tipo": "Inalámbrico", "combustible": "Batería"},
    {"nombre": 'Esmeril de mano 4 1/2" inalámbrico', "marca": "Sin Marca", "tipo": "Inalámbrico", "combustible": "Batería"},
    {"nombre": 'Esmeril de mano 1/2" con enchufe', "marca": "Ryobi", "tipo": "Eléctrico", "combustible": "Cable 110V/220V"},
    {"nombre": "Soplador Industrial", "marca": "Ryobi", "tipo": "Eléctrico", "combustible": "Cable 110V/220V"},
    {"nombre": "Ratchet inalámbrico", "marca": "ACDelco", "tipo": "Inalámbrico", "combustible": "Batería"},
    {"nombre": "Bolso con Herramientas", "marca": "Serbreka", "tipo": "Almacenamiento", "combustible": "N/A"},
    {"nombre": "Cepillo de barrer con pala", "marca": "Sin Marca", "tipo": "Logístico", "combustible": "N/A"},
    {"nombre": "Tornillos varios", "marca": "Sin Marca", "tipo": "Almacenamiento", "combustible": "N/A"},
    {"nombre": "Arnés de seguridad", "marca": "Sin Marca", "tipo": "Seguridad", "combustible": "N/A"},
    {"nombre": "Contenedor plástico", "marca": "Sin Marca", "tipo": "Almacenamiento", "combustible": "N/A"},
    {"nombre": "Careta para esmerilar", "marca": "Sin Marca", "tipo": "Seguridad", "combustible": "N/A"},
    {"nombre": "Extintor de fuego CO2", "marca": "Sin Marca", "tipo": "Seguridad", "combustible": "N/A"},
    {"nombre": "Reflectores con pedestal", "marca": "Sin Marca", "tipo": "Eléctrico", "combustible": "Cable 110V/220V"},
    {"nombre": "Guantes de alta tensión", "marca": "Sin Marca", "tipo": "Seguridad", "combustible": "N/A"},
    {"nombre": "Bolso de Herramientas varias", "marca": "Sin Marca", "tipo": "Almacenamiento", "combustible": "N/A"},
    {"nombre": "Cinta Métrica", "marca": "Sin Marca", "tipo": "Medición", "combustible": "N/A"},
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
            tipo=TipoHerramienta(h_data["tipo"]),
            combustible=h_data["combustible"],
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
            n_c = await seed_clientes(session)
        log.info("Seeded: %d personales, %d herramientas, %d clientes.", n_p, n_h, n_c)
        if n_p == 0 and n_h == 0 and n_c == 0:
            log.info("(Everything already present — nothing inserted.)")


if __name__ == "__main__":
    asyncio.run(main())
