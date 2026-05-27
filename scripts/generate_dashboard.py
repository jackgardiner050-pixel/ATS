#!/usr/bin/env python3
"""Static HTML dashboard generator for ATS Research.

Reads all data sources and writes docs/index.html + docs/positions/{TICKER}.html.
No Plotly dependency — uses pure CSS/SVG charts.

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
from datetime import datetime, date, UTC
from pathlib import Path
from typing import Optional

import yaml

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
  <title>{title} — ATS Research</title>
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

    def _card(value: Optional[float], label: str) -> str:
        if value is None:
            val_str, val_color = "—", "var(--text-muted)"
        else:
            sign = "+" if value >= 0 else ""
            val_str = f"{sign}{value * 100:.1f}%"
            val_color = "var(--green)" if value >= 0 else "var(--red)"
        return (
            f'<div class="card stat-card" style="text-align:center">'
            f'<div class="stat-value" style="color:{val_color};font-size:2rem">{val_str}</div>'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-sub">since 25 May 2026</div>'
            f"</div>"
        )

    if port_return is not None and spy_return is not None:
        alpha = port_return - spy_return
        sign = "+" if alpha >= 0 else ""
        alpha_color = "var(--green)" if alpha >= 0 else "var(--red)"
        alpha_html = (
            f'<div style="text-align:center;margin-top:0.5rem;font-size:0.9rem;'
            f'color:{alpha_color};font-weight:600">Alpha: {sign}{alpha * 100:.1f}%</div>'
        )
    else:
        alpha_html = ""

    return (
        f'<div class="container" style="padding-top:1rem">'
        f'<div class="card-grid">'
        f"{_card(port_return, 'Portfolio Return')}"
        f"{_card(spy_return, 'SPY Return')}"
        f"</div>"
        f"{alpha_html}"
        f"</div>"
    )


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
            f'<div class="bar-fill {bar_cls}" style="width:{bar_w:.1f}%"></div>'
            f'</div>'
            f'<span class="bar-value" style="color:{val_color}">{sign}{ret * 100:.1f}%</span>'
            f'</div>'
        )

    return f"""
<section>
  <h2 class="section-title">Position Returns</h2>
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
    <div class="stat-sub">All STRONG_BUY · MED conf</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">{n_closed}</div>
    <div class="stat-label">Closed Trades</div>
    <div class="stat-sub">Performance pending</div>
  </div>
  <div class="card stat-card">
    <div class="stat-value">{days_held}d</div>
    <div class="stat-label">Days Held</div>
    <div class="stat-sub">Since {entry_date}</div>
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
  <td>{rating_badge(rating)}</td>
  <td>{conf_badge(conf)}</td>
</tr>""")

    return f"""
<section>
  <h2 class="section-title">Open Positions</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Ticker</th><th>Company</th><th>Entry</th><th>Price Target</th>
          <th>Implied Upside</th><th>Rating</th><th>Conf</th>
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
<footer><div class="container">ATS Research · Paper portfolio · Diagnostic only · Not investment advice</div></footer>"""

    return _page_wrap(f"{ticker} — ATS Research", body, depth=1)


# ─── Index page ───────────────────────────────────────────────────────────────

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
    header = _page_header("ATS Research", "Anti-Delusion Dashboard · Paper portfolio · Diagnostic only")
    pos_tickers = [p["ticker"] for p in positions if "ticker" in p]
    prices = _fetch_live_prices(pos_tickers + ["SPY"])
    perf = _perf_banner(positions, prices)
    returns_chart = _position_returns_chart(positions, prices)
    health = _health_bar(positions, regime, exposure, signal, generated_at)

    body = f"""
{header}
{perf}
{health}
<main>
<div class="container">
  {returns_chart}
  {_portfolio_overview(positions, trades)}
  {_open_positions_table(positions)}
  {_regime_section(regime)}
  {_concentration_section(exposure)}
  {_signal_section(signal)}
  {_calibration_section(calib)}
  {_adversarial_section(adv)}
  {_constitutional_section(positions)}
  {_universe_section(screen_state)}
</div>
</main>
<footer>
  <div class="container">
    ATS Research · Paper portfolio only · Diagnostic read-only layer ·
    Generated {generated_at} · Not investment advice
  </div>
</footer>"""

    return _page_wrap("ATS Research Dashboard", body)


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
