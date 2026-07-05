#!/usr/bin/env python3
"""Generate the PRIVATE Gaia fee report (gitignored markdown). Reads the gitignored current
allocation; writes gaia/fee_report.real.md. No personal data ever leaves this private path."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
from scripts._common import get_print
print = get_print(__file__)  # noqa: A001 — ISO-ts + script-name log prefix
sys.path.insert(0, str(_ROOT / "gaia"))
import gaia  # noqa: E402

OUT = _ROOT / "gaia" / "fee_report.real.md"   # GITIGNORED


def main() -> int:
    fa = gaia.fee_analysis(years=30)
    cur = gaia.load_current()
    if not cur or fa["current_all_in_pct"] is None:
        print("no current allocation found — nothing to report", file=sys.stderr)
        return 1

    fund = fa["current_blended_ocf_pct"]
    plat = fa["current_platform_pct"]
    fixed = fa["current_fixed_fee_gbp"]
    all_in = fa["current_all_in_pct"]
    plat_name = (cur.get("platform") or {}).get("name", "platform")
    target = cur.get("target_platform", "a commission-free broker")   # broker name from the gitignored file

    L = []
    L.append("# Gaia — true all-in fee comparison (PRIVATE)\n")
    L.append(f"> Gitignored · never published · generated {date.today().isoformat()}. "
             "Funds + platform fees are approximate — verify on the factsheets.\n")

    L.append(f"## Current setup — {cur.get('label','current')}\n")
    L.append("| Holding | Weight | OCF |")
    L.append("|---|--:|--:|")
    for h in cur["holdings"]:
        L.append(f"| {h['name']} | {h['weight']:.0%} | {h['ocf_pct']:.2f}% |")
    L.append(f"| **Blended fund OCF** | **100%** | **{fund:.2f}%** |\n")
    L.append(f"- Platform ({plat_name}): **{plat:.2f}%/yr + £{fixed:.0f}/yr** flat account fee")
    L.append(f"- **TRUE all-in cost: {fund:.2f}% (funds) + {plat:.2f}% (platform) = "
             f"`{all_in:.2f}%/yr` (+ £{fixed:.0f}/yr flat)**\n")

    L.append(f"## Gaia cores on {target} (fund OCF only — NO platform fee)\n")
    L.append("| Core | Composition | Core all-in OCF | All-in saving vs current | 30y compounding (fees alone) |")
    L.append("|---|---|--:|--:|--:|")
    for c in fa["cores"]:
        comp = " · ".join(f"{t} {w:.0%}" for t, w in c["etfs"].items())
        L.append(f"| Risk {c['risk']}/10 | {comp} | {c['blended_ocf_pct']:.3f}% | "
                 f"**{c['all_in_saving_vs_current_bps']:.0f} bps/yr** + £{fixed:.0f}/yr | "
                 f"**+{c['compounding_uplift_pct_30y']:.1f}%** |")
    L.append("")
    L.append(f"*Saving = current all-in ({all_in:.2f}%) − core fund OCF. The funds-only part of the "
             f"saving is ~{fa['cores'][0]['fund_saving_vs_current_bps']:.0f} bps; dropping the "
             f"{plat:.2f}% platform fee adds the rest. Compounding assumes equal gross returns and "
             f"counts fees only (the certain part).*\n")

    L.append("## The £%.0f/yr flat fee, as a %% (depends on balance)\n" % fixed)
    L.append("| Balance | £%.0f/yr as %%/yr |" % fixed)
    L.append("|--:|--:|")
    for bal in (5000, 10000, 20000, 50000, 100000):
        L.append(f"| £{bal:,} | {fixed/bal*100:.3f}% |")
    L.append("\n*(Generic illustration — not your actual balance. The flat fee matters more on a "
             "small pot, less on a large one; it's an additional saving on top of the % figures.)*\n")

    top = fa["cores"][0]
    L.append("## Headline\n")
    L.append(f"The real saving is **~{top['all_in_saving_vs_current_bps']/100:.2f}%/yr (+ £{fixed:.0f}/yr)** — "
             f"not the ~0.2% funds-only number — because moving to a Gaia core on {target} drops "
             f"**both** the expensive thematic fund fees **and** the {plat:.2f}% platform fee. Over 30 years "
             f"that compounds to **~+{top['compounding_uplift_pct_30y']:.0f}% more terminal wealth from fees "
             f"alone**. It is the one number in this project that is genuinely certain, requires no "
             f"prediction, and is entirely in your control.\n")

    OUT.write_text("\n".join(L))
    print(f"[gaia-report] wrote {OUT}", file=sys.stderr)
    print(f"  current all-in {all_in:.2f}%/yr (+£{fixed:.0f}) · top core saving "
          f"{top['all_in_saving_vs_current_bps']:.0f}bps · +{top['compounding_uplift_pct_30y']:.1f}% over 30y",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
