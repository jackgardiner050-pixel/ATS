#!/usr/bin/env python3
"""Protocol lock — hash-verify the observation protocol + its frozen ruleset.

Mirrors the gaia/rules.yaml + gaia/discipline.py pattern (locked / registered /
lock hash, verified — never silently tuned to flatter). Guards
``docs/OBSERVATION_PROTOCOL.md`` and the exact set of files whose behavior the
protocol pre-registers, so a drift in any of them fails the test suite until a
human deliberately re-registers.

────────────────────────────────────────────────────────────────────────────
HASHING ALGORITHM (must stay reproducible — the lock file depends on it)
────────────────────────────────────────────────────────────────────────────
protocol_sha
    = sha256( bytes of docs/OBSERVATION_PROTOCOL.md ).hexdigest()

ruleset_sha  (combined hash over the frozen ruleset)
    For each path in RULESET_FILES, in THIS FIXED ORDER:
        src/paper_trading.py
        src/engine/calculator.py
        src/signals/momentum.py
        src/signals/revisions.py
        config/constitution.yaml
        config/settings.yaml
        config/universe.yaml
    compute h_i = sha256( file bytes ).hexdigest()  (64-char lowercase hex).
    Concatenate the hex strings in order into one string, no separator:
        combined = h_1 + h_2 + ... + h_7
    ruleset_sha = sha256( combined.encode("utf-8") ).hexdigest()

config/protocol_lock.yaml also stores the per-file digests under ``ruleset_files``
(same order). ``ruleset_sha`` is the authoritative gate; ``ruleset_files`` exists
only so the verifier can name *which* file drifted instead of just "hash
mismatch". Both are recomputed and checked.

────────────────────────────────────────────────────────────────────────────
RE-REGISTRATION — the ONLY sanctioned way the lock changes
────────────────────────────────────────────────────────────────────────────
The lock must never be auto-updated to make a red suite green. To change it:
  1. A human reviews the intended change to the protocol or the ruleset and
     decides it is a legitimate, deliberate re-registration (a new cohort, an
     approved crash-class fix, etc. — see docs/OBSERVATION_PROTOCOL.md §6).
  2. Run  ``python scripts/verify_protocol_lock.py --register``  to rewrite
     config/protocol_lock.yaml with the new sha(s) and today's ``registered``
     date (or hand-edit the yaml to the same effect).
  3. Record the reason — in the commit message and/or a changelog note — so the
     re-registration is auditable.
Running --register is a conscious act. Never wire it into CI or a hook.

Usage:
    python scripts/verify_protocol_lock.py            # verify; exit 0 clean, 1 on drift
    python scripts/verify_protocol_lock.py --register # (re)write the lock file
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts._common import get_print
from src.io_utils import atomic_write_text

print = get_print(__file__)  # noqa: A001 — ISO-ts + script-name log prefix

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = "config/protocol_lock.yaml"
PROTOCOL_DOC = "docs/OBSERVATION_PROTOCOL.md"

# ─── Live Pilot lock (SEPARATE artifact within the same file) ────────────────
# A clearly-named, independently-verifiable section that governs the live-pilot protocol
# DOCUMENT only. It is NOT conflated with the Cohort-1 lock above: its own protocol_sha,
# its own registration, its own re-registration. No ruleset_sha yet — the E1 execution
# code (order cards / fill journal / reconciliation) does not exist; when built, add it to
# this section's ruleset_files via a deliberate re-registration.
LIVE_PILOT_KEY = "live_pilot"
LIVE_PILOT_DOC = "docs/LIVE_PILOT_PROTOCOL.md"

# The frozen ruleset — FIXED ORDER (the combined hash depends on it). Do not
# reorder without a deliberate re-registration.
RULESET_FILES = [
    "src/paper_trading.py",
    "src/engine/calculator.py",
    "src/signals/momentum.py",
    "src/signals/revisions.py",
    "config/constitution.yaml",
    "config/settings.yaml",
    "config/universe.yaml",
]


# ─── Hashing ─────────────────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    """Lowercase hex sha256 of a file's raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_ruleset_file_shas(root: Path = REPO_ROOT) -> dict[str, str]:
    """{relpath: sha256} for each ruleset file, in fixed order. Missing → ''. """
    out: dict[str, str] = {}
    for rel in RULESET_FILES:
        p = root / rel
        out[rel] = sha256_file(p) if p.exists() else ""
    return out


