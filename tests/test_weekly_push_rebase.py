"""Two-publisher race for the weekly pipeline's rebase-guarded push
(scripts/git_publish_guarded.sh), against a SANDBOXED bare remote — never the real repo.

Proves: a concurrent push (Phaethon-style) touching a different file → clean rebase, no data
loss; a genuine same-file conflict → LOUD alert + abort, no force-push, no data drop.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
GUARD = REPO / "scripts" / "git_publish_guarded.sh"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def _ident(wc):
    _git(wc, "config", "user.email", "t@t.local")
    _git(wc, "config", "user.name", "Test")


def _make_remote(tmp):
    remote = tmp / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    base = tmp / "base"
    subprocess.run(["git", "clone", "-q", str(remote), str(base)], check=True)
    _ident(base)
    (base / "docs" / "data").mkdir(parents=True)
    (base / "docs" / "data" / "phaethon_live.json").write_text('{"arm":"A","v":0}\n')
    (base / "docs" / "index.html").write_text("<html>base</html>\n")
    _git(base, "add", "-A"); _git(base, "commit", "-qm", "base"); _git(base, "push", "-q", "origin", "HEAD:main")
    return remote


def _clone(remote, dst):
    subprocess.run(["git", "clone", "-q", str(remote), str(dst)], check=True)
    _ident(dst)
    return dst


def _run_guard(wc, alert_file):
    alert = wc.parent / "alert.sh"
    alert.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$1" >> "' + str(alert_file) + '"\n')
    alert.chmod(0o755)
    env = {**os.environ, "PUBLISH_REMOTE": "origin", "PUBLISH_BRANCH": "main",
           "PUBLISH_BACKUP_REMOTE": "backup", "ALERT_CMD": str(alert)}
    return subprocess.run(["bash", str(GUARD)], cwd=str(wc), capture_output=True, text=True, env=env)


def test_concurrent_publisher_clean_rebase_no_data_loss(tmp_path):
    remote = _make_remote(tmp_path)
    weekly = _clone(remote, tmp_path / "weekly")            # weekly starts at base
    phaethon = _clone(remote, tmp_path / "phaethon")

    # Phaethon publishes first (its own file), racing ahead of the weekly.
    (phaethon / "docs" / "data" / "phaethon_live.json").write_text('{"arm":"A","v":1}\n')
    _git(phaethon, "add", "-A"); _git(phaethon, "commit", "-qm", "phaethon refresh")
    assert _git(phaethon, "push", "-q", "origin", "HEAD:main").returncode == 0

    # Weekly commits a DIFFERENT file, then guarded-publishes (must rebase over phaethon).
    (weekly / "docs" / "index.html").write_text("<html>weekly</html>\n")
    _git(weekly, "add", "-A"); _git(weekly, "commit", "-qm", "weekly dashboard")
    alert_file = tmp_path / "alerts.txt"
    r = _run_guard(weekly, alert_file)
    assert r.returncode == 0, r.stderr
    assert not alert_file.exists()                          # no alert on the happy path

    # The published remote has BOTH changes — nothing was lost or overwritten.
    check = _clone(remote, tmp_path / "check")
    _git(check, "checkout", "-q", "origin/main")
    assert (check / "docs" / "index.html").read_text() == "<html>weekly</html>\n"
    assert (check / "docs" / "data" / "phaethon_live.json").read_text() == '{"arm":"A","v":1}\n'


def test_genuine_conflict_alerts_loud_and_does_not_force_push(tmp_path):
    remote = _make_remote(tmp_path)
    weekly = _clone(remote, tmp_path / "weekly")
    phaethon = _clone(remote, tmp_path / "phaethon")

    # Both touch the SAME file with divergent content → unresolvable by rebase.
    (phaethon / "docs" / "index.html").write_text("<html>PHAETHON</html>\n")
    _git(phaethon, "add", "-A"); _git(phaethon, "commit", "-qm", "phaethon touched index")
    assert _git(phaethon, "push", "-q", "origin", "HEAD:main").returncode == 0

    (weekly / "docs" / "index.html").write_text("<html>WEEKLY</html>\n")
    _git(weekly, "add", "-A"); _git(weekly, "commit", "-qm", "weekly touched index")
    alert_file = tmp_path / "alerts.txt"
    r = _run_guard(weekly, alert_file)

    assert r.returncode != 0                                 # loud failure
    assert alert_file.exists() and "CONFLICT" in alert_file.read_text()
    # No force-push, no drop: the remote still holds PHAETHON's version untouched.
    check = _clone(remote, tmp_path / "check")
    _git(check, "checkout", "-q", "origin/main")
    assert (check / "docs" / "index.html").read_text() == "<html>PHAETHON</html>\n"
    # And the weekly left no rebase in progress.
    assert not (weekly / ".git" / "rebase-merge").exists() and not (weekly / ".git" / "rebase-apply").exists()


def test_local_backup_is_pushed_as_fallback(tmp_path):
    remote = _make_remote(tmp_path)
    backup = tmp_path / "backup.git"
    subprocess.run(["git", "init", "-q", "--bare", str(backup)], check=True)
    weekly = _clone(remote, tmp_path / "weekly")
    _git(weekly, "remote", "add", "backup", str(backup))
    (weekly / "docs" / "index.html").write_text("<html>weekly</html>\n")
    _git(weekly, "add", "-A"); _git(weekly, "commit", "-qm", "weekly")
    r = _run_guard(weekly, tmp_path / "alerts.txt")
    assert r.returncode == 0
    # backup remote received the commit (additive safety net)
    assert _git(backup, "log", "--oneline", "-1", "main").stdout.strip().endswith("weekly")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
