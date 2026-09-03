"""
OneSignal push-notification client + `notify_users` helper.

Mirrors the uploaded `notifications.py` template (single `send_push_via_onesignal`
function, async httpx client, 502-on-non-200 error wrapping) and adds:

  * `notify_users(user_ids, title, message, data)` — fan-out helper that
    batches multiple external_ids into a single OneSignal call. Used by
    `routers/tareas.py` and `routers/pasos.py` to push notifications
    when a task is created or a paso comment is added.
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

ONESIGNAL_APP_ID = os.getenv("ONESIGNAL_APP_ID", "onesignal-id")
ONESIGNAL_REST_API_KEY = os.getenv("ONESIGNAL_REST_API_KEY", "api-key")
ONESIGNAL_URL = "https://api.onesignal.com/notifications"
# When disabled, payloads are logged but NOT sent. Defaults to disabled
# so local dev doesn't need real OneSignal credentials.
# NOTE: parsed as a real boolean — the old `os.getenv(...)` treated the
# string "0" as ENABLED (any non-empty string is truthy).
ONESIGNAL_ENABLED = os.getenv("ONESIGNAL_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")




async def send_push_via_onesignal(
    user_ids: Iterable[str | UUID],
    *,
    title: str,
    message: str,
    subtitle: str | None = None,
    data: dict | None = None,
    small_icon: str | None = None,
    large_icon: str | None = None,
    big_picture: str | None = None,
    buttons: list[dict[str, str]] | None = None,  # [{"id": "view", "text": "Ver tarea"}]
    android_group: str | None = None,
    thread_id: str | None = None,          # iOS grouping
    collapse_id: str | None = None,
    name: str | None = None,               # dashboard-only label, users never see it
    extra: dict | None = None,             # escape hatch for anything else
) -> dict | None:
    external_ids = [str(uid) for uid in user_ids]
    if not external_ids:
        return None

    if not (ONESIGNAL_ENABLED and ONESIGNAL_APP_ID and ONESIGNAL_REST_API_KEY):
        logger.warning("[OneSignal DISABLED] would send %r to %s", title, external_ids)
        return None

    payload: dict = {
        "app_id": ONESIGNAL_APP_ID,
        "headings": {"en": title, "es": title},
        "contents": {"en": message, "es": message},
        "target_channel": "push",
        "include_aliases": {"external_id": external_ids},
    }
    if subtitle:
        payload["subtitle"] = {"en": subtitle, "es": subtitle}
    if data:
        payload["custom_data"] = data   # ← new API name for the device payload
        payload["data"] = data          # harmless duplicate, protects against both behaviors
    if small_icon:
        payload["small_icon"] = small_icon
    if large_icon:
        payload["large_icon"] = large_icon
    if big_picture:
        payload["big_picture"] = big_picture
    if buttons:
        payload["buttons"] = buttons
    if android_group:
        payload["android_group"] = android_group
    if thread_id:
        payload["thread_id"] = thread_id
    if collapse_id:
        payload["collapse_id"] = collapse_id
    if name:
        payload["name"] = name
    if extra:
        payload.update(extra)

    headers = {
        "Authorization": f"Key {ONESIGNAL_REST_API_KEY}",   # ← new API scheme
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(ONESIGNAL_URL, params={"c": "push"}, json=payload, headers=headers)
    if resp.status_code >= 400:
        logger.error("OneSignal error %s: %s", resp.status_code, resp.text)
        raise RuntimeError(f"OneSignal Error ({resp.status_code}): {resp.text}")

    result = resp.json()
    logger.info("OneSignal ok: %s", result)   # shows recipients + invalid alias counts
    return result


async def notify_users(user_ids, *, title, message, **kwargs) -> None:
    try:
        await send_push_via_onesignal(user_ids, title=title, message=message, **kwargs)
    except Exception as exc:
        logger.warning("notify_users failed: %s", exc)
