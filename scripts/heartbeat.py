#!/usr/bin/env python3
"""B-07 — positive heartbeats + dead-man's switch for scheduled jobs.

Three subcommands:

  heartbeat.py write <job> --rc <rc> [--entrypoint PATH] [--tree DIR] [--dir DIR]
      Append/replace <heartbeat_dir>/<job>.json with a small record describing the
      run that just finished. This is called from EVERY wrapped cron line (via
      scripts/heartbeat-wrap.sh). It MUST NEVER fail the calling job: every code
      path is wrapped, and any error prints a warning to stderr and exits 0.
      On success it prints NOTHING to stdout (so previously-silent cron lines
      stay silent and no mail is generated); it only writes to stderr on a
      degraded/failed write. A missing/unparseable --rc is a stderr warning and
      an rc=null record, never a non-zero exit.

  heartbeat.py seed [--config FILE] [--dir DIR] [--now ISO8601]
      Deploy bootstrap. For every job in the registry, write a synthetic
      heartbeat (rc 0, "seeded": true) dated to that job's LAST expected fire,
      UNLESS a real record already exists that is newer. Run this once, just
      before installing the wrapped crontab, so the day-1 board is green and the
      dead-man's switch does not false-alarm for the up-to-a-week it would
      otherwise take every Monday/Sunday-only job to report in. Real heartbeats
      replace the seeds as they land; a job that genuinely never fires ages past
      its grace and flags on the next check.

  heartbeat.py check [--config FILE] [--now ISO8601] [--dir DIR] [--alert-dir DIR]
                     [--health-json FILE] [--health-txt FILE] [--dms-url URL]
                     [--strict]
      Intended to run daily (06:00 UTC). Reads expected_jobs.yaml, and for
      each job compares the last-seen heartbeat against the most recent time its
      cron schedule should have fired (+ grace_minutes). Writes
      <alert-dir>/ALERT_<job>_heartbeat.flag on missing / stale / rc!=0 /
      config-error, clears that flag when a job recovers, renders a jobs-health
      table (text + JSON), and — only when everything is green — pings an
      external dead-man's-switch URL so an OUTAGE of this box (or of cron) trips
      an external alarm. A single unparseable registry entry produces a
      CONFIG_ERROR row + flag for that job only; every other job is still
      evaluated. The checker evaluates its OWN entry (heartbeat_check) against a
      reference point 24h earlier, so a dead checker trips STALE/MISSING while a
      merely-late run does not self-flag.

Design notes
  * `write` is pure stdlib. `check` uses PyYAML if importable, else a tiny
    built-in parser that understands the flat structure of expected_jobs.yaml.
  * All timestamps are UTC ISO-8601 with a trailing 'Z'.
  * The DMS URL is NEVER hardcoded. It is read from --dms-url, then env
    HEARTBEAT_DMS_URL, then a KEY=VALUE / bare-URL file named by env
    HEARTBEAT_DMS_URL_FILE. If none is found, the ping is skipped with a notice.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from functools import lru_cache

UTC = timezone.utc

DEFAULT_HEARTBEAT_DIR = os.environ.get("HEARTBEAT_DIR", "/root/ops/heartbeat")
DEFAULT_ALERT_DIR = os.environ.get("HEARTBEAT_ALERT_DIR", "/root/ops/alerts")
DEFAULT_HEALTH_JSON = os.environ.get("HEARTBEAT_HEALTH_JSON", "/root/ops/jobs_health.json")
DEFAULT_HEALTH_TXT = os.environ.get("HEARTBEAT_HEALTH_TXT", "/root/ops/jobs_health.txt")
# The checker is deployed to /root/ops/heartbeat.py and the registry to
# /root/ops/expected_jobs.yaml (see docs/B-07_WIRING_PLAN.md §1). HEARTBEAT_CONFIG
# (set as a global env line in the wrapped crontab) always wins; this is only the
# fallback for a manual invocation that does not pass --config.
DEFAULT_CONFIG = os.environ.get("HEARTBEAT_CONFIG", "/root/ops/expected_jobs.yaml")

# The registry entry for the checker itself. Evaluated specially: see _evaluate.
SELF_JOB = "heartbeat_check"


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    s = (s or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ─────────────────────────────────────────────────────────────────────────────
# write
# ─────────────────────────────────────────────────────────────────────────────

def _best_effort_git_sha(tree: str) -> str:
    try:
        if not tree:
            return ""
        out = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", tree, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def _atomic_write_json(path: str, obj: dict) -> None:
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".hb-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(obj, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        # mkstemp creates 0600; nothing in a heartbeat/health file is secret and
        # the dashboard (plan §11.11) reads jobs_health.json, so widen to 0644.
        try:
            os.chmod(path, 0o644)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def cmd_write(args) -> int:
    """Record a heartbeat. NEVER fails the caller: always returns 0."""
    try:
        job = args.job
        hb_dir = args.dir or DEFAULT_HEARTBEAT_DIR
        tree = args.tree or os.getcwd()
        raw_rc = getattr(args, "rc", None)
        try:
            rc_val = int(str(raw_rc).strip())
        except (TypeError, ValueError):
            # "write never fails a job": a missing/unparseable --rc is a loud
            # stderr warning + an rc=null record (which `check` surfaces as
            # UNREADABLE), never a non-zero exit.
            sys.stderr.write(
                f"heartbeat: WARNING — missing/invalid --rc {raw_rc!r} for "
                f"{job}; recording rc=null (job exit code preserved)\n"
            )
            rc_val = None
        record = {
            "job": job,
            "ran_at": _iso(_utc_now()),
            "rc": rc_val,
            "git_sha": _best_effort_git_sha(tree),
            "entrypoint": args.entrypoint or "",
            "host": socket.gethostname(),
            "user": _whoami(),
        }
        _atomic_write_json(os.path.join(hb_dir, f"{job}.json"), record)
        # Success is SILENT on stdout: 15 of the 21 wrapped crontab lines have no
        # redirect, so any stdout here would be a mail attempt every run.
        return 0
    except Exception as exc:  # noqa: BLE001 — a heartbeat error must never propagate
        sys.stderr.write(
            f"heartbeat: WARNING — write failed for "
            f"{getattr(args, 'job', '?')}: {exc!r} (job exit code preserved)\n"
        )
        return 0


def _whoami() -> str:
    for getter in (
        lambda: __import__("getpass").getuser(),
        lambda: os.environ.get("USER") or os.environ.get("LOGNAME") or "",
        lambda: str(os.getuid()),
    ):
        try:
            v = getter()
            if v:
                return v
        except Exception:
            continue
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# cron schedule maths
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def _field_values(field: str, lo: int, hi: int) -> frozenset[int]:
    """Expand one cron field to the set of values it matches.

    Cached (the 21 registry schedules recur every check and every back-scan
    minute) — hence the frozenset return so a caller cannot mutate the cache.
    Rejects a non-positive step (``*/0``, ``1-10/0``) with a clear ValueError
    rather than looping forever; `check`'s per-job guard turns that into a
    CONFIG_ERROR row.
    """
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        step = 1
        rng = part
        if "/" in part:
            rng, step_s = part.split("/", 1)
            step = int(step_s)
            if step <= 0:
                raise ValueError(
                    f"invalid step {step!r} in cron field {field!r} (must be >= 1)"
                )
        if rng == "*":
            start, end = lo, hi
        elif "-" in rng:
            a, b = rng.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(rng)
        v = start
        while v <= end:
            if lo <= v <= hi:
                out.add(v)
            v += step
    return frozenset(out)


def _cron_matches(dt: datetime, cron: str) -> bool:
    mi, ho, dom, mon, dow = cron.split()
    if dt.minute not in _field_values(mi, 0, 59):
        return False
    if dt.hour not in _field_values(ho, 0, 23):
        return False
    if dt.month not in _field_values(mon, 1, 12):
        return False
    dom_set = _field_values(dom, 1, 31)
    dow_set = {0 if d == 7 else d for d in _field_values(dow, 0, 7)}
    # cron weekday: Sun=0..Sat=6 ; python weekday(): Mon=0..Sun=6
    cron_wday = (dt.weekday() + 1) % 7
    dom_restricted = dom.strip() != "*"
    dow_restricted = dow.strip() != "*"
    dom_ok = dt.day in dom_set
    dow_ok = cron_wday in dow_set
    if dom_restricted and dow_restricted:
        return dom_ok or dow_ok
    if dom_restricted:
        return dom_ok
    if dow_restricted:
        return dow_ok
    return True


def last_fire_at_or_before(cron: str, now: datetime, max_days: int = 400) -> datetime | None:
    """Greatest minute t <= now that matches `cron`. None if none within max_days.

    The 400-day back-scan (was 45) lets rare schedules — the parked quarterly EPE
    lines the plan §11.1 invites the operator to add, or an annual line — still
    resolve. If nothing is found within 400 days, `_evaluate` renders a visible
    WARN row instead of a silent OK.
    """
    t = now.replace(second=0, microsecond=0)
    limit = t - timedelta(days=max_days)
    while t >= limit:
        if _cron_matches(t, cron):
            return t
        t -= timedelta(minutes=1)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# config loading (PyYAML if available, else a tiny fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _load_config(path: str) -> dict:
    with open(path) as fh:
        text = fh.read()
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return _mini_yaml(text)


def _mini_yaml(text: str) -> dict:
    """Minimal parser for the flat expected_jobs.yaml shape only:

        key: value                 # top-level scalars
        jobs:
          - name: x
            entrypoint: /path
            ...
          - name: y
            ...
    """
    root: dict = {}
    jobs: list[dict] = []
    cur: dict | None = None
    in_jobs = False
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip() if not raw.strip().startswith("#") else ""
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        s = line.strip()
        if indent == 0:
            in_jobs = s.rstrip(":") == "jobs" and s.endswith(":")
            if not in_jobs and ":" in s:
                k, v = s.split(":", 1)
                root[k.strip()] = _scalar(v.strip())
            continue
        if not in_jobs:
            continue
        if s.startswith("- "):
            cur = {}
            jobs.append(cur)
            s = s[2:].strip()
        if cur is not None and ":" in s:
            k, v = s.split(":", 1)
            cur[k.strip()] = _scalar(v.strip())
    root["jobs"] = jobs
    return root


def _scalar(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return v[1:-1]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return int(v)
    except ValueError:
        return v


# ─────────────────────────────────────────────────────────────────────────────
# check
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_dms_url(cli_url: str | None) -> str | None:
    if cli_url:
        return cli_url.strip()
    env = os.environ.get("HEARTBEAT_DMS_URL")
    if env and env.strip():
        return env.strip()
    fpath = os.environ.get("HEARTBEAT_DMS_URL_FILE")
    if fpath and os.path.isfile(fpath):
        try:
            for line in open(fpath):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith(("http://", "https://")):
                    return line
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == "HEARTBEAT_DMS_URL":
                        return v.strip().strip("\"'")
        except Exception:
            pass
    return None


def _dms_ping(url: str, timeout: int = 10) -> tuple[bool, str]:
    try:
        import urllib.request

        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "b07-heartbeat/1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — operator-supplied URL
            return 200 <= resp.status < 400, f"HTTP {resp.status}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc!r}"


def _read_heartbeat(hb_dir: str, job: str) -> dict | None:
    p = os.path.join(hb_dir, f"{job}.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p) as fh:
            return json.load(fh)
    except Exception:
        return {"_unreadable": True}


def _evaluate(job: dict, hb: dict | None, now: datetime) -> dict:
    name = job["name"]
    schedule = job["schedule"]
    grace = timedelta(minutes=int(job.get("grace_minutes", 60)))

    # BLOCKER 1 — self-liveness. The checker evaluates every job at the instant of
    # its own cron fire, so for its OWN entry expected_fire == now: `due` would
    # always be False (a 5-day-stale checker reports OK and still pings the DMS),
    # and a run that starts merely late would flag ITSELF stale (a false external
    # alarm). Fix: evaluate the self entry against a reference point 24h earlier.
    # A checker that has recorded no run in the last ~24h then trips STALE (or
    # MISSING) and withholds the DMS — a dead checker is the worst failure — while
    # a normal or late run stays OK. The 24h shift IS the grace for the self
    # entry (its grace_minutes: 1500 in the registry is a belt-and-braces value
    # that keeps the ordinary code path from false-flagging a late run too).
    is_self = name == SELF_JOB
    ref_now = now - timedelta(hours=24) if is_self else now
    expected = last_fire_at_or_before(schedule, ref_now)
    if is_self:
        due = expected is not None and ref_now >= expected
    else:
        due = expected is not None and ref_now >= (expected + grace)

    row = {
        "name": name,
        "schedule": schedule,
        "entrypoint": job.get("entrypoint", ""),
        "owner_user": job.get("owner_user", ""),
        "tree": job.get("tree", ""),
        "grace_minutes": int(job.get("grace_minutes", 60)),
        "expected_fire": _iso(expected) if expected else None,
        "last_ran_at": None,
        "age_minutes": None,
        "last_rc": None,
        "git_sha": None,
        "status": "OK",
        "reason": "",
    }

    if expected is None:
        # SHOULD-FIX 5 — schedule rarer than the 400-day back-scan. Don't sit at a
        # silent OK/PENDING forever; render a visible (non-alerting) WARN row.
        row["status"] = "WARN"
        row["reason"] = "schedule too rare to monitor (>400d lookback)"
        return row

    if hb is None:
        row["status"] = "MISSING" if due else "PENDING"
        row["reason"] = (
            f"no heartbeat file and last scheduled fire {row['expected_fire']} "
            f"is past grace ({row['grace_minutes']}m)"
            if due else "never seen yet, not due"
        )
        return row

    if hb.get("_unreadable"):
        row["status"] = "UNREADABLE"
        row["reason"] = "heartbeat file present but not valid JSON"
        return row

    try:
        last = _parse_iso(hb.get("ran_at", ""))
    except Exception:
        row["status"] = "UNREADABLE"
        row["reason"] = f"bad ran_at: {hb.get('ran_at')!r}"
        return row

    row["last_ran_at"] = _iso(last)
    row["age_minutes"] = int((now - last).total_seconds() // 60)
    row["last_rc"] = hb.get("rc")
    row["git_sha"] = hb.get("git_sha") or ""

    stale = expected is not None and last < expected and due
    if stale:
        row["status"] = "STALE"
        if is_self:
            row["reason"] = (
                f"checker last recorded a run at {row['last_ran_at']}, before its "
                f"previous-day fire {row['expected_fire']} — checker is not running"
            )
        else:
            row["reason"] = (
                f"last run {row['last_ran_at']} predates scheduled fire {row['expected_fire']} "
                f"(now past {row['grace_minutes']}m grace)"
            )
    elif hb.get("rc") not in (0, None):
        row["status"] = "FAILED"
        row["reason"] = f"last run exited rc={hb.get('rc')}"
    elif hb.get("rc") is None:
        row["status"] = "UNREADABLE"
        row["reason"] = "heartbeat missing rc"
    else:
        row["status"] = "OK"
        row["reason"] = ""
    return row


# CONFIG_ERROR counts toward the unhealthy total (so the DMS is withheld) and
# gets a flag. WARN does NOT — it is visible-but-not-paging.
_ALERT_STATUSES = {"MISSING", "STALE", "FAILED", "UNREADABLE", "CONFIG_ERROR"}


def _render_txt(rows: list[dict], now: datetime, alerts: list[str]) -> str:
    hdr = (f"{'JOB':<24} {'SCHEDULE':<16} {'LAST_RAN(UTC)':<21} {'AGE':>7} {'RC':>4}  "
           f"{'STATUS':<12} {'TREE':<26} REASON")
    warns = [r["name"] for r in rows if r["status"] == "WARN"]
    if alerts:
        summary = f"{len(alerts)} ALERT(S): " + ", ".join(alerts)
    else:
        summary = "ALL CLEAR"
    if warns:
        summary += f"  |  {len(warns)} WARNING(S): " + ", ".join(warns)
    lines = [
        f"# B-07 jobs health @ {_iso(now)}  host={socket.gethostname()}",
        f"# {summary}",
        "",
        hdr,
        "-" * len(hdr),
    ]
    for r in sorted(rows, key=lambda x: x["name"]):
        age = "-" if r["age_minutes"] is None else f"{r['age_minutes']}m"
        rc = "-" if r["last_rc"] is None else str(r["last_rc"])
        last = r["last_ran_at"] or "-"
        tree = r.get("tree") or "-"
        lines.append(
            f"{r['name']:<24} {r['schedule']:<16} {last:<21} {age:>7} {rc:>4}  "
            f"{r['status']:<12} {tree:<26} "
            + (f"({r['reason']})" if r["reason"] else "")
        )
    return "\n".join(lines) + "\n"


def _safe_write(path: str, text: str) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".hb-", suffix=".tmp")
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o644)  # mkstemp -> 0600; the dashboard reads these
        except OSError:
            pass
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"heartbeat: WARNING — could not write {path}: {exc!r}\n")


def _error_row(job, status: str, reason: str) -> dict:
    """A table row for a job whose registry entry could not be evaluated."""
    j = job if isinstance(job, dict) else {}
    return {
        "name": j.get("name", "?"),
        "schedule": j.get("schedule", ""),
        "entrypoint": j.get("entrypoint", ""),
        "owner_user": j.get("owner_user", ""),
        "tree": j.get("tree", ""),
        "grace_minutes": None,
        "expected_fire": None,
        "last_ran_at": None,
        "age_minutes": None,
        "last_rc": None,
        "git_sha": None,
        "status": status,
        "reason": reason,
    }


def _min_inter_fire_gap(cron: str, now: datetime, window_days: int = 2) -> int | None:
    """Smallest gap, in minutes, between consecutive fires of `cron` sampled over
    a short window. None if fewer than two fires occur (nothing to warn about —
    weekly/monthly jobs)."""
    end = now.replace(second=0, microsecond=0)
    t = end - timedelta(days=window_days)
    fires: list[datetime] = []
    while t <= end:
        if _cron_matches(t, cron):
            fires.append(t)
        t += timedelta(minutes=1)
    if len(fires) < 2:
        return None
    return min(int((b - a).total_seconds() // 60) for a, b in zip(fires, fires[1:]))


def _emit_config_warnings(cfg: dict, jobs: list[dict], now: datetime) -> None:
    """Non-fatal, stderr-only sanity checks run once per `check`."""
    try:
        for j in jobs:
            if not isinstance(j, dict):
                continue
            if j.get("name") == SELF_JOB:
                continue  # evaluated against a 24h-earlier ref, not expected+grace
            try:
                sched = j["schedule"]
                grace_min = int(j.get("grace_minutes", 60))
                gap = _min_inter_fire_gap(sched, now)
            except Exception:
                continue  # a broken entry is reported as CONFIG_ERROR by check
            if gap is not None and grace_min >= gap:
                # SHOULD-FIX 6 — grace >= min inter-fire gap makes MISSING/STALE
                # unreachable: the next fire always lands before the grace on the
                # previous one expires.
                sys.stderr.write(
                    f"heartbeat: WARN — {j.get('name', '?')} grace ({grace_min}min) >= "
                    f"min inter-fire gap ({gap}min) — MISSING/STALE unreachable\n"
                )
        defaults = cfg.get("defaults")
        if isinstance(defaults, dict) and defaults.get("host"):
            want = str(defaults["host"]).strip()
            have = socket.gethostname()
            if want and want != have and not have.startswith(want):
                sys.stderr.write(
                    f"heartbeat: WARN — registry defaults.host={want!r} but this box "
                    f"is {have!r} — config deployed to the wrong host?\n"
                )
    except Exception as exc:  # noqa: BLE001 — a warning helper must never fail check
        sys.stderr.write(f"heartbeat: WARN — config-warning pass skipped: {exc!r}\n")


def cmd_seed(args) -> int:
    """BLOCKER 2 — deploy bootstrap. Write a synthetic heartbeat for every job at
    its LAST expected fire, unless a real record already exists that is newer.
    Makes the day-1 board green so the dead-man's switch does not false-alarm for
    the up-to-a-week the Monday/Sunday-only jobs would otherwise take to report.
    Never fails: config-load failure returns 2, per-job failure is a stderr note.
    """
    now = _parse_iso(args.now) if getattr(args, "now", "") else _utc_now()
    hb_dir = args.dir or DEFAULT_HEARTBEAT_DIR
    cfg_path = args.config or DEFAULT_CONFIG

    try:
        cfg = _load_config(cfg_path)
    except Exception as exc:
        sys.stderr.write(f"heartbeat: FATAL — cannot load config {cfg_path}: {exc!r}\n")
        return 2

    jobs = cfg.get("jobs") or []
    seeded: list[str] = []
    kept: list[str] = []
    skipped: list[str] = []
    for j in jobs:
        if not isinstance(j, dict) or "name" not in j or "schedule" not in j:
            sys.stderr.write(f"heartbeat: seed — skipping entry with no name/schedule: {j!r}\n")
            skipped.append(str(j)[:40] if not isinstance(j, dict) else j.get("name", "?"))
            continue
        name = j["name"]
        try:
            expected = last_fire_at_or_before(j["schedule"], now)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(
                f"heartbeat: seed — {name}: unparseable schedule {j['schedule']!r}: {exc}\n"
            )
            skipped.append(name)
            continue
        if expected is None:
            sys.stderr.write(
                f"heartbeat: seed — {name}: no fire within 400d lookback; not seeding\n"
            )
            skipped.append(name)
            continue

        existing = _read_heartbeat(hb_dir, name)
        if existing and not existing.get("_unreadable"):
            try:
                if _parse_iso(existing.get("ran_at", "")) >= expected:
                    kept.append(name)  # a real (or prior) record already covers this fire
                    continue
            except Exception:
                pass

        record = {
            "job": name,
            "ran_at": _iso(expected),
            "rc": 0,
            "git_sha": "",
            "entrypoint": j.get("entrypoint", ""),
            "host": socket.gethostname(),
            "user": _whoami(),
            "seeded": True,
        }
        try:
            _atomic_write_json(os.path.join(hb_dir, f"{name}.json"), record)
            seeded.append(name)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"heartbeat: seed — {name}: write failed: {exc!r}\n")
            skipped.append(name)

    print(
        f"heartbeat: seed — {len(seeded)} seeded, {len(kept)} kept "
        f"(real record newer), {len(skipped)} skipped"
    )
    if seeded:
        print("  seeded:  " + ", ".join(sorted(seeded)))
    if kept:
        print("  kept:    " + ", ".join(sorted(kept)))
    if skipped:
        print("  skipped: " + ", ".join(sorted(skipped)))
    return 0


def cmd_check(args) -> int:
    now = _parse_iso(args.now) if args.now else _utc_now()
    hb_dir = args.dir or DEFAULT_HEARTBEAT_DIR
    alert_dir = args.alert_dir or DEFAULT_ALERT_DIR
    health_json = args.health_json or DEFAULT_HEALTH_JSON
    health_txt = args.health_txt or DEFAULT_HEALTH_TXT
    cfg_path = args.config or DEFAULT_CONFIG

    try:
        cfg = _load_config(cfg_path)
    except Exception as exc:
        sys.stderr.write(f"heartbeat: FATAL — cannot load config {cfg_path}: {exc!r}\n")
        return 2

    jobs = cfg.get("jobs") or []
    _emit_config_warnings(cfg, jobs, now)

    # SHOULD-FIX 3 — one bad registry entry must not kill the whole check. Each
    # job's evaluation is guarded: an unparseable schedule (`@daily`, a 4/6-field
    # expr, `*/0`, ...) becomes a CONFIG_ERROR row + flag for that job only, and
    # every other job is still evaluated.
    rows: list[dict] = []
    for j in jobs:
        if not isinstance(j, dict) or "name" not in j:
            rows.append(_error_row(j, "CONFIG_ERROR", "registry entry has no 'name'"))
            continue
        try:
            rows.append(_evaluate(j, _read_heartbeat(hb_dir, j["name"]), now))
        except Exception as exc:  # noqa: BLE001
            rows.append(_error_row(j, "CONFIG_ERROR", f"{type(exc).__name__}: {exc}"))

    alerts = [r["name"] for r in rows if r["status"] in _ALERT_STATUSES]
    recovered: list[str] = []

    try:
        os.makedirs(alert_dir, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"heartbeat: WARNING — cannot create alert dir {alert_dir}: {exc!r}\n")

    for r in rows:
        flag = os.path.join(alert_dir, f"ALERT_{r['name']}_heartbeat.flag")
        if r["status"] in _ALERT_STATUSES:
            try:
                with open(flag, "w") as fh:
                    fh.write(f"[{_iso(now)}] {r['name']} {r['status']}: {r['reason']}\n")
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(f"heartbeat: WARNING — cannot write {flag}: {exc!r}\n")
        elif os.path.isfile(flag):
            try:
                os.unlink(flag)
                recovered.append(r["name"])
            except Exception:
                pass

    all_clear = not alerts
    blob = {
        "generated_at": _iso(now),
        "host": socket.gethostname(),
        "ok": all_clear,
        "alert_count": len(alerts),
        "alerts": alerts,
        "recovered": recovered,
        "jobs": rows,
    }
    _safe_write(health_json, json.dumps(blob, indent=2) + "\n")
    _safe_write(health_txt, _render_txt(rows, now, alerts))

    print(_render_txt(rows, now, alerts), end="")
    if recovered:
        print(f"heartbeat: cleared {len(recovered)} recovered flag(s): {', '.join(recovered)}")

    # Dead-man's switch: ping ONLY when everything is green. A real outage of this
    # box or of cron means `check` never runs, the ping never happens, and the
    # external monitor raises the alarm on its own.
    dms_url = _resolve_dms_url(args.dms_url)
    if not all_clear:
        print(f"heartbeat: {len(alerts)} alert(s) — NOT pinging dead-man's switch: {', '.join(alerts)}")
    elif not dms_url:
        print("heartbeat: HEARTBEAT_DMS_URL unset (env / file) — skipping dead-man's-switch ping")
    else:
        ok, detail = _dms_ping(dms_url)
        print(f"heartbeat: dead-man's-switch ping {'ok' if ok else 'FAILED'} ({detail})")

    if args.strict and alerts:
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="heartbeat.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("write", help="record a heartbeat for a job that just finished")
    w.add_argument("job")
    # NOT required and NOT type=int: a missing/bad --rc must not make argparse
    # exit 2 (that would fail the wrapped job). cmd_write coerces it and, on
    # failure, warns to stderr + records rc=null, still exiting 0.
    w.add_argument("--rc", default=None, help="the job's real exit code (integer)")
    w.add_argument("--entrypoint", default="", help="entrypoint path (best-effort, informational)")
    w.add_argument("--tree", default="", help="dir to read git sha from (default: cwd)")
    w.add_argument("--dir", default="", help=f"heartbeat dir (default: {DEFAULT_HEARTBEAT_DIR})")
    w.set_defaults(func=cmd_write)

    s = sub.add_parser("seed", help="deploy bootstrap: synthetic heartbeats at each job's last fire")
    s.add_argument("--config", default="", help=f"expected_jobs.yaml (default: {DEFAULT_CONFIG})")
    s.add_argument("--dir", default="", help=f"heartbeat dir (default: {DEFAULT_HEARTBEAT_DIR})")
    s.add_argument("--now", default="", help="override 'now' (ISO-8601 UTC) — for tests")
    s.set_defaults(func=cmd_seed)

    c = sub.add_parser("check", help="evaluate all expected jobs; flag + render health + DMS ping")
    c.add_argument("--config", default="", help=f"expected_jobs.yaml (default: {DEFAULT_CONFIG})")
    c.add_argument("--now", default="", help="override 'now' (ISO-8601 UTC) — for tests")
    c.add_argument("--dir", default="", help=f"heartbeat dir (default: {DEFAULT_HEARTBEAT_DIR})")
    c.add_argument("--alert-dir", default="", help=f"alert dir (default: {DEFAULT_ALERT_DIR})")
    c.add_argument("--health-json", default="", help=f"(default: {DEFAULT_HEALTH_JSON})")
    c.add_argument("--health-txt", default="", help=f"(default: {DEFAULT_HEALTH_TXT})")
    c.add_argument("--dms-url", default="", help="override dead-man's-switch URL")
    c.add_argument("--strict", action="store_true", help="exit 1 if any alerts (not used by cron)")
    c.set_defaults(func=cmd_check)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        if getattr(args, "cmd", None) == "write":
            sys.stderr.write("heartbeat: WARNING — unhandled write error, exiting 0\n")
            sys.stderr.write(traceback.format_exc())
            return 0
        raise


if __name__ == "__main__":
    sys.exit(main())
