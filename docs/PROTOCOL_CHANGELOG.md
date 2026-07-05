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
