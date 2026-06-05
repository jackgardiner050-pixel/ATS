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
        "status": "Parked",
        "note":   "falsified picker — a static basket dominates the active selection (selection adds nothing)",
    },
    {
        "god":    "Oracle",
        "code":   "growth-thesis engine",
        "href":   None,
        "fn":     "Growth-thesis engine — LLM causal reasoning rates durable-vs-peaking growth on a bare "
                  "ticker; primary benchmark a growth/tech ETF (QQQ).",
        "status": "Candidate",
        "note":   "research-grade · v2 growth reorientation · no validated edge",
    },
    {
        "god":    "Hephaestus / Chronos / Artemis",
        "code":   "discovery brain",
        "href":   None,
        "fn":     "Discovery brain — Hephaestus maps each theme's value chain (leader vs second-order "
                  "bottleneck), Chronos tags lifecycle/froth, Artemis is the multi-source feed.",
        "status": "Candidate",
        "note":   "research-grade · observational · human-gated",
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
    labels = ("PAPER ONLY", "HUMAN-AUTHORISED", "NO REAL MONEY", "NO VALIDATED EDGE", "IN DEVELOPMENT")
    pills = "".join(
        f'<span style="display:inline-block;margin:0 .28rem;padding:.06rem .5rem;border:1px solid #3a2f12;'
        f'border-radius:3px;color:#e3b341;font-weight:600;letter-spacing:.02em">{t}</span>'
        for t in labels)
    return f"""<div style="background:#0d1117;border-bottom:1px solid #21262d;
padding:.4rem 0;font-size:.72rem;text-align:center;color:#8b949e">
  <div style="margin-bottom:.25rem">{pills}</div>
  <span style="margin:0 .6rem">No real orders · No broker connection · NOT investment advice</span>
  <span style="margin:0 .4rem;color:#484f58">|</span>
  <span style="margin:0 .6rem">
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
    <a href="olympus_track.html" class="lab-nav-card">
      <span class="lab-nav-title">Live Track</span>
      <span class="lab-nav-sub">Nike &amp; Iris OOS</span>
    </a>
    <a href="macro_card.html" class="lab-nav-card">
      <span class="lab-nav-title">Macro</span>
      <span class="lab-nav-sub">awareness · not a signal</span>
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


# ── v2 lead: what this is + honest verdicts + the growth experiment ───────────

def whats_this_intro() -> str:
    """Short, honest 'what this is' — the most valuable output is what does NOT work."""
    return """<section>
<div class="card" style="border-left:4px solid #bc8cff">
  <h2 style="margin:0 0 .4rem 0;font-size:1.05rem;color:#c9d1d9">What this is</h2>
  <p style="margin:0 0 .5rem 0;font-size:.86rem;color:#c9d1d9;line-height:1.55">
    A disciplined <strong>paper</strong> research project — <strong>paper-only, human-authorised,
    no real money</strong>. Its most valuable output so far is <strong>what doesn't work</strong>:
    a validation harness (point-in-time backtest + a random/passive control + a full cost model +
    a Monte-Carlo luck band) that has <strong>falsified more strategies than it has validated</strong>.
    <strong>Zero validated, decorrelated edges to date.</strong>
  </p>
  <p style="margin:0;font-size:.84rem;color:#8b949e;line-height:1.55">
    The current experiment (<strong>Olympus v2</strong>) tests one honest question:
    can disciplined <em>growth-picking</em> beat a passive <strong>growth ETF (QQQ)</strong>,
    <strong>net of cost</strong>, paper-only? The honest prior is that it may not — and a clean
    negative result would itself be a valid outcome.
  </p>
</div>
</section>"""


def honest_verdicts_leaderboard() -> str:
    """The genuine asset: validation harness + verdicts, ranked by edge vs benchmark NET OF COST."""
    # (strategy, bet, verdict, verdict_color, edge-net-of-cost read — never a raw return)
    rows = [
        ("Hades", "Crash / VIX de-risk timing overlay", "FALSIFIED",
         "#f85149", "net-negative on all 8 crash episodes once a look-ahead artifact was removed and "
                    "recovery cost counted (−1.2 to −1.5 pp/yr in calm markets)"),
        ("Caerus", "Short-horizon catalyst-momentum (liquid US equity)", "FALSIFIED",
         "#f85149", "loses to a random liquid-mover control by −1.59 pp net over 45 PIT trades; the "
                    "catalyst is anti-predictive — you buy the post-event fade"),
        ("Nemesis", "Short-horizon mean-reversion (market-neutral)", "FALSIFIED",
         "#f85149", "real gross reversal (~+17.5%/yr) but two-leg spread + CFD financing crush it to a "
                    "coin flip net (luck band straddles zero)"),
        ("Plutus", "FX carry / value (G10)", "FALSIFIED",
         "#f85149", "carry and value are real gross premia (~+2%/yr each) but the CFD swap markup eats "
                    "them whole — none beats passive net of cost"),
        ("Apollo / SCAI", "Thematic AI-infrastructure momentum", "NO EDGE",
         "#e3b341", "selection adds nothing — a static basket dominates the active picks; never beat "
                    "its own theme calls (AI-regime monoculture, 1 live position)"),
        ("Mercury / Kairos", "Post-earnings drift (liquid slice)", "PARKED · ~NULL",
         "#8b949e", "the drift lives in illiquid names the liquidity filter removes — little-to-no edge "
                    "after costs, the pre-registered prior, confirmed"),
    ]
    body = ""
    for name, bet, verdict, color, why in rows:
        body += (
            f'<tr>'
            f'<td style="padding:.4rem .5rem;color:#c9d1d9;font-weight:600">{name}</td>'
            f'<td style="padding:.4rem .5rem;color:#8b949e;font-size:.78rem">{bet}</td>'
            f'<td style="padding:.4rem .5rem;white-space:nowrap"><span style="color:{color};'
            f'font-weight:700;font-size:.76rem">{verdict}</span></td>'
            f'<td style="padding:.4rem .5rem;color:#8b949e;font-size:.78rem;line-height:1.45">{why}</td>'
            f'</tr>')
    return f"""<section>
<h2 class="section-title">Honest Verdicts — the validation harness is the asset</h2>
<div class="card" style="overflow-x:auto">
  <p style="margin:0 0 .6rem 0;font-size:.82rem;color:#8b949e;line-height:1.5">
    Ranked by <strong>edge vs benchmark, net of cost</strong> — never raw return. Two clean kills
    (Hades, Caerus) came from the <em>same discipline</em>, not cleverer strategies: remove
    look-ahead, count every cost, benchmark net-of-cost against a random/passive control with a
    luck band. <strong>A successful negative result is a valid outcome.</strong>
  </p>
  <table style="width:100%;border-collapse:collapse;font-size:.82rem">
    <thead><tr>
      <th style="text-align:left;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Strategy</th>
      <th style="text-align:left;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Bet</th>
      <th style="text-align:left;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Verdict</th>
      <th style="text-align:left;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Why (net of cost)</th>
    </tr></thead>
    <tbody>{body}</tbody>
  </table>
  <div style="margin-top:.7rem;padding:.55rem .75rem;border:1px solid #2a2d3e;border-radius:4px">
    <p style="margin:0 0 .25rem 0;font-size:.8rem;color:#e3b341;font-weight:600">The cost-access lesson</p>
    <p style="margin:0;font-size:.8rem;color:#8b949e;line-height:1.5">
      Across Caerus, Nemesis and Plutus the edges were <strong>not absent — they were real gross and
      captured by retail trading costs</strong> (spread, financing, swap). The edge isn't missing;
      the broker takes it. The real premia (value, carry, momentum, quality) are cheaply ownable via
      low-cost factor funds — not DIY-tradeable at retail cost. <strong>Capture them cheaply; don't
      trade them expensively.</strong>
    </p>
  </div>
</div>
</section>"""


def growth_v2_section() -> str:
    """Olympus v2 — the growth experiment: roster, the three arms, and the research-grade scorecard."""
    arms = [
        ("Arm A", "obvious theme leaders only", "TSM · ETN · GEV · VRT"),
        ("Arm B", "leaders + second-order bottlenecks", "TSM · ONTO · ETN · ANET"),
        ("Arm C", "second-order bottleneck names only", "ONTO · ANET · TSM"),
    ]
    arm_rows = "".join(
        f'<tr><td style="padding:.35rem .5rem;color:#c9d1d9;font-weight:600;white-space:nowrap">{a}</td>'
        f'<td style="padding:.35rem .5rem;color:#8b949e;font-size:.8rem">{desc}</td>'
        f'<td style="padding:.35rem .5rem;color:#8b949e;font-size:.78rem">{holds}</td></tr>'
        for a, desc, holds in arms)
    return f"""<section>
<h2 class="section-title">Olympus v2 — the growth experiment (early · paper)</h2>
<div class="card">
  <p style="margin:0 0 .6rem 0;font-size:.84rem;color:#c9d1d9;line-height:1.55">
    v2 reorients from non-consensus value to <strong>durable growth</strong>. <strong>Oracle</strong>
    forms a growth thesis on a bare ticker (consensus leaders are fine; the test is "real &amp;
    durable, or hype/peaking?"). The <strong>discovery brain</strong> — Hephaestus (value-chain
    leader vs second-order bottleneck), Chronos (lifecycle / froth), Artemis (multi-source) —
    surfaces candidates. A <strong>harvest-into-core</strong> mandate rides winners then banks gains
    into a passive core, with a tight thesis-break exit. Primary benchmark: a growth/tech ETF
    (<strong>QQQ</strong>) — does picking beat the basket, net of cost?
  </p>
  <table style="width:100%;border-collapse:collapse;margin-bottom:.6rem">
    <thead><tr>
      <th style="text-align:left;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Arm</th>
      <th style="text-align:left;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Discovery filter</th>
      <th style="text-align:left;padding:.3rem .5rem;color:#8b949e;font-weight:500;border-bottom:1px solid #21262d">Paper book (first run)</th>
    </tr></thead>
    <tbody>{arm_rows}</tbody>
  </table>
  <p style="margin:0 0 .5rem 0;padding:.5rem .7rem;border:1px solid #3a2f12;border-radius:4px;
            font-size:.8rem;color:#e3b341;line-height:1.5">
    ⚠ Honest caveat: the three arms are <strong>currently concentrated in AI-infrastructure and
    highly correlated</strong> (they share names — e.g. TSM appears in all three). They are
    <strong>not three independent strategies</strong> yet; treat them as one leveraged AI-infra bet
    under three discovery filters.
  </p>
  <p style="margin:0;font-size:.8rem;color:#8b949e;line-height:1.5">
    <strong>Forward scorecard: research-grade — no validated edge.</strong> Paper books opened with
    <strong>0 resolved decisions</strong> (N=0); each arm is scored vs QQQ and vs each other over the
    holding window. Nothing here is validated; the honest prior is that growth-picking may not beat
    the growth ETF net of cost.
  </p>
</div>
</section>"""
