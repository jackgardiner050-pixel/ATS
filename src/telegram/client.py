"""Telegram bot client — fire-and-forget message sender.

Credentials are loaded from environment variables TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID. Never reads from config files or source code.

Hard rules:
  no_real_orders         : True — this client sends text only, no trade execution
  graceful_failure       : True — network errors are logged, never propagated to caller
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"
_MAX_LENGTH = 4096  # Telegram hard limit per message


def _credentials() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in environment"
        )
    return token, chat_id


def send_message(text: str) -> bool:
    """Send a plain-text message to the configured chat.

    Returns True on success. On any failure (missing credentials, network
    error, API error) logs a warning and returns False — never raises.
    """
    try:
        token, chat_id = _credentials()
        for chunk in _split(text):
            url = f"{_TELEGRAM_API}/bot{token}/sendMessage"
            resp = requests.post(
                url,
                json={"chat_id": chat_id, "text": chunk},
                timeout=15,
            )
            if not resp.ok:
                log.warning("Telegram API error %s: %s", resp.status_code, resp.text[:200])
                return False
        return True
    except Exception as exc:
        log.warning("Telegram send_message failed: %s", exc)
        return False


def _split(text: str, limit: int = _MAX_LENGTH) -> list[str]:
    """Split text into chunks that fit within Telegram's per-message limit."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks
