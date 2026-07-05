# Research — hypothesis registry & discipline

`registry.yaml` is the append-only, hash-chained pre-registration ledger of falsifiable
hypotheses. It is the honest denominator for multiple-testing correction. See
`src/research/registry.py` (loader, hash chain, status machine) and `scripts/registry.py`
(CLI: `new` / `status` / `stats` / `queue`).

## The double-gate is a deliberate choice, not an accident (F7b)

**Candidates must clear BOTH Bonferroni-corrected significance AND the deflated Sharpe —
a deliberate double-gate accepting an elevated false-negative rate, chosen given this
operator's documented history of over-iterating on under-powered results. This is
discipline, not miscalibration.** Both gates were already being applied; this line
declares the choice. Every Stage-1 report template calls both (`src/research/corrections.py`:
`bonferroni_alpha`, `deflated_sharpe`).

## Counting rule (F7a)

The correction denominator `m` counts only entries at **TESTING or beyond**
(TESTING/FAILED/PASSED/RETIRED). REGISTERED (Stage-0) entries are free — registration is
encouraged; *initiating a test* is what spends statistical credibility. `registry.py stats`
shows both `m (correction denominator, TESTING+)` and `total entries registered`.

## Interpretation contract (F5)

Every entry declares `interpretation_contract: {licenses, does_not_license}` — in plain
language, what a PASS would actually support claiming, and the nearest tempting overclaim
it would NOT. It is a required field for new entries. Entries 001–003 predate the field and
were backfilled via an appended `SCHEMA_MIGRATION` event (overlaid at read time) so their
records — and content-hash chain — are never edited (append-only guarantee preserved).

## Queue (F7d)

`registry.py queue` ranks REGISTERED entries by `queue_priority` (stated `survival_prior` ×
`strategic_fit` if given, else prior alone), descending. Informational only — advancing an
entry to TESTING remains a human/operator act.
