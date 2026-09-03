"""B-07 — tests for scripts/heartbeat.py (per-job heartbeats + dead-man's switch).

Named test_heartbeat_jobs.py to avoid colliding with the existing
tests/test_heartbeat.py, which covers the unrelated dashboard-staleness helper
in scripts/generate_dashboard.py.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import heartbeat  # noqa: E402

UTC = timezone.utc


def _args(**kw):
    class A:
        pass

    a = A()
    for k, v in kw.items():
        setattr(a, k, v)
    return a


# ─── cron schedule maths ─────────────────────────────────────────────────────

def test_last_fire_weekday_only():
    # "0 22 * * 1-5" — Saturday 10:00 -> most recent fire is Friday 22:00
    now = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)  # Sat
    got = heartbeat.last_fire_at_or_before("0 22 * * 1-5", now)
    assert got == datetime(2026, 9, 4, 22, 0, tzinfo=UTC)


def test_last_fire_monday_only_from_wednesday():
    # "0 22 * * 1" — Wednesday -> previous Monday 22:00
    now = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)  # Wed
    got = heartbeat.last_fire_at_or_before("0 22 * * 1", now)
    assert got == datetime(2026, 9, 7, 22, 0, tzinfo=UTC)


def test_last_fire_before_todays_slot_returns_yesterday():
    # daily "5 7 * * *" at 06:00 -> yesterday 07:05
    now = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)
    got = heartbeat.last_fire_at_or_before("5 7 * * *", now)
    assert got == datetime(2026, 9, 1, 7, 5, tzinfo=UTC)


# ─── write ──────────────────────────────────────────────────────────────────

def test_write_produces_valid_record(tmp_path):
    rc = heartbeat.cmd_write(
        _args(job="demo_job", rc=0, entrypoint="/root/x.sh", tree=str(tmp_path), dir=str(tmp_path))
    )
    assert rc == 0
    rec = json.loads((tmp_path / "demo_job.json").read_text())
    assert rec["job"] == "demo_job"
    assert rec["rc"] == 0
    assert rec["entrypoint"] == "/root/x.sh"
    assert rec["host"] and rec["user"]
    # ran_at is UTC ISO-8601 with trailing Z and parses back
    assert rec["ran_at"].endswith("Z")
    parsed = heartbeat._parse_iso(rec["ran_at"])
    assert abs((datetime.now(UTC) - parsed).total_seconds()) < 120
    assert "git_sha" in rec  # best-effort; "" is fine


def test_write_records_nonzero_rc(tmp_path):
    heartbeat.cmd_write(_args(job="failer", rc=17, entrypoint="", tree="", dir=str(tmp_path)))
    assert json.loads((tmp_path / "failer.json").read_text())["rc"] == 17


def test_write_swallows_bad_dir(tmp_path):
    # a path whose parent is a regular file -> makedirs/replace will fail
    afile = tmp_path / "not_a_dir"
    afile.write_text("x")
    bad_dir = afile / "sub"
    rc = heartbeat.cmd_write(_args(job="j", rc=0, entrypoint="", tree="", dir=str(bad_dir)))
    assert rc == 0  # never fails the caller
    assert not (bad_dir / "j.json").exists()


# ─── check ──────────────────────────────────────────────────────────────────

CONF = """
defaults:
  host: test
jobs:
  - name: nightly
    entrypoint: /root/nightly.sh
    schedule: "0 22 * * *"
    owner_user: root
    grace_minutes: 60
    tree: /root
