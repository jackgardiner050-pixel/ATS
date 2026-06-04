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
                             override_audit, success_audit, quarterly_review, monthly_rollup)
from olympus import journal, postmortem


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


def cmd_reset(venue: str, notional: float) -> int:
    from olympus.core import paper_portfolio as PP
    if venue == "t212_demo":
        from olympus.adapters.t212_demo import T212DemoBroker, T212Unavailable
        try:
            b = T212DemoBroker()                         # connectivity-checks (fail loud if no key)
            r = b.reset_to_cash()                         # close demo positions, read opening cash
            notional = r.get("opening_cash") or notional
            print(f"T212 demo reset: closed {r['closed_positions']} · opening cash {r['opening_cash']}")
        except T212Unavailable as e:
            print(f"[reset] T212 demo execution unavailable — not faked: {e}", file=sys.stderr)
            return 2
    state = PP.reset_to_cash(notional)                    # clear the internal paper book (VRT/SMCI residue)
    print(f"Olympus paper book reset to cash · notional {state['core_value']} · satellite empty "
          f"(0% → deploy-toward-target has room).")
    return 0


def cmd_artemis_discover() -> int:
    from olympus.discovery import artemis   # imported HERE (CLI); never by a decision member
    cands = artemis.discover()
    print(f"Artemis surfaced {len(cands)} NAKED candidate(s) (ticker + source + date only — no signal):")
    for c in cands:
        print(f"  {c.ticker:6} · source={c.source} · {c.discovery_date} · {c.status}")
    print("\nRESEARCH-GRADE / EXPERIMENTAL. Candidates carry no score downstream (firewall).")
    return 0


def cmd_loop_run(venue: str = "paper") -> int:
    import json
    from olympus import loop
    summary = loop.run(broker_mode=venue)
    print(json.dumps(summary, indent=2, default=str))
    print("\nPAPER/SIMULATED loop run complete — no human in the trade, no broker reachable. "
          "Forward scorecard is the kill-check for any future live step.")
    return 0


def cmd_growth_run() -> int:
    import json
    from olympus import growth_loop
    summary = growth_loop.run()
    print(json.dumps(summary, indent=2, default=str))
    print("\nPAPER/SIMULATED v2 growth run — 3 arms, internal PaperBroker (Hermes friction) only, "
          "no broker reachable. Scored vs QQQ. Human pulls any live trigger.")
    return 0


def cmd_growth_reset(notional: float) -> int:
    from olympus.core import arm_portfolio as AP
    from olympus import arms
    for a in arms.ARM_IDS:
        AP.reset_to_cash(a, notional)
    print(f"reset arm books {list(arms.ARM_IDS)} to cash · notional {notional} each (satellite empty).")
    return 0


def cmd_growth_themes() -> int:
    from olympus.discovery import observational_feed, catalyst_feed
    snap = observational_feed.snapshot()
    print(f"Live growth themes ({len(snap['theme_calls'])}):")
    for c in snap["theme_calls"]:
        print(f"  {c['theme']:20} stage={c['stage']:18} leaders={c['leaders']} bottlenecks={c['bottlenecks']}")
    print("\nCatalysts (AWARENESS only — public beneficiaries, never the private IPO):")
    for r in catalyst_feed.upcoming():
        print(f"  {r['catalyst']}  [{r.get('type')}]  private={r.get('private_company')}  "
              f"→ public beneficiaries {r['public_beneficiaries']}")
    return 0


def cmd_journal() -> int:
    text = journal.render(); _save("journal.md", text); print(text); return 0


def cmd_postmortem_add(a) -> int:
    e = postmortem.record(decision_id=a.decision, ticker=a.ticker.upper(), verdict=a.verdict,
                          classification=a.classification, why=a.why, thesis_drift=a.drift, notes=a.notes or "")
    print(f"post-mortem recorded for {a.decision}: {a.verdict} · {a.classification} (seq #{e['seq']}). "
          f"Feeds success audit + calibration; never auto-applied.")
    return 0


def cmd_screener_run() -> int:
    from olympus.benchmark import screener   # imported HERE only (CLI/measurement), never by a decision member
    picks = screener.run_and_record()
    print(f"naive screener (walled-off) recorded {len(picks)} pick(s): "
          f"{[p['ticker'] for p in picks]} — firewalled from all decision members.")
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
    elif kind == "monthly":
        text = monthly_rollup.render(monthly_rollup.build()); name = "monthly_rollup.md"
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
    lrun = lps.add_parser("run")
    lrun.add_argument("--venue", default="paper", choices=["paper", "t212_demo"])

    gr = sub.add_parser("growth"); grs = gr.add_subparsers(dest="action")
    grs.add_parser("run")
    grt = grs.add_parser("reset"); grt.add_argument("--notional", type=float, default=10000.0)
    grs.add_parser("themes")

    sub.add_parser("journal")

    pm = sub.add_parser("postmortem"); pms = pm.add_subparsers(dest="action")
    pma = pms.add_parser("add")
    pma.add_argument("--decision", required=True); pma.add_argument("--ticker", required=True)
    pma.add_argument("--verdict", required=True, choices=list(postmortem.VERDICTS))
    pma.add_argument("--classification", required=True, choices=list(postmortem.CLASSES))
    pma.add_argument("--why", required=True); pma.add_argument("--drift", default="")
    pma.add_argument("--notes", default="")

    scr = sub.add_parser("screener"); scrs = scr.add_subparsers(dest="action")
    scrs.add_parser("run")

    art = sub.add_parser("artemis"); arts = art.add_subparsers(dest="action")
    arts.add_parser("discover")

    rst = sub.add_parser("reset")
    rst.add_argument("--venue", default="paper", choices=["paper", "t212_demo"])
    rst.add_argument("--notional", type=float, default=10000.0)

    rep = sub.add_parser("report"); rep.add_argument("kind",
        choices=["exposure", "scorecard", "override", "success", "quarterly", "monthly"])
    rep.add_argument("--candidate", default=None)

    args = p.parse_args(argv)
    if args.cmd == "decision" and args.action == "create":
        return cmd_decision_create(args.candidate.upper())
    if args.cmd == "loop" and args.action == "run":
        return cmd_loop_run(getattr(args, "venue", "paper"))
    if args.cmd == "growth" and args.action == "run":
        return cmd_growth_run()
    if args.cmd == "growth" and args.action == "reset":
        return cmd_growth_reset(args.notional)
    if args.cmd == "growth" and args.action == "themes":
        return cmd_growth_themes()
    if args.cmd == "journal":
        return cmd_journal()
    if args.cmd == "postmortem" and args.action == "add":
        return cmd_postmortem_add(args)
    if args.cmd == "screener" and args.action == "run":
        return cmd_screener_run()
    if args.cmd == "artemis" and args.action == "discover":
        return cmd_artemis_discover()
    if args.cmd == "reset":
        return cmd_reset(args.venue, args.notional)
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
