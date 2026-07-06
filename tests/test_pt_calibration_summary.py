"""Regression test for the pt_calibration_study summary-print crash.

The full run collected 711 OK rows correctly but crashed at the final summary because the
`flagged` column loads as OBJECT dtype (OK rows carry python bools; NO_DATA/NO_UPSIDE rows
have no `flagged` key → NaN), so `~ok["flagged"]` did BITWISE not (True→-2, False→-1) and
pandas treated the result as column labels → KeyError. This test loads a fixture results
CSV that reproduces that exact object-dtype condition and asserts summarize_results()
returns a summary instead of crashing — so a future run cannot silently lose its output.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
STUDY = ROOT / "research" / "revisions_pt_validation" / "pt_calibration_study.py"
FIXTURE = ROOT / "research" / "revisions_pt_validation" / "pt_calibration_fixture.csv"


def _load_summarize():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("ptcal_study", STUDY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.summarize_results


def test_summary_survives_object_dtype_flagged():
    df = pd.read_csv(FIXTURE)
    # precondition: the fixture reproduces the crash condition (object, not bool)
    assert df["flagged"].dtype == object, "fixture must reproduce the object-dtype flagged column"

    out = _load_summarize()(df)      # must NOT raise (the original crash)
    labels = {s["label"] for s in out}
    assert labels == {"ALL", "EX-FLAGGED"}, out

    by = {s["label"]: s for s in out}
    # 8 OK rows total; B and D are flagged → EX-FLAGGED drops exactly those two
    assert by["ALL"]["n"] == 8
    assert by["EX-FLAGGED"]["n"] == 6
    # STRONG_BUY band: A,B,D,G (all) vs A,G (ex-flagged, since B,D are flagged out)
    assert by["ALL"]["sb_n"] == 4
    assert by["EX-FLAGGED"]["sb_n"] == 2
    print("  ✓ summarize_results handles object-dtype flagged; EX-FLAGGED excludes flagged rows")


def test_summary_empty_on_too_few_rows():
    df = pd.DataFrame([{"status": "NO_DATA"}, {"status": "NO_DATA"}])
    assert _load_summarize()(df) == []      # no crash, empty summary
    print("  ✓ too few OK rows → empty summary, no crash")


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("pt_calibration summary regression tests passed.")
