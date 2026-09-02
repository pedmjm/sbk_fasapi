# Gestión de Visitas + Informes Técnicos — How To Use

Nueva funcionalidad: **Visitas** (visitas técnicas programadas) e **Informes
Técnicos** (reporte generado a partir de una visita finalizada).

**Routers:** `routers/visitas.py` y `routers/informes.py`
**Migración:** `920487cf0ac1` (tablas `visitas` + `informes_tecnicos`)

> **Requires auth** — send `Authorization: Bearer <token>` on every call
> (get one from `POST /auth/login`).

---

## 1. El flujo (como en la UI)

```text
┌─────────────┐      ┌──────────────────┐      ┌──────────────────────┐
│  Generar     │      │  Visita realizada │      │ Informe técnico       │
│  visita      │ ───► │  y marcada como   │ ───► │ (OPCIONAL, anclado    │
│ (programada) │      │  FINALIZADA       │      │  1:1 a la visita)     │
└─────────────┘      └──────────────────┘      └──────────────────────┘
 POST /visitas        POST /visitas/{id}/       POST /visitas/{id}/informe
                      finalizar                  (solo si finalizada)
```

### Reglas de oro

| Regla | Error si no |
|---|---|
| El informe solo se genera sobre visitas **`finalizada`** | `422` |
| Una visita tiene **máximo un** informe (1:1) | `409` |
| No se edita una visita `finalizada`/`cancelada` (usar finalizar/cancelar) | `422` |
| No se finaliza una visita `cancelada`, ni se cancela una `finalizada` | `422` |
| `number` del informe lo asigna el servidor (`max+1`, sin padding) | — |

Estados de visita: `programada` → `en_progreso` (reservado) → `finalizada` /
`cancelada`.

---

## 2. Quick reference

### Visitas — `/visitas`

| Method | Endpoint | Qué hace |
|---|---|---|
| `GET` | `/visitas` | Lista (filtros: `?estado=&cliente_id=&personal_id=`) |
| `POST` | `/visitas` | Crear visita (estado = `programada`) |
| `GET` | `/visitas/{id}` | Detalle (cliente/sucursal/personal/imagenes/informe) |
| `PUT` | `/visitas/{id}` | Editar (solo si `programada`) |
| `POST` | `/visitas/{id}/finalizar` | Marcar finalizada + resultado de inspección |
| `POST` | `/visitas/{id}/cancelar` | Marcar cancelada |
| `POST` | `/visitas/{id}/imagenes` | Evidencias fotográficas (multipart) |
| `DELETE` | `/visitas/{id}` | Eliminar (+ limpia archivos; el informe cae en cascada) |

### Informes — anclados a la visita + listado global

| Method | Endpoint | Qué hace |
|---|---|---|
| `POST` | `/visitas/{visita_id}/informe` | **Generar** informe (visita `finalizada`) |
| `GET` | `/visitas/{visita_id}/informe` | El informe de esa visita |
| `PUT` | `/visitas/{visita_id}/informe` | Edición parcial |
| `DELETE` | `/visitas/{visita_id}/informe` | Eliminar informe |
| `GET` | `/informes` | Lista global (número descendente, con resumen de visita) |
| `GET` | `/informes/{number}` | Lookup por número secuencial (**sin padding**: `182`) |

---

## 3. Ejemplos (curl)

### 3.1 Crear visita

```bash
curl -X POST "$BASE/visitas" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "cliente_id": "…cliente-uuid…",
        "sucursal_id": "…sucursal-uuid…",        // opcional
        "personal_id": "…personal-uuid…",        // opcional: técnico asignado
        "fecha": "2026-09-05T14:30:00",
        "ubicacion": "Zona Industrial Sur, Galpón 5, Valencia",
        "descripcion": "Mantenimiento breaker principal",
        "telefono_contacto": "+58 241-5553322",
        "detalles_tecnicos": {                   // opcional, libre
          "Voltaje de Línea (V)": "440",
          "Temperatura Operativa (°C)": "62"
        }
      }'
```

Respuesta (`201`) — nota el `estado: "programada"`:

```json
{
  "status": "success",
  "message": "Visita creada exitosamente",
  "data": {
    "id": "…visita-uuid…",
    "cliente_id": "…",
    "sucursal_id": "…",
    "personal_id": "…",
    "creador_id": "…",
    "fecha": "2026-09-05T14:30:00Z",
    "ubicacion": "Zona Industrial Sur, Galpón 5, Valencia",
    "descripcion": "Mantenimiento breaker principal",
    "telefono_contacto": "+58 241-5553322",
    "estado": "programada",
    "detalles_tecnicos": { "Voltaje de Línea (V)": "440" },
    "incidencias": null,
    "observaciones": null,
    "cliente":    { "id": "…", "razon_social": "Industrial Valencia C.A.", "...": "…" },
    "sucursal":   { "id": "…", "nombre_sucursal": "Planta 2" },
    "personal":   { "id": "…", "nombre": "Juan Pérez", "cedula": "…" },
    "imagenes":   [],
    "informe":    null,
    "created_at": "2026-09-02T12:00:00Z",
    "updated_at": "2026-09-02T12:00:00Z"
  }
}
```

