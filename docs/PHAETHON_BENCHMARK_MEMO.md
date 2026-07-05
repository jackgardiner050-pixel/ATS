# Benchmark Consistency — Phaethon vs Olympus (2026-07-05)

## Problem
The two books currently headline **different benchmarks**: both Phaethon arms report
**vs QQQ**, while the Olympus paper book reports **vs SPY TR** (the observation protocol's
net-TR-alpha figure). A reader comparing scorecards can conflate a QQQ-relative number
with an SPY-relative one — they are not the same bar, especially in a tech-led tape.

## Recommendation: one primary benchmark per book, dual-display allowed
- **Phaethon → primary = QQQ.** Both arms are concentrated growth/tech idea-generators
  (MU, CEG, GOOGL, AVGO, NVDA-adjacent names); QQQ is the mandate-appropriate opportunity
  set. Keep it as the **headline**.
- **Olympus → primary = SPY TR.** It is a broad, sector-diversified research book gated to
  large/mid caps; SPY total return is the right bar, and it is already what
  `docs/OBSERVATION_PROTOCOL.md` §4 pre-registers (TWR vs SPY TR).
- **Dual-display is allowed** (e.g. show vs-QQQ *and* vs-SPY for context), but each book
  must have **one clearly-labeled headline figure vs its primary** — never an unlabeled
  number, and never a blended cross-book comparison (§7 no-blended rule still applies).

## Implemented (labeling/display only — NO history rewrite)
- The Phaethon arm JSON now carries `benchmark_primary: "QQQ"` and
  `benchmark_headline: "active return vs QQQ (primary)"` (render), making the headline
  benchmark explicit and machine-checkable. The dashboard panel already labels the row
  "vs QQQ (primary)".
- Olympus continues to headline SPY TR (unchanged — that is already its primary).
- No returns were recomputed or rewritten for this part; this is purely a labeling change.
