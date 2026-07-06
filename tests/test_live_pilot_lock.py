"""Live-pilot lock (a separate, independently-verifiable section of config/protocol_lock.yaml).

ACCEPTANCE: tampering with one byte of LIVE_PILOT_PROTOCOL.md fails verification; the
Cohort-1 lock remains independently verifiable and unaffected.
"""
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.verify_protocol_lock import (
    verify, verify_live_pilot, load_lock,
    REPO_ROOT, LOCK_FILE, PROTOCOL_DOC, RULESET_FILES, LIVE_PILOT_DOC, LIVE_PILOT_KEY,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_committed_live_pilot_lock_is_valid():
    lock = load_lock(REPO_ROOT / LOCK_FILE)
    lp = lock[LIVE_PILOT_KEY]
    assert lp["locked"] is True
    assert lp["protocol_doc"] == LIVE_PILOT_DOC
    assert lp["protocol_sha"] == _sha(REPO_ROOT / LIVE_PILOT_DOC)   # sha of the doc as-is
    assert lp["ruleset_files"] is None                             # no E1 code yet
    assert verify_live_pilot(REPO_ROOT, lock) == []                # clean
    print("  ✓ committed live_pilot lock matches LIVE_PILOT_PROTOCOL.md, ruleset_files=None")


def test_full_verify_passes_both_locks():
    ok, problems = verify(REPO_ROOT, lock_path=REPO_ROOT / LOCK_FILE)
    assert ok, problems     # Cohort-1 AND live_pilot both green
    print("  ✓ verify() green across both the Cohort-1 lock and the live_pilot lock")


def test_one_byte_tamper_of_live_pilot_doc_fails(tmp_path):
    for rel in (LOCK_FILE, PROTOCOL_DOC, LIVE_PILOT_DOC, *RULESET_FILES):
        out = tmp_path / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, out)
    lock = load_lock(tmp_path / LOCK_FILE)
    assert verify_live_pilot(tmp_path, lock) == []                 # clean mirror

    doc = tmp_path / LIVE_PILOT_DOC
    doc.write_bytes(doc.read_bytes() + b"X")                       # ONE byte
    problems = verify_live_pilot(tmp_path, lock)
    assert problems and any(LIVE_PILOT_DOC in p for p in problems)
    # and the full verify (both locks) also fails on it
    ok, full = verify(tmp_path, lock_path=tmp_path / LOCK_FILE)
    assert not ok and any(LIVE_PILOT_DOC in p for p in full)
    print("  ✓ one-byte edit of LIVE_PILOT_PROTOCOL.md is detected")


def test_cohort1_lock_is_independent():
    # a lock with no live_pilot section → verify_live_pilot has nothing to flag
    assert verify_live_pilot(REPO_ROOT, {}) == []
    # the two shas are distinct artifacts: the live_pilot sha is not the Cohort-1 protocol_sha
    lock = load_lock(REPO_ROOT / LOCK_FILE)
    assert lock[LIVE_PILOT_KEY]["protocol_sha"] != lock["protocol_sha"]
    print("  ✓ live_pilot lock is separate from the Cohort-1 lock (distinct shas, independent)")


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("live_pilot lock tests passed.")
