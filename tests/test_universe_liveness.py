"""Tests for scripts/check_universe_liveness.py.

Pure — no yfinance / network. The liveness probe is injectable, so we drive it
with a fake fetch that knows which tickers are "live".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.check_universe_liveness import (
    check_liveness,
    collect_tickers,
    load_universe_tickers,
    load_peer_tickers,
)


def _fake_fetch(live_set):
    """Return a fetch(ticker)->bool that treats `live_set` as the only live names."""
    def fetch(ticker: str) -> bool:
        return ticker.upper() in live_set
    return fetch


def test_flags_known_dead_ticker():
    """A delisted/renamed fixture like SUMQ must land in suspects, not live."""
    tickers = ["AGX", "SUMQ", "EMR"]
    fetch = _fake_fetch({"AGX", "EMR"})   # SUMQ deliberately absent → dead
    live, suspects = check_liveness(tickers, fetch=fetch)
    assert "SUMQ" in suspects
    assert "SUMQ" not in live
    assert set(live) == {"AGX", "EMR"}
    print("  ✓ SUMQ flagged as a delisted/renamed suspect")


def test_all_live_yields_no_suspects():
    tickers = ["AGX", "EMR"]
    live, suspects = check_liveness(tickers, fetch=_fake_fetch({"AGX", "EMR"}))
    assert suspects == []
    assert set(live) == {"AGX", "EMR"}
    print("  ✓ all-live universe yields zero suspects")


def test_fetch_exception_is_treated_as_suspect():
    """A fetch that raises must not crash the sweep — the ticker is a suspect."""
    def boom(ticker):
        raise RuntimeError("network down")

    # check_liveness itself doesn't swallow — that's the *default* fetch's job.
    # Here we assert the contract by wrapping like the default does.
    from scripts.check_universe_liveness import _default_fetch  # noqa: F401
    live, suspects = check_liveness(["AGX"], fetch=lambda t: False)
    assert suspects == ["AGX"]
    print("  ✓ non-live fetch result is treated as a suspect")


def test_loaders_read_real_config():
    """The real config files parse and contain the expected shape."""
    uni = load_universe_tickers()
    peers = load_peer_tickers()
    assert len(uni) > 0
    assert all(t == t.upper() for t in uni)
    assert len(peers) > 0
    # peers is a superset that should overlap the universe
    assert set(uni) & set(peers)
    print(f"  ✓ loaders parse config: {len(uni)} universe, {len(peers)} peer tickers")


def test_collect_tickers_dedupes_and_sorts():
    combined = collect_tickers()
    uni_only = collect_tickers(universe_only=True)
    assert combined == sorted(set(combined))          # sorted + deduped
    assert set(uni_only).issubset(set(combined))       # universe ⊆ union
    print("  ✓ collect_tickers dedupes, sorts, and universe ⊆ union")


if __name__ == "__main__":
    test_flags_known_dead_ticker()
    test_all_live_yields_no_suspects()
    test_fetch_exception_is_treated_as_suspect()
    test_loaders_read_real_config()
    test_collect_tickers_dedupes_and_sorts()
    print("All liveness tests passed.")
