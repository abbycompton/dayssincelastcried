"""Tier 2 fallback: direct crawl of a company's careers page for companies with
no Tier 1 ATS API.

This is inherently lower-fidelity than a structured API: dates are often
missing or relative ("2 days ago"), so every posting from here carries
date_confidence="low" and is held to the freshness filter's normal bar (a
missing date still excludes it -- Tier 2 doesn't get a pass on that, per spec:
"No date = excluded, not included-with-caveat"). It only gets a *reduced*
bar for how confident the pipeline is when a date IS present.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from .http_client import HttpClient
from .jsonld import extract_job_postings
from .models import Posting

logger = logging.getLogger("job_search_agent")

# Anchor text/href patterns that are almost never a job title/link, to cut
# down on nav/footer noise before we even try to extract a title.
_SKIP_HREF_PATTERNS = re.compile(
    r"(privacy|terms|cookie|login|sign-?in|sign-?up|#$|mailto:|tel:|javascript:)", re.I
)
_JOB_HREF_HINTS = re.compile(r"(job|career|position|posting|req|opening|role)", re.I)

_RELATIVE_DATE_RE = re.compile(
    r"(?P<num>\d+)\s*\+?\s*(?P<unit>day|hour|week|month)s?\s+ago", re.I
)


def fetch(company_name: str, careers_url: str, client: HttpClient) -> list[Posting]:
    resp = client.get(careers_url, respect_robots=True)
    if resp is None:
        logger.error("[tier2] %s: could not fetch %s (request failed or robots.txt disallowed)", company_name, careers_url)
        return []
    if resp.status_code != 200:
        logger.error("[tier2] %s: HTTP %s for %s", company_name, resp.status_code, careers_url)
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    # Prefer genuine structured data when the page provides it -- it comes
    # with a real machine-readable date, unlike anything we'd scrape from
    # visible text.
    jsonld_postings = extract_job_postings(soup, source="tier2", url_fallback=careers_url)
    if jsonld_postings:
        for posting in jsonld_postings:
            posting.company = company_name
        return jsonld_postings

    postings: list[Posting] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or _SKIP_HREF_PATTERNS.search(href):
            continue

        title = anchor.get_text(strip=True)
        if not title or not (4 <= len(title) <= 120):
            continue

        # Heuristic: either the link itself looks job-related, or the anchor
        # text matches a job-title shape (avoids grabbing every nav link).
        if not _JOB_HREF_HINTS.search(href) and not _looks_like_job_title(title):
            continue

        absolute_url = urljoin(careers_url, href)
        if urlparse(absolute_url).netloc != urlparse(careers_url).netloc:
            continue  # skip off-site links (ads, social, etc.)
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)

        posted_at = _find_nearby_date(anchor)
        location = _find_nearby_location(anchor)

        postings.append(
            Posting(
                company=company_name,
                title=title,
                url=absolute_url,
                source="tier2",
                location=location,
                posted_at=posted_at,
                date_confidence="low",
                posting_id=None,
                raw={"href": href},
            )
        )

    return postings


def _looks_like_job_title(text: str) -> bool:
    title_keywords = (
        "manager", "director", "lead", "principal", "chief", "engineer",
        "designer", "operations", "program", "coordinator", "specialist",
        "analyst", "head of", "vp ", "vice president",
    )
    lowered = text.lower()
    return any(kw in lowered for kw in title_keywords)


def _find_nearby_date(anchor) -> datetime | None:
    """Looks at the anchor and its immediate siblings/parent text for a date
    string -- either relative ("3 days ago") or absolute. Best-effort only."""
    search_texts = [anchor.get_text(" ", strip=True)]
    if anchor.parent is not None:
        search_texts.append(anchor.parent.get_text(" ", strip=True))

    for text in search_texts:
        rel_match = _RELATIVE_DATE_RE.search(text)
        if rel_match:
            num = int(rel_match.group("num"))
            unit = rel_match.group("unit").lower()
            delta = {
                "hour": timedelta(hours=num),
                "day": timedelta(days=num),
                "week": timedelta(weeks=num),
                "month": timedelta(days=num * 30),
            }[unit]
            return datetime.now() - delta

        try:
            # dateutil is greedy and will misfire on ordinary prose, so only
            # attempt it on short strings that plausibly ARE just a date.
            if len(text) <= 40:
                return dateutil_parser.parse(text, fuzzy=False)
        except (ValueError, OverflowError):
            continue

    return None


def _find_nearby_location(anchor) -> str | None:
    if anchor.parent is None:
        return None
    parent_text = anchor.parent.get_text(" ", strip=True)
    location_match = re.search(
        r"\b(Remote|[A-Z][a-zA-Z.]+(?:\s[A-Z][a-zA-Z.]+)*,\s?[A-Z]{2})\b", parent_text
    )
    return location_match.group(0) if location_match else None
