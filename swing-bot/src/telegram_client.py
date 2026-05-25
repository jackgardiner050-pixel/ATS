"""Swing Bot Telegram client — send-only, ringfenced from long-term agent's client.

Uses SWING_BOT_TOKEN and SWING_BOT_CHAT_ID from .env (never from shared env).
Never raises — returns False on any failure. Chunks messages at 4096 chars.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"
_MAX_CHUNK = 4096
_ENV_PATH = Path(__file__).parent.parent / ".env"


def _load_env() -> dict[str, str]:
    """Read key=value pairs from swing-bot/.env without external deps."""
    env: dict[str, str] = {}
    if not _ENV_PATH.exists():
        return env
    with open(_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def _credentials() -> tuple[str, str]:
    """Return (token, chat_id) from .env, falling back to process env."""
    env = _load_env()
    token = env.get("SWING_BOT_TOKEN") or os.environ.get("SWING_BOT_TOKEN", "")
    chat_id = env.get("SWING_BOT_CHAT_ID") or os.environ.get("SWING_BOT_CHAT_ID", "")
    if not token or not chat_id:
        raise ValueError("SWING_BOT_TOKEN and SWING_BOT_CHAT_ID must be set in swing-bot/.env")
    return token, chat_id


def _split(text: str) -> list[str]:
    """Split text into ≤4096-char chunks at newline boundaries where possible."""
    if len(text) <= _MAX_CHUNK:
        return [text]
    chunks = []
    while text:
        if len(text) <= _MAX_CHUNK:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, _MAX_CHUNK)
        if cut == -1:
            cut = _MAX_CHUNK
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


def send_message(text: str) -> bool:
    """Send a plain-text message to the swing bot channel.

    Returns True on success, False on any failure — never raises.
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
                log.warning("Swing Telegram API error %s: %s", resp.status_code, resp.text[:200])
                return False
        return True
    except ValueError as exc:
        log.warning("Swing Telegram credentials missing: %s", exc)
        return False
    except Exception as exc:
        log.warning("Swing Telegram send_message failed: %s", exc)
        return False
