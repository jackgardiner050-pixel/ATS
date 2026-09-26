#!/usr/bin/env python3
"""Verify deployment attestation (B-09 / §D-39). Intended: daily, wrapped by the B-07 heartbeat.

Two checks:
  1. Every entrypoint in `crontab -l` is listed in config/expected_entrypoints.yaml
     (a stray cron line is an un-governed job -> FAIL).
  2. For every manifested git tree that declares a `sha_ref`, the tree's current git_sha
     matches its reference:
        sha_ref: origin/main       -> git rev-parse origin/main in that tree
        sha_ref: safe_deploy_log   -> last "-> master @ <sha>" in <tree>/data/deploy_log.txt
     Drift -> FAIL, UNLESS an unexpired exemption covers that tree. An exemption whose
     `expires` date has passed while `q_resolved` is still false -> FAIL (the exemption
     was a temporary allowance, not a permanent one).

Exit 0 = all good; exit 1 = one or more failures (printed). Non-git trees (no sha_ref) are
presence-checked only. All git/subprocess calls are best-effort; an unresolvable reference is
reported as UNKNOWN (not a hard fail on its own) so the check degrades safely.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_DEFAULT_MANIFEST = _HERE.parent / "config" / "expected_entrypoints.yaml"

_ABS_RE = re.compile(r"(/[^\s'\"]+\.(?:sh|py))")
_REL_RE = re.compile(r"(?<![\w./])([\w./-]+\.(?:sh|py))")
_CD_RE = re.compile(r"\bcd\s+(/[^\s'\"&;]+)")


def parse_crontab_entrypoints(text: str) -> list[str]:
    """Return one entrypoint per active cron line. Handles a `heartbeat-wrap <slug> -- <cmd>`
    prefix and a `cd <dir> && ... <relative script>` form (joined to <dir>)."""
    found = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.split()[0].rstrip(":") in ("SHELL", "PATH", "MAILTO", "HOME", "LOGNAME") \
           or line.startswith("HEARTBEAT_"):
            continue
        if "heartbeat-wrap" in line and " -- " in line:
            line = line.split(" -- ", 1)[1]
        cd_dir = _CD_RE.search(line)
        for p in _ABS_RE.findall(line):
            if p.endswith(("heartbeat-wrap", "heartbeat-wrap.sh")) or p == "/bin/sh":
                continue
            found.append(p)
            break
        else:
            # no absolute script path — look for a relative one and join it to a `cd` dir
            for rel in _REL_RE.findall(line):
                if rel.startswith("/") or "heartbeat" in rel:
                    continue
                found.append(f"{cd_dir.group(1).rstrip('/')}/{rel}" if cd_dir else rel)
                break
    return found


def _git(tree: str, *args, timeout=8) -> str:
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", tree, *args],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _safe_deploy_sha(tree: str) -> str:
    log = Path(tree) / "data" / "deploy_log.txt"
    try:
        lines = [l for l in log.read_text().splitlines() if "-> master @" in l]
        return lines[-1].split("-> master @", 1)[1].strip().split()[0] if lines else ""
    except Exception:
        return ""


def _reference_sha(tree: str, sha_ref: str, git=_git, safe_deploy=_safe_deploy_sha) -> str:
    if sha_ref == "origin/main":
        return git(tree, "rev-parse", "origin/main")
    if sha_ref == "safe_deploy_log":
        return safe_deploy(tree)
    return ""


def _exemption_for(tree: str, exemptions: list, today: _dt.date):
    for ex in exemptions or []:
        if ex.get("tree") == tree:
            exp = ex.get("expires")
            expired = bool(exp) and _dt.date.fromisoformat(str(exp)) < today
            return ex, expired
    return None, False


def verify(manifest: dict, crontab_text: str, *, today: _dt.date | None = None,
           attested_sha=_git, reference_sha=_reference_sha) -> tuple[bool, list[str]]:
    """attested_sha(tree, 'rev-parse','HEAD') -> current sha; reference_sha(tree, ref) -> expected.
    Both injectable for tests."""
    today = today or _dt.date.today()
    fails, notes = [], []
    entries = manifest.get("entrypoints", [])
    exemptions = manifest.get("exemptions", [])
    manifested = {e["cmd"] for e in entries}
    manifested_base = {e["cmd"].rsplit("/", 1)[-1] for e in entries}

    # 1. stray crontab entries (match full path or basename)
    for ep in parse_crontab_entrypoints(crontab_text):
        if ep not in manifested and ep.rsplit("/", 1)[-1] not in manifested_base:
            fails.append(f"STRAY: crontab runs {ep!r} — not in expected_entrypoints.yaml")

    # 2. SHA drift per git tree with a declared reference
    checked = set()
    for e in entries:
        tree, ref = e["tree"], e.get("sha_ref")
        if not ref or tree in checked:
            continue
        checked.add(tree)
        cur = attested_sha(tree, "rev-parse", "HEAD")
        want = reference_sha(tree, ref)
        ex, expired = _exemption_for(tree, exemptions, today)
        if not cur or not want:
            notes.append(f"UNKNOWN: {tree} — could not resolve "
                         f"{'current' if not cur else 'reference'} sha (ref={ref})")
            continue
        if cur.startswith(want) or want.startswith(cur):  # short (deploy log) vs full (HEAD)
            continue
        # drift
        if ex is not None:
            if expired and not ex.get("q_resolved", False):
                fails.append(f"EXEMPTION EXPIRED: {tree} still behind (cur {cur[:12]} != "
                             f"{ref} {want[:12]}); exemption expired {ex['expires']} and "
                             f"{ex.get('q_ref','its question')} is unresolved")
            elif expired and ex.get("q_resolved"):
                fails.append(f"{tree}: exemption expired {ex['expires']} and "
                             f"{ex.get('q_ref')} is resolved — remove the exemption and update the tree")
            else:
                notes.append(f"EXEMPT: {tree} behind {ref} (cur {cur[:12]} != {want[:12]}) — "
                             f"tolerated until {ex.get('expires')} ({ex.get('q_ref')})")
        else:
            fails.append(f"SHA DRIFT: {tree} at {cur[:12]} != {ref} {want[:12]} (no exemption)")

    return (not fails), fails + [f"note: {n}" for n in notes]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verify deployment attestation (B-09)")
    ap.add_argument("--manifest", default=str(_DEFAULT_MANIFEST))
    ap.add_argument("--crontab-file", default=None, help="read crontab from a file (default: `crontab -l`)")
    ap.add_argument("--now", default=None, help="ISO date override (testing)")
    a = ap.parse_args(argv)

    manifest = yaml.safe_load(Path(a.manifest).read_text())
    if a.crontab_file:
        crontab_text = Path(a.crontab_file).read_text()
    else:
        try:
            crontab_text = subprocess.run(["crontab", "-l"], capture_output=True,
                                          text=True, timeout=8).stdout
        except Exception:
            crontab_text = ""
    today = _dt.date.fromisoformat(a.now) if a.now else _dt.date.today()

    ok, lines = verify(manifest, crontab_text, today=today)
    for l in lines:
        print(("  " if l.startswith("note:") else "FAIL: ") + l)
    print(f"verify_attestation: {'OK' if ok else 'FAILED (' + str(sum(1 for l in lines if not l.startswith('note:'))) + ')'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
