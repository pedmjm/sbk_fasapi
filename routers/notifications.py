"""
Manual OneSignal push endpoint. Mirrors the uploaded `notifications.py`
template's `POST /notifications/send` route, plus a `/test/{id}` route
for quick sanity checks.

Automatic notifications are also fired from `routers/tareas.py` (on task
creation) and `routers/comentarios.py` (on comment creation) — this
router is for ad-hoc / manual pushes.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from auth import get_current_active_user
from models import User
from notifications import send_push_via_onesignal
from schemas import NotificationRequest

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/send")
async def send_notification(
    notif: NotificationRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    # Users can only send notifications to themselves unless they're admin.
    if current_user.id != notif.user_id and current_user.nivel < 2:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only send notifications to yourself",
        )
    return await send_push_via_onesignal(
        user_ids=[str(notif.user_id)],
        title=notif.title,
        message=notif.message,
        data=notif.data,
    )


@router.get("/test/{user_id}")
async def test_send(
    user_id: UUID,
    _current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Quick smoke-test endpoint. Sends a fixed message to the given user."""
    return await send_push_via_onesignal(
        user_ids=[str(user_id)],
        title="¡Hola desde SBK TaskManager!",
        message="Esta es una notificación de prueba.",
    )
