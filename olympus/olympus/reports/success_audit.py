"""Success audit (§12.5) — classify any major winner skill / luck / beta / factor.

A big winner is not proof of skill. This reads the real outcome ledger and forces every major
winner (asset return > +20%) to be classified, so beta-rides and lucky single draws are not
mistaken for repeatable edge.
"""
from __future__ import annotations

from olympus.core import storage
from olympus.core.constants import ADVISORY_FOOTER

MAJOR_THRESHOLD = 20.0   # % asset return to count as a "major winner"


def build() -> dict:
    outcomes = [e["detail"]["outcome"] for e in storage.outcomes()
                if e.get("detail", {}).get("outcome")]
    majors = [o for o in outcomes if (o.get("asset_return") or 0) >= MAJOR_THRESHOLD]
    by_class = {}
    for o in majors:
        by_class.setdefault(o.get("skill_luck_beta_classification", "unclassified"), []).append(o)
    return {"n_outcomes": len(outcomes), "n_major": len(majors), "by_class": by_class, "majors": majors}


def render(s: dict) -> str:
    L = ["# Success Audit — major winners classified", "",
         f"Outcomes recorded: {s['n_outcomes']} · major winners (≥ +{MAJOR_THRESHOLD:.0f}%): {s['n_major']}", ""]
    if not s["majors"]:
        L += ["No major winners to classify yet. (When one appears it must be labelled "
              "skill / luck / beta / factor — a big number is not proof of edge.)"]
    else:
        for cls, items in s["by_class"].items():
            L += [f"## {cls.upper()} ({len(items)})"]
            for o in items:
                L += [f"- {o.get('decision_id')}: asset {o.get('asset_return')}% "
                      f"(vs ACWI {o.get('benchmark_return')}%, vs NVDA {o.get('etf_alternative_return')}%) "
                      f"— {o.get('notes', '')}"]
            L += [""]
    L += [f"> {ADVISORY_FOOTER}"]
    return "\n".join(L) + "\n"
