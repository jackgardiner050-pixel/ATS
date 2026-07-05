"""Protocol-lock verification — wired into the suite so drift fails pytest.

- the live repo must match config/protocol_lock.yaml (the acceptance gate)
- a one-byte tamper in a temp copy of a ruleset file must be detected and named
- the sanctioned re-registration procedure must restore a green check
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.verify_protocol_lock import (
    verify,
    register,
    REPO_ROOT,
    RULESET_FILES,
    LOCK_FILE,
    PROTOCOL_DOC,
)


def test_lock_matches_current_repo_state():
    """The registered lock must match the current protocol + ruleset. Fails the
    full pytest run on any drift."""
    ok, problems = verify()
    assert ok, "protocol lock drift:\n" + "\n".join(problems)
    print("  ✓ live repo matches config/protocol_lock.yaml")


def _mirror_repo(dst: Path) -> Path:
    """Copy the lock file, protocol doc, and every ruleset file into `dst`,
    preserving relative paths, so verify(root=dst) works in isolation."""
    for rel in [LOCK_FILE, PROTOCOL_DOC, *RULESET_FILES]:
        src = REPO_ROOT / rel
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
    return dst


def test_one_byte_tamper_is_detected_and_named(tmp_path):
    root = _mirror_repo(tmp_path)
    # sanity: the mirror verifies clean before tampering
    ok, _ = verify(root=root, lock_path=root / LOCK_FILE)
    assert ok

    target = root / "src/paper_trading.py"
    target.write_bytes(target.read_bytes() + b"\n# tamper\n")   # one-byte-class change

    ok, problems = verify(root=root, lock_path=root / LOCK_FILE)
    assert not ok
    assert any("src/paper_trading.py" in p for p in problems), problems
    assert any(p.startswith("CHANGED") for p in problems)
    print("  ✓ tampering one ruleset file is detected and the file is named")


def test_tamper_in_protocol_doc_is_detected(tmp_path):
    root = _mirror_repo(tmp_path)
    doc = root / PROTOCOL_DOC
    doc.write_bytes(doc.read_bytes() + b"\nedited\n")
    ok, problems = verify(root=root, lock_path=root / LOCK_FILE)
    assert not ok
    assert any(PROTOCOL_DOC in p for p in problems), problems
    print("  ✓ editing the protocol doc is detected")


def test_reregistration_restores_green(tmp_path):
    """The sanctioned procedure — re-register, then verify — restores a clean check."""
    root = _mirror_repo(tmp_path)
    lock_path = root / LOCK_FILE

    target = root / "src/signals/momentum.py"
    target.write_bytes(target.read_bytes() + b"\n# deliberate approved change\n")
    ok, _ = verify(root=root, lock_path=lock_path)
    assert not ok                                   # drift detected

    register(root=root, lock_path=lock_path, registered="2026-07-06")   # human action
    ok, problems = verify(root=root, lock_path=lock_path)
    assert ok, problems                             # green again
    import yaml
    assert yaml.safe_load(lock_path.read_text())["registered"] == "2026-07-06"
    print("  ✓ re-registration restores a green verify")


if __name__ == "__main__":
    import tempfile
    test_lock_matches_current_repo_state()
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        test_one_byte_tamper_is_detected_and_named(tp / "a")
        test_tamper_in_protocol_doc_is_detected(tp / "b")
        test_reregistration_restores_green(tp / "c")
    print("All protocol-lock tests passed.")
