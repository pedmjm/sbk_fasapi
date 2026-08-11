"""
OneSignal push-notification client + `notify_users` helper.

Mirrors the uploaded `notifications.py` template (single `send_push_via_onesignal`
function, async httpx client, 502-on-non-200 error wrapping) and adds:

  * `notify_users(user_ids, title, message, data)` — fan-out helper that
    batches multiple external_ids into a single OneSignal call. Used by
    `routers/tareas.py` and `routers/comentarios.py` to push notifications
    when a task is created or a comment is added.
  * `ONESIGNAL_ENABLED` toggle: when set to "0" (the default in local dev)
    the function logs the payload but does NOT call OneSignal, so you can
    develop without hitting the API.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable
from uuid import UUID

import httpx

logger = logging.getLogger("sbk.notifications")

ONESIGNAL_APP_ID = os.getenv("ONESIGNAL_APP_ID", "your-onesignal-app-id")
ONESIGNAL_REST_API_KEY = os.getenv("ONESIGNAL_REST_API_KEY", "your-rest-api-key")
ONESIGNAL_URL = "https://onesignal.com/api/v1/notifications"
# When disabled, payloads are logged but NOT sent. Defaults to disabled
# so local dev doesn't need real OneSignal credentials.
ONESIGNAL_ENABLED = os.getenv("ONESIGNAL_ENABLED", "0") == "1"


async def send_push_via_onesignal(
    user_ids: Iterable[str | UUID],
    title: str,
    message: str,
    data: dict | None = None,
) -> dict | None:
    """Send a push to one or more users (identified by their UUID as
    OneSignal `external_id`).

    Returns OneSignal's JSON response, or `None` if the call was skipped
    (ONESIGNAL_ENABLED=0). Raises `HTTPException(502)` if OneSignal
    returns a non-200 status.
    """
    external_ids = [str(uid) for uid in user_ids]
    if not external_ids:
        return None

    payload = {
        "app_id": ONESIGNAL_APP_ID,
        "headings": {"en": title},
        "contents": {"en": message},
        "target_channel": "push",
        "include_aliases": {"external_id": external_ids},
    }
    if data:
        payload["data"] = data

    headers = {
        "Authorization": ONESIGNAL_REST_API_KEY,
        "Content-Type": "application/json",
    }

    if not ONESIGNAL_ENABLED:
        logger.info(
            "[OneSignal DISABLED] Would send push: title=%r message=%r to=%s",
            title, message, external_ids,
        )
        return None

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(ONESIGNAL_URL, json=payload, headers=headers)
        if resp.status_code != 200:
            # Don't leak OneSignal's 401 as a FastAPI 401 — that would
            # confuse the client into thinking the user's auth failed.
            logger.error(
                "OneSignal error %s: %s", resp.status_code, resp.text
            )
            # Raise as a plain RuntimeError instead of HTTPException — the
            # caller (a router) can decide whether to surface this to the
            # user or just log it. Push failures shouldn't fail the API
            # request that triggered them.
            raise RuntimeError(
                f"OneSignal Error ({resp.status_code}): {resp.text}"
            )
        return resp.json()


async def notify_users(
    user_ids: Iterable[str | UUID],
    title: str,
    message: str,
    data: dict | None = None,
) -> None:
    """Best-effort push: logs and swallows errors so a notification
    failure never fails the parent API request.

    Use this from routers (tarea created, comment added, etc.).
    """
    try:
        await send_push_via_onesignal(user_ids, title, message, data)
    except Exception as exc:
        logger.warning("notify_users failed: %s", exc)
