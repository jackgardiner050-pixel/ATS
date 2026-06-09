#!/usr/bin/env python3
"""Static HTML dashboard generator for Olympus / ATS Research.

Reads all data sources and writes docs/index.html + docs/positions/{TICKER}.html.
No Plotly dependency — uses pure CSS/SVG charts.

Pantheon display names (rendered labels only — code/data paths unchanged):
  SCAI → Apollo (SCAI) · Hermes v2 → Athena · Hermes v3 → Hermes (execution)
  ATS → Themis · attribution → Mnemosyne · council → Zeus · Mercury → Kairos
  valuation → Demeter · crash → Hades

Usage:
  python scripts/generate_dashboard.py           # full run
  python scripts/generate_dashboard.py --dry-run # print file list only
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, date, timedelta, UTC
from pathlib import Path
from typing import Optional

import yaml

# Olympus display-layer — fail-soft; rest of dashboard still renders if unavailable
try:
    from _olympus import (
        kill_switch_card as _oly_kill_switch_card,
        status_banner as _oly_status_banner,
        olympus_lab_nav as _oly_lab_nav,
        pantheon_roster_section as _oly_roster,
        mnemosyne_independence_card as _oly_independence,
        mnemosyne_reconciliation_card as _oly_reconciliation,
        whats_this_intro as _oly_intro,
        honest_verdicts_leaderboard as _oly_verdicts,
        growth_v2_section as _oly_growth_v2,
    )
    _OLYMPUS_AVAILABLE = True
except Exception:
    _OLYMPUS_AVAILABLE = False
    def _oly_kill_switch_card(): return ""
    def _oly_status_banner(validated_count=None): return ""
    def _oly_lab_nav(): return ""
    def _oly_roster(): return ""
    def _oly_independence(): return ""
    def _oly_reconciliation(): return ""
    def _oly_intro(): return ""
    def _oly_verdicts(): return ""
    def _oly_growth_v2(): return ""

_ROOT = Path(__file__).parent.parent
_DOCS = _ROOT / "docs"
_POSITIONS_PATH = _ROOT / "data" / "paper_positions.yaml"
_TRADES_PATH = _ROOT / "data" / "paper_trades.jsonl"
_SIGNAL_LOG_PATH = _ROOT / "data" / "signal_log.jsonl"
_SCREEN_STATE_PATH = _ROOT / "data" / "screen_state.yaml"
_STATUS_PATH = _ROOT / "data" / "STATUS.txt"
_GOV_DIR = _ROOT / "data" / "governance"

COMPANY_NAMES: dict[str, str] = {
    "ACM": "AECOM", "AMAT": "Applied Materials", "DY": "Dycom Industries",
    "EMR": "Emerson Electric", "GD": "General Dynamics", "GNRC": "Generac Holdings",
    "HUBB": "Hubbell", "J": "Jacobs Solutions", "KMI": "Kinder Morgan",
    "LDOS": "Leidos Holdings", "SPGI": "S&P Global", "TRGP": "Targa Resources",
    "A": "Agilent", "ABBV": "AbbVie", "AGX": "Argan", "AME": "AMETEK",
    "AVAV": "AeroVironment", "CAT": "Caterpillar", "DHR": "Danaher",
    "DOV": "Dover", "EME": "EMCOR Group", "ENTG": "Entegris", "ETN": "Eaton",
    "EXP": "Eagle Materials", "FIX": "Comfort Systems", "FLR": "Fluor",
    "GE": "GE Aerospace", "HII": "HII", "HON": "Honeywell",
    "IDXX": "IDEXX Labs", "IESC": "IEC Electronics", "ISRG": "Intuitive Surgical",
    "ITW": "Illinois Tool Works", "KLAC": "KLA", "KTOS": "Kratos Defense",
    "LDOS": "Leidos", "LLY": "Eli Lilly", "LMT": "Lockheed Martin",
    "LRCX": "Lam Research", "MA": "Mastercard", "MA": "Mastercard",
    "MCO": "Moody's", "MLM": "Martin Marietta", "MOD": "Modine",
    "MSCI": "MSCI Inc", "MTD": "Mettler-Toledo", "MTZ": "MasTec",
    "NOC": "Northrop Grumman", "OKE": "ONEOK", "PH": "Parker Hannifin",
    "PRIM": "Primoris", "PWR": "Quanta Services", "ROK": "Rockwell Automation",
    "RTX": "RTX Corp", "SPGI": "S&P Global", "SPGI": "S&P Global",
    "STRL": "Sterling Infrastructure", "TT": "Trane Technologies",
    "TMO": "Thermo Fisher", "TRGP": "Targa Resources", "V": "Visa",
    "VMC": "Vulcan Materials", "VRT": "Vertiv", "WMB": "Williams Companies",
    "ZTS": "Zoetis",
}

REGIME_COLORS = {
    "risk_on_growth": "bar-blue",
    "disinflationary_expansion": "bar-green",
    "inflationary_cyclical": "bar-orange",
    "risk_off_defensive": "bar-grey",
    "high_volatility_stress": "bar-red",
    "liquidity_panic": "bar-red",
    "mean_reverting_chop": "bar-grey",
}

FACTOR_COLORS = {
    "power_buildout": "bar-blue",
    "ai_capex_cycle": "bar-purple",
    "us_defense_budget": "bar-teal",
    "us_infrastructure_spending": "bar-orange",
    "energy_transition": "bar-green",
    "industrial_cycle": "bar-grey",
    "rate_sensitive_growth": "bar-yellow",
}

THEME_COLORS = {
    "infrastructure_epc": "bar-blue",
    "electrical_industrial": "bar-purple",
    "power_generation": "bar-orange",
    "defense_government": "bar-teal",
    "semicap_equipment": "bar-green",
    "healthcare_tools": "bar-red",
    "energy_midstream": "bar-yellow",
    "industrial_diversified": "bar-grey",
    "financial_data": "bar-blue",
    "construction_materials": "bar-orange",
}


# ─── Data loaders ─────────────────────────────────────────────────────────────

def load_positions() -> list[dict]:
    if not _POSITIONS_PATH.exists():
        return []
    with open(_POSITIONS_PATH) as f:
        data = yaml.safe_load(f) or {}
    return data.get("positions", [])


def load_trades() -> list[dict]:
    if not _TRADES_PATH.exists():
        return []
    trades = []
    with open(_TRADES_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return trades


def load_status() -> str:
    if not _STATUS_PATH.exists():
        return ""
    return _STATUS_PATH.read_text().strip()


def load_screen_state() -> list[dict]:
    if not _SCREEN_STATE_PATH.exists():
        return []
    with open(_SCREEN_STATE_PATH) as f:
        data = yaml.safe_load(f) or {}
    return data.get("state", [])


def load_latest_governance(log_name: str) -> Optional[dict]:
    path = _GOV_DIR / log_name
    if not path.exists():
        return None
    last = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    last = json.loads(line)
                except json.JSONDecodeError:
                    pass
    return last


def load_recommendation(ticker: str) -> Optional[dict]:
    ticker_dir = _ROOT / "runs" / ticker
    if not ticker_dir.exists():
        return None
    runs = sorted(
        [d for d in ticker_dir.iterdir() if d.is_dir() and d.name[0].isdigit()],
        reverse=True,
    )
    for run in runs:
        rec_path = run / "recommendation.json"
        if rec_path.exists():
            try:
                with open(rec_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
    return None


# ─── Formatting helpers ───────────────────────────────────────────────────────

def fmt_pct(v: float, decimals: int = 1) -> str:
    return f"{v * 100:.{decimals}f}%"


def fmt_money(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:.1f}B" if abs(v) >= 1_000_000_000 else f"${v / 1_000_000:.1f}M"
    return f"${v:,.0f}"


def fmt_price(v: float) -> str:
    return f"${v:,.2f}"


def rating_badge(rating: str) -> str:
    cls = {
        "STRONG_BUY": "badge-sb",
        "BUY": "badge-b",
        "HOLD": "badge-h",
        "SELL": "badge-s",
        "STRONG_SELL": "badge-ss",
    }.get(rating, "badge-h")
    label = {
        "STRONG_BUY": "SB",
        "BUY": "B",
        "HOLD": "H",
        "SELL": "S",
        "STRONG_SELL": "SS",
    }.get(rating, rating[:2])
    return f'<span class="badge {cls}">{label}</span>'


def conf_badge(conf: str) -> str:
    cls = {"HIGH": "badge-high", "MED": "badge-med", "LOW": "badge-low"}.get(conf, "badge-h")
    return f'<span class="badge {cls}">{conf}</span>'


def bar_html(pct: float, color: str = "bar-blue", label: str = "", label_right: str = "") -> str:
    width = min(100, max(0, pct * 100))
    label_col = f'<span class="bar-label">{label}</span>' if label else ""
    value_col = f'<span class="bar-value">{label_right}</span>' if label_right else ""
    return (
        f'<div class="bar-row">'
        f'{label_col}'
        f'<div class="bar-track"><div class="bar-fill {color}" style="width:{width:.1f}%"></div></div>'
        f'{value_col}'
        f"</div>"
    )


def health_pill(label: str, status: str, tooltip: str = "") -> str:
    title = f' title="{tooltip}"' if tooltip else ""
    return f'<span class="health-pill {status}"{title}><span class="dot"></span>{label}</span>'


# ─── SVG Football Field ───────────────────────────────────────────────────────

def _football_field_svg(rec: dict) -> str:
    fn = rec.get("fixed_numbers", {})
    current_price = float(fn.get("current_price", rec.get("current_price", 0)))
    pt = float(fn.get("price_target_12m", rec.get("price_target_12m", 0)))

    dcf_gordon_range = fn.get("dcf_gordon_range", [])
    dcf_exit_range = fn.get("dcf_exit_range", [])
    comps_range = fn.get("comps_range", [])

    def safe_range(r):
        if r and len(r) >= 2:
            return float(min(r)), float(max(r))
        return None, None

    ranges = []
    if dcf_gordon_range and len(dcf_gordon_range) >= 2:
        lo, hi = safe_range(dcf_gordon_range)
        if lo and hi:
            ranges.append(("DCF Gordon", lo, hi, "#0d6efd"))
    if dcf_exit_range and len(dcf_exit_range) >= 2:
        lo, hi = safe_range(dcf_exit_range)
        if lo and hi:
            ranges.append(("DCF Exit", lo, hi, "#198754"))
    if comps_range and len(comps_range) >= 2:
        lo, hi = safe_range(comps_range)
        if lo and hi:
            ranges.append(("Comps", lo, hi, "#fd7e14"))

    if not ranges or current_price <= 0:
        return "<p style='color:#6c757d;font-style:italic;font-size:0.82rem'>Valuation data unavailable</p>"

    all_values = [current_price, pt] + [v for _, lo, hi, _ in ranges for v in (lo, hi)]
    x_min = 0.0
    x_max = max(all_values) * 1.15

    W, H = 720, 40 + len(ranges) * 48 + 60
    row_h = 40
    row_start_y = 30

    def x_px(v: float) -> float:
        return 60 + (v - x_min) / (x_max - x_min) * (W - 80)

    svg_parts = [
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="font-family:-apple-system,sans-serif">',
        f'<rect width="{W}" height="{H}" fill="#f8f9fa" rx="6"/>',
    ]

    # Row backgrounds and bars
    for i, (name, lo, hi, color) in enumerate(ranges):
        y = row_start_y + i * (row_h + 8)
        x0 = x_px(lo)
        x1 = x_px(hi)
        bar_w = max(x1 - x0, 4)

        # Row label
        svg_parts.append(
            f'<text x="55" y="{y + row_h // 2 + 4}" text-anchor="end" '
            f'font-size="11" fill="#495057" font-weight="600">{name}</text>'
        )
        # Track
        svg_parts.append(
            f'<rect x="{x_px(x_min)}" y="{y + 8}" width="{x_px(x_max) - x_px(x_min):.1f}" '
            f'height="{row_h - 16}" fill="#e9ecef" rx="4"/>'
        )
        # Range bar
        svg_parts.append(
            f'<rect x="{x0:.1f}" y="{y + 8}" width="{bar_w:.1f}" '
            f'height="{row_h - 16}" fill="{color}" opacity="0.75" rx="4"/>'
        )
        # Lo/Hi labels
        svg_parts.append(
            f'<text x="{x0:.1f}" y="{y + row_h + 2}" text-anchor="middle" '
            f'font-size="9" fill="#6c757d">${lo:,.0f}</text>'
        )
        svg_parts.append(
            f'<text x="{x1:.1f}" y="{y + row_h + 2}" text-anchor="middle" '
            f'font-size="9" fill="#6c757d">${hi:,.0f}</text>'
        )

    axis_y = row_start_y + len(ranges) * (row_h + 8) + 10

    # Current price line
    cpx = x_px(current_price)
    svg_parts.append(
        f'<line x1="{cpx:.1f}" y1="{row_start_y - 5}" x2="{cpx:.1f}" y2="{axis_y}" '
        f'stroke="#212529" stroke-width="2" stroke-dasharray="4,2"/>'
    )
    svg_parts.append(
        f'<text x="{cpx:.1f}" y="{row_start_y - 8}" text-anchor="middle" '
        f'font-size="10" fill="#212529" font-weight="700">Now ${current_price:,.2f}</text>'
    )

    # Price target line
    if pt > 0 and pt != current_price:
        ptx = x_px(pt)
        pt_color = "#198754" if pt > current_price else "#dc3545"
        svg_parts.append(
            f'<line x1="{ptx:.1f}" y1="{row_start_y - 5}" x2="{ptx:.1f}" y2="{axis_y}" '
            f'stroke="{pt_color}" stroke-width="2"/>'
        )
        svg_parts.append(
            f'<text x="{ptx:.1f}" y="{axis_y + 14}" text-anchor="middle" '
            f'font-size="10" fill="{pt_color}" font-weight="700">PT ${pt:,.0f}</text>'
        )

    # X axis
    svg_parts.append(
        f'<line x1="{x_px(x_min):.1f}" y1="{axis_y}" x2="{x_px(x_max):.1f}" y2="{axis_y}" '
        f'stroke="#dee2e6" stroke-width="1"/>'
    )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


# ─── Page templates ───────────────────────────────────────────────────────────

def _page_header(title: str, subtitle: str = "", back: bool = False) -> str:
    back_html = ""
    if back:
        back_html = '<a href="../index.html" class="back-link">← Back to dashboard</a>'
    return f"""