"""


def _write_conf(tmp_path):
    p = tmp_path / "expected_jobs.yaml"
    p.write_text(CONF)
    return p


def _hb(hb_dir, name, ran_at, rc=0):
    hb_dir.mkdir(parents=True, exist_ok=True)
    (hb_dir / f"{name}.json").write_text(
        json.dumps({"job": name, "ran_at": ran_at, "rc": rc, "git_sha": "abc1234",
                    "entrypoint": "/root/nightly.sh", "host": "h", "user": "root"})
    )


def _check(tmp_path, now, **over):
    hb_dir = tmp_path / "hb"
    alert_dir = tmp_path / "alerts"
    a = _args(
        config=str(_write_conf(tmp_path)),
        now=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        dir=str(hb_dir),
        alert_dir=str(alert_dir),
        health_json=str(tmp_path / "health.json"),
        health_txt=str(tmp_path / "health.txt"),
        dms_url="",
        strict=False,
    )
    for k, v in over.items():
        setattr(a, k, v)
    rc = heartbeat.cmd_check(a)
    return rc, hb_dir, alert_dir, tmp_path


def test_check_flags_stale_job(tmp_path):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    hb_dir = tmp_path / "hb"
    # last run was 2 days ago -> predates the most recent 22:00 fire
    _hb(hb_dir, "nightly", "2026-09-01T22:00:05Z", rc=0)
    rc, hb_dir, alert_dir, _ = _check(tmp_path, now)
    assert rc == 0
    flag = alert_dir / "ALERT_nightly_heartbeat.flag"
    assert flag.exists()
    assert "STALE" in flag.read_text()
    health = json.loads((tmp_path / "health.json").read_text())
    assert health["ok"] is False
    assert "nightly" in health["alerts"]


def test_check_flags_bad_rc(tmp_path):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    hb_dir = tmp_path / "hb"
    _hb(hb_dir, "nightly", "2026-09-02T22:00:03Z", rc=1)  # ran on time, but failed
    rc, hb_dir, alert_dir, _ = _check(tmp_path, now)
    flag = alert_dir / "ALERT_nightly_heartbeat.flag"
    assert flag.exists()
    assert "rc=1" in flag.read_text()


def test_check_no_flag_when_on_time_and_rc0(tmp_path):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    hb_dir = tmp_path / "hb"
    _hb(hb_dir, "nightly", "2026-09-02T22:01:00Z", rc=0)  # last night's fire, ok
    rc, hb_dir, alert_dir, _ = _check(tmp_path, now)
    assert rc == 0
    assert not (alert_dir / "ALERT_nightly_heartbeat.flag").exists()
    health = json.loads((tmp_path / "health.json").read_text())
    assert health["ok"] is True
    assert health["jobs"][0]["status"] == "OK"


def test_check_flags_missing_heartbeat(tmp_path):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    rc, hb_dir, alert_dir, _ = _check(tmp_path, now)  # no heartbeat written at all
    assert (alert_dir / "ALERT_nightly_heartbeat.flag").exists()
    assert "MISSING" in (alert_dir / "ALERT_nightly_heartbeat.flag").read_text()


def test_check_clears_flag_on_recovery(tmp_path):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    alert_dir = tmp_path / "alerts"
    alert_dir.mkdir()
    stale_flag = alert_dir / "ALERT_nightly_heartbeat.flag"
    stale_flag.write_text("old alert\n")
    _hb(tmp_path / "hb", "nightly", "2026-09-02T22:01:00Z", rc=0)
    _check(tmp_path, now)
    assert not stale_flag.exists()


def test_check_missing_dms_url_no_crash_no_ping(tmp_path, monkeypatch, capsys):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    called = []
    monkeypatch.setattr(heartbeat, "_dms_ping", lambda *a, **k: called.append(a) or (True, "x"))
    monkeypatch.delenv("HEARTBEAT_DMS_URL", raising=False)
    monkeypatch.delenv("HEARTBEAT_DMS_URL_FILE", raising=False)
    _hb(tmp_path / "hb", "nightly", "2026-09-02T22:01:00Z", rc=0)  # all clear
    rc, *_ = _check(tmp_path, now)
    assert rc == 0
    assert called == []  # no URL resolved -> no ping attempted
    assert "HEARTBEAT_DMS_URL unset" in capsys.readouterr().out


def test_check_dms_pinged_only_on_all_clear(tmp_path, monkeypatch):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    calls = []
    monkeypatch.setattr(heartbeat, "_dms_ping", lambda url, **k: calls.append(url) or (True, "HTTP 200"))

    # 1) alerting run -> NOT pinged
    _hb(tmp_path / "hb", "nightly", "2026-09-01T22:00:00Z", rc=0)  # stale
    _check(tmp_path, now, dms_url="https://dms.example/ping")
    assert calls == []

    # 2) healthy run -> pinged exactly once
    _hb(tmp_path / "hb", "nightly", "2026-09-02T22:00:30Z", rc=0)
    _check(tmp_path, now, dms_url="https://dms.example/ping")
    assert calls == ["https://dms.example/ping"]


def test_check_reads_dms_url_from_file(tmp_path, monkeypatch):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    secret = tmp_path / "heartbeat.env"
    secret.write_text("# dead man switch\nHEARTBEAT_DMS_URL=https://dms.example/from-file\n")
    monkeypatch.delenv("HEARTBEAT_DMS_URL", raising=False)
    monkeypatch.setenv("HEARTBEAT_DMS_URL_FILE", str(secret))
    calls = []
    monkeypatch.setattr(heartbeat, "_dms_ping", lambda url, **k: calls.append(url) or (True, "ok"))
    _hb(tmp_path / "hb", "nightly", "2026-09-02T22:00:30Z", rc=0)
    _check(tmp_path, now, dms_url="")
    assert calls == ["https://dms.example/from-file"]


def test_check_health_table_rendered(tmp_path):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    _hb(tmp_path / "hb", "nightly", "2026-09-02T22:00:30Z", rc=0)
    _check(tmp_path, now)
    txt = (tmp_path / "health.txt").read_text()
    assert "JOB" in txt and "STATUS" in txt and "nightly" in txt
    blob = json.loads((tmp_path / "health.json").read_text())
    assert blob["jobs"][0]["name"] == "nightly"
    assert "generated_at" in blob


def test_mini_yaml_matches_pyyaml_on_real_config():
    """The built-in fallback parser must produce the SAME job list as PyYAML on
    the real registry (it is the parser `check` uses if `import yaml` ever fails).
    """
    yaml = pytest.importorskip("yaml")
    cfg_path = Path(__file__).resolve().parent.parent / "config" / "expected_jobs.yaml"
    text = cfg_path.read_text()
    mini = heartbeat._mini_yaml(text)
    full = yaml.safe_load(text)

    mini_jobs = {j["name"]: j for j in mini["jobs"]}
    full_jobs = {j["name"]: j for j in full["jobs"]}
    assert set(mini_jobs) == set(full_jobs)
    assert "backup" in mini_jobs and "heartbeat_check" in mini_jobs

    fields = {"name", "entrypoint", "schedule", "owner_user", "grace_minutes", "tree"}
    for name, fj in full_jobs.items():
        mj = mini_jobs[name]
        for k in fields:
            if k in fj:
                assert mj.get(k) == fj.get(k), (name, k, mj.get(k), fj.get(k))
        assert isinstance(mj["grace_minutes"], int)
        # schedule must be parseable by the cron evaluator
        assert heartbeat.last_fire_at_or_before(
            mj["schedule"], datetime(2026, 9, 3, 6, 0, tzinfo=UTC)) is not None

    # the checker's own entry carries the 25h self-grace from BLOCKER 1
    assert full_jobs["heartbeat_check"]["grace_minutes"] == 1500


# ─── BLOCKER 1 — heartbeat_check self-liveness ──────────────────────────────

SELF_CONF = """
defaults:
  host: test
