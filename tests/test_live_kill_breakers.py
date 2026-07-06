"""Kill switch (two-step reset, terminal cumulative kill) + breakers (null-threshold fail-safe)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.live import breakers, kill
from src.live.limits import load_live_limits

_OK = {"DAILY_LOSS_HALT_PCT": 0.03, "WEEKLY_LOSS_HALT_PCT": 0.06, "CUMULATIVE_KILL_PCT": 0.20}


def _k(tmp):
    return tmp / "KILL", tmp / "kill_events.jsonl"


# ─── kill sentinel + two-step reset ──────────────────────────────────────────

def test_kill_file_is_source_of_truth(tmp_path):
    ks, kl = _k(tmp_path)
    assert kill.kill_block(ks, kl) == (False, "")
    kill.engage_kill("simulated /kill", sentinel=ks, log=kl)
    blocked, why = kill.kill_block(ks, kl)
    assert blocked and "KILL sentinel" in why and kill.is_killed(ks)
    print("  ✓ KILL file present → generation blocked")


def test_two_step_reset_and_resume_needs_reason(tmp_path):
    ks, kl = _k(tmp_path)
    kill.engage_kill("kill", sentinel=ks, log=kl)
    ks.unlink()                                                   # step 2 alone
    blocked, why = kill.kill_block(ks, kl)
    assert blocked and "two-step" in why                         # confirm not yet logged
    with pytest.raises(ValueError, match="reason"):
        kill.confirm_resume("", log=kl)                          # step 1 needs a reason
    kill.confirm_resume("reviewed, safe to resume", log=kl)      # step 1 done
    assert kill.kill_block(ks, kl)[0] is False                   # both steps done → resumed
    print("  ✓ reset needs BOTH /confirm_resume (with reason) AND file deletion")


def test_cumulative_kill_is_terminal(tmp_path):
    ks, kl = _k(tmp_path)
    kill.engage_kill("cumulative breach", terminal=True, sentinel=ks, log=kl)
    ks.unlink()
    assert kill.kill_block(ks, kl)[0] is True                    # still blocked after deletion
    with pytest.raises(ValueError, match="post-mortem"):
        kill.confirm_resume("resume please", limits={"POST_MORTEM_PATH": None}, log=kl)
    pm = tmp_path / "POST_MORTEM.md"; pm.write_text("what happened")
    kill.confirm_resume("post-mortem complete", limits={"POST_MORTEM_PATH": str(pm)}, log=kl)
    assert kill.kill_block(ks, kl)[0] is False                   # only now resumable
    print("  ✓ cumulative kill terminal: no resume until a POST_MORTEM exists")


# ─── breakers: fail-safe + breaches ──────────────────────────────────────────

def test_null_thresholds_fail_safe_blocks(tmp_path):
    limits = load_live_limits()                                  # committed: breakers are null
    r = breakers.evaluate({"daily_pnl_pct": 0.0}, limits,
                          halt_daily=tmp_path / "hd", halt_weekly=tmp_path / "hw",
                          on_kill=lambda reason: None)
    assert r["blocked"] is True and "FAIL-SAFE" in r["reasons"][0]
    print("  ✓ ANY null breaker threshold → cards BLOCKED (fail-safe, not silently permissive)")


def test_set_thresholds_no_breach_not_blocked(tmp_path):
    r = breakers.evaluate({"daily_pnl_pct": 0.0, "weekly_pnl_pct": 0.0, "cumulative_pnl_pct": 0.0},
                          _OK, halt_daily=tmp_path / "hd", halt_weekly=tmp_path / "hw",
                          on_kill=lambda reason: None)
    assert r["blocked"] is False and r["actions"] == []


def test_daily_and_weekly_breaches(tmp_path):
    hd, hw = tmp_path / "HALT_DAILY", tmp_path / "HALT_WEEKLY"
    r = breakers.evaluate({"daily_pnl_pct": -0.05}, _OK, halt_daily=hd, halt_weekly=hw,
                          on_kill=lambda reason: None)
    assert "HALT_DAILY" in r["actions"] and hd.exists() and r["blocked"]
    r2 = breakers.evaluate({"weekly_pnl_pct": -0.07}, _OK, halt_daily=hd, halt_weekly=hw,
                           on_kill=lambda reason: None)
    assert "HALT_WEEKLY" in r2["actions"] and hw.exists()
    print("  ✓ daily → HALT_DAILY, weekly → HALT_WEEKLY")


def test_cumulative_breach_engages_terminal_kill(tmp_path):
    calls = []
    r = breakers.evaluate({"cumulative_pnl_pct": -0.25}, _OK,
                          halt_daily=tmp_path / "hd", halt_weekly=tmp_path / "hw",
                          on_kill=lambda reason: calls.append(reason))
    assert "KILL_TERMINAL" in r["actions"] and calls and "TERMINATED" in calls[0]
    print("  ✓ cumulative breach → terminal KILL (PILOT TERMINATED)")


def test_no_hardcoded_protocol_numbers_in_src():
    """The -3/-6/-20 draft numbers must live in config, never in src/live code."""
    for p in (Path(__file__).parent.parent / "src" / "live").glob("*.py"):
        t = p.read_text()
        for n in ("0.03", "0.06", "0.20"):
            assert n not in t, f"{p.name} hardcodes a breaker number {n}"
    print("  ✓ no breaker numbers hardcoded in src/live (config-only)")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_live_kill_cli_status_smoke(capsys):
    import importlib.util, sys
    from pathlib import Path
    p = Path(__file__).parent.parent / "scripts" / "live_kill.py"
    spec = importlib.util.spec_from_file_location("live_kill", p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    assert m.main(["status"]) == 0                       # operator status runs clean
    out = capsys.readouterr().out
    assert "kill" in out and "HALT_DAILY" in out
    print("  ✓ live_kill.py status CLI wired")