<header class="page-header">
  <div class="container">
    <h1>{title}</h1>
    {f'<span class="subtitle">{subtitle}</span>' if subtitle else ""}
    {back_html}
  </div>
</header>"""


def _page_wrap(title: str, body: str, depth: int = 0) -> str:
    css_path = ("../assets/style.css" if depth > 0 else "assets/style.css")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="robots" content="noindex,nofollow">
  <title>{title} — Olympus</title>
  <link rel="stylesheet" href="{css_path}">
</head>
<body>
{body}
</body>
</html>"""


# ─── Section renderers ────────────────────────────────────────────────────────

def _health_bar(
    positions: list[dict],
    regime: Optional[dict],
    exposure: Optional[dict],
    signal: Optional[dict],
    last_run: str,
) -> str:
    pills = []

    # Positions
    n = len(positions)
    pills.append(health_pill(f"{n} Positions", "blue"))

    # Regime
    if regime:
        r = regime.get("leading_regime", "unknown").replace("_", " ").title()
        conf = regime.get("confidence", 0)
        status = "green" if conf >= 0.5 else "yellow"
        pills.append(health_pill(f"Regime: {r}", status, f"{fmt_pct(conf)} confidence"))
    else:
        pills.append(health_pill("Regime: N/A", "yellow"))

    # Exposure warnings
    if exposure:
        warnings = exposure.get("warnings", [])
        violations = [w for w in warnings if "[VIOLATION]" in w]
        watches = [w for w in warnings if "[WATCH]" in w]
        if violations:
            pills.append(health_pill(f"{len(violations)} Violations", "red"))
        elif watches:
            pills.append(health_pill(f"{len(watches)} Watches", "yellow"))
        else:
            pills.append(health_pill("Exposure OK", "green"))

    # Signal quality
    if signal:
        any_decay = signal.get("any_decay_warning", False)
        pills.append(health_pill("Signal Decay" if any_decay else "Signals OK", "yellow" if any_decay else "green"))

    pills_html = "\n".join(f"  {p}" for p in pills)
    last_run_html = f'<span class="health-last-run">Last run: {last_run}</span>' if last_run else ""

    return f"""
<div class="health-bar">
  <div class="container">
{pills_html}
{last_run_html}
  </div>
</div>"""


def _fetch_live_prices(tickers: list[str]) -> dict[str, float]:
    """Download latest close prices for tickers via yfinance. Returns {} on any failure."""
    try:
        import yfinance as yf
        data = yf.download(tickers, period="1d", progress=False, auto_adjust=True)
        prices: dict[str, float] = {}
        if "Close" in data:
            close = data["Close"].iloc[-1]
            for t in tickers:
                try:
                    v = float(close[t])
                    if not math.isnan(v):
                        prices[t] = v
                except (KeyError, TypeError, ValueError):
                    pass
        return prices
    except Exception:
        return {}


def _perf_banner(positions: list[dict], prices: dict[str, float]) -> str:
    """Top-of-page performance banner: portfolio return vs SPY, two equal side-by-side cards."""
    if not positions:
        return ""

    spy_entry = 745.64
    port_return: Optional[float] = None
    spy_return: Optional[float] = None

    returns = []
    for p in positions:
        t = p.get("ticker", "")
        entry = float(p.get("entry_price", 0))
        if t in prices and entry > 0:
            returns.append((prices[t] - entry) / entry)
    if returns:
        port_return = sum(returns) / len(returns)
    if "SPY" in prices:
        spy_return = (prices["SPY"] - spy_entry) / spy_entry
    qqq_return: Optional[float] = None
    try:
        import json as _j
        _qe = _j.loads((_DOCS / "data" / "ats_live.json").read_text()).get("qqq_entry_price")
        if "QQQ" in prices and _qe:
            qqq_return = (prices["QQQ"] - _qe) / _qe
    except Exception:
        pass

    def _card(value: Optional[float], label: str, elem_id: str = "") -> str:
        if value is None:
            val_str, val_color = "—", "var(--text-muted)"
        else:
            sign = "+" if value >= 0 else ""
            val_str = f"{sign}{value * 100:.1f}%"
            val_color = "var(--green)" if value >= 0 else "var(--red)"
        id_attr = f' id="{elem_id}"' if elem_id else ""
        return (
            f'<div class="card stat-card" style="text-align:center">'
            f'<div class="stat-value"{id_attr} style="color:{val_color};font-size:2rem">{val_str}</div>'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-sub">since 25 May 2026</div>'
            f"</div>"
        )

    if port_return is not None and spy_return is not None:
        alpha = port_return - spy_return
        sign = "+" if alpha >= 0 else ""
        alpha_color = "var(--green)" if alpha >= 0 else "var(--red)"
        alpha_html = (
            f'<div id="live-alpha-value" style="text-align:center;margin-top:0.5rem;font-size:0.9rem;'
            f'color:{alpha_color};font-weight:600">Alpha: {sign}{alpha * 100:.1f}%</div>'
        )
    else:
        alpha_html = ""

    return (
        f'<div class="container" style="padding-top:1rem">'
        f'<div class="card-grid">'
        f"{_card(port_return, 'Portfolio Return', 'live-port-return')}"
        f"{_card(spy_return, 'SPY Return', 'live-spy-return')}"
        f"{_card(qqq_return, 'QQQ Return', 'live-qqq-return')}"
        f"</div>"
        f"{alpha_html}"
        f"</div>"
    )


def _themis_meta(positions: list[dict]) -> dict:
    """Honestly derive the shared entry-call labels from the data (no hardcoding)."""
    ratings = {p.get("entry_rating", "") for p in positions}
    confs = {p.get("entry_confidence", "") for p in positions}
    entry_dates = {p.get("entry_date", "") for p in positions}
    entry_date = sorted(entry_dates)[0] if entry_dates else ""
    days_held = 0
    try:
        days_held = (date.today() - date.fromisoformat(entry_date)).days
    except (ValueError, TypeError):
        pass
    one = lambda s: next(iter(s)) if len(s) == 1 else "mixed"
    nice = ""
    try:
        nice = date.fromisoformat(entry_date).strftime("%-d %b %Y")
    except (ValueError, TypeError):
        nice = entry_date
    return {"rating": one(ratings).replace("_", " "), "conf": one(confs),
            "entry_date": entry_date, "entry_date_nice": nice, "days_held": days_held,
            "uniform": len(ratings) == 1 and len(confs) == 1 and len(entry_dates) == 1}


def _themis_scorecard_note(positions: list[dict]) -> str:
    """Narrative that explains the section: what these are, who rated them, when, how held, vs what.

    Makes the honesty explicit: the ratings are the ORIGINAL entry calls (a fixed scorecard, not
    re-rated); only the prices/returns below refresh live. Days-held is computed client-side so it
    cannot silently freeze between dashboard rebuilds.
    """
    if not positions:
        return ""
    m = _themis_meta(positions)
    n = len(positions)
    rc = (f"all <b>rated {m['rating']} · {m['conf']} confidence</b>" if m["uniform"]
          else "rated per the table below")
    return f"""
<div class="card" style="margin-bottom:0.75rem;font-size:0.82rem;line-height:1.5">
  <b>Themis (ATS) paper book.</b> {n} equal-weight positions, {rc} by the Themis governance
  model on <b>{m['entry_date_nice']}</b>. These are the <b>original entry calls — a fixed
  scorecard, not re-rated.</b> The returns below are <b>live since entry</b> (prices refresh every
  5&nbsp;min during market hours); the <b>ratings and date do not change</b>, so the call stays
  honest. Held <b><span id="themis-days-held" data-entry-date="{m['entry_date']}">{m['days_held']}</span>
  days</b> · benchmark <b>SPY</b> (return-since-entry vs SPY shown in the banner above).
  <span style="color:var(--text-muted)">Paper-only · diagnostic.</span>
</div>
<script>(function(){{
  function upd(){{
    /* keep every days-held counter current regardless of when the page was last rebuilt */
    document.querySelectorAll('[data-entry-date]').forEach(function(el){{
      var ed=el.getAttribute('data-entry-date');if(!ed)return;
      var d=Math.floor((Date.now()-new Date(ed+'T00:00:00Z').getTime())/86400000);
      if(d>=0)el.textContent=d;
    }});
  }}
  if(document.readyState!=='loading')upd();else document.addEventListener('DOMContentLoaded',upd);
}})();</script>"""


def _position_returns_chart(positions: list[dict], prices: dict[str, float]) -> str:
    """Sorted horizontal bar chart: current % return per position, best at top."""
    if not positions or not prices:
        return ""

    rows: list[tuple[str, float]] = []
    for p in positions:
        t = p.get("ticker", "")
        entry = float(p.get("entry_price", 0))
        if t in prices and entry > 0:
            rows.append((t, (prices[t] - entry) / entry))

    if not rows:
        return ""

    rows.sort(key=lambda x: x[1], reverse=True)

    _BAR_SCALE = 0.30  # 30% return maps to full bar width
    bar_rows = []
    for ticker, ret in rows:
        bar_w = min(100.0, abs(ret) / _BAR_SCALE * 100)
        bar_cls = "bar-green" if ret >= 0 else "bar-red"
        val_color = "var(--green)" if ret >= 0 else "var(--red)"
        sign = "+" if ret >= 0 else ""
        bar_rows.append(
            f'<div class="bar-row">'
            f'<span class="bar-label-sm">'
            f'<a href="positions/{ticker}.html" class="ticker-link">{ticker}</a>'
            f'</span>'
            f'<div class="bar-track">'
            f'<div id="pos-fill-{ticker}" class="bar-fill {bar_cls}" style="width:{bar_w:.1f}%"></div>'
            f'</div>'
            f'<span id="pos-val-{ticker}" class="bar-value" style="color:{val_color}">{sign}{ret * 100:.1f}%</span>'
            f'</div>'
        )

    return f"""
<section>
  <h2 class="section-title">Position Returns</h2>
  {_themis_scorecard_note(positions)}
  <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.4rem">
    Live return since entry · sorted best-first · rating fixed at entry (see note)
  </div>
  <div class="card">
    {"".join(bar_rows)}
  </div>
</section>"""


def _portfolio_overview(positions: list[dict], trades: list[dict]) -> str:
    if not positions:
        return '<section><h2 class="section-title">Portfolio Overview</h2><div class="card"><p style="color:var(--text-muted)">No open positions.</p></div></section>'

    entry_date = positions[0].get("entry_date", "N/A")
    today = date.today()
    try:
        ed = date.fromisoformat(entry_date)
        days_held = (today - ed).days
    except (ValueError, TypeError):
        days_held = 0

    n_pos = len(positions)
    n_closed = len(trades)
    spy_entry = positions[0].get("spy_entry_price", 0)

    # Implied upside bars
    upsides = []
    for p in positions:
        ticker = p.get("ticker", "")
        ep = float(p.get("entry_price", 0))
        pt = float(p.get("price_target", 0))
        if ep > 0 and pt > 0:
            upside = (pt - ep) / ep
            upsides.append((ticker, upside, ep, pt))
    upsides.sort(key=lambda x: x[1], reverse=True)

    max_upside = max((u for _, u, _, _ in upsides), default=1.0)
    upside_rows = []
    for ticker, upside, ep, pt in upsides:
        bar_w = min(100, upside / max(max_upside, 0.01) * 100)
        color = "bar-blue" if upside >= 0 else "bar-red"
        upside_rows.append(
            f'<div class="bar-row">'
            f'<span class="bar-label-sm"><a href="positions/{ticker}.html" class="ticker-link">{ticker}</a></span>'
            f'<div class="bar-track"><div class="bar-fill {color}" style="width:{bar_w:.1f}%"></div></div>'
            f'<span class="bar-value">{fmt_pct(upside)}</span>'
            f"</div>"
        )

    stats_html = f"""
<div class="card-grid" style="margin-bottom:1rem">
  <div class="card stat-card">
    <div class="stat-value">{n_pos}</div>
    <div class="stat-label">Open Positions</div>
    <div class="stat-sub">Rated STRONG_BUY · MED on {entry_date} (entry calls — fixed)</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">{n_closed}</div>
    <div class="stat-label">Closed Trades</div>
    <div class="stat-sub">Performance pending</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value"><span id="ov-days-held" data-entry-date="{entry_date}">{days_held}</span>d</div>
    <div class="stat-label">Days Held</div>
    <div class="stat-sub">Since {entry_date} · updates daily</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">{fmt_price(spy_entry)}</div>
    <div class="stat-label">SPY at Entry</div>
    <div class="stat-sub">Paper benchmark</div>
  </div>
</div>"""

    upside_html = '<div class="card"><p class="section-title" style="margin-bottom:.75rem">Implied Upside to PT</p>' + "\n".join(upside_rows) + '</div>'

    return f"""
<section>
  <h2 class="section-title">Portfolio Overview</h2>
  {stats_html}
  {upside_html}
  <p style="font-size:0.72rem;color:var(--text-muted);margin-top:0.5rem">
    Equity curve will populate as positions close. All figures are paper-only.
  </p>
</section>"""


def _open_positions_table(positions: list[dict]) -> str:
    if not positions:
        return ""
    rows = []
    for p in positions:
        ticker = p.get("ticker", "")
        name = COMPANY_NAMES.get(ticker, ticker)
        ep = float(p.get("entry_price", 0))
        pt = float(p.get("price_target", 0))
        upside = (pt - ep) / ep if ep > 0 else 0
        bar_w = min(100, max(0, upside * 100 / 2))  # cap bar at 200% for visual
        rating = p.get("entry_rating", "")
        conf = p.get("entry_confidence", "")
        rows.append(f"""
<tr>
  <td><a href="positions/{ticker}.html" class="ticker-link">{ticker}</a></td>
  <td style="color:var(--text-muted);font-size:0.77rem">{name}</td>
  <td>{fmt_price(ep)}</td>
  <td>{fmt_price(pt)}</td>
  <td>
    <div class="upside-bar-wrap">
      <div class="upside-bar-track"><div class="upside-bar-fill" style="width:{bar_w:.0f}%"></div></div>
      <span style="font-size:0.77rem;font-weight:600">{fmt_pct(upside)}</span>
    </div>
  </td>
  <td id="pos-price-{ticker}" style="font-variant-numeric:tabular-nums">—</td>
  <td id="pos-today-{ticker}" style="font-variant-numeric:tabular-nums">—</td>
  <td id="pos-return-{ticker}" style="font-variant-numeric:tabular-nums;font-weight:600">—</td>
  <td>{rating_badge(rating)}</td>
  <td>{conf_badge(conf)}</td>
</tr>""")

    return f"""
<section>
  <h2 class="section-title">Open Positions</h2>
  <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.2rem">
    Entry / Price Target / Rating / Conf are the <b>original entry call</b> (Themis, fixed) ·
    Current / Today % / Return refresh live
  </div>
  <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.4rem" id="live-cards-ts">Live prices loading…</div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Ticker</th><th>Company</th><th>Entry</th><th>Price Target</th>
          <th>Implied Upside</th><th>Current</th><th>Today %</th><th>Return</th>
          <th>Rating</th><th>Conf</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</section>"""


