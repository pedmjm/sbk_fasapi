# Pasos & Paso Comments — How To Use

Comments now belong to **pasos** (steps), not to the tarea. Each paso gets its
own independent view in the GUI, so all paso endpoints live under
`/pasos/{tarea_id}/{paso_id}` in `routers/pasos.py`.

> **Requires auth** — send `Authorization: Bearer <token>` on every call
> (get one from `POST /auth/login`).

---

## 1. Quick reference

| Method | Endpoint | What it does |
|---|---|---|
| `POST` | `/pasos/{tarea_id}` | Add a paso to a tarea |
| `GET` | `/pasos/{tarea_id}/{paso_id}` | Full paso detail (comentarios + tarea summary) — **use this in the paso view** |
| `PUT` | `/pasos/{tarea_id}/{paso_id}` | Update a paso (toggle `completado`, edit fields) |
| `DELETE` | `/pasos/{tarea_id}/{paso_id}` | Delete a paso (cleans its comments + image files) |
| `GET` | `/pasos/{tarea_id}/{paso_id}/comentarios` | List the paso's comments (newest first) |
| `POST` | `/pasos/{tarea_id}/{paso_id}/comentarios` | **Add a comment** (tarea must be `en_progreso`) |
| `DELETE` | `/comentarios/{comentario_id}` | Delete a comment (author or admin) |

Pasos are **optional** — a tarea without pasos simply has `pasos: []`.
Tarea responses (`GET /tareas`, `GET /tareas/{id}`) now nest each paso's
comments inside it: `pasos[].comentarios[]` (there is no tarea-level
`comentarios` array anymore).

---

## 2. Typical flow

```text
1. GET  /tareas/{tarea_id}                 → read pasos[].id
2. POST /tareas/{tarea_id}/iniciar         → tarea becomes en_progreso
3. GET  /pasos/{tarea_id}/{paso_id}        → render the independent paso view
4. POST /pasos/{tarea_id}/{paso_id}/comentarios   (repeat per step)
5. PUT  /pasos/{tarea_id}/{paso_id}        → { "completado": true }
```

### ⚠️ The golden rule

> Comments can only be added while the tarea is **`en_progreso`**.
> `pendiente`, `completada` or `cancelada` → **422** with a clear message.

---

## 3. Examples (curl)

### Add a paso

```bash
curl -X POST "$BASE/pasos/$TAREA_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "actividad": "Revisar tablero eléctrico",
        "metodo": "Medir con multímetro",
        "requerimiento": "Guantes dieléctricos"
      }'
```

Response (`201`):

```json
{
  "status": "success",
  "message": "Paso agregado",
  "data": {
    "id": "…paso-uuid…",
    "tarea_id": "…tarea-uuid…",
    "actividad": "Revisar tablero eléctrico",
    "metodo": "Medir con multímetro",
    "requerimiento": "Guantes dieléctricos",
    "completado": false,
    "created_at": "2026-09-01T12:00:00Z",
    "comentarios": []
  }
}
```

### Get the independent paso view

```bash
curl "$BASE/pasos/$TAREA_ID/$PASO_ID" -H "Authorization: Bearer $TOKEN"
```

```json
{
  "status": "success",
  "data": {
    "id": "…paso-uuid…",
    "tarea_id": "…tarea-uuid…",
    "actividad": "Revisar tablero eléctrico",
    "completado": false,
    "created_at": "2026-09-01T12:00:00Z",
    "comentarios": [
      {
        "id": "…comentario-uuid…",
        "paso_id": "…paso-uuid…",
        "autor": { "id": "…", "name": "Juan Pérez" },
        "texto": "El tablero estaba corroido",
        "imagenes": [ { "id": 12, "url": "https://…/storage/comentarios/…/foto.jpg" } ]
      }
    ],
    "tarea": {
      "id": "…tarea-uuid…",
      "titulo": "Mantenimiento sucursal norte",
      "estado": "en_progreso",
      "cliente_id": "…",
      "sucursal_id": "…",
      "fecha_limite": "2026-09-05"
    }
  }
}
```

### Comment on a paso (text + images, multipart)

```bash
curl -X POST "$BASE/pasos/$TAREA_ID/$PASO_ID/comentarios" \
  -H "Authorization: Bearer $TOKEN" \
  -F "texto=Falla confirmada en el breaker 3" \
  -F "imagenes=@foto1.jpg" \
  -F "imagenes=@foto2.jpg"
```

* `texto` is optional, `imagenes[]` is optional — but at least one is required
  (otherwise `422`).
* While the tarea is **not** `en_progreso`:

  ```json
  { "detail": "No se puede comentar: la tarea está 'pendiente' y debe estar 'en_progreso'." }
  ```

* On success a OneSignal push goes to the tarea creator + assigned personal
  (everyone except the comment's author), with
  `data = { tarea_id, paso_id, comentario_id, action: "paso.comentario.created" }`.

### List a paso's comments

```bash
curl "$BASE/pasos/$TAREA_ID/$PASO_ID/comentarios" -H "Authorization: Bearer $TOKEN"
```

Newest first — ready to render top-down in a chat-like view.

### Mark a paso as completed

```bash
curl -X PUT "$BASE/pasos/$TAREA_ID/$PASO_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "completado": true }'
```

### Delete a comment

```bash
curl -X DELETE "$BASE/comentarios/$COMENTARIO_ID" -H "Authorization: Bearer $TOKEN"
```

Allowed for the comment's author or users with `nivel >= 2`; also removes the
comment's image files from disk.

---

## 4. Tarea responses (changed shape)

`GET /tareas` and `GET /tareas/{tarea_id}` — comments are nested per paso:

```json
{
  "pasos": [
    {
      "id": "…paso-uuid…",
      "actividad": "Revisar tablero eléctrico",
      "completado": true,
      "comentarios": [ { "id": "…", "texto": "…", "autor": {}, "imagenes": [] } ]
    }
  ]
}
```

The old top-level `comentarios: [...]` field on the tarea is **gone**.

---

## 5. Breaking changes (old → new)

| Old endpoint | New endpoint |
|---|---|
| `POST   /tareas/{tarea_id}/pasos` | `POST   /pasos/{tarea_id}` |
| `PUT    /tareas/{tarea_id}/pasos/{paso_id}` | `PUT    /pasos/{tarea_id}/{paso_id}` |
| `DELETE /tareas/{tarea_id}/pasos/{paso_id}` | `DELETE /pasos/{tarea_id}/{paso_id}` |
| `GET    /tareas/{tarea_id}/comentarios` | `GET    /pasos/{tarea_id}/{paso_id}/comentarios` |
| `POST   /tareas/{tarea_id}/comentarios` | `POST   /pasos/{tarea_id}/{paso_id}/comentarios` |
| `DELETE /comentarios/{comentario_id}` | *(unchanged)* |

* `routers/comentarios.py` was deleted; everything lives in `routers/pasos.py`.
* Tarea-level comments were **purged** by migration `b7e2c4d9f0a1`
  (`DELETE FROM comentarios` + their `imagenes` rows).
* `GET /pasos/{tarea_id}/{paso_id}` is new — built for the GUI's
  independent paso screen.

---

## 6. Data model recap

```
Tarea 1—N PasosTarea        (pasos are optional)
Paso  1—N Comentario        (NEW: comments hang off the paso)
Comentario.tarea_id         (kept, denormalized, for cascade cleanup +
                             notifications)
Comentario 1—N Imagen       (polymorphic: imageable_type = 'Comentario')
```

Deleting a paso or a tarea cascades to their comments, and the API also
deletes the comments' image rows + physical files (no orphans).
