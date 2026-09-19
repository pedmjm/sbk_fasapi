# Flujo de Revisión (estado `en_revision`) — Tareas y Visitas

Nuevo paso intermedio entre `en_progreso` y el cierre final: **solo nivel 1 o superior puede enviar a revision, solo los revisores (nivel ≥ 2) cierran o devuelven.**
Incluye la gestión de imágenes de visitas (subir/eliminar solo con la
visita abierta).

**Migración:** `f2b8d1e6a4c9` (agrega `EN_REVISION` a los enums
`estado_tarea` y `estado_visita` en Postgres — ya aplicada).

---

## 1. Diagramas de estado

### Tareas

```text
pendiente ──iniciar──► en_progreso ──completar──► en_revision ──aprobar (nivel≥2)──► completada
    │                     ▲   │                      │                                  │
    │                     │   └──────────────────────┘                     reabrir (nivel≥2)
    │                     └────devolver (nivel≥2)──────┘                          │
    └──cancelar──► cancelada        (desde en_revision, cancelar solo nivel≥2)    ▼
                                                               (vuelve a en_revision)
```

### Visitas

```text
programada ──► en_progreso ──finalizar──► en_revision ──cerrar (nivel≥2)──► finalizada ──► informe opcional
                  ▲   │                      │                                   │
                  │   └──────────────────────┘                        reabrir (nivel≥2)
                  └────devolver (nivel≥2)──────┘                               │
   (desde en_revision, cancelar solo nivel≥2)                                    ▼
                                                                (vuelve a en_revision)
```

> **✅ SÍ se puede volver a revisar una actividad cerrada** (antes no se
> podía): `POST /tareas/{id}/reabrir` (desde `completada`) y
> `POST /visitas/{id}/reabrir` (desde `finalizada`) la devuelven a
> `en_revision`, y desde ahí se decide otra vez con `devolver` (abrir a
> en_progreso) o `aprobar`/`cerrar` (cerrar de nuevo). Requiere nivel ≥ 2;
> body opcional `{"motivo": "..."}` (notifica a creador+asignados). El
> informe de una visita reabierta permanece anclado (no se toca).

> **Cambió el significado de los botones existentes:**
> * `POST /tareas/{id}/completar` ya NO marca `completada` — ahora envía a
>   **`en_revision`**. Requiere nivel 1.
> * `POST /visitas/{id}/finalizar` ya NO marca `finalizada` — ahora envía a
>   **`en_revision`** (mismo body de incidencias/observaciones/detalles).
> * `finalizada` (visita) / `completada` (tarea) ahora SOLO las alcanza un
>   revisor al aprobar/cerrar.

---

## 2. Endpoints

### Envío a revisión (cualquier usuario autenticado nivel >0)

| Endpoint | Antes | Ahora |
|---|---|---|
| `POST /tareas/{id}/completar` | → `completada` (nivel ≥ 1) | → `en_revision` (cualquiera); debe estar `en_progreso` |
| `POST /visitas/{id}/finalizar` | → `finalizada` | → `en_revision`; mismo body `{incidencias?, observaciones?, detalles_tecnicos?}` |

Errores: `422` si el estado no es `en_progreso` (o ya está
en revisión/cerrada/cancelada).

### Revisión — SOLO nivel ≥ 2 (403 al resto)

| Endpoint | Qué hace | Desde → Hacia |
|---|---|---|
| `POST /tareas/{id}/aprobar` | Cierra la tarea | `en_revision` → `completada` |
| `POST /tareas/{id}/devolver` | Devuelve para edición. Body opcional `{"motivo": "..."}` | `en_revision` → `en_progreso` |
| `POST /tareas/{id}/reabrir` | Reabre una tarea ya cerrada. Body opcional `{"motivo": "..."}` | `completada` → `en_revision` |
| `POST /visitas/{id}/cerrar` | Cierra la visita | `en_revision` → `finalizada` |
| `POST /visitas/{id}/devolver` | Devuelve para edición. Body opcional `{"motivo": "..."}` | `en_revision` → `en_progreso` |
| `POST /visitas/{id}/reabrir` | Reabre una visita ya cerrada. Body opcional `{"motivo": "..."}` | `finalizada` → `en_revision` |

```bash
# técnico envía a revisión
curl -X POST "$BASE/tareas/$TAREA_ID/completar" -H "Authorization: Bearer $TEC"

# revisor devuelve (con motivo)
curl -X POST "$BASE/tareas/$TAREA_ID/devolver" \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"motivo": "Faltan fotos de evidencia"}'

# revisor cierra
curl -X POST "$BASE/visitas/$VISITA_ID/cerrar" -H "Authorization: Bearer $ADMIN"
```

