# Constitutional Exceptions Log

One-off, human-approved exceptions to the system's hard constitutional boundaries
(research/trading ringfence, deploy guards, etc.). Each entry is a deliberate,
logged exception — NOT a change to the rules and NOT a precedent. The rules
themselves remain enforced by `tests/test_constitutional_guards.py` and
`config/constitution.yaml`. This file is separate from `docs/PROTOCOL_CHANGELOG.md`,
which is scoped only to protocol-lock re-registrations.

---

## 2026-07-05 — Research script run on the trading host (one-off)

**Exception:** `research/revisions_pt_validation/pt_calibration_study.py` was run
directly on the trading host, because `ats-research-simfin` no longer exists and no
interim research droplet was available at the time.

**Approval:** Human-approved decision (Jack Gardiner).

**Why it was acceptable in this instance:** the script is a **read-only research
script** confirmed to touch **no broker libraries**, **no trading credentials**, and
**no path in `src/paper_trading.py`'s decision logic**. It only reads EDGAR filings
(via edgartools) and yfinance prices and writes a results CSV under `research/`.

**Not a precedent:** this does **not** set precedent. Future research work should use
a dedicated research environment; this exception must **not** be treated as license to
route research onto `ats-trading` as a default going forward. When a research
environment is re-provisioned, research runs return there.
