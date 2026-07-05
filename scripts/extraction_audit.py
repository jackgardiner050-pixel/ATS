#!/usr/bin/env python3
"""Extraction audit — cross-check EDGAR-extracted fundamentals against yfinance.

For every ticker in config/universe.yaml, pull extracted fundamentals (edgar_client)
and independent yfinance references, run src/data/extraction_invariants, and write
runs/audits/extraction_audit_<date>.md (severity-sorted table + per-field drift
distribution). Exits non-zero if any SEV_HIGH violation is found, and (best-effort)
sends a Telegram alert on SEV_HIGH.

Diagnostic only — reads fundamentals, never touches ratings/positions/trades. The
invariant thresholds come from the original bug reports (KNOWN_BUGS.md) and must NOT
be loosened to make the live universe pass — a SEV_HIGH is a finding to report.

Usage:
    python scripts/extraction_audit.py
    python scripts/extraction_audit.py --tickers ACM,EMR
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import get_print
from src.data.extraction_invariants import run_invariants, SEV_HIGH, SEV_MED

print = get_print(__file__)  # noqa: A001 — ISO-ts + script-name log prefix

_ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = _ROOT / "config" / "universe.yaml"
AUDIT_DIR = _ROOT / "runs" / "audits"


# ─── data adapters (real EDGAR / yfinance; wrapped so one bad ticker can't crash) ──

def extracted_for(ticker: str) -> dict:
    """Latest-FY extracted fundamentals via edgar_client, plus PT/price from the
    most recent recommendation.json if present. Missing fields stay None."""
    out: dict = {}
    try:
        from src.data.edgar_client import fetch_company, extract_historical_metrics, init_edgar
        init_edgar()
        cd = fetch_company(ticker)
        metrics = extract_historical_metrics(cd)
        if metrics:
            latest = metrics[sorted(metrics)[-1]]
            for k in ("revenue", "cost_of_revenue", "gross_profit",
                      "operating_income", "sga", "shares", "net_debt"):
                out[k] = latest.get(k)
            if out.get("net_debt") is None:
                td, cash = latest.get("total_debt"), latest.get("cash")
                if td is not None and cash is not None:
                    out["net_debt"] = td - cash
    except Exception as e:
        print(f"  {ticker}: edgar extract failed: {e}")
    out.setdefault("price_target", None)
    out.setdefault("current_price", None)
    try:
        import json
        run_dirs = sorted((_ROOT / "runs" / ticker).glob("*/recommendation.json"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        if run_dirs:
            rec = json.loads(run_dirs[0].read_text())
            out["price_target"] = rec.get("price_target_12m") or rec.get("price_target")
            out["current_price"] = rec.get("current_price")
    except Exception:
        pass
    return out


def reference_for(ticker: str) -> dict:
    try:
        import yfinance as yf
        info = yf.Ticker(ticker.upper()).info or {}
        return {k: info.get(k) for k in
                ("totalRevenue", "grossMargins", "operatingMargins",
                 "totalDebt", "totalCash", "sharesOutstanding")}
    except Exception:
        return {}


# ─── audit core (injectable fetchers → testable without network) ─────────────

def audit_tickers(
    tickers: list[str],
    extracted_fn: Callable[[str], dict] = extracted_for,
    reference_fn: Callable[[str], dict] = reference_for,
) -> list[dict]:
    violations: list[dict] = []
    for t in tickers:
        try:
            v = run_invariants(t, extracted_fn(t), reference_fn(t))
            violations.extend(v)
        except Exception as e:
            print(f"  {t}: invariant run failed: {e}")
    return violations


_SEV_ORDER = {SEV_HIGH: 0, SEV_MED: 1}


def render_markdown(violations: list[dict], n_tickers: int, date_str: str) -> str:
    highs = [v for v in violations if v["severity"] == SEV_HIGH]
    lines = [
        f"# Extraction Audit — {date_str}",
        "",
        f"- tickers audited: **{n_tickers}**",
        f"- violations: **{len(violations)}**  (SEV_HIGH: **{len(highs)}**, "
        f"SEV_MED: **{len(violations) - len(highs)}**)",
        "",
        "> Thresholds are carried from KNOWN_BUGS.md (BUG-002/004/005/006) and are "
        "NOT tuned to the current universe. A SEV_HIGH is a finding, not a threshold bug.",
        "",
        "## Violations (severity-sorted)",
        "",
        "| severity | ticker | check | extracted | reference |",
        "|----------|--------|-------|-----------|-----------|",
    ]
    for v in sorted(violations, key=lambda x: (_SEV_ORDER.get(x["severity"], 9), x["ticker"])):
        lines.append(f"| {v['severity']} | {v['ticker']} | {v['check']} | "
                     f"{v['extracted']} | {v['reference']} |")
    if not violations:
        lines.append("| — | — | none | — | — |")

    # Drift distribution per check (count + severity split)
    lines += ["", "## Distribution per check", "",
              "| check | n | SEV_HIGH | SEV_MED |", "|-------|---|----------|---------|"]
    by_check: dict[str, list[dict]] = defaultdict(list)
    for v in violations:
        by_check[v["check"]].append(v)
    for check, vs in sorted(by_check.items()):
        nh = sum(1 for x in vs if x["severity"] == SEV_HIGH)
        lines.append(f"| {check} | {len(vs)} | {nh} | {len(vs) - nh} |")
    if not by_check:
        lines.append("| — | 0 | 0 | 0 |")
    return "\n".join(lines) + "\n"


def _alert_high(highs: list[dict], date_str: str) -> None:
    try:
        from src.telegram.client import send_message
        tickers = ", ".join(sorted({v["ticker"] for v in highs}))
        send_message(f"⚠️ Extraction audit {date_str}: {len(highs)} SEV_HIGH "
                     f"violation(s) — {tickers}. See runs/audits/.")
    except Exception as e:
        print(f"  telegram alert skipped: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit EDGAR extraction vs yfinance (diagnostic).")
    ap.add_argument("--tickers", type=str, default=None, help="comma list; overrides universe")
    ap.add_argument("--universe", type=Path, default=UNIVERSE_PATH)
    args = ap.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = [t.upper() for t in (yaml.safe_load(args.universe.read_text()) or {}).get("universe", [])]

    date_str = date.today().isoformat()
    print(f"Auditing extraction for {len(tickers)} tickers...")
    violations = audit_tickers(tickers)
    highs = [v for v in violations if v["severity"] == SEV_HIGH]

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = AUDIT_DIR / f"extraction_audit_{date_str}.md"
    out_path.write_text(render_markdown(violations, len(tickers), date_str))
    print(f"Wrote {out_path}  ({len(violations)} violations, {len(highs)} SEV_HIGH)")

    if highs:
        _alert_high(highs, date_str)
        print(f"EXIT nonzero: {len(highs)} SEV_HIGH violation(s) — report, do not suppress.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