---

## 3. Qué queda bloqueado en `en_revision`

El estado `en_revision` es **"cerrado con candado"**: nada se edita hasta
que un revisor la devuelva a `en_progreso`.

| Acción | en_revision | en_progreso |
|---|---|---|
| `PUT /tareas/{id}` (todo, incl. personal) | ❌ `422` | solo `personal_ids` |
| Agregar/eliminar pasos | ❌ `422` | ✅ (creador/admin) |
| Comentarios de paso | ❌ `422` (requiere en_progreso) | ✅ |
| `POST /visitas/{id}` (PUT edición) | ❌ `422` | ✅ |
| Subir/eliminar imágenes de visita | ❌ `422` | ✅ |
| Cancelar | solo nivel ≥ 2 | según reglas normales |
| Chat de la tarea | sigue abierto (lectura y escritura) | ✅ |
| Informe técnico (visita) | ❌ (requiere `finalizada`) | ❌ — solo tras `cerrar` |

> **Informe:** se genera únicamente sobre una visita `finalizada`, es
> decir, **después de que el revisor la cierre**.

---

## 4. Imágenes de visitas — subir Y eliminar (solo visita abierta)

**Abierta** = `programada` o `en_progreso`.

```
POST   /visitas/{visita_id}/imagenes            subir (multipart imagenes[])
DELETE /visitas/{visita_id}/imagenes/{imagen_id}  eliminar UNA imagen (fila + archivo)
```

* En `en_revision`/`finalizada`/`cancelada` ambas → `422` con mensaje:
  `"La visita está 'X': solo se pueden gestionar imágenes mientras esté
  abierta (programada/en_progreso)"`.
* El `imagen_id` sale del detalle de la visita (`imagenes[].id`).
* `DELETE` valida que la imagen pertenezca a esa visita (si no → `404`).

```bash
# subir
curl -X POST "$BASE/visitas/$VISITA_ID/imagenes" \
  -H "Authorization: Bearer $TOKEN" -F "imagenes=@foto.jpg"

# eliminar
curl -X DELETE "$BASE/visitas/$VISITA_ID/imagenes/$IMAGEN_ID" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 5. Notificaciones (best-effort)

| Evento | Quién recibe push | `action` |
|---|---|---|
| Tarea/Visita enviada a revisión | usuarios nivel ≥ 2 (sin el emisor) | `tarea.revision` / `visita.revision` |
| Tarea aprobada / Visita cerrada | creador + personal asignado | `tarea.aprobada` / `visita.cerrada` |
| Tarea/Visita devuelta | creador + personal asignado (con el motivo en el mensaje) | `tarea.devuelta` / `visita.devuelta` |

---

## 6. Ajustes para la UI (resumen)

| Pantalla | Cambio |
|---|---|
| Botón "Finalizar tarea/visita" | Sigue igual (mismo endpoint) pero ahora lleva a `en_revision` — mostrar estado "En revisión" |
| Detalle tarea/visita en `en_revision` | Ocultar edición: pasos, personal, imágenes, comentarios. Mostrar botones **Aprobar/Devolver** SOLO si `nivel >= 2` (con diálogo de motivo al devolver) |
| Detalle tarea `completada` / visita `finalizada` | Botón **"Reabrir a revisión"** para `nivel >= 2` (con motivo opcional) → vuelve a `en_revision` y reaparecen Aprobar/Devolver |
| Lista de pendientes de revisión (nuevo) | Filtrar `GET /tareas?...` / `GET /visitas?estado=en_revision` para el dashboard del revisor |
| Galería de imágenes de visita | Agregar botón eliminar (X) por miniatura → `DELETE /visitas/{id}/imagenes/{imagen_id}`; ocultar upload y delete si la visita no está abierta |
| "Informe técnico" de la visita | Habilitar solo con estado `finalizada` (post-cierre) |
| Fix incluido | `POST /tareas/{id}/cancelar` tenía un `NameError` (nunca cargaba la tarea) — corregido; ahora también valida estado |

---

## 7. Compatibilidad

* Datos existentes: ningún estado previo cambia; `en_revision` es un valor
  nuevo del enum (migración `f2b8d1e6a4c9` ya aplicada en Postgres).
* Tokens/usuarios: sin cambios.
* La UI que hoy usa `finalizar`/`completar` sigue funcionando (mismo
  método y path) — solo cambia el estado resultante y el mensaje.
