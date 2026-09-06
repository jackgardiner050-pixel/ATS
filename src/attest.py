"""Deployment attestation (B-09 / §35, §D-39).

`attest()` returns a dict describing *exactly which code is running right now*:

    {git_sha, git_sha_short, tree_path, dirty, branch, venv_hash, protocol_lock_sha,
     entrypoint, argv, config_hashes, host, user, attested_at}

It is diagnostic metadata: **every field is best-effort and nothing here ever raises**
into the caller (a broken `git` or missing venv degrades to null / "", never an exception).
Importable by both trees (ATS repo and the olympus council). The intended consumers are
each ledger record header and the B-07 heartbeat; `scripts/verify_attestation.py` compares
the recorded `git_sha` against the tree's reference SHA.
"""
from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _run(args, cwd=None, timeout=8) -> str:
    try:
        out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _tree_root(start: Path) -> Path:
    top = _run(["git", "-c", "safe.directory=*", "-C", str(start), "rev-parse",
                "--show-toplevel"])
    return Path(top) if top else start


def _sha256_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except Exception:
        return None


def _venv_hash() -> str | None:
    """sha256 over a sorted `pip freeze` (interpreter-agnostic ordering)."""
    freeze = _run([sys.executable, "-m", "pip", "freeze", "--disable-pip-version-check"],
                  timeout=30)
    if not freeze:
        return None
    norm = "\n".join(sorted(l.strip() for l in freeze.splitlines() if l.strip()))
    return hashlib.sha256(norm.encode()).hexdigest()


def attest(entrypoint: str | None = None, argv: list[str] | None = None,
           config_paths=None, tree: str | Path | None = None) -> dict:
    root = _tree_root(Path(tree) if tree else Path(__file__).resolve().parent)
    git = lambda *a: _run(["git", "-c", "safe.directory=*", "-C", str(root), *a])

    full = git("rev-parse", "HEAD")
    porcelain = git("status", "--porcelain")
    lock = root / "config" / "protocol_lock.yaml"

    cfg_hashes = {}
    for c in (config_paths or []):
        cp = Path(c)
        if not cp.is_absolute():
            cp = root / cp
        cfg_hashes[str(c)] = _sha256_file(cp)

    return {
        "git_sha": full or None,
        "git_sha_short": (full[:12] or None) if full else None,
        "tree_path": str(root),
        "dirty": bool(porcelain),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD") or None,
        "venv_hash": _venv_hash(),
        "protocol_lock_sha": _sha256_file(lock),
        "entrypoint": entrypoint or (sys.argv[0] if sys.argv else None),
        "argv": list(argv) if argv is not None else list(sys.argv),
        "config_hashes": cfg_hashes,
        "host": socket.gethostname(),
        "user": os.environ.get("USER") or os.environ.get("LOGNAME") or _run(["id", "-un"]) or None,
        "attested_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(attest(entrypoint="attest.py --selftest"), indent=2))