def compute_ruleset_sha(root: Path = REPO_ROOT) -> str:
    """sha256 of the concatenated per-file hex digests, in fixed order."""
    combined = "".join(compute_ruleset_file_shas(root).values())
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def compute_protocol_sha(root: Path = REPO_ROOT) -> str:
    return sha256_file(root / PROTOCOL_DOC)


def compute_live_pilot_sha(root: Path = REPO_ROOT) -> str:
    return sha256_file(root / LIVE_PILOT_DOC)


# ─── Lock file I/O ───────────────────────────────────────────────────────────

def load_lock(lock_path: Path) -> dict:
    return yaml.safe_load(lock_path.read_text()) or {}


def build_lock(root: Path = REPO_ROOT, registered: str | None = None,
               lock_path: Path | None = None) -> dict:
    data = {
        "locked": True,
        "registered": registered or str(date.today()),
        "protocol_sha": compute_protocol_sha(root),
        "ruleset_sha": compute_ruleset_sha(root),
        "ruleset_files": compute_ruleset_file_shas(root),
    }
    # Preserve the SEPARATE live_pilot lock across a Cohort-1 re-registration — it is a
    # distinct artifact and is never rebuilt or cleared by the Cohort-1 --register path.
    lock_path = lock_path or (root / LOCK_FILE)
    if lock_path.exists():
        existing = load_lock(lock_path)
        if LIVE_PILOT_KEY in existing:
            data[LIVE_PILOT_KEY] = existing[LIVE_PILOT_KEY]
    return data


_LOCK_HEADER = (
    "# config/protocol_lock.yaml — LOCKED observation protocol.\n"
    "# See docs/OBSERVATION_PROTOCOL.md and scripts/verify_protocol_lock.py.\n"
    "# Verified by tests/test_protocol_lock.py — a drift here fails the suite.\n"
    "# Change ONLY via deliberate re-registration: run\n"
    "#   python scripts/verify_protocol_lock.py --register\n"
    "# then record the reason in the commit message. Never auto-update to go green.\n"
)


def register(root: Path = REPO_ROOT, lock_path: Path | None = None,
             registered: str | None = None) -> Path:
    """(Re)write the lock file from current repo state. Deliberate human action.
    Preserves the separate live_pilot lock section."""
    lock_path = lock_path or (root / LOCK_FILE)
    data = build_lock(root, registered, lock_path)
    body = yaml.dump(data, sort_keys=False, default_flow_style=False)
    atomic_write_text(lock_path, _LOCK_HEADER + body)
    return lock_path


def register_live_pilot(root: Path = REPO_ROOT, lock_path: Path | None = None,
                        registered: str | None = None) -> Path:
    """(Re)register ONLY the live_pilot lock section — protocol_sha of LIVE_PILOT_PROTOCOL.md.
    Leaves the Cohort-1 lock untouched. Deliberate human action. No ruleset_sha yet: the E1
    execution code does not exist, so this lock covers the PROTOCOL DOCUMENT only."""
    lock_path = lock_path or (root / LOCK_FILE)
    data = load_lock(lock_path) if lock_path.exists() else {}
    data[LIVE_PILOT_KEY] = {
        "locked": True,
        "registered": registered or str(date.today()),
        "protocol_doc": LIVE_PILOT_DOC,
        "protocol_sha": compute_live_pilot_sha(root),
        "ruleset_files": None,   # E1 execution code not built yet — document-only lock
    }
    body = yaml.dump(data, sort_keys=False, default_flow_style=False)
    atomic_write_text(lock_path, _LOCK_HEADER + body)
    return lock_path


