"""Tests for scripts/extraction_audit.py — harness wiring (no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.extraction_audit import audit_tickers, render_markdown
from src.data.extraction_invariants import SEV_HIGH


def _good_ext(t):
    return {"revenue": 10_000_000_000, "gross_profit": 3_500_000_000,
            "operating_income": 1_500_000_000, "shares": 100_000_000,
            "net_debt": 2_000_000_000, "price_target": 120.0, "current_price": 100.0}


def _good_ref(t):
    return {"totalRevenue": 10_100_000_000, "operatingMargins": 0.15,
            "totalDebt": 3_000_000_000, "totalCash": 1_100_000_000,
            "sharesOutstanding": 101_000_000}


def _bad_ext(t):
    e = _good_ext(t); e["price_target"] = 900.0   # 9x price → SEV_HIGH
    return e


def test_audit_clean_universe_no_violations():
    v = audit_tickers(["A", "B"], extracted_fn=_good_ext, reference_fn=_good_ref)
    assert v == []
    print("  ✓ clean fetchers → no violations")


def test_audit_flags_sev_high_and_renders():
    v = audit_tickers(["BAD"], extracted_fn=_bad_ext, reference_fn=_good_ref)
    assert any(x["severity"] == SEV_HIGH for x in v)
    md = render_markdown(v, 1, "2026-07-05")
    assert "SEV_HIGH" in md and "price_target_vs_price_ratio" in md and "BAD" in md
    print("  ✓ SEV_HIGH surfaced in violations and rendered markdown")


def test_one_bad_ticker_does_not_abort_the_sweep():
    def _explode(t):
        if t == "BOOM":
            raise RuntimeError("edgar down")
        return _good_ext(t)
    v = audit_tickers(["A", "BOOM", "B"], extracted_fn=_explode, reference_fn=_good_ref)
    assert v == []          # A and B clean, BOOM skipped, no crash
    print("  ✓ a failing ticker is skipped, sweep continues")


def test_render_empty_is_valid_markdown():
    md = render_markdown([], 60, "2026-07-05")
    assert "Extraction Audit" in md and "none" in md
    print("  ✓ empty audit renders valid markdown")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("All extraction-audit harness tests passed.")
