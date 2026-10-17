"""B-09 — deployment attestation + verifier."""
import datetime as dt

import pytest
import yaml

from src.attest import attest
from scripts.verify_attestation import verify, parse_crontab_entrypoints


# ── attest() ──────────────────────────────────────────────────────────────
def test_attest_returns_all_fields_and_never_raises():
    d = attest(entrypoint="x.py", argv=["x.py", "--go"],
               config_paths=["config/protocol_lock.yaml"])
    for k in ("git_sha", "tree_path", "dirty", "venv_hash", "protocol_lock_sha",
              "entrypoint", "argv", "config_hashes", "host", "user", "attested_at"):
        assert k in d
    assert d["entrypoint"] == "x.py" and d["argv"] == ["x.py", "--go"]
    assert isinstance(d["dirty"], bool)
    assert d["config_hashes"]["config/protocol_lock.yaml"] is not None


def test_attest_on_a_nonexistent_tree_degrades_not_raises():
    d = attest(tree="/no/such/tree/anywhere")
    assert d["git_sha"] is None and d["dirty"] is False  # best-effort


# ── crontab parsing ──────────────────────────────────────────────────────
def test_parse_strips_heartbeat_wrap_prefix():
    cron = (
        "SHELL=/bin/bash\n"
        "0 6 * * * /root/ops/heartbeat-wrap ats_screen -- /root/agent/run_ats_screen.sh >> /x 2>&1\n"
        "45 21 * * 1-5 /root/agent/olympus/scripts/run_olympus_loop.sh\n"
        "# a comment\n"
    )
    eps = parse_crontab_entrypoints(cron)
    assert "/root/agent/run_ats_screen.sh" in eps
    assert "/root/agent/olympus/scripts/run_olympus_loop.sh" in eps
    assert not any("heartbeat-wrap" in e for e in eps)


# ── verify() ─────────────────────────────────────────────────────────────
MANIFEST = {
    "entrypoints": [
        {"cmd": "/root/agent/olympus/scripts/run_olympus_loop.sh",
         "tree": "/root/agent/olympus", "sha_ref": "safe_deploy_log"},
        {"cmd": "/root/agent/run_ats_screen.sh",
         "tree": "/root/agent/ats-live", "sha_ref": "origin/main"},
        {"cmd": "/root/backup/run_backup.sh", "tree": "/root/backup"},
    ],
    "exemptions": [
        {"tree": "/root/agent/ats-live", "q_ref": "Q-D7", "q_resolved": False,
         "expires": "2026-12-31"},
    ],
}
CRON_CLEAN = (
    "45 21 * * 1-5 /root/agent/olympus/scripts/run_olympus_loop.sh\n"
    "0 9 * * 0 /root/agent/run_ats_screen.sh\n"
    "30 3 * * * /root/backup/run_backup.sh\n"
)


def _shas(sha_olympus="aaa", sha_atslive="bbb", ref_olympus="aaa", ref_main="ccc"):
    def attested(tree, *a):
        return {"/root/agent/olympus": sha_olympus, "/root/agent/ats-live": sha_atslive}.get(tree, "")
    def reference(tree, ref, **kw):
        return {"safe_deploy_log": ref_olympus, "origin/main": ref_main}.get(ref, "")
    return attested, reference


def test_clean_state_passes():
    a, r = _shas(sha_olympus="aaa", ref_olympus="aaa", sha_atslive="bbb", ref_main="ccc")
    ok, lines = verify(MANIFEST, CRON_CLEAN, today=dt.date(2026, 9, 3),
                       attested_sha=a, reference_sha=r)
    # ats-live drift is covered by an unexpired exemption -> not a failure
    assert ok, lines
    assert any("EXEMPT: /root/agent/ats-live" in l for l in lines)


def test_stray_crontab_entry_fails():
    a, r = _shas(sha_olympus="aaa", ref_olympus="aaa")
    cron = CRON_CLEAN + "0 4 * * * /root/rogue/mystery_job.sh\n"
    ok, lines = verify(MANIFEST, cron, today=dt.date(2026, 9, 3), attested_sha=a, reference_sha=r)
    assert not ok
    assert any("STRAY" in l and "mystery_job.sh" in l for l in lines)


def test_sha_drift_on_unexempted_tree_fails():
    a, r = _shas(sha_olympus="aaa", ref_olympus="zzz")  # olympus drifted, no exemption
    ok, lines = verify(MANIFEST, CRON_CLEAN, today=dt.date(2026, 9, 3),
                       attested_sha=a, reference_sha=r)
    assert not ok
    assert any("SHA DRIFT: /root/agent/olympus" in l for l in lines)


def test_atslive_exemption_holds_while_unexpired():
    a, r = _shas(sha_olympus="aaa", ref_olympus="aaa", sha_atslive="old", ref_main="new")
    ok, lines = verify(MANIFEST, CRON_CLEAN, today=dt.date(2026, 11, 1),
                       attested_sha=a, reference_sha=r)
    assert ok
    assert any("EXEMPT" in l and "ats-live" in l for l in lines)


def test_atslive_exemption_trips_on_expiry_with_qd7_unresolved():
    a, r = _shas(sha_olympus="aaa", ref_olympus="aaa", sha_atslive="old", ref_main="new")
    ok, lines = verify(MANIFEST, CRON_CLEAN, today=dt.date(2027, 1, 1),  # past expires 2026-12-31
                       attested_sha=a, reference_sha=r)
    assert not ok
    assert any("EXEMPTION EXPIRED" in l and "Q-D7" in l for l in lines)


def test_expired_exemption_but_qd7_resolved_still_flags_stale_tree():
    m = yaml.safe_load(yaml.safe_dump(MANIFEST))
    m["exemptions"][0]["q_resolved"] = True
    a, r = _shas(sha_olympus="aaa", ref_olympus="aaa", sha_atslive="old", ref_main="new")
    ok, lines = verify(m, CRON_CLEAN, today=dt.date(2027, 1, 1), attested_sha=a, reference_sha=r)
    assert not ok
    assert any("exemption expired" in l and "resolved" in l for l in lines)


def test_short_vs_full_sha_are_equivalent():
    """safe_deploy_log yields a short sha; `git rev-parse HEAD` yields the full one — a
    full sha that starts with the reference short sha is NOT drift."""
    m = {
        "entrypoints": [{"cmd": "/x/loop.sh", "tree": "/root/agent/olympus",
                         "sha_ref": "safe_deploy_log"}],
        "exemptions": [],
    }
    def attested(tree, *a): return "41ef8f99f52ab083619511f65a420badc3dd6781"
    def reference(tree, ref, **kw): return "41ef8f9"
    ok, lines = verify(m, "0 0 * * * /x/loop.sh\n", today=dt.date(2026, 9, 3),
                       attested_sha=attested, reference_sha=reference)
    assert ok, lines