def _regime_section(regime: Optional[dict]) -> str:
    if not regime:
        return '<section><h2 class="section-title">Regime Intelligence</h2><div class="card adv-disabled">Regime data unavailable — run governance pipeline.</div></section>'

    probabilities = regime.get("probabilities", {})
    leading = regime.get("leading_regime", "unknown")
    confidence = float(regime.get("confidence", 0))
    conditions = regime.get("conditions", {})
    ts = regime.get("timestamp", "")[:10]

    leading_display = leading.replace("_", " ").title()

    # Sort probabilities descending
    sorted_probs = sorted(probabilities.items(), key=lambda x: x[1], reverse=True)
    prob_bars = []
    for regime_name, prob in sorted_probs:
        color = REGIME_COLORS.get(regime_name, "bar-grey")
        label = regime_name.replace("_", " ").title()
        is_leading = regime_name == leading
        label_display = f"<strong>{label}</strong>" if is_leading else label
        prob_bars.append(bar_html(prob, color, label_display, fmt_pct(prob)))

    # Active conditions
    active = [k.replace("_", " ") for k, v in conditions.items() if v == 1.0]
    cond_tags = "".join(
        f'<span class="condition-tag active">{c}</span>' for c in active
    )

    return f"""
<section>
  <h2 class="section-title">Regime Intelligence</h2>
  <div class="card">
    <div class="regime-name">{leading_display}</div>
    <div class="regime-confidence">{fmt_pct(confidence)} confidence · as of {ts}</div>
    {"".join(prob_bars)}
    <div style="margin-top:0.75rem;font-size:0.72rem;color:var(--text-muted);margin-bottom:0.3rem">Active conditions</div>
    <div class="conditions-grid">{cond_tags}</div>
  </div>
</section>"""


def _concentration_section(exposure: Optional[dict]) -> str:
    if not exposure:
        return '<section><h2 class="section-title">Portfolio Concentration</h2><div class="card adv-disabled">Exposure data unavailable.</div></section>'

    theme_weights = exposure.get("theme_weights", {})
    factor_weights = exposure.get("factor_weights", {})
    warnings = exposure.get("warnings", [])

    # Theme bars
    sorted_themes = sorted(theme_weights.items(), key=lambda x: x[1], reverse=True)
    theme_bars = []
    for theme, w in sorted_themes:
        if theme == "unknown":
            continue
        color = THEME_COLORS.get(theme, "bar-grey")
        label = theme.replace("_", " ").title()
        warn_marker = " ⚠" if w >= 0.20 else ""
        theme_bars.append(bar_html(w, color, label + warn_marker, fmt_pct(w)))

    # Factor bars
    sorted_factors = sorted(factor_weights.items(), key=lambda x: x[1], reverse=True)
    factor_bars = []
    for factor, w in sorted_factors:
        color = FACTOR_COLORS.get(factor, "bar-grey")
        label = factor.replace("_", " ").title()
        warn_marker = " ⚠" if w >= 0.30 else ""
        factor_bars.append(bar_html(w, color, label + warn_marker, fmt_pct(w)))

    # Warnings list
    warn_items = []
    for w in warnings:
        cls = "violation" if "[VIOLATION]" in w else "watch"
        text = w.replace("[VIOLATION]", "").replace("[WATCH]", "").strip()
        warn_items.append(f'<li class="{cls}">{text}</li>')
    if not warnings:
        warn_items.append('<li class="ok">No concentration violations</li>')

    return f"""
<section>
  <h2 class="section-title">Portfolio Concentration</h2>
  <div class="card" style="margin-bottom:0.75rem">
    <div style="font-size:0.8rem;font-weight:600;margin-bottom:0.5rem">Theme Exposure (limit 25%)</div>
    {"".join(theme_bars)}
  </div>
  <div class="card" style="margin-bottom:0.75rem">
    <div style="font-size:0.8rem;font-weight:600;margin-bottom:0.5rem">Factor Exposure (limit 40%)</div>
    {"".join(factor_bars)}
  </div>
  <ul class="warnings">{"".join(warn_items)}</ul>
</section>"""


def _signal_section(signal: Optional[dict]) -> str:
    if not signal:
        return '<section><h2 class="section-title">Signal Reliability</h2><div class="card adv-disabled">Signal tracker data unavailable.</div></section>'

    signals = signal.get("signals", {})
    cards = []

    signal_display = {
        "momentum_12m": ("12M Price Momentum", "Q1 consistency vs STRONG_BUY ratings"),
        "eps_revisions": ("EPS Revisions", "Positive revision consistency with bullish ratings"),
        "signal_alignment": ("Signal Alignment", "Multi-signal agreement rate"),
        "cohort_outlier": ("Cohort Outlier Flag", "HIGH confidence outlier vs cohort"),
    }

    for key, info in signals.items():
        name, desc = signal_display.get(key, (key, ""))
        quality = info.get("overall_quality")
        decay = info.get("decay_warning", False)
        instability = info.get("instability_score", None)

        if quality is not None:
            q_pct = quality
            if q_pct >= 0.55:
                q_cls, q_label = "quality-good", "HEALTHY"
            elif q_pct >= 0.45:
                q_cls, q_label = "quality-warn", "MARGINAL"
            else:
                q_cls, q_label = "quality-poor", "DECAYING"
            quality_html = f'<div class="signal-quality {q_cls}">{q_label} ({fmt_pct(q_pct)})</div>'
            bar = bar_html(q_pct, "bar-blue" if q_pct >= 0.45 else "bar-red", "", "")
        else:
            quality_html = f'<div class="signal-quality neutral">Structural Only</div>'
            bar = ""

        meta_parts = []
        if decay:
            meta_parts.append("⚠ Decay warning")
        if instability is not None:
            meta_parts.append(f"Instability: {fmt_pct(instability)}")
        for k in ("n_q1", "n_q5", "n_positive", "n_negative", "n_high_alignment", "n_zero_alignment"):
            if k in info:
                label = k.replace("n_", "#").replace("_", " ")
                meta_parts.append(f"{label}: {info[k]}")

        meta_html = f'<div class="signal-meta">{" · ".join(meta_parts)}</div>' if meta_parts else ""

        cards.append(f"""
<div class="card signal-card">
  <div class="signal-header">
    <span class="signal-name">{name}</span>
    {quality_html}
  </div>
  <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.35rem">{desc}</div>
  {bar}
  {meta_html}
</div>""")

    return f"""
<section>
  <h2 class="section-title">Signal Reliability</h2>
  {"".join(cards)}
</section>"""


def _calibration_section(calib: Optional[dict]) -> str:
    if not calib:
        return '<section><h2 class="section-title">Confidence Calibration</h2><div class="card adv-disabled">Calibration data unavailable.</div></section>'

    total_entries = calib.get("total_signal_entries", 0)
    total_closed = calib.get("total_closed_trades", 0)
    conf_dist = calib.get("confidence_distribution", {})
    tier_perf = calib.get("tier_performance", {})
    min_obs = calib.get("min_observations_required", 20)

    # Confidence distribution bars
    total_sigs = sum(conf_dist.values()) or 1
    dist_bars = []
    for tier in ("HIGH", "MED", "LOW", "BROKEN"):
        count = conf_dist.get(tier, 0)
        frac = count / total_sigs
        color = {"HIGH": "bar-green", "MED": "bar-blue", "LOW": "bar-yellow", "BROKEN": "bar-red"}.get(tier, "bar-grey")
        dist_bars.append(bar_html(frac, color, tier, f"{count} ({fmt_pct(frac)})"))

    # Tier performance
    if total_closed >= min_obs:
        perf_rows = []
        for tier, stats in tier_perf.items():
            if isinstance(stats, dict) and "avg_return" in stats:
                avg_ret = float(stats["avg_return"])
                n = stats.get("n", 0)
                perf_rows.append(f'<tr><td>{tier}</td><td>{n}</td><td>{fmt_pct(avg_ret)}</td></tr>')
        perf_html = f"""
<div style="margin-top:0.75rem">
  <div style="font-size:0.8rem;font-weight:600;margin-bottom:0.4rem">Tier Performance</div>
  <div class="table-wrap">
    <table><thead><tr><th>Tier</th><th>Trades</th><th>Avg Return</th></tr></thead>
    <tbody>{"".join(perf_rows)}</tbody></table>
  </div>
</div>""" if perf_rows else ""
    else:
        needed = min_obs - total_closed
        perf_html = f'<p style="font-size:0.8rem;color:var(--text-muted);margin-top:0.75rem">⏳ Tier performance unlocks after {min_obs} closed trades ({needed} more needed)</p>'

    return f"""
<section>
  <h2 class="section-title">Confidence Calibration</h2>
  <div class="card">
    <div style="display:flex;gap:1rem;margin-bottom:0.75rem;font-size:0.82rem">
      <span><strong>{total_entries}</strong> signal entries</span>
      <span><strong>{total_closed}</strong> closed trades</span>
    </div>
    <div style="font-size:0.8rem;font-weight:600;margin-bottom:0.4rem">Universe Signal Distribution</div>
    {"".join(dist_bars)}
    {perf_html}
  </div>
</section>"""


def _adversarial_section(adv: Optional[dict]) -> str:
    if not adv:
        return f"""
<section>
  <h2 class="section-title">Adversarial Critique</h2>
  <div class="card">
    <div class="adv-disabled">
      Adversarial review not yet run. Pass <code>--adversarial</code> flag to governance runner to enable
      (requires ANTHROPIC_API_KEY, ~$0.001/run).
    </div>
  </div>
</section>"""

    status = adv.get("status", "unknown")
    concerns = adv.get("concerns", [])
    assumption_challenges = adv.get("assumption_challenges", [])
    ts = adv.get("timestamp", "")[:10]

    if status in ("no_api_key", "disabled"):
        return f"""
<section>
  <h2 class="section-title">Adversarial Critique</h2>
  <div class="card"><div class="adv-disabled">Adversarial review disabled — no API key.</div></div>
</section>"""

    concern_items = []
    for c in (concerns or []):
        if isinstance(c, str):
            concern_items.append(f'<div class="adv-concern">{c}</div>')
        elif isinstance(c, dict):
            text = c.get("concern") or c.get("text") or str(c)
            concern_items.append(f'<div class="adv-concern">{text}</div>')

    for c in (assumption_challenges or []):
        if isinstance(c, str):
            concern_items.append(f'<div class="adv-concern">{c}</div>')

    concerns_html = "".join(concern_items) if concern_items else '<p style="font-size:0.82rem;color:var(--green)">No critical concerns flagged.</p>'

    return f"""
<section>
  <h2 class="section-title">Adversarial Critique</h2>
  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem">
      <span style="font-size:0.8rem;font-weight:600">Claude Haiku critique</span>
      <span style="font-size:0.72rem;color:var(--text-muted)">as of {ts}</span>
    </div>
    {concerns_html}
    <p style="font-size:0.72rem;color:var(--text-muted);margin-top:0.5rem">
      Diagnostic only — LLM critique of exposure warnings. Never price targets or trade decisions.
    </p>
  </div>
</section>"""


def _constitutional_section(positions: list[dict]) -> str:
    hard_booleans = [
        ("NO_LEVERAGE", True, "No leveraged positions"),
        ("NO_SHORT_SELLING", True, "No short selling"),
        ("NO_AUTONOMOUS_EXECUTION", True, "No autonomous order placement"),
        ("HUMAN_APPROVAL_REQUIRED", True, "Human approval required for all decisions"),
        ("NO_LIVE_PNL_LEARNING", True, "No learning from realised P&L"),
        ("NO_BROKER_INTEGRATION", True, "No broker integration"),
        ("NO_SELF_MODIFYING_RISK_RULES", True, "Risk rules cannot self-modify"),
    ]

    items = []
    for key, expected, desc in hard_booleans:
        items.append(f"""
<div class="const-item">
  <span class="const-check check-pass">✓</span>
  <span style="font-weight:600;min-width:200px">{key}</span>
  <span style="color:var(--text-muted);font-size:0.77rem">{desc}</span>
</div>""")

    # Position constraints
    all_constrained = all(
        p.get("constraints", {}).get("no_real_orders", False)
        for p in positions
    ) if positions else True

    constraint_item = f"""
<div class="const-item">
  <span class="const-check {'check-pass' if all_constrained else 'check-fail'}">{'✓' if all_constrained else '✗'}</span>
  <span style="font-weight:600;min-width:200px">POSITION CONSTRAINTS</span>
  <span style="color:var(--text-muted);font-size:0.77rem">All positions carry no_real_orders constraint</span>
</div>"""

    return f"""
<section>
  <h2 class="section-title">Constitutional Compliance</h2>
  <div class="card">
    {"".join(items)}
    {constraint_item}
    <p style="font-size:0.72rem;color:var(--text-muted);margin-top:0.75rem">
      Hard booleans enforced by <code>load_constitution()</code> at runtime. HUMAN-EDITABLE only via <code>config/constitution.yaml</code>.
    </p>
  </div>
</section>"""