jobs:
  - name: heartbeat_check
    entrypoint: /root/ops/heartbeat.py check
    schedule: "0 6 * * *"
    owner_user: root
    grace_minutes: 1500
    tree: /root/ops
"""


def _self_check(tmp_path, now, age_hours, monkeypatch):
    """Run `check` on a registry that is ONLY heartbeat_check, with its own
    heartbeat `age_hours` old. Returns (health_blob, alert_dir, dms_calls)."""
    (tmp_path / "expected_jobs.yaml").write_text(SELF_CONF)
    hb_dir = tmp_path / "hb"
    hb_dir.mkdir()
    ran = (now - timedelta(hours=age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (hb_dir / "heartbeat_check.json").write_text(json.dumps(
        {"job": "heartbeat_check", "ran_at": ran, "rc": 0, "git_sha": "",
         "entrypoint": "x", "host": "h", "user": "root"}))
    alert_dir = tmp_path / "alerts"
    calls = []
    monkeypatch.setattr(heartbeat, "_dms_ping",
                        lambda url, **k: calls.append(url) or (True, "HTTP 200"))
    a = _args(
        config=str(tmp_path / "expected_jobs.yaml"),
        now=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        dir=str(hb_dir), alert_dir=str(alert_dir),
        health_json=str(tmp_path / "health.json"),
        health_txt=str(tmp_path / "health.txt"),
        dms_url="https://dms.example/ping", strict=False,
    )
    rc = heartbeat.cmd_check(a)
    assert rc == 0
    blob = json.loads((tmp_path / "health.json").read_text())
    return blob, alert_dir, calls


def test_self_check_stale_and_dms_withheld_when_26h_old(tmp_path, monkeypatch):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    blob, alert_dir, calls = _self_check(tmp_path, now, 26, monkeypatch)
    row = blob["jobs"][0]
    assert row["status"] == "STALE"
    assert blob["ok"] is False
    assert (alert_dir / "ALERT_heartbeat_check_heartbeat.flag").exists()
    assert calls == []  # a dead checker must NOT ping the dead-man's switch


def test_self_check_ok_when_20h_old(tmp_path, monkeypatch):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    blob, alert_dir, calls = _self_check(tmp_path, now, 20, monkeypatch)
    row = blob["jobs"][0]
    assert row["status"] == "OK"
    assert blob["ok"] is True
    assert not (alert_dir / "ALERT_heartbeat_check_heartbeat.flag").exists()
    assert calls == ["https://dms.example/ping"]


def test_self_check_late_run_does_not_self_flag(tmp_path, monkeypatch):
    # checker fires 35 min late; its last (on-time) run was ~24h05m ago -> still OK
    now = datetime(2026, 9, 3, 6, 35, tzinfo=UTC)
    blob, _alert_dir, _calls = _self_check(tmp_path, now, 24.0, monkeypatch)
    assert blob["jobs"][0]["status"] == "OK"


def test_self_check_missing_heartbeat_flags(tmp_path, monkeypatch):
    (tmp_path / "expected_jobs.yaml").write_text(SELF_CONF)
    calls = []
    monkeypatch.setattr(heartbeat, "_dms_ping",
                        lambda url, **k: calls.append(url) or (True, "x"))
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    a = _args(
        config=str(tmp_path / "expected_jobs.yaml"),
        now=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        dir=str(tmp_path / "hb"), alert_dir=str(tmp_path / "alerts"),
        health_json=str(tmp_path / "h.json"), health_txt=str(tmp_path / "h.txt"),
        dms_url="https://dms.example/ping", strict=False,
    )
    heartbeat.cmd_check(a)
    blob = json.loads((tmp_path / "h.json").read_text())
    assert blob["jobs"][0]["status"] == "MISSING"
    assert blob["ok"] is False
    assert calls == []


# ─── BLOCKER 2 — seed ──────────────────────────────────────────────────────

def _real_cfg():
    return str(Path(__file__).resolve().parent.parent / "config" / "expected_jobs.yaml")


def test_seed_then_check_reports_zero_alerts(tmp_path, monkeypatch):
    hb_dir = tmp_path / "hb"
    calls = []
    monkeypatch.setattr(heartbeat, "_dms_ping",
                        lambda url, **k: calls.append(url) or (True, "HTTP 200"))
    rc = heartbeat.cmd_seed(_args(config=_real_cfg(), dir=str(hb_dir), now=""))
    assert rc == 0
    # every registry job now has a seeded record
    seeded = list(hb_dir.glob("*.json"))
    assert len(seeded) >= 21
    rec = json.loads(seeded[0].read_text())
    assert rec["seeded"] is True and rec["rc"] == 0

    a = _args(
        config=_real_cfg(), now="",
        dir=str(hb_dir), alert_dir=str(tmp_path / "al"),
        health_json=str(tmp_path / "h.json"), health_txt=str(tmp_path / "h.txt"),
        dms_url="https://dms.example/ping", strict=False,
    )
    assert heartbeat.cmd_check(a) == 0
    blob = json.loads((tmp_path / "h.json").read_text())
    assert blob["ok"] is True
    assert blob["alerts"] == []
    assert calls == ["https://dms.example/ping"]      # green board -> DMS pinged
    assert not any((tmp_path / "al").glob("ALERT_*"))


def test_seed_keeps_newer_real_record(tmp_path):
    hb_dir = tmp_path / "hb"
    hb_dir.mkdir()
    fresh = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (hb_dir / "backup.json").write_text(json.dumps(
        {"job": "backup", "ran_at": fresh, "rc": 0, "git_sha": "real123",
         "entrypoint": "/root/backup/run_backup.sh", "host": "h", "user": "root"}))
    heartbeat.cmd_seed(_args(config=_real_cfg(), dir=str(hb_dir), now=""))
    rec = json.loads((hb_dir / "backup.json").read_text())
    assert "seeded" not in rec          # real, newer record left untouched
    assert rec["git_sha"] == "real123"


# ─── SHOULD-FIX 3 — one bad registry entry does not kill the check ──────────

BAD_CONF = """
defaults:
  host: test
