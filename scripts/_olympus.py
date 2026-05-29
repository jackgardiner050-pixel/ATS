"""Olympus display-layer — pantheon names, kill-switch card, roster.

Display-only shim for generate_dashboard.py.
All internal code paths, JSON keys, and file names are unchanged.
Call olympus_display_name(key) to get the rendered name for any key.
All public functions are fail-soft and return empty strings / safe HTML on error.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# ── Display-name map (code name → rendered label) ────────────────────────────
# Never rename modules/files — only the rendered HTML uses these strings.

DISPLAY_NAMES: dict[str, str] = {
    "scai":          "Apollo (SCAI)",
    "scai_ii":       "Apollo (SCAI)",
    "SCAI":          "Apollo (SCAI)",
    "SCAI-II":       "Apollo (SCAI)",
    "hermes_v2":     "Athena (Hermes v2)",
    "Hermes v2":     "Athena (Hermes v2)",
    "hermes_v3":     "Hermes (execution)",
    "Hermes v3":     "Hermes (execution)",
    "hermes_v1":     "Hermes v1 → Apollo",      # folded into Apollo/Hermes
    "Hermes v1":     "Hermes v1 → Apollo",
    "hermes":        "Hermes v1 → Apollo",
    "ats":           "Themis (ATS)",
    "ATS":           "Themis (ATS)",
    "attribution":   "Mnemosyne",
    "council":       "Zeus (Council)",
    "mercury":       "Kairos",
    "Mercury":       "Kairos",
    "valuation":     "Demeter",
    "val_v1":        "Demeter",
    "crash":         "Hades",
}

def display_name(key: str) -> str:
    return DISPLAY_NAMES.get(key, key)


# ── Pantheon roster config ────────────────────────────────────────────────────
# Drive badges from this config, not prose.

PANTHEON_ROSTER: list[dict] = [
    {
        "god":    "Themis (ATS)",
        "code":   "ATS",
        "href":   "./",
        "fn":     "Top-level paper portfolio — position tracking, governance, constitutional checks.",
        "status": "Active",
    },
    {
        "god":    "Apollo (SCAI)",
        "code":   "SCAI-II",
        "href":   "scai/",
        "fn":     "Structural/thematic AI-infrastructure monitor — selects baskets by regime signals.",
        "status": "Active",
    },
    {
        "god":    "Hermes v1 → Apollo",
        "code":   "Hermes v1",
        "href":   "hermes/",
        "fn":     "Experimental paper lab — original basket-rotation prototype. Folded into Apollo.",
        "status": "Active",
    },
    {
        "god":    "Athena (Hermes v2)",
        "code":   "Hermes v2",
        "href":   "hermes_v2/",
        "fn":     "Learning lab — generates and critiques hypotheses. Read-only; no capital.",
        "status": "Active",
    },
    {
        "god":    "Hermes (execution)",
        "code":   "Hermes v3",
        "href":   "hermes_v3/",
        "fn":     "Execution / variant arena — tests exit rules and the market-neutral spread (v3-N).",
        "status": "Active",
    },
    {
        "god":    "Kairos",
        "code":   "Mercury",
        "href":   None,
        "fn":     "Event-timing member — earnings-event decay study.",
        "status": "Parked",
        "note":   "parked — below noise floor",
    },
    {
        "god":    "Demeter",
        "code":   "val_v1",
        "href":   None,
        "fn":     "Cross-sectional value member — trailing earnings-yield spread, sector-neutral.",
        "status": "Candidate",
        "note":   "candidate — decorrelation pending ~Oct 2026",
    },
    {
        "god":    "Mnemosyne",
        "code":   "attribution",
        "href":   "council/mnemosyne.html",
        "fn":     "Attribution / live-vs-backtest reconciliation layer. Cross-cutting; not a trading member.",
        "status": "Active",
    },
    {
        "god":    "Zeus (Council)",
        "code":   "council",
        "href":   "council/",
        "fn":     "Council orchestration layer — precondition-gated; inactive until ≥2 validated members.",
        "status": "Designed",
    },
    {
        "god":    "Hades",
        "code":   "crash",
        "href":   None,
        "fn":     "Crash / tail-hedge member — not yet designed.",
        "status": "Designed",
    },
]

_STATUS_COLORS = {
    "Active":    ("#3fb950", "#1a2a1a"),
    "Candidate": ("#e3b341", "#2a2a1a"),
    "Parked":    ("#8b949e", "#1c1c1c"),
    "Designed":  ("#58a6ff", "#1a1e2e"),
}


def _status_badge(status: str) -> str:
    fg, bg = _STATUS_COLORS.get(status, ("#c9d1d9", "#21262d"))
    return (
        f'<span style="display:inline-block;font-size:.7rem;padding:.1rem .45rem;'
        f'border-radius:3px;font-weight:600;background:{bg};color:{fg}">'
        f'{status}</span>'
    )


# ── Kill-switch card ──────────────────────────────────────────────────────────

def _load_kill_switch_result() -> Optional[dict]:
    """Try to evaluate the v2 kill switch. Returns None on any error."""
    try:
        _council = Path(__file__).parent.parent.parent / "trading" / "council"
        sys.path.insert(0, str(_council))
        from mnemosyne.kill_switch_check import evaluate, KillSwitchIntegrityError
        from mnemosyne.reconciler import reconcile_all
        return evaluate(mne_reconciliation=reconcile_all())
    except Exception:
        return None


def _load_attribution_summary() -> Optional[dict]:
    """Load latest Mnemosyne reconciliation summary. Fail-soft → None."""
    try:
        _council = Path(__file__).parent.parent.parent / "trading" / "council"
        sys.path.insert(0, str(_council))
        from mnemosyne.reconciler import reconcile_all, make_summary
        results = reconcile_all()
        return {"results": results, "summary": make_summary(results)}
    except Exception:
        return None


def _load_attribution_correlation() -> Optional[dict]:
    """Load latest independence check from attribution history. Fail-soft → None."""
    try:
        _council = Path(__file__).parent.parent.parent / "trading" / "council"
        sys.path.insert(0, str(_council))
        from attribution.history import load_history
        from attribution.correlation import summarise
        from attribution.readers import read_all
        history  = load_history()
        snaps    = read_all()
        return summarise(history, snaps)
    except Exception:
        return None


def kill_switch_card() -> str:
    """Top-of-page kill-switch card. Reads v2 kill switch live. Fail-soft."""
    ks = _load_kill_switch_result()
    if ks is None:
        return (
            '<section><div class="card" style="border-left:3px solid #484f58">'
            '<p style="color:#484f58;font-size:.8rem">Kill-switch check unavailable '
            '(council module not loaded).</p></div></section>'
        )

    status    = ks.get("status", "?")
    n_val     = ks.get("n_validated", 0)
    n_need    = ks.get("min_validated_needed", 2)
    days_left = ks.get("days_to_deadline", 0)
    deadline  = ks.get("deadline", "?")
    ver       = ks.get("ks_version", "?")

    if status == "STOP":
        border, icon, color = "#f85149", "🛑", "#f85149"
    elif status == "APPROACHING":
        border, icon, color = "#e3b341", "⚠", "#e3b341"
    else:  # PASS
        border, icon, color = "#3fb950", "✓", "#3fb950"

    days_str = (
        f"{days_left} days remaining" if days_left > 0
        else f"deadline {'today' if days_left == 0 else f'{-days_left}d past'}"
    )

    return f"""<section>