def _universe_section(screen_state: list[dict]) -> str:
    if not screen_state:
        return ""

    rating_order = ["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]
    counts: dict[str, int] = {r: 0 for r in rating_order}
    total = 0
    for item in screen_state:
        r = item.get("last_rating", "HOLD")
        if r in counts:
            counts[r] += 1
            total += 1

    if total == 0:
        return ""

    # Rating distribution bar
    segs = []
    seg_class = {"STRONG_BUY": "seg-sb", "BUY": "seg-b", "HOLD": "seg-h", "SELL": "seg-s", "STRONG_SELL": "seg-ss"}
    for r in rating_order:
        n = counts[r]
        if n == 0:
            continue
        pct = n / total * 100
        label = n if pct > 8 else ""
        segs.append(f'<div class="rating-dist-seg {seg_class[r]}" style="flex:{pct:.1f}">{label}</div>')

    _badge_cls = {"STRONG_BUY": "badge-sb", "BUY": "badge-b", "HOLD": "badge-h", "SELL": "badge-s", "STRONG_SELL": "badge-ss"}
    legend = " &nbsp; ".join(
        f'<span class="badge {_badge_cls.get(r, "badge-h")}">{r.replace("_"," ")}: {counts[r]}</span>'
        for r in rating_order if counts[r] > 0
    )

    # Table (sorted by rating then expected return)
    rating_rank = {r: i for i, r in enumerate(rating_order)}
    sorted_state = sorted(
        screen_state,
        key=lambda x: (rating_rank.get(x.get("last_rating", "HOLD"), 99), -float(x.get("last_expected_return", 0)))
    )

    rows = []
    for item in sorted_state[:30]:  # cap at 30 rows for mobile
        ticker = item.get("ticker", "")
        rating = item.get("last_rating", "")
        conf = item.get("last_confidence", "")
        pt = float(item.get("last_pt", 0))
        er = float(item.get("last_expected_return", 0))
        earnings = item.get("earnings_date_next", "")
        rows.append(f"""
<tr>
  <td style="font-weight:600">{ticker}</td>
  <td>{rating_badge(rating)}</td>
  <td>{conf_badge(conf)}</td>
  <td>{fmt_price(pt)}</td>
  <td style="font-weight:{'600' if er >= 0.15 else '400'};color:{'var(--green)' if er >= 0.15 else 'var(--text)'}">{fmt_pct(er)}</td>
  <td style="color:var(--text-muted);font-size:0.75rem">{earnings}</td>
</tr>""")

    more = f'<p style="font-size:0.72rem;color:var(--text-muted);text-align:center;padding:0.5rem">+{len(screen_state)-30} more tickers in universe</p>' if len(screen_state) > 30 else ""

    return f"""
<section>
  <h2 class="section-title">Universe Snapshot ({total} tickers)</h2>
  <div class="card" style="margin-bottom:0.75rem">
    <div class="rating-dist">{"".join(segs)}</div>
    <div style="font-size:0.72rem;margin-top:0.4rem">{legend}</div>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Ticker</th><th>Rating</th><th>Conf</th><th>Price Target</th><th>Exp Return</th><th>Earnings</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
  {more}
</section>"""


# ─── Per-position detail page ─────────────────────────────────────────────────

def _position_detail_page(pos: dict, rec: Optional[dict]) -> str:
    ticker = pos.get("ticker", "")
    name = COMPANY_NAMES.get(ticker, ticker)
    ep = float(pos.get("entry_price", 0))
    pt = float(pos.get("price_target", 0))
    upside = (pt - ep) / ep if ep > 0 else 0
    rating = pos.get("entry_rating", "")
    conf = pos.get("entry_confidence", "")
    entry_date = pos.get("entry_date", "")

    # Valuation details from recommendation
    wacc = ""
    tgr = ""
    exit_mult = ""
    fy1_rev = ""
    fy1_eps = ""
    company_name = name
    signal_alignment = []
    confidence_flags = []

    if rec:
        company_name = rec.get("company_name", name)
        assum = rec.get("assumptions", {})
        wacc = fmt_pct(float(assum.get("wacc", 0)))
        tgr = fmt_pct(float(assum.get("terminal_growth", 0)))
        exit_mult = f"{float(assum.get('exit_multiple_used', 0)):.1f}x"
        mo = rec.get("model_outputs", {})
        fy1_rev = fmt_money(float(mo.get("fy1_revenue", 0)))
        fy1_eps = f"${float(mo.get('fy1_eps', 0)):.2f}"
        signal_alignment = rec.get("signal_alignment", [])
        confidence_flags = rec.get("confidence_flags", [])

    football_svg = _football_field_svg(rec) if rec else "<p style='color:#6c757d;font-style:italic'>No valuation data.</p>"

    # Signal alignment rows
    align_rows = []
    for sa in signal_alignment:
        sig = sa.get("signal", "")
        aln = sa.get("alignment", "neutral")
        reason = sa.get("reason", "")
        aln_cls = {"aligns": "aligns", "contradicts": "contradicts"}.get(aln, "neutral")
        icon = {"aligns": "✓", "contradicts": "✗", "neutral": "–"}.get(aln, "–")
        align_rows.append(f"""
<div class="alignment-row">
  <span class="{aln_cls}" style="min-width:16px">{icon}</span>
  <span style="min-width:120px;font-weight:600;font-size:0.77rem">{sig}</span>
  <span style="font-size:0.77rem;color:var(--text-muted)">{reason}</span>
</div>""")

    # Confidence flags
    flags_html = ""
    if confidence_flags:
        flag_tags = "".join(f'<span class="condition-tag">{f.replace("_", " ")}</span>' for f in confidence_flags)
        flags_html = f'<div style="margin-top:0.5rem"><div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:0.3rem">Confidence flags</div><div class="conditions-grid">{flag_tags}</div></div>'

    upside_color = "var(--green)" if upside >= 0 else "var(--red)"

    header = _page_header(f"{ticker} — {company_name}", f"Position detail · {entry_date}", back=True)
    body = f"""
{header}
<main>
<div class="container">

<div class="card" style="margin-bottom:1rem">
  <div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:1rem;flex-wrap:wrap">
    {rating_badge(rating)}
    {conf_badge(conf)}
    <span style="font-size:0.82rem;color:var(--text-muted)">Paper position · all paper-only constraints applied</span>
  </div>
  <div class="detail-grid">
    <div>
      <div class="detail-label">Entry Price</div>
      <div class="detail-value">{fmt_price(ep)}</div>
    </div>
    <div>
      <div class="detail-label">Price Target (12m)</div>
      <div class="detail-value" style="color:{upside_color}">{fmt_price(pt)}</div>
    </div>
    <div>
      <div class="detail-label">Implied Upside</div>
      <div class="detail-value" style="color:{upside_color}">{fmt_pct(upside)}</div>
    </div>
    <div>
      <div class="detail-label">FY1 Revenue</div>
      <div class="detail-value">{fy1_rev}</div>
    </div>
    <div>
      <div class="detail-label">FY1 EPS</div>
      <div class="detail-value">{fy1_eps}</div>
    </div>
    <div>
      <div class="detail-label">WACC</div>
      <div class="detail-value">{wacc}</div>
    </div>
    <div>
      <div class="detail-label">Terminal Growth</div>
      <div class="detail-value">{tgr}</div>
    </div>
    <div>
      <div class="detail-label">Exit Multiple</div>
      <div class="detail-value">{exit_mult}</div>
    </div>
  </div>
  {flags_html}
</div>

<section>
  <h2 class="section-title">Valuation Football Field</h2>
  <div class="card football-field">
    {football_svg}
    <p style="font-size:0.72rem;color:var(--text-muted);margin-top:0.5rem">
      Bars show valuation method ranges. Vertical lines: current price (dashed) and price target.
    </p>
  </div>
</section>

<section>
  <h2 class="section-title">Signal Alignment</h2>
  <div class="card">
    {"".join(align_rows) if align_rows else '<p style="color:var(--text-muted);font-size:0.82rem">No signal alignment data.</p>'}
  </div>
</section>

</div>
</main>
<footer><div class="container">Olympus · Paper portfolio · Diagnostic only · Not investment advice</div></footer>"""

    return _page_wrap(f"{ticker} — Olympus", body, depth=1)


# ─── Factor alpha section ─────────────────────────────────────────────────────

def _factor_alpha_section() -> str:
    """Factor-adjusted alpha card — reads docs/data/factor_alpha.json (pre-computed)."""
    import json as _json
    from pathlib import Path as _Path

    fa_path = _Path(__file__).parent.parent / "docs" / "data" / "factor_alpha.json"
    data: dict = {}
    if fa_path.exists():
        try:
            data = _json.loads(fa_path.read_text())
        except Exception:
            pass

    computed_at = (data.get("computed_at") or "")[:16].replace("T", " ")
    systems = data.get("systems", {})

    STATUS_COLORS = {
        "insufficient": "#e3b341",
        "preliminary":  "#58a6ff",
        "ok":           "#3fb950",
    }
    STATUS_LABELS = {
        "insufficient": "Accumulating (< 20 obs)",
        "preliminary":  "Preliminary (20–59 obs)",
        "ok":           "OK (≥ 60 obs)",
    }

    def _fmt_alpha(sys_data: dict) -> str:
        alpha = sys_data.get("alpha_pct_per_day")
        ci_lo = sys_data.get("alpha_ci_lo")
        ci_hi = sys_data.get("alpha_ci_hi")
        status = sys_data.get("status", "insufficient")
        if alpha is None or status == "insufficient":
            return "—"
        color = "#3fb950" if alpha > 0 else "#f85149"
        # Annualise for readability: alpha_annual = alpha * 252
        ann = alpha * 252
        sign = "+" if ann >= 0 else ""
        ci_str = ""
        if ci_lo is not None and ci_hi is not None:
            ci_lo_ann = ci_lo * 252
            ci_hi_ann = ci_hi * 252
            ci_str = f' <span style="color:#8b949e;font-size:0.72rem">95% CI [{ci_lo_ann:+.1f}%, {ci_hi_ann:+.1f}%]</span>'
        return f'<span style="color:{color};font-weight:600">{sign}{ann:.1f}% ann.</span>{ci_str}'

    def _fmt_loadings(sys_data: dict) -> str:
        loadings = sys_data.get("factor_loadings") or {}
        if not loadings:
            return "—"
        parts = [f"{k}: {v:+.2f}" for k, v in list(loadings.items())[:3]]
        return ", ".join(parts)

    rows = ""
    display_order = [("ats", "ATS"), ("scai", "SCAI-II"), ("hermes", "Hermes v1"), ("hermes_v2", "Hermes v2")]
    for sys_id, sys_label in display_order:
        sd = systems.get(sys_id, {})
        status = sd.get("status", "insufficient")
        n_obs = sd.get("n_obs", 0) or 0
        color = STATUS_COLORS.get(status, "#e3b341")
        label = STATUS_LABELS.get(status, status)
        rf_str = "^IRX" if sd.get("rf_used") else "rf=0"
        rows += f"""<tr>
          <td style="font-weight:600">{sys_label}</td>
          <td><span style="color:{color};font-size:0.75rem">{label}</span></td>
          <td style="text-align:right">{n_obs}</td>
          <td>{_fmt_alpha(sd)}</td>
          <td style="font-size:0.72rem;color:#8b949e">{_fmt_loadings(sd)}</td>
          <td style="font-size:0.72rem;color:#8b949e">{rf_str}</td>
        </tr>"""

    note = data.get("note", "")
    ts_str = f" · Computed {computed_at} UTC" if computed_at else ""

    return f"""<section>
<h2 class="section-title">Factor-Adjusted Alpha</h2>
<div class="card">
  <p style="font-size:0.78rem;color:#8b949e;margin-bottom:0.75rem">
    OLS intercept from regression on SPY + SMH + MTUM + IWM + QUAL with Newey-West HAC 95% CI.
    Replaces SPY-relative as the primary metric once any system reaches "ok" status (≥ 60 daily obs).
    Dollar-weighted portfolio returns (start-of-day MV weights, not 1/N){ts_str}.
  </p>
  <table style="font-size:0.8rem">
    <thead><tr>
      <th style="text-align:left">System</th>
      <th style="text-align:left">Status</th>
      <th style="text-align:right">Obs</th>
      <th style="text-align:left">Factor Alpha (annualised)</th>
      <th style="text-align:left">Top loadings</th>
      <th style="text-align:left">rf</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>
</section>"""


def _backtest_section() -> str:
    """Walk-forward backtest card — reads docs/data/backtest_walk_forward.json."""
    import json as _json
    from pathlib import Path as _Path

    bk_path = _Path(__file__).parent.parent / "docs" / "data" / "backtest_walk_forward.json"
    data: dict = {}
    if bk_path.exists():
        try:
            data = _json.loads(bk_path.read_text())
        except Exception:
            pass

    status = data.get("status", "insufficient_data")
    reason = data.get("status_reason", "")
    run_date = data.get("run_date", "")
    n_variants = data.get("n_variants", 0)
    n_folds = data.get("n_folds", 0)
    prereg_ver = data.get("preregistration_version", "—")
    dist = data.get("oos_sharpe_distribution") or []
    mean_oos = data.get("mean_oos_sharpe")
    median_oos = data.get("median_oos_sharpe")
    pct_pos = data.get("pct_positive_oos")
    purge = data.get("purge_days", 5)
    embargo = data.get("embargo_days", 3)
    min_train = data.get("min_train_days", 30)
    test_days = data.get("test_days", 30)

    STATUS_COLORS = {
        "ok": "#3fb950",
        "insufficient_data": "#e3b341",
    }
    color = STATUS_COLORS.get(status, "#e3b341")
    status_label = "OK" if status == "ok" else "Accumulating"

    def _fmt(v, digits=3):
        return f"{v:.{digits}f}" if v is not None else "—"

    if dist:
        dist_html = f"""<table style="font-size:0.8rem;margin-top:0.5rem">
      <thead><tr>
        <th style="text-align:left">Folds</th>
        <th style="text-align:right">Mean OOS Sharpe</th>
        <th style="text-align:right">Median</th>
        <th style="text-align:right">% Positive Folds</th>
      </tr></thead>
      <tbody><tr>
        <td>{len(dist)}</td>
        <td style="text-align:right;{'color:#3fb950' if mean_oos and mean_oos > 0 else 'color:#f85149'}">{_fmt(mean_oos)}</td>
        <td style="text-align:right">{_fmt(median_oos)}</td>
        <td style="text-align:right">{_fmt(pct_pos, 1)}%</td>
      </tr></tbody>
    </table>"""
    else:
        dist_html = f'<p style="color:#8b949e;font-size:0.8rem;margin-top:0.5rem">{reason or "No OOS data yet — accumulating closed trades."}</p>'

    ts_str = f" · Run {run_date}" if run_date else ""

    return f"""<section>
<h2 class="section-title">Walk-Forward Validation</h2>
<div class="card">
  <p style="font-size:0.78rem;color:#8b949e;margin-bottom:0.75rem">
    Expanding-window walk-forward with purge={purge}d / embargo={embargo}d gaps.
    Parameters locked from preregistration v{prereg_ver} before OOS scoring.
    Output is a distribution of OOS Sharpes, not a single number.
    {n_variants} variants · {n_folds} folds · min_train={min_train}d · test={test_days}d{ts_str}.
  </p>
  <div style="margin-bottom:0.5rem">
    <span style="color:{color};font-weight:600;font-size:0.85rem">{status_label}</span>
  </div>
  {dist_html}
</div>
</section>"""


# ─── Heartbeat ───────────────────────────────────────────────────────────────

def _most_recent_expected_run_utc(now: Optional[datetime] = None) -> datetime:
    """Return the most recent weekday at 21:00 UTC at or before *now*."""
    if now is None:
        now = datetime.now(UTC)
    # Start from today's 21:00 UTC and walk backward until we land on a weekday.
    candidate = now.replace(hour=21, minute=0, second=0, microsecond=0)
    if candidate > now:
        candidate -= timedelta(days=1)
    # weekday(): Mon=0 … Sun=6; skip Sat(5) and Sun(6)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _heartbeat_state(hb_path: Path, now: Optional[datetime] = None) -> dict:
    """Read heartbeat.json and return a status dict.

    Returns:
        status: "ok" | "stale" | "never_run" | "unreadable"
        last_run_utc: datetime (tz-aware UTC) or None
        expected_utc: datetime (the most recent expected run)
        commit: str or ""
    """
    if now is None:
        now = datetime.now(UTC)
    expected = _most_recent_expected_run_utc(now)

    if not hb_path.exists():
        return {"status": "never_run", "last_run_utc": None, "expected_utc": expected, "commit": ""}

    try:
        raw = json.loads(hb_path.read_text())
        ts_str = raw.get("last_run_utc", "")
        commit = raw.get("commit", "")
        last_run = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=UTC)
        status = "ok" if last_run >= expected else "stale"
        return {"status": status, "last_run_utc": last_run, "expected_utc": expected, "commit": commit}
    except Exception:
        return {"status": "unreadable", "last_run_utc": None, "expected_utc": expected, "commit": ""}


