#!/bin/bash
# VERBATIM copy of the off-repo droplet publisher (/root/phaethon-panel-publish.sh) as
# of migration 2026-07-05, committed for audit / provenance. NOT run — the live path is
# scripts/phaethon/publish.sh (thin wrapper) + src/phaethon/ (render + governance). Kept
# so the frozen render math can be diffed against the migrated Python. Do not edit.
# ─────────────────────────────────────────────────────────────────────────────
# Phaethon dashboard panel publisher — BOTH arms (disciplined A + aggressive B), from the consolidated
# box. Builds rich, sanitised per-arm JSON (holdings + cost-basis + return + vs-QQQ + drawdown/kill-switch)
# and pushes. Root publishes; Phaethon only writes its scorecard. Paper/research; % + market prices only.
set -uo pipefail
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ); LOG=/root/phaethon-panel.log
REPO=/root/phaethon-panel-repo
export GIT_SSH_COMMAND="ssh -i /root/.ssh/phaethon_panel_push_key -o StrictHostKeyChecking=accept-new"
# build a rich arm JSON from scorecard_public.json + book.json
build() { # $1=state-dir $2=arm-tag $3=out-file
  python3 - "$1" "$2" "$3" <<'PY'
import json,sys,datetime
sd,arm,out=sys.argv[1],sys.argv[2],sys.argv[3]
sc=json.load(open(sd+"/scorecard_public.json")); bk=json.load(open(sd+"/book.json"))
tv=bk["cash"]+sum(h["shares"]*h["last_price"] for h in bk["holdings"].values()) or 1
agg=(arm=="B")
hold=[{"ticker":t,"bought_at":round(h.get("cost_basis") or h.get("entry_price") or 0,2),
       "last":round(h["last_price"],2),"weight_pct":round(h["shares"]*h["last_price"]/tv*100,1)}
      for t,h in bk["holdings"].items()]
o={"arm":"aggressive-B" if agg else "disciplined","label":"Aggressive (B)" if agg else "Disciplined (A)",
   "mandate":"+10%/qtr, concentrated" if agg else "research-grade discipline",
   "n_positions":sc.get("n_positions"),"holdings":hold,"cash_pct":round(bk["cash"]/tv*100,1),
   "active_return_pct":sc.get("active_return_pct"),"vs_qqq_pp":sc.get("vs_qqq_pp"),
   "trend":sc.get("trend"),"n_marks":sc.get("n_marks"),
   "halted":bool(sc.get("halted")) if agg else None,"drawdown_pct":sc.get("drawdown_pct"),
   "kill_switch":"-25% peak-to-trough" if agg else "n/a (disciplined arm)",
   "mode":"paper/simulated","isolated":True,"forward_only":True,"research_grade":True,"benchmark":"QQQ",
   "as_of":datetime.date.today().isoformat()}
json.dump(o,open(out,"w"),indent=2)
PY
}
cd "$REPO" || { echo "[$TS] no repo" >> "$LOG"; exit 1; }
for a in 1 2; do
  git fetch --depth 1 origin main -q 2>>"$LOG" || true; git reset --hard origin/main -q 2>>"$LOG"
  mkdir -p "$REPO/docs/data"
  build /home/phaethon/phaethon/trader/state   A "$REPO/docs/data/phaethon_live.json"   2>>"$LOG"
  build /home/phaethon/phaethon/trader_b/state B "$REPO/docs/data/phaethon_b_live.json"  2>>"$LOG"
  # SANITISE GATE — refuse on any personal/account data
  if grep -iqE "moneybox|trading ?212|t212|gardiner|live\.co|gmail|£|real.account|real.holding|sipp|\bisa\b" "$REPO/docs/data/phaethon_live.json" "$REPO/docs/data/phaethon_b_live.json"; then
    echo "[$TS] ABORT — personal data; NOT publishing" >> "$LOG"; exit 1; fi
  git add docs/data/phaethon_live.json docs/data/phaethon_b_live.json 2>>"$LOG"
  git diff --cached --quiet && { echo "[$TS] no change" >> "$LOG"; exit 0; }
  git commit -q -m "phaethon panel refresh — both arms — $TS" 2>>"$LOG"
  git push -q origin HEAD:main 2>>"$LOG" && { echo "[$TS] published BOTH arms from droplet" >> "$LOG"; exit 0; }
  echo "[$TS] push race retry $a" >> "$LOG"
done
echo "[$TS] FAILED" >> "$LOG"; exit 1