def verify_live_pilot(root: Path = REPO_ROOT, lock: dict | None = None) -> list[str]:
    """Independently verify the live_pilot lock section. Returns a list of drift problems
    (empty = clean, or the section is absent)."""
    if lock is None:
        lp_file = root / LOCK_FILE
        lock = load_lock(lp_file) if lp_file.exists() else {}
    lp = lock.get(LIVE_PILOT_KEY)
    if not lp:
        return []   # no live_pilot lock registered
    problems: list[str] = []
    if lp.get("locked") is not True:
        problems.append("live_pilot: 'locked' is not true — the live pilot protocol is not locked")
    if not (root / LIVE_PILOT_DOC).exists():
        problems.append(f"MISSING  {LIVE_PILOT_DOC}  (locked live-pilot doc is gone)")
        return problems
    got = compute_live_pilot_sha(root)
    exp = lp.get("protocol_sha", "")
    if got != exp:
        problems.append(
            f"CHANGED  {LIVE_PILOT_DOC}  (live_pilot protocol_sha {exp[:12]}… → {got[:12]}…)")
    return problems


# ─── Verification ────────────────────────────────────────────────────────────

def verify(root: Path = REPO_ROOT, lock_path: Path | None = None) -> tuple[bool, list[str]]:
    """Recompute hashes from current state and compare to the lock file.

    Returns (ok, problems). `problems` names the specific file(s) that drifted.
    """
    lock_path = lock_path or (root / LOCK_FILE)
    problems: list[str] = []

    if not lock_path.exists():
        return False, [f"lock file not found: {lock_path}"]

    lock = load_lock(lock_path)
    if lock.get("locked") is not True:
        problems.append("protocol_lock.yaml: 'locked' is not true — protocol is not locked")

    # Protocol document
    got_protocol = compute_protocol_sha(root)
    exp_protocol = lock.get("protocol_sha", "")
    if got_protocol != exp_protocol:
        problems.append(
            f"CHANGED  {PROTOCOL_DOC}  (protocol_sha "
            f"{exp_protocol[:12]}… → {got_protocol[:12]}…)"
        )

    # Ruleset — per file (names the offender)
    got_files = compute_ruleset_file_shas(root)
    exp_files = lock.get("ruleset_files", {}) or {}
    for rel in RULESET_FILES:
        got = got_files.get(rel, "")
        exp = exp_files.get(rel, "")
        if got == "":
            problems.append(f"MISSING  {rel}  (file expected by the lock is gone)")
        elif exp == "":
            problems.append(f"UNTRACKED  {rel}  (no baseline hash in the lock)")
        elif got != exp:
            problems.append(f"CHANGED  {rel}  ({exp[:12]}… → {got[:12]}…)")

    # Combined ruleset hash — authoritative gate. If it drifts but every file
    # matched above, the algorithm/order itself changed rather than a file.
    got_combined = compute_ruleset_sha(root)
    exp_combined = lock.get("ruleset_sha", "")
    ruleset_file_drift = any(p.startswith(("CHANGED  src", "CHANGED  config",
                                           "MISSING", "UNTRACKED")) for p in problems)
    if got_combined != exp_combined and not ruleset_file_drift:
        problems.append(
            f"ruleset_sha mismatch ({exp_combined[:12]}… → {got_combined[:12]}…) "
            f"with no single file pinpointed — check RULESET_FILES order / algorithm"
        )

    # Live pilot lock — a separate, independently-verifiable artifact in the same file.
    problems.extend(verify_live_pilot(root, lock))

    return (len(problems) == 0), problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify (or --register) the protocol lock.")
    ap.add_argument("--register", action="store_true",
                    help="rewrite config/protocol_lock.yaml from current state (deliberate re-registration)")
    ap.add_argument("--register-live-pilot", action="store_true",
                    help="(re)register ONLY the live_pilot lock section (protocol_sha of LIVE_PILOT_PROTOCOL.md)")
    args = ap.parse_args()

    if args.register:
        path = register()
        print(f"Re-registered protocol lock → {path}")
        print("  Record the reason for this re-registration in the commit message.")
        return 0

    if args.register_live_pilot:
        path = register_live_pilot()
        print(f"Re-registered live_pilot lock (LIVE_PILOT_PROTOCOL.md) → {path}")
        print("  Record the reason for this re-registration in the commit message.")
        return 0

    ok, problems = verify()
    if ok:
        print("Protocol lock OK — protocol + ruleset match config/protocol_lock.yaml.")
        return 0

    print("PROTOCOL LOCK DRIFT — the following no longer match the registered lock:")
    for p in problems:
        print(f"  {p}")
    print("If this change is intentional, re-register deliberately: "
          "python scripts/verify_protocol_lock.py --register")
    return 1


if __name__ == "__main__":
    sys.exit(main())