def _hermes_v3_last_variant_run() -> str:
    """Honest fallback: the ACTUAL last Hermes v3 run from the variant summary.

    The heartbeat banner reads docs/data/heartbeat.json (written by a heartbeat cron
    that isn't wired). When that's absent we don't claim 'never run' if the engine has
    in fact produced runs — we read the real artifact. No fabrication.
    """
    try:
        import json as _json
        p = Path.home() / "trading" / "hermes_v3_lab" / "data" / "variants" / "variant_summary.json"
        d = _json.loads(p.read_text())
        ts = d.get("generated_at") or d.get("as_of_date") or ""
        return ts[:16].replace("T", " ") if ts else ""
    except Exception:
        return ""


def _phaethon_panel() -> str:
    """Phaethon — the isolated, forward-only paper experiment. TWO arms in one panel, clearly distinguished:
    Arm A (disciplined) and Arm B (aggressive, +10%/qtr mandate with a -25% drawdown kill-switch). Each arm
    shows holdings + bought-at price, return, vs QQQ, trend, marks; B also shows drawdown + kill-switch state.
    PUBLIC, sanitized: research-grade, vs QQQ, % + market prices only, no personal data. Both feeds are
    published daily from the consolidated always-on box; this re-renders them client-side."""
    import json as _json

    def _load(name):
        try:
            return _json.loads((_DOCS / "data" / name).read_text())
        except Exception:
            return None

    def _pct(v, pp=False):
        if v is None:
            return '<span style="color:#5c6080">—</span>'
        c = "#3fb950" if v >= 0 else "#f85149"
        return f'<span style="color:{c}">{"+" if v >= 0 else ""}{v}{"pp" if pp else "%"}</span>'

    def _arm(d, accent, is_b):
        """Server-side initial paint of one arm card (the client script rebuilds the same structure)."""
        if not d:
            return ('<div class="card adv-disabled" style="border-left:3px solid ' + accent + '">'
                    'arm feed not available yet</div>')
        trend = d.get("trend", "—")
        tcol = "#3fb950" if "IMPROV" in trend else "#f85149" if "DEGRAD" in trend else "#9fb6cd"
        rows = ""
        for h in d.get("holdings", []) or []:
            ba = h.get("bought_at")
            rows += (f'<tr><td style="padding:.25rem .5rem;font-weight:600;color:#c9d1d9">{h.get("ticker")}</td>'
                     f'<td style="padding:.25rem .5rem;color:#8b949e;text-align:right">bought @ ${ba}</td>'
                     f'<td style="padding:.25rem .5rem;color:#9fb6cd;text-align:right">{h.get("weight_pct")}%</td></tr>')
        if not rows:
            rows = '<tr><td colspan="3" style="padding:.25rem .5rem;color:#5c6080">no positions yet</td></tr>'
        # kill-switch badge (arm B only)
        ks = ""
        if is_b:
            if d.get("halted"):
                ks = ('<span style="color:#f85149;font-weight:600">⛔ KILL-SWITCH HALTED'
                      + (f' (drawdown {d.get("drawdown_pct")}%)' if d.get("drawdown_pct") is not None else '')
                      + ' — no new buys</span>')
            else:
                dd = d.get("drawdown_pct")
                ks = ('<span style="color:#3fb950">kill-switch armed · −25% peak-to-trough</span>'
                      + (f' <span style="color:#8b949e">· drawdown {dd}%</span>' if dd is not None else ''))
        return (
            f'<div class="card" style="border-left:3px solid {accent}">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:.4rem">'
            f'<span style="font-weight:700;color:{accent}">{d.get("label","—")}</span>'
            f'<span style="font-size:.72rem;color:#8b949e">{d.get("mandate","")}</span></div>'
            + (f'<div id="ph{"B" if is_b else "A"}-ks" style="font-size:.74rem;margin-bottom:.4rem">{ks}</div>' if is_b else '')
            + f'<table style="width:100%;border-collapse:collapse;font-size:.78rem;margin-bottom:.45rem">'
            f'<thead><tr><th style="text-align:left;padding:.2rem .5rem;color:#5c6080;font-weight:500">What it bought</th>'
            f'<th style="text-align:right;padding:.2rem .5rem;color:#5c6080;font-weight:500">entry</th>'
            f'<th style="text-align:right;padding:.2rem .5rem;color:#5c6080;font-weight:500">weight</th></tr></thead>'
            f'<tbody id="ph{"B" if is_b else "A"}-holds">{rows}</tbody></table>'
            f'<table style="width:100%;border-collapse:collapse;font-size:.8rem">'
            f'<tr><td style="padding:.25rem .5rem;color:#8b949e">Positions</td><td style="padding:.25rem .5rem;text-align:right" id="ph{"B" if is_b else "A"}-pos">{d.get("n_positions","—")} · {d.get("cash_pct","—")}% cash</td></tr>'
            f'<tr><td style="padding:.25rem .5rem;color:#8b949e">Active return</td><td style="padding:.25rem .5rem;text-align:right" id="ph{"B" if is_b else "A"}-ret">{_pct(d.get("active_return_pct"))}</td></tr>'
            f'<tr><td style="padding:.25rem .5rem;color:#8b949e">vs QQQ (primary)</td><td style="padding:.25rem .5rem;text-align:right" id="ph{"B" if is_b else "A"}-vs">{_pct(d.get("vs_qqq_pp"), True)}</td></tr>'
            f'<tr><td style="padding:.25rem .5rem;color:#8b949e">Improve / degrade</td><td style="padding:.25rem .5rem;text-align:right;color:{tcol};font-weight:600" id="ph{"B" if is_b else "A"}-trend">{trend}</td></tr>'
            f'<tr><td style="padding:.25rem .5rem;color:#8b949e">Marks</td><td style="padding:.25rem .5rem;text-align:right" id="ph{"B" if is_b else "A"}-marks">{d.get("n_marks","—")}</td></tr>'
            f'</table></div>')

    a = _load("phaethon_live.json")
    b = _load("phaethon_b_live.json")
    if not a and not b:
        return ""
    as_of = (a or b or {}).get("as_of", "")
    return f"""<section>
<h2 class="section-title">Phaethon — isolated autonomous paper experiment (two arms)</h2>
<div class="card">
  <div style="padding:.5rem .7rem;border:1px solid #2a2440;border-radius:4px;margin-bottom:.6rem;
              font-size:.8rem;color:#b9a5e0;line-height:1.5">
    An <strong>autonomous agent</strong> forms its own multi-angle ideas, which a <strong>local Zeus
    governance</strong> grounds (priced-in, invalidation, sizing, internal concentration) before
    <strong>paper</strong> execution — fully sandboxed on a separate box, with no access to the real
    portfolio. Two arms run side by side: <strong>A — disciplined</strong> (the original strict gate) and
    <strong>B — aggressive</strong> (relaxed gate, +10%/qtr mandate, concentrated, with a −25% drawdown
    kill-switch). Do not read early marks as a track record.
    <div style="margin-top:.4rem;color:#8b6fd6;font-weight:600;font-size:.74rem">
      research-grade · forward-only · isolated · paper-only · no real money
    </div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:.7rem" id="ph-arms">
    {_arm(a, "#8b6fd6", False)}
    {_arm(b, "#f0883e", True)}
  </div>
  <p style="font-size:.72rem;color:#5c6080;margin-top:.5rem">Paper/simulated · isolated experiment · % + market prices only · the experiment's value is the improve/degrade-vs-QQQ trend, not the level. Both arms published daily from the consolidated always-on box{(' · as of ' + as_of) if as_of else ''}.</p>
</div>
<script>
(function(){{
  function f(v,pp){{if(v===null||v===undefined)return'<span style="color:#5c6080">—</span>';var c=v>=0?'#3fb950':'#f85149';return'<span style="color:'+c+'">'+(v>=0?'+':'')+v+(pp?'pp':'%')+'</span>';}}
  function set(id,html){{var e=document.getElementById(id);if(e)e.innerHTML=html;}}
  function render(d,P,isB){{
    if(!d)return;
    var hr='';(d.holdings||[]).forEach(function(h){{hr+='<tr><td style="padding:.25rem .5rem;font-weight:600;color:#c9d1d9">'+h.ticker+'</td><td style="padding:.25rem .5rem;color:#8b949e;text-align:right">bought @ $'+h.bought_at+'</td><td style="padding:.25rem .5rem;color:#9fb6cd;text-align:right">'+h.weight_pct+'%</td></tr>';}});
    if(!hr)hr='<tr><td colspan="3" style="padding:.25rem .5rem;color:#5c6080">no positions yet</td></tr>';
    set('ph'+P+'-holds',hr);
    set('ph'+P+'-pos',(d.n_positions!=null?d.n_positions:'—')+' · '+(d.cash_pct!=null?d.cash_pct:'—')+'% cash');
    set('ph'+P+'-ret',f(d.active_return_pct,false));
    set('ph'+P+'-vs',f(d.vs_qqq_pp,true));
    var t=d.trend||'—',tc=t.indexOf('IMPROV')>=0?'#3fb950':(t.indexOf('DEGRAD')>=0?'#f85149':'#9fb6cd');
    var te=document.getElementById('ph'+P+'-trend');if(te){{te.innerHTML=t;te.style.color=tc;}}
    set('ph'+P+'-marks',(d.n_marks!=null?d.n_marks:'—'));
    if(isB){{
      var ks;
      if(d.halted){{ks='<span style="color:#f85149;font-weight:600">⛔ KILL-SWITCH HALTED'+(d.drawdown_pct!=null?' (drawdown '+d.drawdown_pct+'%)':'')+' — no new buys</span>';}}
      else{{ks='<span style="color:#3fb950">kill-switch armed · −25% peak-to-trough</span>'+(d.drawdown_pct!=null?' <span style="color:#8b949e">· drawdown '+d.drawdown_pct+'%</span>':'');}}
      set('phB-ks',ks);
    }}
  }}
  fetch('data/phaethon_live.json?t='+Date.now()).then(function(r){{return r.ok?r.json():Promise.reject();}}).then(function(d){{render(d,'A',false);}}).catch(function(){{}});
  fetch('data/phaethon_b_live.json?t='+Date.now()).then(function(r){{return r.ok?r.json():Promise.reject();}}).then(function(d){{render(d,'B',true);}}).catch(function(){{}});
}})();
</script>
</section>"""


