"""ATS version lineage — included in every governance output for auditability.

Bump GOVERNANCE_VERSION whenever src/governance/* logic changes.
Bump UNIVERSE_VERSION whenever config/universe.yaml or universe_taxonomy.yaml changes.
Bump ATS_VERSION for significant cross-cutting releases.
"""
ATS_VERSION = "3.0.0"         # Phase III complete (universe governance)
GOVERNANCE_VERSION = "2.1.0"  # Phase II + Phase III universe intelligence layer
UNIVERSE_VERSION = "1.1.0"    # 147 tickers, 25 economic behavior archetypes
BUILD_DATE = "2026-05-26"


def version_dict() -> dict:
    return {
        "ats_version": ATS_VERSION,
        "governance_version": GOVERNANCE_VERSION,
        "universe_version": UNIVERSE_VERSION,
        "build_date": BUILD_DATE,
    }
