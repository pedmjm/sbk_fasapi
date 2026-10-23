"""
Envío de emails transaccionales vía el SMTP de cPanel.

- Usa `smtplib` de la stdlib (sin dependencias nuevas).
- La función pública es `async` y ejecuta el envío en un threadpool
  (`run_in_threadpool`) para no bloquear el event loop de FastAPI.
- Soporta puerto 465 (SMTP_SSL) y 587/25 (STARTTLS).
- Si faltan credenciales o el servidor rechaza el envío, lanza
  `RuntimeError`; el caller decide cómo traducirlo (503, etc.).
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("sbk.email")


SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "SBK")
# Fuerza STARTTLS incluso si el puerto no es 587 (25, 2525, etc.)
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "0").strip().lower() in (
    "1", "true", "yes", "on",
)


def _send_blocking(to_email: str, subject: str, html_body: str) -> None:
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        raise RuntimeError(
            "SMTP no configurado: faltan SMTP_HOST / SMTP_USER / SMTP_PASSWORD"
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((SMTP_FROM_NAME, SMTP_USER))
    msg["To"] = to_email
    msg.set_content("Este correo requiere un cliente con soporte HTML.")
    msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()

    if SMTP_PORT == 465:
        # SSL directo (lo más común en cPanel).
        with smtplib.SMTP_SSL(
            SMTP_HOST, SMTP_PORT, context=context, timeout=20
        ) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    else:
        # STARTTLS (587 / 25).
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            if SMTP_USE_TLS or SMTP_PORT == 587:
                server.starttls(context=context)
                server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)


async def send_email_smtp(to_email: str, *, subject: str, html_body: str) -> None:
    """Envía un email HTML. Async-safe: el trabajo bloqueante corre en un
    thread del pool. Lanza RuntimeError si falla."""
    try:
        await run_in_threadpool(_send_blocking, to_email, subject, html_body)
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP auth rechazada para %s: %s", SMTP_USER, exc)
        raise RuntimeError(f"SMTP auth: {exc}") from exc
    except smtplib.SMTPException as exc:
        logger.error("SMTP error enviando a %s: %s", to_email, exc)
        raise RuntimeError(f"SMTP error: {exc}") from exc
    except Exception as exc:
        logger.error("Error enviando email a %s: %s", to_email, exc)
        raise