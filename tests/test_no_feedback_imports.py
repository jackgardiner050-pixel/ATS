"""PERMANENT feedback-loop guard (PART E).

Hard constitutional constraint (no_live_pnl_learning): realized outcomes must never
flow back into the rating engine or signals. This asserts that attribution reporting
and the trades ledger are imported/referenced NOWHERE under src/engine or src/signals.
This is not a one-time check — it runs in CI forever. A failure means a feedback path
was introduced and must be removed, not the test.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Tokens that would indicate outcome data feeding back into decision code.
FORBIDDEN_IMPORT_SUBSTR = ["attribution_report", "attribution_log", "paper_trading", "nav_ledger"]
FORBIDDEN_TEXT = ["paper_trades.jsonl", "attribution_report", "nav_history.jsonl"]
GUARDED_DIRS = ["src/engine", "src/signals"]


def _py_files(rel_dir):
    d = ROOT / rel_dir
    return [p for p in d.rglob("*.py") if "__pycache__" not in p.parts] if d.exists() else []


def _imports(path):
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return []
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_no_outcome_data_imported_in_engine_or_signals():
    offenders = []
    for rel in GUARDED_DIRS:
        for path in _py_files(rel):
            for mod in _imports(path):
                if any(sub in mod for sub in FORBIDDEN_IMPORT_SUBSTR):
                    offenders.append(f"{path.relative_to(ROOT)} imports {mod}")
    assert not offenders, "feedback-loop import(s) in decision code:\n" + "\n".join(offenders)


def test_no_outcome_files_referenced_in_engine_or_signals():
    offenders = []
    for rel in GUARDED_DIRS:
        for path in _py_files(rel):
            text = path.read_text()
            for token in FORBIDDEN_TEXT:
                if token in text:
                    offenders.append(f"{path.relative_to(ROOT)} references {token}")
    assert not offenders, "outcome-data reference(s) in decision code:\n" + "\n".join(offenders)


if __name__ == "__main__":
    test_no_outcome_data_imported_in_engine_or_signals()
    test_no_outcome_files_referenced_in_engine_or_signals()
    print("Feedback-loop guard passed.")