<div class="card" style="border-left:4px solid {border};padding:0.75rem 1rem 0.6rem">
  <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:0.3rem">
    <span style="color:{color};font-size:1rem;font-weight:700">{icon} {status}</span>
    <span style="color:#c9d1d9;font-size:.85rem;font-weight:600">Zeus (Council) Kill Switch</span>
    <span style="margin-left:auto;font-size:.72rem;color:#484f58">v{ver} · hash-locked</span>
  </div>
  <p style="margin:0 0 .25rem 0;font-size:.82rem;color:#c9d1d9">
    <strong>{n_val}/{n_need}</strong> members validated ·
    <strong>{days_str}</strong> (deadline {deadline})
  </p>
  <p style="margin:0;font-size:.75rem;color:#8b949e">
    Validated = positive forward alpha point estimate + decorrelated (|r|&lt;0.4) + Mnemosyne-clean.
    At deadline with &lt;{n_need} legs: STOP — inconclusive is not a state that permits continuation.
  </p>
</div>
</section>"""


def status_banner(validated_count: Optional[int] = None) -> str:
    """Top status banner — paper-only, evidence-phase disclaimer."""
    if validated_count is None:
        ks = _load_kill_switch_result()
        validated_count = ks.get("n_validated", 0) if ks else 0
    min_needed = 2
    return f"""<div style="background:#0d1117;border-bottom:1px solid #21262d;
padding:.35rem 0;font-size:.72rem;text-align:center;color:#8b949e">
  <span style="margin:0 1rem">
    <span style="color:#e3b341;font-weight:600">● PAPER ONLY</span> · No real orders ·
    No broker connection · NOT investment advice
  </span>
  <span style="margin:0 1rem;color:#484f58">|</span>
  <span style="margin:0 1rem">
    <span style="color:#e3b341;font-weight:600">{validated_count} of {min_needed} members validated</span>
     — evidence phase · no durable edge claimed
  </span>
