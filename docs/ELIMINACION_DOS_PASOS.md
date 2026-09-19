# Eliminación en Dos Pasos (4 ojos) — Tareas y Visitas

Ningún admin puede eliminar una tarea/visita solo: **un admin la marca y
OTRO admin distinto confirma la eliminación** (principio de 4 ojos).

**Migración:** `a4c7e9f1b3d6` (ya aplicada) · **Routers:** `tareas.py`,
`visitas.py`

---

## 1. El flujo

```text
                    POST /marcar-eliminar (admin A, nivel ≥ 2)
  Tarea/Visita ────────────────────────────────────────────►  MARCADA  🚩
  (cualquier estado)                                             │
                                    ┌───────────────────────────┤
                                    │                           │
                    POST /desmarcar-eliminar        DELETE (admin B ≠ A,
                    (cualquier admin)                 nivel ≥ 2) confirma
                              │                           │
                              ▼                           ▼
                        de vuelta a la          🗑️ ELIMINADA de verdad
                        normalidad              (cleanup completo)
```

* **Marcar** no cambia el estado de flujo (`pendiente`, `en_progreso`,
  `en_revision`, `completada`… se conserva). Es una bandera ortogonal.
* Quien marcó **no puede** confirmar la eliminación → `403`.
* Al marcar, los demás admins reciben push:
  `"Tarea/Visita marcada para eliminar — requiere confirmación de otro
  administrador"` (`action: tarea.eliminar_marcada` /
  `visita.eliminar_marcada`).

## 2. Endpoints (todos nivel ≥ 2)

| Method | Endpoint | Qué hace |
|---|---|---|
| `POST` | `/tareas\|visitas/{id}/marcar-eliminar` | Marca 🚩 + notifica a los demás admins |
| `POST` | `/tareas\|visitas/{id}/desmarcar-eliminar` | Cancela la solicitud (cualquier admin) |
| `DELETE` | `/tareas\|visitas/{id}` | **Confirma** la eliminación (solo otro admin) |

### Respuestas de error exactas del DELETE

| Caso | Código | `detail` |
|---|---|---|
| Nivel < 2 | `403` | `Requires nivel >= 2` |
| Sin marcar | `422` | `La tarea/visita debe estar marcada para eliminar antes (POST .../marcar-eliminar)` |
| El mismo que marcó | `403` | `El administrador que marcó la tarea/visita no puede eliminarla — requiere confirmación de otro administrador` |

La eliminación real ejecuta el cleanup completo existente: tarea
(imágenes propias, de comentarios, de chat + pivots) / visita (imágenes +
informe en cascada).

## 3. Campos nuevos en los payloads

`GET /tareas`, `GET /tareas/{id}`, `GET /visitas`, `GET /visitas/{id}`
(listas y detalle, también los objetos anidados) ahora incluyen:

```json
{
  "…": "…",
  "eliminar_marcada": true,
  "eliminar_marcada_por_id": "…uuid del admin que marcó…"
}
```

`eliminar_marcada: false` + `eliminar_marcada_por_id: null` cuando no
está marcada. (Si la cuenta del marcador fue eliminada, el id queda
`null` pero la marca persiste — cualquier admin puede confirmar.)

## 4. Ajustes para la GUI

| Pantalla / componente | Cambio |
|---|---|
| Lista y detalle de tarea/visita | Badge 🚩 **"Marcada para eliminar"** cuando `eliminar_marcada == true` (mostrar quién marcó: cruzar `eliminar_marcada_por_id` con la lista de usuarios) |
| Menú admin (nivel ≥ 2) | Opción **"Marcar para eliminar"** → `POST .../marcar-eliminar` con confirmación ("Otro administrador deberá confirmar") |
| Elemento ya marcado — vista por OTRO admin | Botón **"Confirmar eliminación"** → `DELETE .../{id}` (diálogo fuerte: acción irreversible) + opción **"Cancelar solicitud"** → `POST .../desmarcar-eliminar` |
| Elemento ya marcado — vista del marcador | NO mostrar "Confirmar eliminación" (el server da 403); solo "Cancelar solicitud" |
| Cola de eliminación (opcional, dashboard admin) | Filtrar client-side la lista donde `eliminar_marcada == true` |
| Notificación push `*.eliminar_marcada` | Tocar → abrir la tarea/visita con el diálogo de confirmación |
| Delete directo (viejo botón) | Ya no existe para nivel < 2 ni sin marca — adaptar mensajes de error con los `detail` de la tabla |

## 5. Curl examples

```bash
# Admin A marca
curl -X POST "$BASE/tareas/$TAREA_ID/marcar-eliminar" -H "Authorization: Bearer $ADMIN_A"

# Admin A intenta borrar → 403
curl -X DELETE "$BASE/tareas/$TAREA_ID" -H "Authorization: Bearer $ADMIN_A"

# Admin B confirma → 200
curl -X DELETE "$BASE/tareas/$TAREA_ID" -H "Authorization: Bearer $ADMIN_B"

# Cancelar la solicitud
curl -X POST "$BASE/visitas/$VISITA_ID/desmarcar-eliminar" -H "Authorization: Bearer $ADMIN_A"
```