Si la visita tiene `personal_id`, el técnico asignado recibe push
(`action: "visita.created"`, agrupado en `visitas`).

### 3.2 Adjuntar evidencias fotográficas

```bash
curl -X POST "$BASE/visitas/$VISITA_ID/imagenes" \
  -H "Authorization: Bearer $TOKEN" \
  -F "imagenes=@panel_1.jpg" \
  -F "imagenes=@panel_2.jpg"
```

Los archivos viven en `storage/visitas/{visita_id}/` y se devuelven en el
campo `imagenes` (con `url` pública) del detalle.

### 3.3 Finalizar la visita (con el resultado de la inspección)

```bash
curl -X POST "$BASE/visitas/$VISITA_ID/finalizar" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "incidencias": "Breaker 3 con contactos carbonizados",
        "observaciones": "Se recomienda reemplazo de unidad de disparo",
        "detalles_tecnicos": {
          "Voltaje de Línea (V)": "440",
          "Amperaje de Consumo (A)": "310",
          "Temperatura Operativa (°C)": "78"
        }
      }'
```

Todos los campos del body son opcionales. `estado` pasa a `"finalizada"`.

Errores esperados:
* Visita `cancelada` → `422 "No se puede finalizar una visita cancelada"`
* Ya finalizada → `422 "La visita ya está finalizada"`

### 3.4 Generar el informe técnico (opcional)

```bash
curl -X POST "$BASE/visitas/$VISITA_ID/informe" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "titulo": "Informe de mantenimiento breaker principal",
        "orden_de_compra": "OC-2026-0451",
        "general_information": {
          "atencion": "Ing. María Rodríguez",
          "garantia": "6 meses"
        },
        "identificacion_del_equipo": {
          "equipo": "Breaker 480V",
          "marca": "Square D",
          "voltaje": "480V",
          "modelo": "Masterpact NW08",
          "tipo": "Tripol",
          "corriente": "800A",
          "unidad_de_disparo": "Micrologic 5.0",
          "alimenta": "Tablero TP-2",
          "categoria": "Categoria III"
        },
        "condiciones_del_equipo": {
          "camaras_de_extincion_de_arco": "Buenas",
          "contactos_fijos": "Carbonizados",
          "tornilleria_en_general": "Ajustada"
        },
        "pruebas_electricas": {
          "pruebas_de_resistencia_de_aislamiento_megger_test": {
            "voltaje_vdc": "1000",
            "mediciones": {
              "a_vs_b": ">9999 MΩ",
              "b_vs_c": ">9999 MΩ",
              "c_vs_a": ">9999 MΩ",
              "a_b_c_vs_tierra": ">9999 MΩ",
              "entrada_vs_salida": ">9999 MΩ",
              "salida_vs_entrada": ">9999 MΩ"
            }
          },
          "unidad_de_disparo_tipo": "Micrologic 5.0",
          "tipo_de_prueba": "Primaria",
          "valores_de_disparo": {
            "valor_teorico_long_delay": "0.8 x In",
            "valor_dejado": "0.8 x In",
            "simulacion_del_disparo_por_corto_circuito_short_delay": "OK",
            "tierra_ground": "OK"
          }
        },
        "observaciones": "Contactos fijos con carbonización avanzada.",
        "recomendaciones": "Reemplazo de unidad de disparo en próximo parada."
      }'
```

Respuesta (`201`) — estructura anidada idéntica a la plantilla del reporte,
más `id`/`number`/`visita_id`/`visita`:

```json
{
  "status": "success",
  "message": "Informe técnico generado",
  "data": {
    "id": "…informe-uuid…",
    "number": 1,
    "visita_id": "…visita-uuid…",
    "titulo": "Informe de mantenimiento breaker principal",
    "fecha_de_emision": "2026-09-02",
    "orden_de_compra": "OC-2026-0451",
    "lugar": "Zona Industrial Sur, Galpón 5, Valencia",
    "general_information": {
      "cliente": "Industrial Valencia C.A.",
      "atencion": "Ing. María Rodríguez",
      "fecha_de_ejecucion": "2026-09-05",
      "garantia": "6 meses"
    },
    "identificacion_del_equipo": { "…": "…" },
    "condiciones_del_equipo": { "…": "…" },
    "pruebas_electricas": { "…": "…" },
    "observaciones": "Contactos fijos con carbonización avanzada.",
    "recomendaciones": "Reemplazo de unidad de disparo en próximo parada.",
    "visita": {
      "id": "…visita-uuid…",
      "fecha": "2026-09-05T14:30:00Z",
      "estado": "finalizada",
      "ubicacion": "Zona Industrial Sur, Galpón 5, Valencia",
      "cliente": "Industrial Valencia C.A."
    },
    "created_at": "2026-09-02T15:00:00Z",
    "updated_at": "2026-09-02T15:00:00Z"
  }
}
```

