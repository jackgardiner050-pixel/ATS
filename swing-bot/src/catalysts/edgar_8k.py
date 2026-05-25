"""Poll EDGAR for new 8-K filings for watchlist tickers.

Phase A: rule-based — material if item code is in high-priority list (1.01, 2.01).
Phase B: filing text passed to classifier.py for Haiku classification.

API: SEC EDGAR EFTS full-text search (free, no key required).
Rate limit: 10 req/sec; we use 1 batch request per poll cycle.
Identity header required by SEC: set EDGAR_IDENTITY in environment.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_CIK_CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "cik_map_cache.json"
_CIK_CACHE_TTL_DAYS = 7

_HIGH_PRIORITY_ITEMS = {"1.01", "2.01"}
_WATCH_ITEMS = {"1.01", "2.01", "5.02", "7.01", "8.01"}


def _user_agent() -> str:
    return os.environ.get("EDGAR_IDENTITY", "Swing Bot research@example.com")


def _headers() -> dict:
    return {"User-Agent": _user_agent(), "Accept-Encoding": "gzip, deflate"}


# ─── CIK map ─────────────────────────────────────────────────────────────────

def _load_cik_map(force_refresh: bool = False) -> dict[str, int]:
    """Return {ticker_upper: cik_int} map, cached locally for 7 days."""
    if not force_refresh and _CIK_CACHE_PATH.exists():
        age = (datetime.now() - datetime.fromtimestamp(_CIK_CACHE_PATH.stat().st_mtime)).days
        if age < _CIK_CACHE_TTL_DAYS:
            with open(_CIK_CACHE_PATH) as f:
                return {k: int(v) for k, v in json.load(f).items()}

    try:
        resp = requests.get(_TICKERS_URL, headers=_headers(), timeout=15)
        resp.raise_for_status()
        raw = resp.json()  # {idx: {cik_str, ticker, title}}
        cik_map = {
            entry["ticker"].upper(): int(entry["cik_str"])
            for entry in raw.values()
            if "ticker" in entry and "cik_str" in entry
        }
        _CIK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CIK_CACHE_PATH, "w") as f:
            json.dump(cik_map, f)
        log.info("CIK map refreshed: %d tickers", len(cik_map))
        return cik_map
    except Exception as exc:
        log.warning("CIK map fetch failed: %s", exc)
        return {}


# ─── EDGAR polling ────────────────────────────────────────────────────────────

def _get_todays_8ks(today: Optional[str] = None) -> list[dict]:
    """Fetch all 8-K filings for today from EDGAR EFTS search (single request)."""
    d = today or date.today().isoformat()
    params = {
        "forms": "8-K",
        "dateRange": "custom",
        "startdt": d,
        "enddt": d,
    }
    try:
        resp = requests.get(_EFTS_URL, params=params, headers=_headers(), timeout=20)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        return hits
    except Exception as exc:
        log.warning("EDGAR EFTS search failed: %s", exc)
        return []


def _cik_from_accession(accession: str) -> Optional[int]:
    """Extract CIK from accession number prefix (first 10 digits)."""
    try:
        prefix = accession.split("-")[0].lstrip("0")
        return int(prefix) if prefix else None
    except (ValueError, IndexError):
        return None


def _get_filing_items(cik: int, accession: str) -> list[str]:
    """Fetch item codes for a specific 8-K filing via the submissions API."""
    try:
        url = _SUBMISSIONS_URL.format(cik=cik)
        resp = requests.get(url, headers=_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})
        accessions = recent.get("accessionNumber", [])
        items_list = recent.get("items", [])
        # Normalize accession for comparison
        acc_norm = accession.replace("-", "")
        for idx, acc in enumerate(accessions):
            if acc.replace("-", "") == acc_norm:
                raw_items = items_list[idx] if idx < len(items_list) else ""
                return [i.strip() for i in raw_items.split(",") if i.strip()]
        return []
    except Exception as exc:
        log.debug("Failed to fetch filing items for CIK %d: %s", cik, exc)
        return []


def get_recent_8ks(
    watchlist_tickers: set[str],
    seen_accessions: set[str],
    phase_b_enabled: bool = False,
) -> list[dict]:
    """Return new material 8-K catalysts for watchlist tickers.

    Args:
        watchlist_tickers: Set of uppercase ticker symbols to filter by.
        seen_accessions:   Accession numbers already processed this session.
        phase_b_enabled:   If True, also returns filing text for Haiku classification.

    Returns:
        List of catalyst dicts:
          {ticker, accession, items, material, text_excerpt, filed_date, catalyst_type}
    """
    cik_map = _load_cik_map()
    watchlist_ciks = {cik_map[t]: t for t in watchlist_tickers if t in cik_map}

    if not watchlist_ciks:
        log.warning("No CIKs found for watchlist tickers — check CIK cache")
        return []

    hits = _get_todays_8ks()
    catalysts: list[dict] = []

    for hit in hits:
        accession = hit.get("_id", "")
        if not accession or accession in seen_accessions:
            continue

        cik = _cik_from_accession(accession)
        if cik not in watchlist_ciks:
            continue

        ticker = watchlist_ciks[cik]
        time.sleep(0.15)  # EDGAR rate limit courtesy pause
        items = _get_filing_items(cik, accession)

        watch_items_found = [i for i in items if i in _WATCH_ITEMS]
        if not watch_items_found:
            continue

        high_priority = any(i in _HIGH_PRIORITY_ITEMS for i in items)
        # Phase A: material if high-priority item code present
        # Phase B: Haiku classifier overrides this with text analysis
        material = high_priority

        text_excerpt = ""
        if phase_b_enabled:
            text_excerpt = _fetch_filing_text(cik, accession)

        catalysts.append({
            "ticker": ticker,
            "accession": accession,
            "items": items,
            "watch_items": watch_items_found,
            "high_priority": high_priority,
            "material": material,
            "text_excerpt": text_excerpt[:5000] if text_excerpt else "",
            "filed_date": date.today().isoformat(),
            "catalyst_type": "8K",
        })
        seen_accessions.add(accession)

    return catalysts


def _fetch_filing_text(cik: int, accession: str) -> str:
    """Fetch the primary document text for an 8-K filing (for Phase B Haiku classification)."""
    try:
        acc_nodash = accession.replace("-", "")
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{acc_nodash}-index.htm"
        )
        resp = requests.get(index_url, headers=_headers(), timeout=15)
        # Crude text extraction — Phase B can improve this
        return resp.text[:5000]
    except Exception:
        return ""