jobs:
  - name: good_job
    entrypoint: /root/good.sh
    schedule: "0 22 * * *"
    owner_user: root
    grace_minutes: 60
    tree: /root
  - name: bad_job
    entrypoint: /root/bad.sh
    schedule: "@daily"
    owner_user: root
    grace_minutes: 60
    tree: /root
"""


def test_check_bad_entry_flagged_good_entry_still_evaluated(tmp_path):
    (tmp_path / "expected_jobs.yaml").write_text(BAD_CONF)
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    _hb(tmp_path / "hb", "good_job", "2026-09-02T22:00:05Z", rc=0)
    a = _args(
        config=str(tmp_path / "expected_jobs.yaml"),
        now=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        dir=str(tmp_path / "hb"), alert_dir=str(tmp_path / "al"),
        health_json=str(tmp_path / "h.json"), health_txt=str(tmp_path / "h.txt"),
        dms_url="", strict=False,
    )
    assert heartbeat.cmd_check(a) == 0
    blob = json.loads((tmp_path / "h.json").read_text())
    by = {r["name"]: r for r in blob["jobs"]}
    assert by["good_job"]["status"] == "OK"                # still evaluated
    assert by["bad_job"]["status"] == "CONFIG_ERROR"
    assert "bad_job" in blob["alerts"]                     # counts as unhealthy
    flag = tmp_path / "al" / "ALERT_bad_job_heartbeat.flag"
    assert flag.exists()
    assert "CONFIG_ERROR" in flag.read_text()


# ─── SHOULD-FIX 4 — */0 must raise, not hang ───────────────────────────────

import signal  # noqa: E402
from contextlib import contextmanager  # noqa: E402


@contextmanager
def _time_limit(seconds):
    def _handler(signum, frame):
        raise TimeoutError("timed out — likely an infinite loop")
    old = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def test_zero_step_raises_value_error_not_hang():
    with _time_limit(5):
        with pytest.raises(ValueError):
            heartbeat._field_values("*/0", 0, 59)
        with pytest.raises(ValueError):
            heartbeat._field_values("1-10/0", 0, 59)


def test_zero_step_in_check_is_config_error_not_hang(tmp_path):
    (tmp_path / "expected_jobs.yaml").write_text("""