def _gaia_panel() -> str:
    """Gaia — three rules-based diversified low-cost cores vs a public all-world benchmark. Shows
    composition + blended fee + paper return vs benchmark. PUBLIC ONLY: never the current allocation
    or the fee-saving-vs-current (those are private/gitignored). Honest: cost + risk, not which-wins."""
    import json as _json
    try:
        d = _json.loads((_DOCS / "data" / "gaia_cores_live.json").read_text())
    except Exception:
        return ('<section><h2 class="section-title">Gaia — diversified low-cost cores</h2>'
                '<div class="card adv-disabled">Gaia core feed not available yet '
                '(run the constructor + publisher).</div></section>')

    def _pct(v, pp=False):
        if v is None:
            return '<span style="color:#5c6080">—</span>'
        c = "#3fb950" if v >= 0 else "#f85149"
        return f'<span style="color:{c}">{"+" if v >= 0 else ""}{v}{"pp" if pp else "%"}</span>'

    b = d.get("benchmark", {})
    rows = ""
    for c in d.get("cores", []):
        comp = " · ".join(f"{t} {int(round(w*100))}%" for t, w in (c.get("etfs") or {}).items())
        rows += (
            f'<tr>'
            f'<td style="padding:.4rem .5rem;font-weight:600;color:#c9d1d9;white-space:nowrap">Risk {c.get("risk")}/10</td>'
            f'<td style="padding:.4rem .5rem;color:#8b949e;font-size:.78rem">{comp}</td>'
            f'<td style="padding:.4rem .5rem;text-align:right;color:#9fb6cd">{c.get("blended_ocf_pct")}%</td>'
            f'<td style="padding:.4rem .5rem;text-align:right" id="gaia-{c.get("id")}-ret">{_pct(c.get("return_pct"))}</td>'
            f'<td style="padding:.4rem .5rem;text-align:right" id="gaia-{c.get("id")}-vs">{_pct(c.get("vs_benchmark_pp"), True)}</td>'
            f'<td style="padding:.4rem .5rem;text-align:right" id="gaia-{c.get("id")}-qqq">{_pct(c.get("vs_qqq_pp"), True)}</td>'
            f'</tr>')
    q = d.get("qqq", {})
    bench_row = (
        f'<tr style="border-top:1px solid #21262d">'
        f'<td style="padding:.4rem .5rem;color:#8b949e;white-space:nowrap">Benchmark</td>'
        f'<td style="padding:.4rem .5rem;color:#8b949e;font-size:.78rem">{b.get("ticker")} — {b.get("name","")}</td>'
        f'<td style="padding:.4rem .5rem;text-align:right;color:#9fb6cd">{b.get("ocf_pct")}%</td>'
        f'<td style="padding:.4rem .5rem;text-align:right" id="gaia-bench-ret">{_pct(b.get("return_pct"))}</td>'
        f'<td style="padding:.4rem .5rem;text-align:right;color:#5c6080">—</td>'
        f'<td style="padding:.4rem .5rem;text-align:right;color:#5c6080">—</td>'
        f'</tr>')
    qqq_row = (
        f'<tr>'
        f'<td style="padding:.4rem .5rem;color:#8b949e;white-space:nowrap">Benchmark</td>'
        f'<td style="padding:.4rem .5rem;color:#8b949e;font-size:.78rem">{q.get("ticker","QQQ")} — {q.get("name","Nasdaq-100")}</td>'
        f'<td style="padding:.4rem .5rem;text-align:right;color:#5c6080">—</td>'
        f'<td style="padding:.4rem .5rem;text-align:right" id="gaia-qqq-ret">{_pct(q.get("return_pct"))}</td>'
        f'<td style="padding:.4rem .5rem;text-align:right;color:#5c6080">—</td>'
        f'<td style="padding:.4rem .5rem;text-align:right;color:#5c6080">—</td>'
        f'</tr>')
    days = d.get("days", 0)
    return f"""<section>
<h2 class="section-title">Gaia — diversified low-cost cores (research, not advice)</h2>
<div class="card" style="overflow-x:auto">
  <div style="padding:.5rem .7rem;border:1px solid #21323e;border-radius:4px;margin-bottom:.6rem;
              font-size:.8rem;color:#9fb6cd;line-height:1.5">
    Three rules-based cores from cheap, broad ETFs (lowest-cost per sleeve; not optimised), marked
    forward vs a global all-world ETF. <strong>Research candidates, not advice.</strong> In an AI
    bull these diversified cores will likely <strong>lag an AI-heavy tilt on raw return</strong> —
    their value is <strong>lower cost + lower concentration risk, not more return</strong>.
    <strong>Read as cost + risk, not "which wins."</strong>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:.82rem">
    <thead><tr>
      <th style="text-align:left;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Core</th>
      <th style="text-align:left;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Composition (lowest-cost broad ETFs)</th>
      <th style="text-align:right;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Blended fee</th>
      <th style="text-align:right;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Paper return ({days}d)</th>
      <th style="text-align:right;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">vs all-world</th>
      <th style="text-align:right;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">vs QQQ</th>
    </tr></thead>
    <tbody>{rows}{bench_row}{qqq_row}</tbody>
  </table>
  <p style="font-size:.72rem;color:#5c6080;margin-top:.5rem">
    Paper/simulated · % only · marked daily since inception vs the all-world benchmark · the
    current-allocation comparison is private and never shown here.
  </p>
</div>
<script>
(function(){{
  function f(v,pp){{if(v===null||v===undefined)return'<span style="color:#5c6080">—</span>';var c=v>=0?'#3fb950':'#f85149';return'<span style="color:'+c+'">'+(v>=0?'+':'')+v+(pp?'pp':'%')+'</span>';}}
  function set(id,html){{var e=document.getElementById(id);if(e)e.innerHTML=html;}}
  fetch('data/gaia_cores_live.json?t='+Date.now()).then(function(r){{return r.ok?r.json():Promise.reject();}}).then(function(d){{
    (d.cores||[]).forEach(function(c){{set('gaia-'+c.id+'-ret',f(c.return_pct,false));set('gaia-'+c.id+'-vs',f(c.vs_benchmark_pp,true));set('gaia-'+c.id+'-qqq',f(c.vs_qqq_pp,true));}});
    if(d.benchmark)set('gaia-bench-ret',f(d.benchmark.return_pct,false));
    if(d.qqq)set('gaia-qqq-ret',f(d.qqq.return_pct,false));
  }}).catch(function(){{}});
}})();
</script>
</section>"""


def _growth_arms_panel() -> str:
    """A/B/C live paper-performance panel — sourced from docs/data/growth_arms_live.json (each arm's
    paper ledger, marked vs QQQ primary + SPY secondary). Honest, research-grade, % only — never a
    track record. Fail-soft: renders a placeholder if the feed isn't present yet."""
    import json as _json
    try:
        d = _json.loads((_DOCS / "data" / "growth_arms_live.json").read_text())
        arms = d.get("arms", {})
    except Exception:
        return ('<section><h2 class="section-title">Growth arms — live paper performance</h2>'
                '<div class="card adv-disabled">Arm performance feed not available yet '
                '(run the growth loop + publisher).</div></section>')

    def _pct(v, pp=False):
        if v is None:
            return '<span style="color:#5c6080">—</span>'
        c = "#3fb950" if v >= 0 else "#f85149"
        return f'<span style="color:{c}">{"+" if v >= 0 else ""}{v}{"pp" if pp else "%"}</span>'

    rows = ""
    max_days = 0
    for a in ("A", "B", "C"):
        m = arms.get(a, {})
        if not m.get("available"):
            rows += (f'<tr><td style="padding:.4rem .5rem;font-weight:600">Arm {a}</td>'
                     f'<td colspan="6" style="padding:.4rem .5rem;color:#5c6080">not run yet</td></tr>')
            continue
        max_days = max(max_days, m.get("days_held", 0) or 0)
        rows += (
            f'<tr>'
            f'<td style="padding:.4rem .5rem;font-weight:600;color:#c9d1d9">Arm {a}</td>'
            f'<td style="padding:.4rem .5rem;color:#8b949e;font-size:.78rem">{m.get("label","")}</td>'
            f'<td style="padding:.4rem .5rem;text-align:center" id="ga-{a}-n">{m.get("n_positions","—")}</td>'
            f'<td style="padding:.4rem .5rem;text-align:center" id="ga-{a}-d">{m.get("days_held","—")}</td>'
            f'<td style="padding:.4rem .5rem;text-align:right" id="ga-{a}-ret">{_pct(m.get("active_return_pct"))}</td>'
            f'<td style="padding:.4rem .5rem;text-align:right" id="ga-{a}-qqq">{_pct(m.get("vs_qqq_pp"), True)}</td>'
            f'<td style="padding:.4rem .5rem;text-align:right" id="ga-{a}-spy">{_pct(m.get("vs_spy_pp"), True)}</td>'
            f'</tr>')
    tgt = d.get("scorecard_target", 30)
    return f"""<section>
<h2 class="section-title">Growth arms — live paper performance (A/B/C)</h2>
<div class="card" style="overflow-x:auto">
  <div style="padding:.5rem .7rem;border:1px solid #3a2f12;border-radius:4px;margin-bottom:.6rem;
              font-size:.8rem;color:#e3b341;line-height:1.5">
    <strong>research-grade · {max_days} day{'s' if max_days != 1 else ''} · scorecard 0/{tgt} resolved ·
    not statistically meaningful yet.</strong> The three arms are
    <strong>AI-infrastructure-concentrated and highly correlated — not independent strategies</strong>.
    <strong>QQQ is the real test</strong>; beating the S&amp;P with an AI-infra book in an AI bull is
    <em>expected, not edge</em>. Do not read these early numbers as a track record.
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:.82rem">
    <thead><tr>
      <th style="text-align:left;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Arm</th>
      <th style="text-align:left;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Discovery filter</th>
      <th style="text-align:center;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Pos</th>
      <th style="text-align:center;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Days</th>
      <th style="text-align:right;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Paper return</th>
      <th style="text-align:right;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">vs QQQ (primary)</th>
      <th style="text-align:right;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">vs S&amp;P (secondary)</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="font-size:.72rem;color:#5c6080;margin-top:.5rem">
    Paper/simulated · marked since inception vs QQQ &amp; SPY from each arm's paper ledger · updates as
    the loop runs forward · % only, no positions sizing shown.
  </p>
</div>
<script>
(function(){{
  function f(v,pp){{if(v===null||v===undefined)return'<span style="color:#5c6080">—</span>';var c=v>=0?'#3fb950':'#f85149';return'<span style="color:'+c+'">'+(v>=0?'+':'')+v+(pp?'pp':'%')+'</span>';}}
  function set(id,html){{var e=document.getElementById(id);if(e)e.innerHTML=html;}}
  fetch('data/growth_arms_live.json?t='+Date.now()).then(function(r){{return r.ok?r.json():Promise.reject();}}).then(function(d){{
    ['A','B','C'].forEach(function(a){{var m=(d.arms||{{}})[a];if(!m||!m.available)return;
      set('ga-'+a+'-n',m.n_positions);set('ga-'+a+'-d',m.days_held);
      set('ga-'+a+'-ret',f(m.active_return_pct,false));set('ga-'+a+'-qqq',f(m.vs_qqq_pp,true));set('ga-'+a+'-spy',f(m.vs_spy_pp,true));
    }});
  }}).catch(function(){{}});
}})();
</script>
</section>"""


def _hermes_v3_compute_banner() -> str:
    """Honest Hermes v3 status: the variant marks are from the last daily COMPUTE, not live.

    Uses the real compute timestamp from the droplet's variant_summary.json (generated_at) — NOT
    the dashboard republish time — so the label never implies intraday liveness the page lacks.
    """
    ts = _hermes_v3_last_variant_run()        # compute time (UTC) from variant_summary.generated_at
    when = f"{ts} UTC" if ts else "unknown"
    return (
        '<div class="hb-banner hb-stale">'
        f'Hermes v3 — paper shadow arena · <strong>marks as of last compute {when}</strong>. '
        'Positions are not live-marked intraday; figures are from the last daily compute, not live prices.'
        '</div>'
    )


def _hermes_v3_heartbeat_badge() -> str:
    """Render an HTML banner showing the last successful Hermes v3 run time."""
    state = _heartbeat_state(_DOCS / "data" / "heartbeat.json")
    status = state["status"]
    commit = state["commit"]
    expected = state["expected_utc"]

    if status == "ok":
        ts = state["last_run_utc"].strftime("%Y-%m-%d %H:%M UTC")
        commit_tag = f" · <code>{commit}</code>" if commit else ""
        return (
            f'<div class="hb-banner hb-ok">'
            f'&#10003; Hermes v3 last run: <strong>{ts}</strong>{commit_tag}'
            f'</div>'
        )
    elif status == "stale":
        ts = state["last_run_utc"].strftime("%Y-%m-%d %H:%M UTC")
        exp = expected.strftime("%Y-%m-%d %H:%M UTC")
        return (
            f'<div class="hb-banner hb-stale">'
            f'&#9888; STALE — last run: {ts} · expected by {exp}'
            f'</div>'
        )
    elif status == "never_run":
        # No live heartbeat file exists — but the engine may still have produced real
        # runs. Be honest: surface the actual last run (from the variant summary) AND the
        # gap (no automated heartbeat/schedule). Do NOT fabricate a heartbeat or hide the gap.
        last = _hermes_v3_last_variant_run()
        if last:
            return (
                f'<div class="hb-banner hb-stale">'
                f'&#9888; Hermes v3 last run: <strong>{last}</strong> (variant summary) · '
                f'no automated heartbeat/schedule recording runs'
                f'</div>'
            )
        return (
            f'<div class="hb-banner hb-stale">'
            f'&#9888; Hermes v3 — not yet run'
            f'</div>'
        )
    else:  # unreadable
        return (
            f'<div class="hb-banner hb-stale">'
            f'&#9888; Heartbeat file unreadable'
            f'</div>'
        )


# ─── Cross-system overlap ────────────────────────────────────────────────────