#### Qué se auto-completa desde la visita (solo si el cliente NO lo envía)

| Campo del informe | Origen |
|---|---|
| `general_information.cliente` | `visita.cliente.razon_social` |
| `general_information.fecha_de_ejecucion` | fecha de la visita |
| `lugar` | `visita.ubicacion` |
| `fecha_de_emision` | hoy (fecha de generación) |
| `number` | `max(number) + 1` — **sin padding** |

> **Padding:** el servidor guarda `number` como Integer (ej. `182`).
> El cliente lo formatea para mostrar: `str(number).zfill(6)` → `"000182"`.

#### Errores esperados

| Caso | Respuesta |
|---|---|
| Visita no finalizada | `422 "No se puede generar el informe: la visita está 'programada' y debe estar 'finalizada'."` |
| Ya tiene informe | `409 "Esta visita ya tiene un informe técnico."` |
| Visita no existe | `404 "Visita no encontrada"` |

### 3.5 Editar el informe (parcial)

```bash
curl -X PUT "$BASE/visitas/$VISITA_ID/informe" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "titulo": "Informe de mantenimiento correctivo",
        "condiciones_del_equipo": {
          "contactos_fijos": "Reemplazados",
          "accesorios": "Buenos"
        }
      }'
```

Solo se tocan los campos enviados; **una sección enviada se reemplaza
completa** (los campos de esa sección no incluidos quedan `null`).
`number` y `visita_id` no son editables.

### 3.6 Consultas

```bash
# El informe de una visita
curl "$BASE/visitas/$VISITA_ID/informe" -H "Authorization: Bearer $TOKEN"

# Lista global de informes (number descendente)
curl "$BASE/informes" -H "Authorization: Bearer $TOKEN"

# Lookup por número (SIN padding)
curl "$BASE/informes/182" -H "Authorization: Bearer $TOKEN"

# Visitas filtradas
curl "$BASE/visitas?estado=programada&cliente_id=$CLIENTE_ID" -H "Authorization: Bearer $TOKEN"
```

En `GET /visitas` y `GET /visitas/{id}` el informe (si existe) viene anidado
en `informe`.

### 3.7 Eliminar

```bash
curl -X DELETE "$BASE/visitas/$VISITA_ID/informe" -H "Authorization: Bearer $TOKEN"  # solo el informe
curl -X DELETE "$BASE/visitas/$VISITA_ID" -H "Authorization: Bearer $TOKEN"          # visita + informe + imágenes
```

Al borrar la visita se eliminan sus imágenes (filas + archivos físicos) y el
informe cae por FK cascade.

---

## 4. Modelo de datos

```
Cliente 1─N Visita N─1 Personal (técnico asignado, opcional)
Sucursal 1─N Visita (opcional)
Visita 1─1 InformeTecnico  (UNIQUE visita_id — anclado a la visita)
Visita 1─N Imagen          (polimórfico: imageable_type = 'Visita')
```

* `visitas.estado`: enum `estado_visita` (`programada|en_progreso|finalizada|cancelada`)
* `visitas.detalles_tecnicos`: JSON libre (`{"Voltaje de Línea (V)": "440"}`)
* `informes_tecnicos`: columnas planas con prefijo por sección —
  `gen_*` (general_information), `eq_*` (identificación del equipo),
  `cond_*` (condiciones del equipo, 15 campos), `pr_*` (pruebas eléctricas:
  megger + mediciones + valores de disparo) — la API las expone anidadas
  exactamente como la plantilla JSON del reporte.
* `informes_tecnicos.number`: Integer UNIQUE, auto-incremental (max+1).

## 5. Notas de integración con la UI (Flet)

* El booleano `finalizado` del dummy de la app ↔ `estado == "finalizada"`.
* `visita_id` visual "Visita N° 123" puede usar los últimos 3 dígitos del
  UUID o el `number` del informe.
* Para el dropdown de clientes: `GET /clientes`; para técnicos:
  `GET /personal`.
* El borrador local (`.sbk_visita_draft.json`) sigue siendo responsabilidad
  del cliente; el API no guarda borradores de visitas.
