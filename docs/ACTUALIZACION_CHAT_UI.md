# Actualización Chat UI — Cambios del Servidor (2026-09)

Documento para alinear la UI con los cambios del backend. Responde a los
cambios hechos en la app (CommentInputBox, burbujas con imágenes,
long-press → comentario, color por participante, pasos/personal editables).

**Archivos backend:** `routers/chat.py`, `routers/pasos.py`,
`routers/tareas.py`, `schemas.py`. **Sin migraciones** (no cambió la BD).

---

## 1. Mensajes con imágenes — `POST /tareas/{tarea_id}/mensajes/imagenes`

El WS sigue siendo **solo texto**; los mensajes con imágenes van por REST
 multipart:

```
POST /tareas/{tarea_id}/mensajes/imagenes     (auth Bearer)
  texto:    (opcional) texto del mensaje
  imagenes: (opcional) archivos jpg/png/webp, máx 5 MB c/u
```

```bash
curl -X POST "$BASE/tareas/$TAREA_ID/mensajes/imagenes" \
  -H "Authorization: Bearer $TOKEN" \
  -F "texto=Falla confirmada en el breaker 3" \
  -F "imagenes=@foto1.jpg" -F "imagenes=@foto2.jpg"
```

Reglas del servidor:
* Solo **participantes** (mismo check que el WS) → espectador recibe
  **`403`** `{"detail": "Solo el creador y el personal asignado pueden escribir en este chat."}`
* `texto` **o** `imagenes` (al menos uno) → si no, `422`.
* `contenido` queda **`""`** cuando el mensaje solo tiene imágenes.
* Archivos en `storage/chat/{mensaje_id}/`; filas en `imagenes`
  (`imageable_type='ChatMensaje'`).
* El servidor hace **broadcast a la sala WS** con el payload completo
  (con `imagenes`), así los clientes conectados lo ven en tiempo real
  **sin re-fetch**. También dispara OneSignal a participantes no
  conectados (mismo comportamiento que un mensaje de texto).

Respuesta (`201`) y payload del broadcast (idéntico + `"type": "mensaje"`):

```json
{
  "status": "success", "message": "Mensaje enviado",
  "data": {
    "id": "…uuid…", "tarea_id": "…", "autor_id": "…",
    "contenido": "Falla confirmada en el breaker 3",
    "created_at": "2026-09-02T20:15:00Z",
    "autor": { "id": "…", "name": "Juan Pérez", "…": "…" },
    "imagenes": [
      { "id": 41, "path": "chat/…/abc.jpg",
        "url": "https://APP/storage/chat/…/abc.jpg",
        "imageable_type": "ChatMensaje", "imageable_id": "…",
        "created_at": "…" }
    ],
    "color": "#E8F5E9"
  }
}
```

> **UI:** renderiza `mensaje['imagenes']` (campo `url`); caption =
> `contenido` (puede ser `""` → solo miniaturas).

---

## 2. Color de burbujas — calculado por el servidor

**Sin cambios de BD.** Todo payload de mensaje (WS, broadcast, historial,
REST) ahora incluye `"color": "#hex"` calculado determinísticamente:

```python
PALETA = ["#E3F2FD", "#F3E5F5", "#E8F5E9", "#FFF8E1",
          "#FFEBEE", "#E0F7FA", "#F1F8E9", "#EDE7F6"]
color = PALETA[autor_id.int % 8]     # UUID → entero → módulo 8
```

* La **misma paleta** debe estar en la UI (es la fallback que ya tienen:
  usa la del servidor si viene, si no esta misma fórmula/paleta).
* Estable por usuario en todos los clientes (mismo `autor_id` → mismo
  índice). Los 8 tonos son claros, aptos como fondo de burbuja con texto
  oscuro.

---

## 3. Payload actualizado de mensajes (WS + historial + REST)

`historial` y cada `mensaje` (WS y REST) ahora traen:

```json
{
  "id": "…", "tarea_id": "…", "autor_id": "…", "contenido": "…",
  "created_at": "…",
  "autor": { "id": "…", "name": "…", "email": "…", "foto_perfil": "…" },
  "imagenes": [ { "id": 41, "url": "…", "…": "…" } ],
  "color": "#E3F2FD"
}
```

* `imagenes: []` en mensajes de solo texto.
* `GET /tareas/{tarea_id}/mensajes?limite=100` — sin cambios, pero cada
  mensaje ahora incluye `imagenes` y `color` (batch-load server-side).

---