def _compute_overlap_html(scai_path, hermes_jrnl) -> str:
    """Compute and render cross-system holdings overlap.

    Agreement between systems that share the same universe and governance rules
    is mechanical, not corroborating. This block makes that explicit.
    """
    import json as _json

    lines_out: list[str] = []

    try:
        # --- load SCAI-II open positions ---
        scai_baskets: dict[str, dict] = {}   # cluster_name → mark record
        if scai_path.exists():
            sm = _json.loads(scai_path.read_text())
            for m in sm.get("marks", []):
                if m.get("status") == "open":
                    cluster = m["basket_name"].split("—")[-1].strip()
                    scai_baskets[cluster] = m

        # --- load Hermes v1 open positions ---
        hermes_baskets: dict[str, dict] = {}  # cluster_name → journal record
        if hermes_jrnl.exists():
            seen: dict = {}
            for line in hermes_jrnl.read_text().splitlines():
                if line.strip():
                    d = _json.loads(line)
                    if "paper_id" in d:
                        seen[d["paper_id"]] = d
            for d in seen.values():
                if d.get("status") == "open":
                    cluster = d["basket_name"].split("—")[-1].strip()
                    hermes_baskets[cluster] = d

        if not scai_baskets and not hermes_baskets:
            return ""

        # --- Jaccard on basket/cluster names ---
        s_set = set(scai_baskets.keys())
        h_set = set(hermes_baskets.keys())
        union = s_set | h_set
        intersection = s_set & h_set
        basket_jaccard = len(intersection) / len(union) if union else 0.0
        overlap_pct = int(round(basket_jaccard * 100))
        n_shared = len(intersection)
        n_total = len(union)

        # --- Jaccard on tickers (SCAI carries tickers; Hermes journal does not) ---
        s_tickers: set[str] = set()
        h_tickers: set[str] = set()
        for m in scai_baskets.values():
            s_tickers.update(m.get("tickers") or [])
        # Hermes journal has no tickers field — ticker overlap not computable
        ticker_line = ""
        if s_tickers:
            ticker_line = (
                f'<span style="color:#484f58"> · tickers held by SCAI-II: '
                f'{", ".join(sorted(s_tickers))}'
                f' (Hermes journal carries no ticker list)</span>'
            )

        # --- high-overlap warning threshold ---
        high_overlap = basket_jaccard > 0.80

        # --- side-by-side scores for shared clusters ---
        score_rows: list[str] = []
        for cluster in sorted(intersection):
            s_score = scai_baskets[cluster].get("selection_score")
            h_score = hermes_baskets[cluster].get("selection_score")
            s_str = f"{s_score:.3f}" if s_score is not None else "—"
            h_str = f"{h_score:.3f}" if h_score is not None else "—"
            score_rows.append(
                f'<tr><td style="padding:0.1rem 0.6rem 0.1rem 0">{cluster}</td>'
                f'<td style="padding:0.1rem 0.6rem 0.1rem 0;color:#d29922">SCAI-II: {s_str}</td>'
                f'<td style="padding:0.1rem 0 0.1rem 0;color:#58a6ff">Hermes: {h_str}</td></tr>'
            )

        # --- build HTML ---
        overlap_color = "#ffa726" if high_overlap else "#484f58"
        lines_out.append(
            f'<div style="margin-top:0.7rem;padding:0.55rem 0.75rem;'
            f'border:1px solid #2a2d3e;border-radius:4px;font-size:0.80rem">'
        )
        lines_out.append(
            f'<p style="margin:0 0 0.3rem 0;color:{overlap_color};font-weight:600">'
            f'Holdings overlap (Hermes v1 ↔ SCAI-II): {overlap_pct}% '
            f'({n_shared}/{n_total} clusters)</p>'
        )
        if ticker_line:
            lines_out.append(f'<p style="margin:0 0 0.3rem 0">{ticker_line}</p>')

        if high_overlap:
            lines_out.append(
                f'<p style="margin:0 0 0.4rem 0;color:#ffa726">'
                f'⚠ High overlap — systems share universe constraints and governance rules; '
                f'agreement is mechanical, not corroborating. '
                f'Treat as one bet.</p>'
            )

        lines_out.append(
            f'<p style="margin:0 0 0.3rem 0;color:#484f58">'
            f'Note: these systems operate on the same watchlist and the same governance '
            f'block rules. Cluster-level agreement reflects shared constraints, '
            f'not independent signal.</p>'
        )

        if score_rows:
            lines_out.append(
                f'<p style="margin:0 0 0.2rem 0;color:#484f58">'
                f'Shared clusters — differing selection scores (constraint-driven, not independent):</p>'
            )
            lines_out.append('<table style="border-collapse:collapse;margin:0">')
            lines_out.extend(score_rows)
            lines_out.append('</table>')

        lines_out.append('</div>')

    except Exception:
        pass

    return "\n".join(lines_out)


# ─── Index page ───────────────────────────────────────────────────────────────

def _systems_overview() -> str:
    """Cross-system comparison card — reads SCAI-II, Hermes, and Hermes v3 summary JSON read-only."""
    from pathlib import Path as _Path
    import json as _json

    _home = _Path.home()
    scai_path   = _home / "trading" / "scai_lab"  / "data" / "paper" / "structural_paper_summary.json"
    hermes_path = _home / "trading" / "hermes_lab" / "data" / "paper" / "summary.json"
    hermes_jrnl = _home / "trading" / "hermes_lab" / "data" / "paper" / "journal.jsonl"
    hermes_reg  = _home / "trading" / "hermes_lab" / "data" / "learning" / "regime_memory.jsonl"
    h3_summary  = _home / "trading" / "hermes_v3_lab" / "data" / "variants" / "variant_summary.json"

    def _td(val, href=None, color=None, elem_id=None):
        inner = f'<a href="{href}" style="color:#58a6ff">{val}</a>' if href else str(val)
        style = f' style="color:{color}"' if color else ""
        id_attr = f' id="{elem_id}"' if elem_id else ""
        return f"<td{style}{id_attr}>{inner}</td>"

    rows = []

    # ATS row
    rows.append(
        "<tr>"
        + _td("Themis (ATS)", href="./")
        + _td("Long-term paper portfolio")
        + _td("Active", color="#3fb950")
        + _td("$5,000")
        + _td('<span id="sys-pot-ats">—</span>')
        + _td('<span id="sys-ret-ats">see above</span>')
        + _td('<span id="sys-spy-ats">—</span>')
        + _td("—") + _td("See portfolio above") + _td("—")
        + "</tr>"
    )

    # SCAI-II row
    scai_open, scai_baskets, scai_updated = "—", "—", "—"
    if scai_path.exists():
        try:
            s = _json.loads(scai_path.read_text())
            scai_open    = str(s.get("n_open", 0))
            scai_updated = (s.get("mark_date") or s.get("last_updated", "")[:10])
            names = [m["basket_name"].split("—")[-1].strip() for m in s.get("marks", []) if m.get("status") == "open"]
            scai_baskets = ", ".join(names) if names else "none"
        except Exception:
            pass
    rows.append(
        "<tr>"
        + _td("Apollo (SCAI)", href="scai/")
        + _td("Structural rotation monitor")
        + _td("Paper-only", color="#3fb950")
        + _td("$5,000")
        + _td('<span id="sys-pot-scai">—</span>')
        + _td('<span id="sys-ret-scai">—</span>')
        + _td('<span id="sys-spy-scai">—</span>')
        + _td(scai_open) + _td(scai_baskets) + _td(scai_updated)
        + "</tr>"
    )

    # Hermes v1 row
    hermes_open, hermes_baskets, hermes_updated = "—", "—", "—"
    hermes_breadth = "—"
    if hermes_path.exists():
        try:
            h = _json.loads(hermes_path.read_text())
            hermes_open    = str(h.get("n_open", 0))
            hermes_updated = h.get("updated_at", "")[:10]
        except Exception:
            pass
    if hermes_jrnl.exists():
        try:
            seen: dict = {}
            for line in hermes_jrnl.read_text().splitlines():
                if line.strip():
                    d = _json.loads(line)
                    if "paper_id" in d:
                        seen[d["paper_id"]] = d
            names = [d["basket_name"].split("—")[-1].strip() for d in seen.values() if d.get("status") == "open"]
            hermes_baskets = ", ".join(names) if names else "none"
        except Exception:
            pass
    if hermes_reg.exists():
        try:
            reg_lines = [l for l in hermes_reg.read_text().splitlines() if l.strip()]
            if reg_lines:
                reg = _json.loads(reg_lines[-1])
                bp = reg.get("summary", {}).get("breadth_pct")
                if bp is not None:
                    hermes_breadth = f"{bp:.1f}%"
        except Exception:
            pass
    rows.append(
        "<tr>"
        + _td("Hermes v1 → Apollo", href="hermes/")
        + _td(f'Experimental paper lab · breadth {hermes_breadth}')
        + _td("Observation v1", color="#d29922")
        + _td("$5,000")
        + _td('<span id="sys-pot-hermes">—</span>')
        + _td('<span id="sys-ret-hermes">—</span>')
        + _td('<span id="sys-spy-hermes">—</span>')
        + _td(hermes_open) + _td(hermes_baskets) + _td(hermes_updated)
        + "</tr>"
    )

    # Hermes v2 row (critique-only — no pot)
    v2_rep_dir = _home / "trading" / "hermes_learning_lab" / "data" / "reports"
    v2_open, v2_proposals, v2_near_miss, v2_updated = "—", "—", "—", "—"
    try:
        v2_comp_dir = _home / "trading" / "hermes_learning_lab" / "data" / "comparisons"
        comp_files = sorted(v2_comp_dir.glob("comparison_*.json")) if v2_comp_dir.exists() else []
        if comp_files:
            cdata = _json.loads(comp_files[-1].read_text())
            v2_updated = comp_files[-1].stem.replace("comparison_", "")
            v2_open = str(cdata.get("summary", {}).get("n_convergent_selected", "—"))
            v2_near_miss = str(cdata.get("summary", {}).get("n_convergent_blocked", "—")) + " conv. blocked"
        prop_dir = _home / "trading" / "hermes_learning_lab" / "data" / "proposals"
        v2_proposals = str(len(list(prop_dir.glob("p2_*.json")))) if prop_dir.exists() else "—"
    except Exception:
        pass
    rows.append(
        "<tr>"
        + _td("Athena (Hermes v2)", href="hermes_v2/")
        + _td(f'Learning lab · {v2_proposals} proposals · {v2_near_miss}')
        + _td("Learning", color="#58a6ff")
        + _td('<span style="color:#484f58">critique-only</span>')
        + _td('<span style="color:#484f58">no pot</span>')
        + _td("—")
        + _td("—")
        + _td(v2_open) + _td("Read-only") + _td(v2_updated)
        + "</tr>"
    )

    # Hermes v3 row
    h3_open, h3_best_ret, h3_updated = "—", "—", "—"
    h3_n_variants = "10"
    if h3_summary.exists():
        try:
            d3 = _json.loads(h3_summary.read_text())
            variants = d3.get("variants", [])
            h3_n_variants = str(len(variants))
            if variants:
                rets = [v.get("net_return_pct", 0) or 0 for v in variants]
                h3_best_ret = f'{max(rets):+.1f}%'
                h3_open = str(sum(v.get("open_positions", 0) for v in variants))
            h3_updated = d3.get("as_of_date", "—")
        except Exception:
            pass
    rows.append(
        "<tr>"
        + _td("Hermes (execution)", href="hermes_v3/")
        + _td(f'Shadow rotation lab · {h3_n_variants} variants · paper only')
        + _td("PAPER / SHADOW", color="#bc8cff")
        + _td(f"$5k × {h3_n_variants}")
        + _td('<span id="sys-pot-h3">—</span>')
        + _td(f'<span id="sys-ret-h3">best: {h3_best_ret}</span>')
        + _td('<span id="sys-spy-h3">—</span>')
        + _td(h3_open) + _td("10 variants") + _td(h3_updated)
        + "</tr>"
    )

    # Hermes v3-N (market-neutral spread) row — additive, fail-soft
    h3n_spread_ret, h3n_n_trades = "—", "—"
    if h3_summary.exists():
        try:
            d3n = _json.loads(h3_summary.read_text())
            mn_row = next(
                (v for v in d3n.get("variants", []) if v.get("variant_id") == "market_neutral_spread"),
                None,
            )
            if mn_row:
                sm = mn_row.get("spread_metrics") or {}
                sr = sm.get("spread_return_pct")
                h3n_spread_ret = f'{sr:+.1f}%' if sr is not None else "—"
                nl = sm.get("n_long_trades", 0)
                ns = sm.get("n_short_trades", 0)
                h3n_n_trades = f"{nl}L/{ns}S"
        except Exception:
            pass
    rows.append(
        "<tr>"
        + _td("Hermes v3-N (Hermes)", href="hermes_v3/")
        + _td(f'Market-neutral spread · paper only · spread return {h3n_spread_ret}')
        + _td("PAPER / SHADOW", color="#bc8cff")
        + _td("$5k (spread)")
        + _td("—")
        + _td(f'<span id="sys-ret-h3n">{h3n_spread_ret}</span>')
        + _td("n/a — spread only")
        + _td(h3n_n_trades) + _td("Long/short legs") + _td(h3_updated)
        + "</tr>"
    )

    # Cross-system overlap (mechanical — shared governance, not independent signal)
    overlap_html = _compute_overlap_html(scai_path, hermes_jrnl)

    rows_html = "\n      ".join(rows)
    return f"""<section>
<h2 class="section-title">Olympus — Research Systems</h2>
<div class="card" style="overflow-x:auto">
  <table>
    <thead><tr>
      <th>System</th><th>Role</th><th>Status</th>
      <th>Start Pot</th><th>Curr Pot</th><th>Return</th><th>SPY</th>
      <th>Open</th><th>Notes</th><th>Updated</th>
    </tr></thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
  {overlap_html}
  <p style="margin-top:0.5rem;font-size:0.72rem;color:#484f58">
    Paper-only · No real orders · No broker connection · Diagnostic only ·
    Pot values live-updated from lab JSONs every 5 min
  </p>
</div>
</section>"""


def _live_strip_html(data_url: str, benchmark_label: str = "SPY") -> str:
    """Live data strip: fetches JSON and renders portfolio/benchmark/alpha/market status."""
    return f"""<div id="live-strip"><div class="live-inner" style="color:#5c6080;font-size:.78rem;padding:.4rem 1.25rem">Loading live data…</div></div>
<style>
#live-strip{{background:#080a12;border-bottom:1px solid #1a1d2e;padding:.45rem 0;font-size:.78rem;}}
.live-inner{{max-width:1100px;margin:0 auto;padding:0 1.25rem;display:flex;align-items:center;gap:1.1rem;flex-wrap:wrap;}}
.live-item{{color:#9fa8da;}}.live-item strong{{color:#c5cae9;}}
.live-pill{{display:inline-block;padding:.1rem .55rem;border-radius:4px;font-weight:700;font-size:.75rem;}}
.live-open{{background:#1b3a37;color:#26a69a;}}.live-closed{{background:#2a1a1a;color:#ef5350;}}
.live-pre{{background:#3a2d1a;color:#ffa726;}}.live-ah{{background:#3a2d1a;color:#ffa726;}}
.live-stale{{color:#ffa726;font-weight:600;}}.live-ts{{margin-left:auto;color:#5c6080;font-size:.72rem;cursor:default;}}
</style>
<script>
(function(){{
  var URL='{data_url}', BM='{benchmark_label}', INTERVAL=5*60*1000;
  function fmt(v,d){{if(v===null||v===undefined)return'—';return(v>=0?'+':'')+v.toFixed(d||1)+'%';}}
  function pill(status){{var m={{open:['live-open','● OPEN'],closed:['live-closed','● CLOSED'],pre_market:['live-pre','◐ PRE'],after_hours:['live-ah','◐ AH']}};var p=m[status]||['live-pre',status||'?'];return'<span class="live-pill '+p[0]+'">'+p[1]+'</span>';}}
  function render(d){{
    var el=document.getElementById('live-strip');if(!el)return;
    var stale=d.stale_warning?'<span class="live-stale">⚠ stale</span>':'';
    var bm_lbl=BM;
    var bm_ret=d.spy_return_pct!==undefined?d.spy_return_pct:(d.baskets&&d.baskets[0]?d.baskets[0].benchmark_return_pct:null);
    var alpha=d.alpha_vs_spy_pct!==undefined?d.alpha_vs_spy_pct:(d.baskets&&d.baskets[0]?d.baskets[0].alpha_vs_benchmark_pct:null);
    var port=d.portfolio_return_pct;
    var today=d.portfolio_today_pct;
    el.innerHTML='<div class="live-inner">'+pill(d.market_status)
      +'<span class="live-item">Portfolio <strong>'+fmt(port)+'</strong></span>'
      +'<span class="live-item">Today <strong>'+fmt(today)+'</strong></span>'
      +'<span class="live-item">'+bm_lbl+' <strong>'+fmt(bm_ret)+'</strong></span>'
      +(alpha!==null&&alpha!==undefined?'<span class="live-item">Alpha <strong>'+fmt(alpha)+'</strong></span>':'')
      +stale
      +'<span class="live-ts" title="'+(d.delay_warning||'')+'">Updated '+d.fetched_at_uk+'</span>'
      +'</div>';
  }}
  function load(){{fetch(URL+'?t='+Date.now()).then(function(r){{return r.ok?r.json():Promise.reject(r.status);}}).then(render).catch(function(){{var el=document.getElementById('live-strip');if(el)el.innerHTML='<div class="live-inner" style="color:#5c6080">Live data unavailable</div>';}});}}
  load();setInterval(load,INTERVAL);
}})();
</script>"""