</div>"""


def olympus_lab_nav() -> str:
    """Navigation bar with Olympus / pantheon labelling."""
    return """
<nav class="lab-nav">
  <div class="container">
    <span class="lab-nav-label" style="color:#bc8cff;font-weight:700">Olympus</span>
    <a href="." class="lab-nav-card lab-nav-active">
      <span class="lab-nav-title">Themis</span>
      <span class="lab-nav-sub">ATS · Main</span>
    </a>
    <a href="scai/" class="lab-nav-card">
      <span class="lab-nav-title">Apollo</span>
      <span class="lab-nav-sub">SCAI-II</span>
    </a>
    <a href="hermes/" class="lab-nav-card">
      <span class="lab-nav-title">Hermes v1</span>
      <span class="lab-nav-sub">→ Apollo</span>
    </a>
    <a href="hermes_v2/" class="lab-nav-card">
      <span class="lab-nav-title">Athena</span>
      <span class="lab-nav-sub">Hermes v2</span>
    </a>
    <a href="hermes_v3/" class="lab-nav-card">
      <span class="lab-nav-title">Hermes</span>
      <span class="lab-nav-sub">Hermes v3</span>
    </a>
    <a href="council/" class="lab-nav-card">
      <span class="lab-nav-title">Zeus</span>
      <span class="lab-nav-sub">Council</span>
    </a>
    <a href="council/mnemosyne.html" class="lab-nav-card">
      <span class="lab-nav-title">Mnemosyne</span>
      <span class="lab-nav-sub">Attribution</span>
    </a>
  </div>
</nav>"""


def pantheon_roster_section() -> str:
    """Pantheon roster card — each member with god name, function, status badge."""
    rows_html = ""
    for m in PANTHEON_ROSTER:
        god    = m["god"]
        code   = m["code"]
        fn     = m["fn"]
        status = m["status"]
        note   = m.get("note", "")
        href   = m.get("href")

        god_cell = (
            f'<a href="{href}" style="color:#bc8cff;font-weight:600;text-decoration:none">{god}</a>'
            if href else
            f'<span style="color:#bc8cff;font-weight:600">{god}</span>'
        )
        code_cell = f'<span style="color:#8b949e;font-size:.75rem">{code}</span>'
        note_cell = (
            f'<span style="color:#8b949e;font-size:.73rem;font-style:italic">{note}</span>'
            if note else ""
        )
        rows_html += f"""<tr>
<td style="padding:.4rem .6rem">{god_cell}<br>{code_cell}</td>
<td style="padding:.4rem .6rem;font-size:.8rem;color:#c9d1d9">{fn}{f"<br>{note_cell}" if note_cell else ""}</td>
<td style="padding:.4rem .6rem;white-space:nowrap">{_status_badge(status)}</td>
</tr>"""

    return f"""<section>
<h2 class="section-title">Olympus — Pantheon Roster</h2>
<div class="card" style="overflow-x:auto">
  <table style="width:100%;border-collapse:collapse">
    <thead><tr>
      <th style="text-align:left;padding:.35rem .6rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Member</th>
      <th style="text-align:left;padding:.35rem .6rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Function</th>
      <th style="text-align:left;padding:.35rem .6rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Status</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p style="margin-top:.5rem;font-size:.72rem;color:#484f58">
    Active = running · Candidate = evidence accruing · Parked = below noise floor ·
    Designed = not yet built
  </p>
</div>
</section>"""


def mnemosyne_independence_card() -> str:
    """Holdings-overlap (Jaccard) card from the attribution layer. Fail-soft."""
    try:
        corr_summary = _load_attribution_correlation()
        if corr_summary is None:
            raise ValueError("no data")

        flagged     = corr_summary.get("flagged", False)
        flag_msg    = corr_summary.get("flag_message", "")
        max_jacc    = corr_summary.get("max_jaccard_active")
        mean_jacc   = corr_summary.get("mean_jaccard_active")
        n_hist      = corr_summary.get("n_history_records", 0)

        if flagged:
            icon  = "⚠"
            color = "#e3b341"
            label = "MONOCULTURE"
        else:
            icon  = "✓"
            color = "#3fb950"
            label = "OK"

        max_str  = f"{max_jacc:.2f}" if max_jacc is not None else "—"
        mean_str = f"{mean_jacc:.2f}" if mean_jacc is not None else "—"

        return f"""<section>