## 4. Cambiar personal con la tarea EN PROGRESO — ✅ permitido

`PUT /tareas/{tarea_id}` ahora acepta **solo** `personal_ids` cuando la
tarea está `en_progreso` (el PersonalPicker hace un PUT con el reemplazo
completo — exactamente lo que la UI ya hace):

```bash
curl -X PUT "$BASE/tareas/$TAREA_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"personal_ids": ["uuid1", "uuid2"]}'
```

| Estado de la tarea | PUT completo | PUT solo `personal_ids` |
|---|---|---|
| `pendiente` | ✅ | ✅ |
| `en_progreso` | ❌ `422 "Tarea en progreso: solo se puede modificar el personal asignado"` | ✅ |
| `completada` / `cancelada` | ❌ `422` | ❌ `422` |

> No hay (ni hace falta) un endpoint dedicado tipo `agregarHerramienta`:
  el PUT con `personal_ids` **reemplaza** la lista completa. Los usuarios
  que entren al chat tras el cambio obtienen su rol recalculado al
  conectarse (participante/espectador según la asignación vigente).

---

## 5. Pasos ON THE GO — ✅ permitidos (creador / admin)

`POST /pasos/{tarea_id}` y `DELETE /pasos/{tarea_id}/{paso_id}` ya **no
restringen por estado** — funcionan con la tarea `pendiente` o
`en_progreso`. Permiso:

| Quién | Puede agregar/eliminar pasos |
|---|---|
| Creador de la tarea | ✅ (en cualquier estado) |
| Usuario con nivel ≥ 2 (admin/super) | ✅ |
| Cualquier otro | ❌ `403 "Solo el creador de la tarea (o un admin) puede agregar/eliminar pasos."` |

* `DELETE` avisa implícitamente: borra el paso **y sus comentarios**
  (filas + archivos). La confirmación de la UI ya lo advierte.
* `PUT /pasos/{tarea_id}/{paso_id}` (toggle `completado`) sigue
  disponible para cualquier usuario autenticado — sin cambios.

---

## 6. Copia chat → comentario CON imágenes (`imagen_ids`)

`POST /pasos/{tarea_id}/{paso_id}/comentarios` acepta un campo nuevo junto
a `texto` y `imagenes[]`:

```
imagen_ids: '[41, 42]'   (form field; JSON lista de ids de Imagen existentes)
```

* Usa los `id` que vienen en `mensaje['imagenes'][i]['id']` del chat.
* El servidor crea filas `Imagen` nuevas para el comentario apuntando al
  **mismo archivo físico** — **sin duplicar en disco**.
* La respuesta incluye las imágenes del comentario (mismas URLs).
* Se puede enviar solo `imagen_ids`, solo archivos, solo texto, o
  combinaciones.

```bash
curl -X POST "$BASE/pasos/$TAREA_ID/$PASO_ID/comentarios" \
  -H "Authorization: Bearer $TOKEN" \
  -F "texto=Falla confirmada (copiado del chat)" \
  -F 'imagen_ids=[41, 42]'
```

Errores: `422 "Uno o más imagen_ids no existen."` si algún id es inválido.

> **Ciclo de vida del archivo compartido:** el archivo físico solo se
> borra cuando la última fila que lo referencia se elimina (comentario,
> mensaje de chat con su tarea, etc.). La UI no debe preocuparse por él.

---

## 7. Resumen de integración para la UI

| Cambio UI | Qué usar |
|---|---|
| CommentInputBox solo texto | WS `{"type":"mensaje","contenido":…}` (igual) |
| CommentInputBox con imágenes | `POST /tareas/{id}/mensajes/imagenes` (multipart) |
| Burbujas con imágenes | `mensaje['imagenes'][*]['url']`, caption = `contenido` |
| Color de burbuja | `mensaje['color']` del servidor; fallback = paleta de §2 |
| Long-press → comentario con fotos | `POST /pasos/{t}/{p}/comentarios` con `imagen_ids=[ids de mensaje['imagenes']]` + `texto` |
| PersonalPicker en tarea iniciada | `PUT /tareas/{id}` con `{"personal_ids": [...]}` (reemplazo completo) — ya no da 422 |
| Agregar/eliminar paso en progreso | `POST /pasos/{tareaId}` / `DELETE /pasos/{tareaId}/{pasoId}` — solo creador/admin (403 al resto) |
| Validación de rol antes de mostrar acciones | Sigue igual: participantes escriben, espectadores leen (el server responde 403/`error` si la UI no valida) |