def _lab_nav() -> str:
    """Navigation bar linking to all sub-dashboards."""
    return """
<nav class="lab-nav">
  <div class="container">
    <span class="lab-nav-label">Dashboards</span>
    <a href="." class="lab-nav-card lab-nav-active">
      <span class="lab-nav-title">ATS</span>
      <span class="lab-nav-sub">Main Dashboard</span>
    </a>
    <a href="scai/" class="lab-nav-card">
      <span class="lab-nav-title">SCAI-II</span>
      <span class="lab-nav-sub">Structural Monitor</span>
    </a>
    <a href="hermes/" class="lab-nav-card">
      <span class="lab-nav-title">Hermes v1</span>
      <span class="lab-nav-sub">Experimental Paper Lab</span>
    </a>
    <a href="hermes_v2/" class="lab-nav-card">
      <span class="lab-nav-title">Hermes v2</span>
      <span class="lab-nav-sub">Learning Lab</span>
    </a>
    <a href="hermes_v3/" class="lab-nav-card">
      <span class="lab-nav-title">Hermes v3</span>
      <span class="lab-nav-sub">Shadow Lab</span>
    </a>
  </div>
</nav>"""


def _systems_live_js() -> str:
    """JS that reads lab live JSONs and updates the systems overview pot/return/SPY cells."""
    return """<script>
(function(){
  var INTERVAL=5*60*1000;
  function fmt(v){if(v===null||v===undefined)return'—';return(v>=0?'+':'')+v.toFixed(1)+'%';}
  function pot(ret,start){if(ret===null||ret===undefined)return'$'+(start||5000).toFixed(0);return'$'+(start*(1+ret/100)).toFixed(0);}
  function setEl(id,html){var e=document.getElementById(id);if(e)e.innerHTML=html;}
  function loadScai(){fetch('data/scai_live.json?t='+Date.now()).then(function(r){return r.ok?r.json():Promise.reject();}).then(function(d){
    setEl('sys-pot-scai',pot(d.portfolio_return_pct,5000));
    setEl('sys-ret-scai',fmt(d.portfolio_return_pct));
    setEl('sys-spy-scai',fmt(d.spy_return_pct));
  }).catch(function(){});}
  function loadHermes(){fetch('data/hermes_live.json?t='+Date.now()).then(function(r){return r.ok?r.json():Promise.reject();}).then(function(d){
    setEl('sys-pot-hermes',pot(d.portfolio_return_pct,5000));
    setEl('sys-ret-hermes',fmt(d.portfolio_return_pct));
    setEl('sys-spy-hermes',fmt(d.spy_return_pct));
  }).catch(function(){});}
  function loadH3(){fetch('data/hermes_v3_live.json?t='+Date.now()).then(function(r){return r.ok?r.json():Promise.reject();}).then(function(d){
    var vs=d.variants||[];
    var totalStart=vs.length*5000;
    var totalCurr=vs.reduce(function(s,v){return s+(v.current_pot||5000);},0);
    var bestRet=d.best_variant_return_pct;
    setEl('sys-pot-h3','$'+totalCurr.toFixed(0)+' total');
    setEl('sys-ret-h3','best: '+fmt(bestRet));
    setEl('sys-spy-h3',fmt(d.spy_return_pct));
  }).catch(function(){});}
  function loadAts(){fetch('data/ats_live.json?t='+Date.now()).then(function(r){return r.ok?r.json():Promise.reject();}).then(function(d){
    setEl('sys-pot-ats',pot(d.portfolio_return_pct,5000));
    setEl('sys-ret-ats',fmt(d.portfolio_return_pct));
    setEl('sys-spy-ats',fmt(d.spy_return_pct));
  }).catch(function(){});}
  function loadAll(){loadScai();loadHermes();loadH3();loadAts();}
  loadAll();setInterval(loadAll,INTERVAL);
})();
</script>"""


def _live_cards_js() -> str:
    """JS block that updates perf banner, position bars, and positions table from ats_live.json every 5 min."""
    return """<script>
(function(){
  var URL='data/ats_live.json', INTERVAL=5*60*1000, STALE_MINS=20, BAR_SCALE=0.30;
  var NA_HTML='<span style="color:#5c6080;font-size:0.72em">unavailable</span>';
  function fmtPct(v){if(v===null||v===undefined)return'—';return(v>=0?'+':'')+v.toFixed(1)+'%';}
  function fmtPrice(v){if(v===null||v===undefined)return'—';return'$'+parseFloat(v).toFixed(2);}
  /* posColor: null/undefined → muted grey so blanks don't flash green */
  function posColor(v){if(v===null||v===undefined)return'#8b949e';return v>=0?'var(--green)':'var(--red)';}
  function isMarketHours(){var n=new Date(),d=n.getUTCDay();if(d===0||d===6)return false;var m=n.getUTCHours()*60+n.getUTCMinutes();return m>=810&&m<1200;}
  /* setLivePct: uses innerHTML so we can show styled "unavailable" when value is null */
  function setLivePct(id,v){
    var el=document.getElementById(id);if(!el)return;
    if(v===null||v===undefined){el.innerHTML=NA_HTML;el.style.color='';}
    else{el.textContent=(v>=0?'+':'')+v.toFixed(1)+'%';el.style.color=v>=0?'var(--green)':'var(--red)';}
  }
  function render(d){
    var pricesOk=d.n_priced&&d.n_priced>0;
    setLivePct('live-port-return',d.portfolio_return_pct);
    setLivePct('live-spy-return',d.spy_return_pct);
    setLivePct('live-qqq-return',d.qqq_return_pct);
    var alphaEl=document.getElementById('live-alpha-value');
    if(alphaEl){
      if(d.alpha_vs_spy_pct===null||d.alpha_vs_spy_pct===undefined){alphaEl.innerHTML='Alpha: '+NA_HTML;alphaEl.style.color='';}
      else{alphaEl.textContent='Alpha: '+fmtPct(d.alpha_vs_spy_pct);alphaEl.style.color=posColor(d.alpha_vs_spy_pct);}
    }
    (d.positions||[]).forEach(function(p){
      var t=p.ticker, ret=p.return_pct, day=p.day_change_pct;
      var hasRet=ret!==null&&ret!==undefined;
      var fillEl=document.getElementById('pos-fill-'+t);
      if(fillEl){fillEl.style.width=(hasRet?Math.min(100,Math.abs(ret)/BAR_SCALE):0).toFixed(1)+'%';fillEl.className='bar-fill '+(hasRet&&ret>=0?'bar-green':'bar-red');}
      var valEl=document.getElementById('pos-val-'+t);
      if(valEl){valEl.innerHTML=hasRet?fmtPct(ret):NA_HTML;valEl.style.color=posColor(ret);}
      var prEl=document.getElementById('pos-price-'+t);
      if(prEl)prEl.textContent=fmtPrice(p.last_price);
      var tdEl=document.getElementById('pos-today-'+t);
      if(tdEl){tdEl.textContent=fmtPct(day);tdEl.style.color=posColor(day);}
      var rtEl=document.getElementById('pos-return-'+t);
      if(rtEl){rtEl.innerHTML=hasRet?fmtPct(ret):NA_HTML;rtEl.style.color=posColor(ret);}
    });
    var tsEl=document.getElementById('live-cards-ts');
    if(tsEl){
      if(!pricesOk){
        tsEl.innerHTML='<span style="color:#ffa726;font-weight:600">&#9888; Prices unavailable — market may be closed or data delayed</span>';
      } else {
        var age=(Date.now()-new Date(d.fetched_at_utc).getTime())/60000;
        var warn=isMarketHours()&&age>STALE_MINS?' <span style="color:#ffa726;font-weight:600">&#9888; stale ('+Math.round(age)+'min old)</span>':'';
        tsEl.innerHTML='Live prices as of '+d.fetched_at_uk+warn;
      }
    }
  }
  function load(){fetch(URL+'?t='+Date.now()).then(function(r){return r.ok?r.json():Promise.reject(r.status);}).then(render).catch(function(){var e=document.getElementById('live-cards-ts');if(e)e.innerHTML='<span style="color:#ffa726">&#9888; Live data unavailable</span>';});}
  load();setInterval(load,INTERVAL);
})();
</script>"""


def build_index(
    positions: list[dict],
    trades: list[dict],
    regime: Optional[dict],
    exposure: Optional[dict],
    signal: Optional[dict],
    calib: Optional[dict],
    adv: Optional[dict],
    screen_state: list[dict],
    generated_at: str,
) -> str:
    header = _page_header("Olympus", "Evidence phase · Paper portfolio · Diagnostic only")
    pos_tickers = [p["ticker"] for p in positions if "ticker" in p]
    prices = _fetch_live_prices(pos_tickers + ["SPY"])
    perf = _perf_banner(positions, prices)
    returns_chart = _position_returns_chart(positions, prices)
    health = _health_bar(positions, regime, exposure, signal, generated_at)

    lab_nav  = _oly_lab_nav() or _lab_nav()   # Olympus nav, fallback to original
    # _systems_overview() (old "Research Systems" table) retired — it framed Apollo/SCAI + Hermes as
    # active rotation systems, contradicting the v2 Honest Verdicts. Model status now lives in the
    # verdicts leaderboard + v2 section + the updated roster.
    heartbeat = _hermes_v3_heartbeat_badge()

    # Single clean v2 story: lead with what-this-is + honest verdicts + the growth experiment, then
    # the governance gate, the roster, and an HONEST (compute-time, not live) Hermes v3 note. The old
    # ATS/Themis paper-book sections (position returns, overview, open positions, concentration,
    # regime, signal, calibration, adversarial, constitutional, factor-alpha, walk-forward, universe)
    # and the ATS live-strip/perf/health summaries are retired from the LANDING — the data files are
    # untouched and the detail still lives on the per-track sub-pages linked in the nav.
    body = f"""
{_oly_status_banner()}
{header}
<div class="container" style="padding-top:1rem">
{_oly_intro()}
{_oly_verdicts()}
{_oly_growth_v2()}
{_growth_arms_panel()}
{_gaia_panel()}
{_phaethon_panel()}
</div>
{_oly_kill_switch_card()}
{lab_nav}
<main>
<div class="container">
  {_oly_roster()}
  {_oly_independence()}
  {_oly_reconciliation()}
  {_hermes_v3_compute_banner()}
</div>
</main>
<footer>
  <div class="container">
    Olympus · Paper / advisory only · No real money · No validated edge ·
    Page generated {generated_at} · Not investment advice
  </div>
</footer>"""

    return _page_wrap("Olympus Dashboard", body + _live_cards_js() + _systems_live_js())


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate ATS static HTML dashboard")
    parser.add_argument("--dry-run", action="store_true", help="Print files that would be written, then exit")
    args = parser.parse_args()

    print("[dashboard] Loading data sources...", file=sys.stderr)
    positions = load_positions()
    trades = load_trades()
    screen_state = load_screen_state()
    regime = load_latest_governance("regime_log.jsonl")
    exposure = load_latest_governance("exposure_log.jsonl")
    signal = load_latest_governance("signal_tracker_log.jsonl")
    calib = load_latest_governance("calibration_log.jsonl")
    adv = load_latest_governance("adversarial_log.jsonl")

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    tickers = [p["ticker"] for p in positions if "ticker" in p]

    files_to_write = [
        "docs/index.html",
        "docs/.nojekyll",
    ] + [f"docs/positions/{t}.html" for t in tickers]

    if args.dry_run:
        print(f"[dashboard] Would write {len(files_to_write)} files:")
        for f in files_to_write:
            print(f"  {f}")
        return

    # Ensure directories
    (_DOCS / "assets").mkdir(parents=True, exist_ok=True)
    (_DOCS / "positions").mkdir(parents=True, exist_ok=True)

    # .nojekyll
    (_DOCS / ".nojekyll").write_text("")
    print("[dashboard] Wrote docs/.nojekyll", file=sys.stderr)

    # index.html
    index_html = build_index(
        positions=positions,
        trades=trades,
        regime=regime,
        exposure=exposure,
        signal=signal,
        calib=calib,
        adv=adv,
        screen_state=screen_state,
        generated_at=generated_at,
    )
    (_DOCS / "index.html").write_text(index_html, encoding="utf-8")
    print(f"[dashboard] Wrote docs/index.html ({len(index_html):,} chars)", file=sys.stderr)

    # Per-position pages
    for pos in positions:
        ticker = pos.get("ticker", "")
        if not ticker:
            continue
        rec = load_recommendation(ticker)
        detail_html = _position_detail_page(pos, rec)
        out_path = _DOCS / "positions" / f"{ticker}.html"
        out_path.write_text(detail_html, encoding="utf-8")
        print(f"[dashboard]   {ticker}: {len(detail_html):,} chars", file=sys.stderr)

    total = 2 + len(positions)
    print(f"[dashboard] Done. {total} files written to docs/", file=sys.stderr)


if __name__ == "__main__":
    main()
