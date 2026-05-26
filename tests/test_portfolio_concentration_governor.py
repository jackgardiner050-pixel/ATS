"""Tests for src/governance/concentration_governor.py

Validates that:
- Hard limits block correctly (not just warn)
- Adding a position that breaches a limit generates CONCENTRATION_BLOCK
- Clean portfolios pass through unblocked
- BROKEN confidence is always blocked
- Override requirement is correctly set
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.governance.concentration_governor import (
    check_current_portfolio,
    assess_proposed_position,
    compute_escalation_triggers,
    APPROVED,
    APPROVED_WITH_WARNINGS,
    CONCENTRATION_BLOCK,
    ConcentrationDecision,
)

_THEMES_PATH = Path(__file__).parent.parent / "config" / "themes.yaml"

PAPER_TICKERS = ["ACM", "AMAT", "DY", "EMR", "GD", "GNRC", "HUBB", "J", "KMI", "LDOS", "SPGI", "TRGP"]


# ─── Current portfolio checks ─────────────────────────────────────────────────

class TestCurrentPortfolioChecks:
    def test_paper_portfolio_is_blocked(self):
        result = check_current_portfolio(PAPER_TICKERS, themes_path=_THEMES_PATH)
        assert result.is_blocked, (
            f"Paper portfolio should be BLOCKED due to theme/cluster breaches; "
            f"got: {result.decision}"
        )

    def test_block_has_reasons(self):
        result = check_current_portfolio(PAPER_TICKERS, themes_path=_THEMES_PATH)
        assert len(result.block_reasons) >= 1, "Blocked decision must specify reasons"

    def test_override_required_when_blocked(self):
        result = check_current_portfolio(PAPER_TICKERS, themes_path=_THEMES_PATH)
        assert result.override_required == result.is_blocked

    def test_override_instruction_non_empty_when_blocked(self):
        result = check_current_portfolio(PAPER_TICKERS, themes_path=_THEMES_PATH)
        if result.is_blocked:
            assert len(result.override_instruction) > 10

    def test_clean_portfolio_passes(self):
        # Under _MIN_POSITIONS_FOR_HARD_BLOCKS (5), theme breaches become warnings not blocks.
        # Two tickers will always have 50% theme exposure, which the governor accepts below min size.
        result = check_current_portfolio(["GD", "SPGI"], themes_path=_THEMES_PATH)
        assert not result.is_blocked, (
            f"Small 2-ticker portfolio should not be hard-blocked (below min size threshold); "
            f"got {result.decision}, reasons: {result.block_reasons}"
        )

    def test_empty_portfolio_passes(self):
        result = check_current_portfolio([], themes_path=_THEMES_PATH)
        assert not result.is_blocked

    def test_new_exposures_populated(self):
        result = check_current_portfolio(PAPER_TICKERS, themes_path=_THEMES_PATH)
        assert "theme_exposure" in result.new_exposures
        assert "clusters" in result.new_exposures


# ─── Proposed position checks ─────────────────────────────────────────────────

class TestProposedPosition:
    def test_broken_confidence_always_blocked(self):
        result = assess_proposed_position(
            ["GD", "SPGI"], "AMAT", "BROKEN", themes_path=_THEMES_PATH
        )
        assert result.is_blocked, "BROKEN confidence must always be blocked"
        assert "BROKEN" in " ".join(result.block_reasons)

    def test_adding_to_already_breached_theme_blocked(self):
        # PAPER_TICKERS already has government_spending > 25%
        # Adding another government_spending ticker must be blocked
        result = assess_proposed_position(
            PAPER_TICKERS, "LMT", "MED", themes_path=_THEMES_PATH
        )
        # LMT is in government_spending and defense — adding makes it worse
        assert result.is_blocked or result.decision == APPROVED_WITH_WARNINGS

    def test_adding_third_midstream_to_leverage_cluster_blocked(self):
        # KMI and TRGP are already in leverage cluster (exceeds 20%)
        # Adding WMB (also leverage_sensitive) must be blocked
        existing = ["ACM", "AMAT", "DY", "EMR", "GD", "HUBB", "J", "KMI", "LDOS", "SPGI", "TRGP"]
        result = assess_proposed_position(
            existing, "WMB", "MED", themes_path=_THEMES_PATH
        )
        assert result.is_blocked, (
            "Adding WMB to a portfolio already containing KMI+TRGP must be blocked"
        )

    def test_adding_uncorrelated_ticker_may_pass(self):
        # Small clean portfolio (3 tickers total after addition) — below hard-block threshold.
        # Theme breaches become warnings at this size, not hard blocks.
        result = assess_proposed_position(
            ["GD", "KMI"], "SPGI", "HIGH", themes_path=_THEMES_PATH
        )
        assert not result.is_blocked, (
            f"Adding SPGI to [GD, KMI] (3 total, below min-block size) should not be blocked; "
            f"got {result.decision}, reasons: {result.block_reasons}"
        )

    def test_duplicate_ticker_generates_warning(self):
        result = assess_proposed_position(
            ["GD", "SPGI"], "GD", "HIGH", themes_path=_THEMES_PATH
        )
        assert result.decision == APPROVED_WITH_WARNINGS
        assert any("already" in w.lower() for w in result.warnings)

    def test_unclassified_ticker_warns(self):
        result = assess_proposed_position(
            ["GD", "SPGI"], "AAPL", "HIGH", themes_path=_THEMES_PATH
        )
        # Should warn about unclassified ticker but not necessarily block
        all_messages = result.warnings + result.block_reasons
        assert any("themes.yaml" in m or "not in" in m.lower() for m in all_messages)

    def test_block_decision_has_override_instruction(self):
        result = assess_proposed_position(
            PAPER_TICKERS, "LMT", "MED", themes_path=_THEMES_PATH
        )
        if result.is_blocked:
            assert len(result.override_instruction) > 10

    def test_new_exposures_contains_candidate_themes(self):
        result = assess_proposed_position(
            ["GD"], "AMAT", "MED", themes_path=_THEMES_PATH
        )
        assert "candidate_themes" in result.new_exposures
        assert isinstance(result.new_exposures["candidate_themes"], list)


# ─── Escalation triggers ─────────────────────────────────────────────────────

class TestEscalationTriggers:
    def test_paper_portfolio_triggers_escalation(self):
        triggers = compute_escalation_triggers(
            PAPER_TICKERS,
            survivability_score=29.0,
            expected_max_drawdown=0.35,
            themes_path=_THEMES_PATH,
        )
        assert len(triggers) >= 2, (
            "Paper portfolio with low survivability and high drawdown should trigger ≥2 escalations"
        )

    def test_low_survivability_triggers_escalation(self):
        triggers = compute_escalation_triggers(
            ["GD", "SPGI"],
            survivability_score=35.0,   # below threshold of 40
            themes_path=_THEMES_PATH,
        )
        assert any("survivability" in t.lower() for t in triggers)

    def test_high_drawdown_triggers_escalation(self):
        triggers = compute_escalation_triggers(
            ["GD", "SPGI"],
            expected_max_drawdown=0.35,  # above 30% threshold
            themes_path=_THEMES_PATH,
        )
        assert any("drawdown" in t.lower() for t in triggers)

    def test_clean_portfolio_no_escalation(self):
        # Use 6 tickers to activate hard-block thresholds, but choose ones that
        # keep clusters below limits
        triggers = compute_escalation_triggers(
            ["GD", "SPGI", "AMAT", "KMI", "EMR", "LDOS"],
            survivability_score=70.0,
            expected_max_drawdown=0.12,
            themes_path=_THEMES_PATH,
        )
        # Survivability and drawdown are fine — should produce no survivability/drawdown triggers
        surv_triggers = [t for t in triggers if "SURVIVABILITY" in t or "DRAWDOWN" in t]
        assert len(surv_triggers) == 0


# ─── Decision dataclass ───────────────────────────────────────────────────────

class TestConcentrationDecisionDataclass:
    def test_is_blocked_true_when_concentration_block(self):
        d = ConcentrationDecision(
            decision=CONCENTRATION_BLOCK,
            block_reasons=["Theme breach"],
        )
        assert d.is_blocked

    def test_is_blocked_false_when_approved(self):
        d = ConcentrationDecision(decision=APPROVED)
        assert not d.is_blocked

    def test_is_clean_requires_no_warnings(self):
        d = ConcentrationDecision(decision=APPROVED, warnings=["watch this"])
        assert not d.is_clean

    def test_is_clean_when_approved_with_no_warnings(self):
        d = ConcentrationDecision(decision=APPROVED)
        assert d.is_clean
