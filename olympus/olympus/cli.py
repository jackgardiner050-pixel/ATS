"""Olympus MVP CLI — the candidate flow (§15).

`olympus decision create --candidate ORCL` runs the real end-to-end slice:
  Oracle(real ledger) → Athena-Nemesis(real critique) → Hecate(real exposure) →
  Tyche(real governance limits + survivability) → Themis-Mnemosyne(real constitution +
  correlated-council) → Zeus(synthesis) → Hermes(pathway), then records the governed decision
  to the REAL hash-chained pit_ledger. Paper-only; human authorisation required.
"""
from __future__ import annotations

import argparse
import sys

from olympus.core import config, storage
from olympus.adapters import oracle_adapter, athena_nemesis_adapter, hecate_adapter
from olympus.adapters import themis_mnemosyne_adapter as themis
from olympus.adapters import hermes_adapter
from olympus.members import tyche, zeus
from olympus.reports import zeus_report


def cmd_decision_create(ticker: str) -> int:
    rating = oracle_adapter.get_rating(ticker)
    if rating is None:
        print(f"[olympus] no Oracle rating for {ticker} in the forward-test ledger.", file=sys.stderr)
        return 2
    candidate = oracle_adapter.to_candidate(rating)
    thesis = oracle_adapter.thesis_view(rating)
    cid = candidate.candidate_id

    critique = athena_nemesis_adapter.critique(thesis, candidate_id=cid)
    exposure = hecate_adapter.assess(ticker, candidate_id=cid)
    allocation = tyche.size(thesis, critique, candidate_id=cid)
    independence = themis.evidence_independence(thesis, critique)
    governance = themis.governance_check(thesis, exposure, allocation)
    pathway = hermes_adapter.pathway(thesis, allocation)
    decision = zeus.decide(thesis, critique, exposure, allocation, governance,
                           independence, pathway, candidate_id=cid)

    # record to the REAL hash-chained decision ledger
    entry = storage.append_decision(decision.to_dict(), ticker=ticker, decision=decision.decision,
                                    data_as_of=rating["as_of_date"])
    ok, errs = storage.verify()

    report = zeus_report.render(decision)
    out = config.REPORTS_DIR / f"zeus_{cid}.md"
    out.write_text(report)

    print(report)
    print("─" * 72)
    print(f"governed_ok: {governance['governed_ok']} · constitution_violations: "
          f"{len(governance['constitution_violations'])} · override_required: {allocation.override_required}")
    print(f"recorded to REAL pit_ledger: seq #{entry['seq']} kind={entry['kind']} "
          f"hash={entry['hash'][:12]}… · chain_ok={ok} errs={errs}")
    print(f"ledger: {storage.DECISIONS}")
    print(f"report: {out}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="olympus")
    sub = p.add_subparsers(dest="cmd")
    dec = sub.add_parser("decision")
    dsub = dec.add_subparsers(dest="action")
    dc = dsub.add_parser("create"); dc.add_argument("--candidate", required=True)
    args = p.parse_args(argv)

    if args.cmd == "decision" and args.action == "create":
        return cmd_decision_create(args.candidate.upper())
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
