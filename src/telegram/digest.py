"""Weekly digest formatter — pure function, no I/O.

Formats screener results + paper book metrics into the weekly Telegram message.
Hard rule: never invents numbers — all figures come from the supplied data dicts.
"""
from __future__ import annotations

from typing import Optional


def _rev_sym(direction: Optional[str]) -> str:
    return {"POSITIVE": "▲", "NEGATIVE": "▼", "FLAT": "·"}.get(direction or "", "—")


def _mom_str(quintile: Optional[int]) -> str:
    return f"Q{quintile}" if quintile is not None else "—"


def _ret_str(ret: Optional[float]) -> str:
    if ret is None:
        return "?"
    return f"{ret*100:+.0f}%"


def format_digest(
    results: list[dict],
    paper_book: dict,
    changes: list[dict],
    today: str,
) -> str:
    """Build the weekly digest string.

    Args:
        results:    list of ticker dicts from summary.json
        paper_book: dict with keys n_open, n_closed, avg_unrealized_pct,
                    spy_return_pct, entry_date_first (all optional)
        changes:    list of {ticker, old_rating, new_rating, old_conf, new_conf}
        today:      ISO date string e.g. "2026-05-25"
    """
    lines: list[str] = []
    lines.append(f"📊 Weekly Screen — {today}")
    lines.append("")

    # ── STRONG_BUY (MED/HIGH) — act candidates ──────────────────────────────
    sb_med_high = [
        r for r in results
        if r.get("rating") == "STRONG_BUY"
        and r.get("confidence") in ("MED", "HIGH")
        and r.get("ok")
    ]
    sb_low = [
        r for r in results
        if r.get("rating") == "STRONG_BUY"
        and r.get("confidence") == "LOW"
        and r.get("ok")
    ]

    if sb_med_high:
        lines.append(f"🟢 STRONG_BUY (MED+) — Act candidates ({len(sb_med_high)}):")
        for r in sorted(sb_med_high, key=lambda x: -(x.get("expected_return") or 0)):
            pt = r.get("price_target") or 0
            ret = r.get("expected_return")
            conf = r.get("confidence", "?")
            mom = _mom_str(r.get("momentum_quintile"))
            rev = _rev_sym(r.get("revision_direction"))
            lines.append(
                f"  • {r['ticker']:<6} — PT ${pt:>5.0f} ({_ret_str(ret)}) — "
                f"Conf {conf} — Mom {mom}, Rev {rev}"
            )
        if sb_low:
            tickers = ", ".join(r["ticker"] for r in sb_low)
            lines.append(f"  ⚠️  LOW conf (excluded as candidates): {tickers}")
    else:
        lines.append("🟢 STRONG_BUY (MED+) — none this week")

    lines.append("")

    # ── BUY ─────────────────────────────────────────────────────────────────
    buy = [
        r for r in results
        if r.get("rating") == "BUY" and r.get("ok")
    ]
    if buy:
        names = ", ".join(r["ticker"] for r in sorted(buy, key=lambda x: x["ticker"]))
        lines.append(f"🟩 BUY — Positive lean ({len(buy)}): {names}")
        lines.append("")

    # ── HOLD ─────────────────────────────────────────────────────────────────
    hold = [r for r in results if r.get("rating") == "HOLD" and r.get("ok")]
    lines.append(f"🟡 HOLD — No action ({len(hold)} names) — /holds")

    # ── STRONG_SELL ──────────────────────────────────────────────────────────
    ss = [r for r in results if r.get("rating") in ("SELL", "STRONG_SELL") and r.get("ok")]
    ss_count = sum(1 for r in results if r.get("rating") == "STRONG_SELL" and r.get("ok"))
    sell_count = sum(1 for r in results if r.get("rating") == "SELL" and r.get("ok"))
    if ss_count or sell_count:
        lines.append(
            f"🔴 STRONG_SELL/SELL — Avoid / exit "
            f"({ss_count} SS, {sell_count} S) — /sells"
        )

    lines.append("")

    # ── Paper book ───────────────────────────────────────────────────────────
    n_open = paper_book.get("n_open", 0)
    n_closed = paper_book.get("n_closed", 0)
    avg_ret = paper_book.get("avg_unrealized_pct")
    spy_ret = paper_book.get("spy_return_pct")
    start_date = paper_book.get("entry_date_first", "—")

    if n_open and avg_ret is not None and spy_ret is not None:
        alpha = avg_ret - spy_ret
        lines.append(
            f"📈 Paper book: {n_open} open, {n_closed} closed | "
            f"avg ret {avg_ret*100:+.1f}% vs SPY {spy_ret*100:+.1f}% "
            f"(α {alpha*100:+.1f}%) since {start_date}"
        )
    else:
        lines.append(
            f"📈 Paper book: {n_open} open positions, {n_closed} closed — "
            f"use /portfolio for current marks"
        )

    lines.append("")

    # ── Rating changes ────────────────────────────────────────────────────────
    if changes:
        lines.append(f"🔔 Changes this week ({len(changes)}):")
        for c in changes:
            old = f"{c['old_rating']} {c['old_conf']}" if c.get("old_conf") else c.get("old_rating", "?")
            new = f"{c['new_rating']} {c['new_conf']}" if c.get("new_conf") else c.get("new_rating", "?")
            lines.append(f"  • {c['ticker']}: {old} → {new}")
    else:
        lines.append("🔔 Changes this week: none")

    lines.append("")
    lines.append("/help for commands")

    return "\n".join(lines)


def format_holds(results: list[dict]) -> str:
    """Format the /holds command response."""
    hold = [r for r in results if r.get("rating") == "HOLD" and r.get("ok")]
    if not hold:
        return "No HOLD names currently."
    lines = ["🟡 Current HOLDs:\n"]
    for r in sorted(hold, key=lambda x: -(x.get("expected_return") or 0)):
        pt = r.get("price_target") or 0
        conf = r.get("confidence", "?")
        ret = _ret_str(r.get("expected_return"))
        lines.append(f"  • {r['ticker']:<6} PT ${pt:>5.0f} ({ret}) [{conf}]")
    return "\n".join(lines)


def format_sells(results: list[dict]) -> str:
    """Format the /sells command response."""
    sells = [
        r for r in results
        if r.get("rating") in ("SELL", "STRONG_SELL") and r.get("ok")
    ]
    if not sells:
        return "No SELL / STRONG_SELL names currently."
    lines = ["🔴 Current SELL / STRONG_SELL:\n"]
    for r in sorted(sells, key=lambda x: x.get("expected_return") or 0):
        rating = r.get("rating", "?")
        conf = r.get("confidence", "?")
        ret = _ret_str(r.get("expected_return"))
        lines.append(f"  • {r['ticker']:<6} {rating:<13} ({ret}) [{conf}]")
    return "\n".join(lines)
