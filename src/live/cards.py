"""Render an order intent as a compact Telegram order card. Pure — no I/O, no sending.

The card is a PROPOSAL. It carries the card_id and the exact reply syntax the human uses
after they place the order themselves. Sending is done by the script via
src.telegram.client.send_message; card generation never places an order.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass


def _d(intent) -> dict:
    return asdict(intent) if is_dataclass(intent) else dict(intent)


def render_card(intent) -> str:
    d = _d(intent)
    lg = d.get("limit_guidance")
    limit = f"£{float(lg):,.2f}" if lg else "your discretion (no limit guidance)"
    return (
        f"📋 ORDER CARD  [{d['card_id']}]   (E1 — you place this order)\n"
        f"{d['side']} {d['ticker']}   ~£{float(d['notional_gbp']):,.0f}\n"
        f"limit guidance: {limit}\n"
        f"rule: {d.get('source_rule', '?')}  ·  cohort: {d.get('cohort', '?')}\n"
        f"— PROPOSAL ONLY. No order has been placed. —\n"
        f"After you execute, reply:  /fill {d['card_id']} <price> <qty>"
    )


def render_batch(intents: list) -> str:
    if not intents:
        return "No admissible order cards this run."
    return f"\n\n{'─' * 28}\n\n".join(render_card(i) for i in intents)
