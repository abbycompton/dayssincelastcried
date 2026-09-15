"""Live-link verification: run immediately before sending the digest, never
from a cached prior crawl (per spec -- a posting that was live yesterday may
not be live today).

Checks, in order: HTTP 200, no soft-404 phrasing, and the expected job title
(or a strong fuzzy match of it) still appears in the rendered response body.

Known limitation: this is a plain HTTP fetch, not a headless browser. A page
that 404s only after client-side JS runs (observed once with an Airbnb
careers link, which returned full content on direct fetch but reportedly
404'd in-browser) can still pass this check. There is no cheap fix for that
without a browser automation dependency; treat this as "best available
automated signal," not a guarantee.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from rapidfuzz import fuzz

from .http_client import HttpClient
from .models import Posting

logger = logging.getLogger("job_search_agent")

_SOFT_404_PHRASES = (
    "no longer available",
    "no longer accepting applications",
    "position has been filled",
    "job not found",
    "page not found",
    "posting has closed",
    "this job is no longer open",
)

_TITLE_MATCH_THRESHOLD = 80


@dataclass
class VerifiedPosting:
    posting: Posting
    verified_at: datetime


def verify_postings(postings: list[Posting], client: HttpClient) -> list[VerifiedPosting]:
    verified: list[VerifiedPosting] = []
    for posting in postings:
        if _verify_one(posting, client):
            verified.append(VerifiedPosting(posting=posting, verified_at=datetime.now(timezone.utc)))
        else:
            logger.info("[verify] dropped (failed live check): %s @ %s (%s)", posting.title, posting.company, posting.url)
    return verified


def _verify_one(posting: Posting, client: HttpClient) -> bool:
    if not posting.url:
        return False

    resp = client.get(posting.url)
    if resp is None or resp.status_code != 200:
        return False

    body_text = _extract_text(resp.text)
    body_lower = body_text.lower()

    if any(phrase in body_lower for phrase in _SOFT_404_PHRASES):
        return False

    title_lower = posting.title.lower().strip()
    if title_lower and title_lower in body_lower:
        return True

    # Fall back to a fuzzy check against the page's visible text in case of
    # minor formatting differences (e.g. "Sr." vs "Senior").
    return fuzz.partial_ratio(title_lower, body_lower) >= _TITLE_MATCH_THRESHOLD


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(" ", strip=True)