<h2 class="section-title">Mnemosyne — Independence Check</h2>
<div class="card">
  <p style="font-size:.85rem;font-weight:600;color:{color}">
    {icon} {label} — {flag_msg}
  </p>
  <p style="font-size:.78rem;color:#8b949e;margin-top:.35rem">
    Active-member holdings Jaccard: max={max_str} · mean={mean_str} ·
    history records={n_hist}
    (flag trips if max or mean &gt; 0.8 among members with non-empty holdings)
  </p>
  {'<p style="font-size:.75rem;color:#e3b341;margin-top:.3rem">⚠ Current state: SCAI, Hermes v1, and Hermes v3 all hold {VRT, SMCI} — Jaccard=1.0. Three systems, one bet. Not yet independent.</p>' if flagged else ''}
</div>
</section>"""

    except Exception:
        return (
            '<section><h2 class="section-title">Mnemosyne — Independence Check</h2>'
            '<div class="card adv-disabled">Attribution data unavailable.</div></section>'
        )


def mnemosyne_reconciliation_card() -> str:
    """Live-vs-backtest accruing state card. Fail-soft."""
    try:
        attr = _load_attribution_summary()
        if attr is None:
            raise ValueError("no data")

        results = attr.get("results", {})
        summary = attr.get("summary", {})

        n_diverged = summary.get("n_diverged", 0)
        if n_diverged:
            icon, color = "⚠", "#e3b341"
            headline = f"{n_diverged} member(s) show live-vs-backtest divergence."
        else:
            icon, color = "✓", "#3fb950"
            headline = "No live-vs-backtest divergence detected."

        rows_html = ""
        for mid, r in results.items():
            if r.get("status") == "not_built":
                continue
            dname = DISPLAY_NAMES.get(mid, mid)
            for metric, mr in r.get("metrics", {}).items():
                n     = mr.get("n_forward", 0)
                nnd   = mr.get("n_needed", 12)
                bt    = mr.get("backtest_mean")
                rv    = mr.get("realized_mean")
                flag  = mr.get("divergence_flag", False)
                bt_s  = f"{bt:+.4f}" if bt is not None else "—"
                rv_s  = f"{rv:+.4f}" if rv is not None else f"accruing ({n}/{nnd})"
                flag_s = '<span style="color:#f85149">DIVERGED</span>' if flag else "—"
                rows_html += (
                    f"<tr>"
                    f'<td style="padding:.3rem .5rem;color:#c9d1d9">{dname}</td>'
                    f'<td style="padding:.3rem .5rem;color:#8b949e;font-size:.75rem">{metric}</td>'
                    f'<td style="padding:.3rem .5rem">{bt_s}</td>'
                    f'<td style="padding:.3rem .5rem">{rv_s}</td>'
                    f'<td style="padding:.3rem .5rem">{flag_s}</td>'
                    f"</tr>"
                )

        return f"""<section>
<h2 class="section-title">Mnemosyne — Live vs Backtest</h2>
<div class="card">
  <p style="font-size:.85rem;font-weight:600;color:{color}">{icon} {headline}</p>
  <table style="width:100%;border-collapse:collapse;margin-top:.5rem;font-size:.78rem">
    <thead><tr>
      <th style="text-align:left;color:#8b949e;padding:.25rem .5rem;border-bottom:1px solid #21262d">Member</th>
      <th style="text-align:left;color:#8b949e;padding:.25rem .5rem;border-bottom:1px solid #21262d">Metric</th>
      <th style="text-align:left;color:#8b949e;padding:.25rem .5rem;border-bottom:1px solid #21262d">Backtest</th>
      <th style="text-align:left;color:#8b949e;padding:.25rem .5rem;border-bottom:1px solid #21262d">Realised</th>
      <th style="text-align:left;color:#8b949e;padding:.25rem .5rem;border-bottom:1px solid #21262d">Flag</th>
    </tr></thead>
    <tbody>{rows_html or "<tr><td colspan='5' style='color:#484f58;padding:.4rem .5rem'>No members with registered expectations.</td></tr>"}</tbody>
  </table>
  <p style="font-size:.72rem;color:#484f58;margin-top:.4rem">
    Divergence flags only after N ≥ min_forward_n observations. "Accruing" = insufficient forward data.
    <a href="council/mnemosyne.html" style="color:#58a6ff">Full Mnemosyne dashboard →</a>
  </p>
</div>
</section>"""

    except Exception:
        return (
            '<section><h2 class="section-title">Mnemosyne — Live vs Backtest</h2>'
            '<div class="card adv-disabled">Mnemosyne data unavailable.</div></section>'
        )