defaults:
  host: test
jobs:
  - name: loopy
    entrypoint: /root/loopy.sh
    schedule: "*/0 * * * *"
    owner_user: root
    grace_minutes: 60
    tree: /root
""")
    a = _args(
        config=str(tmp_path / "expected_jobs.yaml"),
        now="2026-09-03T06:00:00Z",
        dir=str(tmp_path / "hb"), alert_dir=str(tmp_path / "al"),
        health_json=str(tmp_path / "h.json"), health_txt=str(tmp_path / "h.txt"),
        dms_url="", strict=False,
    )
    with _time_limit(5):
        assert heartbeat.cmd_check(a) == 0
    blob = json.loads((tmp_path / "h.json").read_text())
    assert blob["jobs"][0]["status"] == "CONFIG_ERROR"


# ─── SHOULD-FIX 5 — schedules rarer than the lookback ──────────────────────

def test_annual_schedule_resolves_within_400d():
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    got = heartbeat.last_fire_at_or_before("0 19 31 3 *", now)   # annual, Mar 31 19:00
    assert got == datetime(2026, 3, 31, 19, 0, tzinfo=UTC)


def test_impossible_schedule_emits_warn_row_not_silent_ok(tmp_path):
    (tmp_path / "expected_jobs.yaml").write_text("""
defaults:
  host: test
jobs:
  - name: never_fires
    entrypoint: /root/never.sh
    schedule: "0 0 30 2 *"
    owner_user: root
    grace_minutes: 60
    tree: /root
