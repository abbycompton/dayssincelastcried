"""Tier 2 fallback: direct crawl of a company's careers page for companies with
no Tier 1 ATS API.

This is inherently lower-fidelity than a structured API: dates are often
missing or relative ("2 days ago"), so every posting from here carries
date_confidence="low" and is held to the freshness filter's normal bar (a
missing date still excludes it -- Tier 2 doesn't get a pass on that, per spec:
"No date = excluded, not included-with-caveat"). It only gets a *reduced*
bar for how confident the pipeline is when a date IS present.

Two things keep this from silently coming back blank on a modern SPA-style
careers page:
  1. ATS sniffing (ats_sniff.py): if the page embeds a known Greenhouse/
     Lever/Ashby/SmartRecruiters/Workday board, fetch that directly instead
     of trying to scrape the wrapper page's text.
  2. A headless-render fallback (render.py, optional): if the static fetch
     finds nothing at all, retry through a real headless browser so
     client-side-rendered listings get a chance to show up.
If both come up empty, that's logged as a distinct warning rather than
silently looking like "zero open roles today" -- see the bottom of fetch().
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from . import ats_sniff
from .ats import ashby, greenhouse, lever, smartrecruiters, workday
from .http_client import HttpClient
from .jsonld import extract_job_postings
from .models import Posting
from .render import Renderer

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

_ATS_MODULES = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workday": workday,
}


def fetch(
    company_name: str,
    careers_url: str,
    client: HttpClient,
    renderer: Renderer | None = None,
) -> list[Posting]:
    resp = client.get(careers_url, respect_robots=True)
    if resp is None:
        logger.error("[tier2] %s: could not fetch %s (request failed or robots.txt disallowed)", company_name, careers_url)
        return []
    if resp.status_code != 200:
        logger.error("[tier2] %s: HTTP %s for %s", company_name, resp.status_code, careers_url)
        return []

    postings = _process_html(resp.text, careers_url, company_name, client)
    if postings:
        return postings

    rendered = False
    if renderer is not None and renderer.available:
        rendered_html = renderer.render(careers_url)
        rendered = True
        if rendered_html:
            postings = _process_html(rendered_html, careers_url, company_name, client)
            if postings:
                return postings

    logger.warning(
        "[tier2] %s: zero postings found at %s (%s) -- likely a JS-rendered page "
        "this crawler can't fully see into, a stale/wrong careers_url, or a page "
        "structure it doesn't recognize. NOT necessarily \"no open roles today\" -- "
        "worth a manual check.",
        company_name, careers_url, "static + rendered" if rendered else "static only",
    )
    return []


def _process_html(html: str, careers_url: str, company_name: str, client: HttpClient) -> list[Posting]:
    """Runs the JSON-LD + anchor-heuristic parse; if that finds nothing, tries
    an ATS handoff before giving up on this HTML."""
    soup = BeautifulSoup(html, "lxml")

    postings = _extract_jsonld(soup, careers_url, company_name)
    if postings:
        return postings

    postings = _extract_anchors(soup, careers_url, company_name)
    if postings:
        return postings

    sniff_result = ats_sniff.sniff(html)
    if sniff_result:
        return _handoff_to_ats(sniff_result, company_name, client)

    return []


def _extract_jsonld(soup: BeautifulSoup, careers_url: str, company_name: str) -> list[Posting]:
    postings = extract_job_postings(soup, source="tier2", url_fallback=careers_url)
    for posting in postings:
        posting.company = company_name
    return postings


def _handoff_to_ats(sniff_result: tuple[str, str], company_name: str, client: HttpClient) -> list[Posting]:
    ats, slug_or_url = sniff_result
    module = _ATS_MODULES.get(ats)
    if module is None:
        return []
    try:
        postings = module.fetch(company_name, slug_or_url, client)
    except Exception:
        logger.exception("[tier2] %s: ATS handoff to %s failed", company_name, ats)
        return []
    if postings:
        logger.info(
            "[tier2] %s: found an embedded %s board (%s) with %d posting(s) -- "
            "consider moving this company from tier2 to '%s' in config/companies.yaml "
            "for a more reliable daily crawl",
            company_name, ats, slug_or_url, len(postings), ats,
        )
    return postings


def _extract_anchors(soup: BeautifulSoup, careers_url: str, company_name: str) -> list[Posting]:
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
