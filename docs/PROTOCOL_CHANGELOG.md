# Protocol Lock Changelog

Every deliberate re-registration of `config/protocol_lock.yaml` is recorded here.
The lock is NEVER auto-updated to fix drift — each entry corresponds to a
human-approved re-registration performed via the sanctioned procedure in
`scripts/verify_protocol_lock.py`'s docstring (`--register`). This sibling file is
used (rather than an in-yaml comment section) because the lock is written with
`yaml.dump`, which does not preserve comments across re-registration.

---

## 2026-07-05 — Baseline re-registration (ahead of items 10 & 4)

**Reason:** Planned re-registration ahead of honest-return-math (item 10) and
flagged-off exit-rules-v2 (item 4) changes, per human decision 2026-07-05. Baseline
confirmed clean before either change.

**Details:** `verify_protocol_lock.py --register` was run against the current repo
state and reproduced the existing `protocol_sha` and `ruleset_sha` with no change
(the lock file was byte-identical), confirming there was no pre-existing drift. This
records the deliberate decision that the two upcoming, reviewed edits to locked files
(`src/paper_trading.py` close_position accounting; `src/paper_trading.py` +
`config/settings.yaml` exit_rules_v2, default OFF) are approved and forthcoming. The
lock is re-registered again — establishing a new clean baseline — only AFTER both
changes land together, not after each individual change.

---

## 2026-07-05 — Re-registration after items 10 & 4 (new baseline)

**Reason:** Re-registration after items 10 (honest return math) and 4 (exit-rules-v2,
flag OFF) — human-approved 2026-07-05 batch.

**Details:** Both reviewed changes have now landed:
- `src/paper_trading.py` close_position — net/gross returns, dividend-adjusted total
  return, cost haircut (item 10).
- `src/paper_trading.py` evaluate_exit_v2 + process_screener_results gating, and
  `config/settings.yaml` `exit_rules_v2: false` (item 4, flag OFF, not activated).

`verify_protocol_lock.py --register` was run against this combined state, updating the
`ruleset_sha` and the per-file digests for `src/paper_trading.py` and
`config/settings.yaml` (all other ruleset files unchanged). This is the new clean
baseline; `verify_protocol_lock.py` exits 0. Any further change to a locked file will
again require a deliberate re-registration.

---

## 2026-07-05 — Baseline re-registration ahead of momentum-signal neutralization

**Reason:** Planned re-registration ahead of momentum-signal neutralization (item 8
finding: Q1−Q5 spread t=0.09, n=121). Evidence: signal-validation-studies branch.
Human-approved 2026-07-05.

**Details:** `verify_protocol_lock.py --register` was run against the current
(pre-change) state and reproduced the existing hashes (lock byte-identical),
confirming a clean baseline before the edit. The upcoming change adds an
observation-only status note to `src/signals/momentum.py` (a ruleset_file) and
neutralizes the momentum→confidence link in `src/signals/escalation.py` (NOT a
ruleset_file). The lock is re-registered again after the change lands.

---

## 2026-07-05 — Re-registration after momentum-signal neutralization (item 8)

**Reason:** Re-registered after momentum-signal neutralization (item 8). Momentum
quintile no longer affects entry confidence; still computed/logged for attribution.
Evidence-driven, human-approved 2026-07-05.

**Details:** The change landed as: (a) `src/signals/escalation.py` — momentum quintile
classified NEUTRAL always (not a ruleset_file, no hash impact); (b)
`src/signals/momentum.py` — an OBSERVATION-ONLY docstring note (a ruleset_file → its
per-file digest changed). `verify_protocol_lock.py --register` updated `ruleset_sha` and
the `src/signals/momentum.py` digest (all other ruleset files unchanged);
`verify_protocol_lock.py` exits 0 — new clean baseline. `_assign_quintiles` /
`_fetch_single_return` were preserved unchanged.

---

## 2026-07-05 — Baseline re-registration ahead of exit_rules_v2 cohort-scope guard

**Reason:** Planned re-registration ahead of exit_rules_v2 cohort-scope guard (fixing a
gap where activation would have coupled Legacy Cohort positions to the new exit logic,
contradicting protocol §1.2). Human-approved 2026-07-05.

**Details:** `verify_protocol_lock.py --register` was run against the current pre-change
state (lock byte-identical), confirming a clean baseline before the edit. The upcoming
change gates `evaluate_exit_v2` in `src/paper_trading.py` (a ruleset_file) to
`cohort_1` only. exit_rules_v2 remains false — this task fixes the gap, it does not
activate the flag.

---

## 2026-07-05 — Re-registration after exit_rules_v2 cohort-scope guard

**Reason:** Re-registered after exit_rules_v2 cohort-scope guard — v2 exit logic now
structurally excludes `legacy_pre_fix` positions regardless of flag state. Protocol §1.2
compliance restored. Human-approved 2026-07-05.

**Details:** `src/paper_trading.py` `process_screener_results` now gates both v2 passes on
`cohort == "cohort_1"`; legacy (and any non-cohort_1) positions are unreachable by
PT_HIT/TIME_STOP/STALE and continue to exit only via RATING_DOWNGRADE + their (separate)
forced-sunset mechanism. `verify_protocol_lock.py --register` updated `ruleset_sha` and the
`src/paper_trading.py` digest; `verify_protocol_lock.py` exits 0 — new clean baseline.
exit_rules_v2 stays false (activation is a separate subsequent step). NOTE: the forced-sunset
mechanism (§1.2, force-close legacy on 2026-08-23) does NOT yet exist as code — flagged as a
separate gap, not built here.

---

## 2026-07-05 — Baseline re-registration ahead of Legacy Cohort forced-sunset mechanism

**Reason:** Planned re-registration ahead of Legacy Cohort forced-sunset mechanism
(protocol §1.2, previously unimplemented gap). Human-approved 2026-07-05.

**Details:** `verify_protocol_lock.py --register` was run against the current pre-change
state (lock byte-identical), confirming a clean baseline. The upcoming change adds an
unconditional forced-sunset pass to `process_screener_results` in `src/paper_trading.py`
(a ruleset_file): legacy_pre_fix positions force-close on/after LEGACY_SUNSET_DATE
(2026-08-23) with exit_reason FORCED_SUNSET, independent of the exit_rules_v2 flag.
