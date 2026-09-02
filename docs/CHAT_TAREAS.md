# Chat por Tarea (WebSocket) — How To Use

Cada tarea tiene su propia **sala de chat en tiempo real**. Los mensajes se
persisten (`chat_mensajes`) y cada mensaje genera una **notificación push
OneSignal** a los participantes que NO están conectados a la sala en ese
momento.

**Router:** `routers/chat.py` · **Tabla:** `chat_mensajes` · **Migración:** `d9c4e7f2a6b8`

---

## 1. Roles

| Rol | Quién | Puede escribir | Recibe historial/broadcast | Recibe push |
|---|---|---|---|---|
| **participante** | Creador de la tarea + usuarios vinculados al personal asignado (por cédula) | ✅ | ✅ | ✅ (solo si NO está conectado) |
| **espectador** | Cualquier otro usuario autenticado | ❌ (`error`) | ✅ | ❌ nunca |

---

## 2. Endpoints

### Historial REST

```
GET /tareas/{tarea_id}/mensajes?limite=100      (auth Bearer; límite 1..500)
```

Devuelve los últimos N mensajes en orden **ascendente** (listo para render):

```json
{ "status": "success", "data": [
    { "id": "…uuid…", "tarea_id": "…", "autor_id": "…",
      "contenido": "arrancando el trabajo",
      "created_at": "2026-09-02T15:04:05Z",
      "autor": { "id": "…", "name": "Juan Pérez", "email": "…", "nivel": 0 } }
] }
```

### WebSocket

```
WS /ws/tareas/{tarea_id}?token=<JWT>
```

* El token va en el **query param** (los browsers no permiten header
  Authorization en WebSocket).
* Token inválido / usuario desactivado / `token_version` desfasada →
  conexión cerrada con code **4401**. Tarea inexistente → **4404**.
* Se aceptan múltiples conexiones por usuario (varias pestañas); el
  anuncio de desconexión solo se emite al cerrar la última.

---

## 3. Protocolo (JSON)

### Servidor → Cliente

| type | Payload | Cuándo |
|---|---|---|
| `historial` | `{rol, mensajes: [...]}` | Al conectar (últimos 100) |
| `usuario_conectado` | `{user_id, name, rol}` | Alguien entra a la sala |
| `usuario_desconectado` | `{user_id, name}` | Alguien sale (última conexión) |
| `mensaje` | `{id, tarea_id, autor_id, autor, contenido, created_at}` | Nuevo mensaje |
| `error` | `{detail}` | Payload inválido / espectador intenta escribir |

### Cliente → Servidor

```json
{ "type": "mensaje", "contenido": "texto del mensaje" }
```

`contenido` vacío → `error`. Cualquier otro `type` → `error`.

---

## 4. Qué pasa con cada mensaje

```text
participante envía {"type":"mensaje","contenido":"…"}
  │
  ├─ 1. Se persiste en chat_mensajes (historial REST lo ve)
  ├─ 2. Broadcast {"type":"mensaje", …} a TODA la sala
  │     (participantes Y espectadores conectados)
  └─ 3. OneSignal → participantes NO conectados (sin el autor):
        title: "Chat: {titulo de la tarea}"
        message: "{autor.name}: {contenido[:80]}"
        data: {tarea_id, mensaje_id, action: "chat.message"}
        agrupado por hilo "chat:{tarea_id}"
```

Espectadores **nunca** reciben push. El autor nunca se auto-notifica.

---

## 5. Cliente de ejemplo (JavaScript / navegador)

```javascript
const tareaId = "…uuid…";
const token = localStorage.getItem("access_token");

const ws = new WebSocket(
  `wss://TU_DOMINIO/ws/tareas/${tareaId}?token=${token}`
);

ws.onopen = () => console.log("conectado a la sala");
ws.onclose = (e) => {
  if (e.code === 4401) alert("Sesión inválida — vuelve a iniciar sesión");
};

ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  switch (msg.type) {
    case "historial":          // al entrar: msg.rol dice si puedes escribir
      msg.mensajes.forEach(renderMensaje);
      setInputEnabled(msg.rol === "participante");
      break;
    case "mensaje":            // mensaje nuevo en tiempo real
      renderMensaje(msg);
      break;
    case "usuario_conectado":
    case "usuario_desconectado":
      mostrarPresencia(msg);   // opcional: "Juan se unió"
      break;
    case "error":
      toast(msg.detail);       // p.ej. espectador intentó escribir
      break;
  }
};

// Enviar (solo participante):
function enviar(texto) {
  ws.send(JSON.stringify({ type: "mensaje", contenido: texto }));
}
```

> **Reconexión:** el WS puede caerse (red, deploy). Re-conecta con backoff
> y usa `GET /tareas/{tarea_id}/mensajes` para re-sincronizar el historial.
> Al reconectar recibirás un `historial` fresco igual que al entrar.

### Nota sobre OneSignal

El push usa `notify_users()` (external_id = user id). Si el usuario recibe
la notificación y abre la app, la GUI debe navegar a la tarea usando
`data.tarea_id` (`action: "chat.message"`).

---

## 6. Modelo de datos

```
Tarea 1─N chat_mensajes   (FK CASCADE: al borrar la tarea se borra el chat)
User  1─N chat_mensajes   (autor)
```

```sql
chat_mensajes (
  id          UUID PK,
  tarea_id    UUID FK → tareas.id ON DELETE CASCADE (index),
  autor_id    UUID FK → users.id  ON DELETE CASCADE (index),
  contenido   TEXT NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT now()
)
```

No hay edición ni borrado de mensajes individuales (historial inmutable);
la sala muere con su tarea.
