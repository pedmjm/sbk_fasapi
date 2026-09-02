"""
Chat por tarea — WebSocket en tiempo real + historial REST.

Cada tarea tiene su propia sala. Roles:
  * **Participante**: el creador de la tarea y los usuarios vinculados al
    personal asignado (por cédula). Pueden escribir.
  * **Espectador**: cualquier otro usuario autenticado. Solo lee
    (recibe historial y broadcast), no puede escribir y NUNCA recibe
    notificaciones push.

Notificaciones: cada mensaje dispara un push OneSignal a los
**participantes que NO están conectados a la sala en ese momento**
(exceptuando al autor). Los espectadores no reciben push.

Endpoints:
  WS  /ws/tareas/{tarea_id}?token=JWT     sala de chat en tiempo real
  GET /tareas/{tarea_id}/mensajes         historial (?limite=100)

Protocolo WS (JSON):
  server → cliente:
    {"type": "historial", "mensajes": [...]}          al conectar
    {"type": "usuario_conectado", "user_id", "name", "rol"}
    {"type": "usuario_desconectado", "user_id", "name"}
    {"type": "mensaje", "id", "tarea_id", "autor": {...},
     "contenido", "created_at"}
    {"type": "error", "detail": "..."}
  cliente → server:
    {"type": "mensaje", "contenido": "texto"}
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import ALGORITHM, SECRET_KEY, get_current_active_user
from database import async_session, get_db
from models import MensajeChat, Personal, Tarea, User
from notifications import notify_users
from schemas import Envelope, MensajeChatOut, UserOut

router = APIRouter(tags=["chat"])

HISTORIAL_DEFAULT = 100


# ─── Helpers ────────────────────────────────────────────────────────────────

def _serialize_mensaje(m: MensajeChat) -> dict:
    data = MensajeChatOut.model_validate(m).model_dump(mode="json")
    data["autor"] = UserOut.model_validate(m.autor).model_dump(mode="json")
    return data


async def _participantes_de_tarea(tarea: Tarea) -> set[uuid.UUID]:
    """User ids de los participantes: creador + usuarios vinculados al
    personal asignado (por cédula)."""
    ids = {tarea.creador_id}
    cedulas = [p.cedula for p in tarea.personal if p.cedula]
    if cedulas:
        async with async_session() as db:
            users = (
                await db.execute(select(User).where(User.cedula.in_(cedulas)))
            ).scalars().all()
            ids.update(u.id for u in users)
    return ids


async def _auth_ws_user(token: Optional[str]) -> Optional[User]:
    """Valida el JWT del query param manualmente (los WebSockets no pueden
    usar el header Authorization de los browsers). None → cerrar conexión."""
    if not token:
        return None
    try:
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = uuid.UUID(str(payload.get("sub")))
    except (InvalidTokenError, ValueError):
        return None

    async with async_session() as db:
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if user is None or user.disabled:
            return None
        # Token-version check (same rule as auth.get_current_user).
        ver = payload.get("ver", 0)
        if not isinstance(ver, int) or ver != user.token_version:
            return None
        return user


# ─── Connection manager ─────────────────────────────────────────────────────

class ChatConnectionManager:
    """Salas por tarea. Soporta múltiples conexiones por usuario
    (varias pestañas) y recuerda el rol de cada usuario en la sala."""

    def __init__(self) -> None:
        # tarea_id → user_id → set[WebSocket]
        self._rooms: dict[uuid.UUID, dict[uuid.UUID, set[WebSocket]]] = {}
        # tarea_id → user_id → rol ("participante" | "espectador")
        self._roles: dict[uuid.UUID, dict[uuid.UUID, str]] = {}

    async def connect(self, tarea_id: uuid.UUID, user: User, ws: WebSocket, rol: str) -> None:
        await ws.accept()
        self._rooms.setdefault(tarea_id, {}).setdefault(user.id, set()).add(ws)
        self._roles.setdefault(tarea_id, {})[user.id] = rol

    def disconnect(self, tarea_id: uuid.UUID, user_id: uuid.UUID, ws: WebSocket) -> bool:
        """Elimina la conexión. Devuelve True si el usuario sigue teniendo
        otras conexiones abiertas en la sala."""
        room = self._rooms.get(tarea_id)
        if not room:
            return False
        conns = room.get(user_id)
        if conns:
            conns.discard(ws)
            if not conns:
                room.pop(user_id, None)
                self._roles.get(tarea_id, {}).pop(user_id, None)
        if not room:
            self._rooms.pop(tarea_id, None)
            self._roles.pop(tarea_id, None)
        return user_id in room

    def rol(self, tarea_id: uuid.UUID, user_id: uuid.UUID) -> str:
        return self._roles.get(tarea_id, {}).get(user_id, "espectador")

    def connected_user_ids(self, tarea_id: uuid.UUID) -> set[uuid.UUID]:
        return set(self._rooms.get(tarea_id, {}).keys())

    def connected_participant_ids(self, tarea_id: uuid.UUID) -> set[uuid.UUID]:
        roles = self._roles.get(tarea_id, {})
        return {uid for uid in roles if roles[uid] == "participante"}

    async def broadcast(self, tarea_id: uuid.UUID, payload: dict) -> None:
        room = self._rooms.get(tarea_id, {})
        for conns in list(room.values()):
            for ws in list(conns):
                try:
                    await ws.send_json(payload)
                except Exception:
                    # Conexión muerta: se limpia en el finally del endpoint.
                    pass


manager = ChatConnectionManager()


# ─── REST: historial ────────────────────────────────────────────────────────

@router.get("/tareas/{tarea_id}/mensajes", response_model=Envelope)
async def list_mensajes(
    tarea_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    limite: int = Query(HISTORIAL_DEFAULT, ge=1, le=500),
):
    """Historial del chat de la tarea (asc). Los espectadores también
    pueden leerlo."""
    tarea = (
        await db.execute(select(Tarea).where(Tarea.id == tarea_id))
    ).scalar_one_or_none()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    mensajes = (
        await db.execute(
            select(MensajeChat)
            .options(selectinload(MensajeChat.autor))
            .where(MensajeChat.tarea_id == tarea_id)
            .order_by(MensajeChat.created_at.desc())
            .limit(limite)
        )
    ).scalars().all()
    # Últimos N en orden ascendente.
    return Envelope(data=[_serialize_mensaje(m) for m in reversed(mensajes)])


# ─── WebSocket: sala por tarea ──────────────────────────────────────────────

@router.websocket("/ws/tareas/{tarea_id}")
async def chat_tarea_ws(ws: WebSocket, tarea_id: uuid.UUID):
    token = ws.query_params.get("token")
    user = await _auth_ws_user(token)
    if user is None:
        await ws.close(code=4401)  # unauthorized
        return

    async with async_session() as db:
        tarea = (
            await db.execute(
                select(Tarea)
                .options(selectinload(Tarea.personal))
                .where(Tarea.id == tarea_id)
            )
        ).scalar_one_or_none()
    if tarea is None:
        await ws.close(code=4404)  # tarea no encontrada
        return

    participantes = await _participantes_de_tarea(tarea)
    rol = "participante" if user.id in participantes else "espectador"

    await manager.connect(tarea_id, user, ws, rol)

    # 1. Historial inicial al que entra.
    async with async_session() as db:
        mensajes = (
            await db.execute(
                select(MensajeChat)
                .options(selectinload(MensajeChat.autor))
                .where(MensajeChat.tarea_id == tarea_id)
                .order_by(MensajeChat.created_at.desc())
                .limit(HISTORIAL_DEFAULT)
            )
        ).scalars().all()
    await ws.send_json({
        "type": "historial",
        "rol": rol,
        "mensajes": [_serialize_mensaje(m) for m in reversed(mensajes)],
    })

    # 2. Avisar a la sala.
    await manager.broadcast(tarea_id, {
        "type": "usuario_conectado",
        "user_id": str(user.id),
        "name": user.name,
        "rol": rol,
    })

    try:
        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                await ws.send_json({"type": "error", "detail": "Mensaje debe ser JSON válido"})
                continue

            mtype = msg.get("type")

            if mtype != "mensaje":
                await ws.send_json({"type": "error", "detail": f"Tipo no soportado: {mtype!r}"})
                continue

            contenido = str(msg.get("contenido") or "").strip()
            if not contenido:
                await ws.send_json({"type": "error", "detail": "contenido vacío"})
                continue

            if rol != "participante":
                await ws.send_json({
                    "type": "error",
                    "detail": "Solo el creador y el personal asignado pueden escribir en este chat.",
                })
                continue

            # 3. Persistir.
            async with async_session() as db:
                m = MensajeChat(
                    tarea_id=tarea_id,
                    autor_id=user.id,
                    contenido=contenido,
                )
                db.add(m)
                await db.commit()
                await db.refresh(m, attribute_names=["autor"])

            payload = _serialize_mensaje(m)
            payload["type"] = "mensaje"

            # 4. Broadcast a TODOS (participantes y espectadores).
            await manager.broadcast(tarea_id, payload)

            # 5. OneSignal SOLO a participantes desconectados (sin el autor).
            conectados = manager.connected_participant_ids(tarea_id)
            destinatarios = {
                uid for uid in participantes
                if uid not in conectados and uid != user.id
            }
            if destinatarios:
                await notify_users(
                    destinatarios,
                    title=f"Chat: {tarea.titulo}",
                    message=f"{user.name}: {contenido[:80]}",
                    data={
                        "tarea_id": str(tarea_id),
                        "mensaje_id": str(m.id),
                        "action": "chat.message",
                    },
                    android_group=f"chat:{tarea_id}",
                    thread_id=f"chat:{tarea_id}",
                    name="chat.message",
                )
    except WebSocketDisconnect:
        pass
    finally:
        sigue_conectado = manager.disconnect(tarea_id, user.id, ws)
        # Solo anunciar desconexión cuando era su última conexión.
        if not sigue_conectado:
            await manager.broadcast(tarea_id, {
                "type": "usuario_desconectado",
                "user_id": str(user.id),
                "name": user.name,
            })