""")
    a = _args(
        config=str(tmp_path / "expected_jobs.yaml"),
        now="2026-09-03T06:00:00Z",
        dir=str(tmp_path / "hb"), alert_dir=str(tmp_path / "al"),
        health_json=str(tmp_path / "h.json"), health_txt=str(tmp_path / "h.txt"),
        dms_url="", strict=False,
    )
    assert heartbeat.cmd_check(a) == 0
    blob = json.loads((tmp_path / "h.json").read_text())
    row = blob["jobs"][0]
    assert row["status"] == "WARN"
    assert "too rare" in row["reason"]
    assert blob["ok"] is True            # WARN is visible but not a hard alert
    assert blob["alerts"] == []


# ─── SHOULD-FIX 6 — grace >= min inter-fire gap ───────────────────────────

def test_grace_ge_inter_fire_gap_warns_to_stderr(tmp_path, capsys):
    (tmp_path / "expected_jobs.yaml").write_text("""
defaults:
  host: test
jobs:
  - name: chatty
    entrypoint: /root/chatty.sh
    schedule: "*/15 * * * *"
    owner_user: root
    grace_minutes: 60
    tree: /root
""")
    a = _args(
        config=str(tmp_path / "expected_jobs.yaml"),
        now="2026-09-03T06:00:00Z",
        dir=str(tmp_path / "hb"), alert_dir=str(tmp_path / "al"),
        health_json=str(tmp_path / "h.json"), health_txt=str(tmp_path / "h.txt"),
        dms_url="", strict=False,
    )
    heartbeat.cmd_check(a)
    err = capsys.readouterr().err
    assert "chatty" in err and "min inter-fire gap" in err


# ─── SHOULD-FIX 7 — write is silent on success ───────────────────────────

def test_write_success_prints_nothing_to_stdout(tmp_path, capsys):
    heartbeat.cmd_write(_args(job="silent", rc=0, entrypoint="", tree="", dir=str(tmp_path)))
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == ""


# ─── small fix — write never exits non-zero on a bad --rc ─────────────────

def test_write_bad_rc_exits_zero_and_records_null(tmp_path, capsys):
    rc = heartbeat.cmd_write(
        _args(job="badrc", rc="not-an-int", entrypoint="", tree="", dir=str(tmp_path)))
    assert rc == 0
    rec = json.loads((tmp_path / "badrc.json").read_text())
    assert rec["rc"] is None
    assert "invalid --rc" in capsys.readouterr().err


def test_write_missing_rc_via_cli_exits_zero(tmp_path):
    # argparse must NOT exit 2 when --rc is absent
    assert heartbeat.main(["write", "norc", "--dir", str(tmp_path)]) == 0
    assert json.loads((tmp_path / "norc.json").read_text())["rc"] is None


# ─── deploy-plan fix — DEFAULT_CONFIG points at the installed path ────────

def test_default_config_is_installed_ops_path(monkeypatch):
    import importlib
    monkeypatch.delenv("HEARTBEAT_CONFIG", raising=False)
    mod = importlib.reload(heartbeat)
    try:
        assert mod.DEFAULT_CONFIG == "/root/ops/expected_jobs.yaml"
    finally:
        monkeypatch.undo()
        importlib.reload(heartbeat)


def test_default_config_honours_env_override(monkeypatch):
    import importlib
    monkeypatch.setenv("HEARTBEAT_CONFIG", "/somewhere/else.yaml")
    mod = importlib.reload(heartbeat)
    try:
        assert mod.DEFAULT_CONFIG == "/somewhere/else.yaml"
    finally:
        monkeypatch.undo()
        importlib.reload(heartbeat)


# ─── health files are world-readable for the dashboard ──────────────────

def test_health_and_heartbeat_files_written_0644(tmp_path):
    import stat
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    _hb(tmp_path / "hb", "nightly", "2026-09-02T22:00:30Z", rc=0)
    _check(tmp_path, now)
    for f in ("health.json", "health.txt"):
        mode = stat.S_IMODE((tmp_path / f).stat().st_mode)
        assert mode == 0o644, (f, oct(mode))
    # the real heartbeat writer (mkstemp -> 0600) must widen to 0644 too
    heartbeat.cmd_write(_args(job="w", rc=0, entrypoint="", tree="", dir=str(tmp_path / "wr")))
    assert stat.S_IMODE((tmp_path / "wr" / "w.json").stat().st_mode) == 0o644


# ─── tree surfaced in the health table ─────────────────────────────────

def test_tree_shown_in_health_table(tmp_path):
    now = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
    _hb(tmp_path / "hb", "nightly", "2026-09-02T22:00:30Z", rc=0)
    _check(tmp_path, now)
    txt = (tmp_path / "health.txt").read_text()
    assert "TREE" in txt and "/root" in txt
