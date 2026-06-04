"""Olympus MVP CLI (§15) — clarity over polish. Paper/advisory only; human authorisation required.

Commands:
  olympus decision create --candidate ORCL
  olympus override add --decision <id> --action BUY|HOLD|REDUCE|EXIT|SKIP --rationale "..."
  olympus outcome add --decision <id> --ticker T --asset-return 12 --benchmark-return 4
                      --etf-return 8 --classification skill|luck|beta|factor|unresolved [--notes ".."]
  olympus report exposure --candidate T
  olympus report scorecard|override|success|quarterly
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from olympus.core import config, storage
from olympus.adapters import oracle_adapter, athena_nemesis_adapter, hecate_adapter
from olympus.adapters import themis_mnemosyne_adapter as themis
from olympus.adapters import hermes_adapter
from olympus.members import tyche, zeus
from olympus.models.records import HumanOverride, ForwardOutcome
from olympus.reports import (zeus_report, exposure_report, forward_scorecard,
                             override_audit, success_audit, quarterly_review)


def _save(name: str, text: str):
    out = config.REPORTS_DIR / name
    out.write_text(text)
    return out


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
    entry = storage.append_decision(decision.to_dict(), ticker=ticker, decision=decision.decision,
                                    data_as_of=rating["as_of_date"])
    ok, errs = storage.verify()
    report = zeus_report.render(decision)
    out = _save(f"zeus_{cid}.md", report)
    print(report)
    print("─" * 72)
    print(f"recorded to REAL pit_ledger: seq #{entry['seq']} kind={entry['kind']} "
          f"hash={entry['hash'][:12]}… · chain_ok={ok} · governed_ok={governance['governed_ok']}")
    print(f"decision_id: {decision.decision_id}  ·  report: {out}")
    return 0


def cmd_override_add(decision_id: str, action: str, rationale: str) -> int:
    zd = next(((e.get("detail", {}) or {}).get("zeus_decision") for e in storage.decisions()
               if (e.get("detail", {}) or {}).get("zeus_decision", {}).get("decision_id") == decision_id), None)
    if zd is None:
        print(f"[olympus] decision {decision_id} not found in the decision ledger.", file=sys.stderr)
        return 2
    ov = HumanOverride(override_id=f"ovr_{decision_id}_{date.today().isoformat()}",
                       decision_id=decision_id, zeus_decision=zd["decision"], human_action=action,
                       rationale=rationale, date=date.today().isoformat())
    entry = storage.append_override(ov.to_dict(), ticker=zd.get("candidate_id", "").split("_")[-1] or "NA")
    print(f"override recorded: Zeus {zd['decision']} → human {action} (seq #{entry['seq']}, "
          f"hash {entry['hash'][:12]}…). Human authorisation is the human's; this only records it.")
    return 0


def cmd_outcome_add(args) -> int:
    rel = None
    if args.asset_return is not None and args.benchmark_return is not None:
        rel = round(args.asset_return - args.benchmark_return, 2)
    oc = ForwardOutcome(outcome_id=f"out_{args.decision}_{date.today().isoformat()}",
                        decision_id=args.decision, measurement_date=date.today().isoformat(),
                        asset_return=args.asset_return, benchmark_return=args.benchmark_return,
                        etf_alternative_return=args.etf_return, relative_return=rel,
                        skill_luck_beta_classification=args.classification,
                        conviction=args.conviction, notes=args.notes or "")
    entry = storage.append_outcome(oc.to_dict(), ticker=args.ticker.upper())
    print(f"outcome recorded for {args.decision}: asset {args.asset_return}% vs ACWI "
          f"{args.benchmark_return}% (rel {rel}%) · {args.classification} (seq #{entry['seq']}).")
    return 0


def cmd_loop_run() -> int:
    import json
    from olympus import loop
    summary = loop.run()
    print(json.dumps(summary, indent=2, default=str))
    print("\nPAPER/SIMULATED loop run complete — no human in the trade, no broker reachable. "
          "Forward scorecard is the kill-check for any future live step.")
    return 0


def cmd_report(kind: str, candidate: str | None) -> int:
    if kind == "exposure":
        exp = exposure_report.build(candidate or "ORCL"); text = exposure_report.render(exp); name = "exposure_report.md"
    elif kind == "scorecard":
        text = forward_scorecard.render(forward_scorecard.build()); name = "forward_scorecard.md"
    elif kind == "override":
        text = override_audit.render(override_audit.build()); name = "override_audit.md"
    elif kind == "success":
        text = success_audit.render(success_audit.build()); name = "success_audit.md"
    elif kind == "quarterly":
        text = quarterly_review.render(quarterly_review.build()); name = "quarterly_review.md"
    else:
        print(f"[olympus] unknown report '{kind}'", file=sys.stderr); return 2
    out = _save(name, text)
    print(text)
    print(f"\n[saved: {out}]")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="olympus")
    sub = p.add_subparsers(dest="cmd")

    dec = sub.add_parser("decision"); ds = dec.add_subparsers(dest="action")
    dc = ds.add_parser("create"); dc.add_argument("--candidate", required=True)

    ov = sub.add_parser("override"); os_ = ov.add_subparsers(dest="action")
    oa = os_.add_parser("add"); oa.add_argument("--decision", required=True)
    oa.add_argument("--action", dest="human_action", required=True)
    oa.add_argument("--rationale", required=True)

    oc = sub.add_parser("outcome"); ocs = oc.add_subparsers(dest="action")
    ocadd = ocs.add_parser("add"); ocadd.add_argument("--decision", required=True)
    ocadd.add_argument("--ticker", required=True)
    ocadd.add_argument("--asset-return", dest="asset_return", type=float)
    ocadd.add_argument("--benchmark-return", dest="benchmark_return", type=float)
    ocadd.add_argument("--etf-return", dest="etf_return", type=float)
    ocadd.add_argument("--classification", default="unresolved")
    ocadd.add_argument("--conviction", type=int, default=None)
    ocadd.add_argument("--notes", default="")

    lp = sub.add_parser("loop"); lps = lp.add_subparsers(dest="action")
    lps.add_parser("run")

    rep = sub.add_parser("report"); rep.add_argument("kind",
        choices=["exposure", "scorecard", "override", "success", "quarterly"])
    rep.add_argument("--candidate", default=None)

    args = p.parse_args(argv)
    if args.cmd == "decision" and args.action == "create":
        return cmd_decision_create(args.candidate.upper())
    if args.cmd == "loop" and args.action == "run":
        return cmd_loop_run()
    if args.cmd == "override" and args.action == "add":
        return cmd_override_add(args.decision, args.human_action, args.rationale)
    if args.cmd == "outcome" and args.action == "add":
        return cmd_outcome_add(args)
    if args.cmd == "report":
        return cmd_report(args.kind, args.candidate)
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
