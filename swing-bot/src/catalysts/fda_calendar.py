"""Monitor FDA approval announcements via FDA's free RSS feed.

Polls: https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drug-approvals-actions/rss.xml
No API key required. 15-min polling during market hours.

Returns a catalyst if the approved drug's sponsor ticker is in the watchlist.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

import requests

log = logging.getLogger(__name__)

_FDA_RSS = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drug-approvals-actions/rss.xml"
_TIMEOUT = 15


def get_fda_approvals(
    watchlist_tickers: set[str],
    seen_items: set[str],
) -> list[dict]:
    """Poll FDA approval RSS feed and return catalysts for watchlist tickers.

    Args:
        watchlist_tickers: Set of uppercase ticker symbols.
        seen_items:        RSS item GUIDs already processed.

    Returns:
        List of catalyst dicts: {ticker, title, link, published, catalyst_type}
    """
    try:
        resp = requests.get(_FDA_RSS, timeout=_TIMEOUT, headers={"User-Agent": "SwingBot/1.0"})
        resp.raise_for_status()
        return _parse_rss(resp.text, watchlist_tickers, seen_items)
    except Exception as exc:
        log.warning("FDA RSS fetch failed: %s", exc)
        return []


def _parse_rss(xml: str, watchlist_tickers: set[str], seen_items: set[str]) -> list[dict]:
    """Parse FDA RSS XML and match tickers from item titles/descriptions."""
    catalysts: list[dict] = []
    # Minimal XML parsing without lxml dependency
    items = xml.split("<item>")[1:]
    for item_xml in items:
        guid = _extract_tag(item_xml, "guid") or _extract_tag(item_xml, "link") or ""
        if guid in seen_items:
            continue

        title = _extract_tag(item_xml, "title") or ""
        description = _extract_tag(item_xml, "description") or ""
        link = _extract_tag(item_xml, "link") or ""
        pub_date = _extract_tag(item_xml, "pubDate") or ""

        # Try to match a watchlist ticker from the title or description
        ticker = _match_ticker(title + " " + description, watchlist_tickers)
        if ticker:
            catalysts.append({
                "ticker": ticker,
                "title": title,
                "link": link,
                "published": pub_date,
                "catalyst_type": "FDA_APPROVAL",
                "material": True,
                "confidence": 1.0,
            })
            seen_items.add(guid)

    return catalysts


def _extract_tag(xml: str, tag: str) -> Optional[str]:
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.DOTALL)
    return match.group(1).strip() if match else None


def _match_ticker(text: str, watchlist_tickers: set[str]) -> Optional[str]:
    """Attempt to find a watchlist ticker mentioned in FDA announcement text."""
    text_upper = text.upper()
    for ticker in watchlist_tickers:
        # Match ticker as whole word (e.g., "MRNA" but not inside "ORMRNA")
        if re.search(rf"\b{re.escape(ticker)}\b", text_upper):
            return ticker
    return None
