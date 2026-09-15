"""Extracts schema.org JobPosting structured data from a page's JSON-LD blocks.

Many career sites and aggregators (Indeed, Built In, and plenty of Tier 2
company sites) embed <script type="application/ld+json"> JobPosting markup
for SEO. When present, it's a genuine machine-readable source for the posted
date, so it's preferred over any date parsed from visible page text.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from bs4 import BeautifulSoup

from .models import Posting

logger = logging.getLogger("job_search_agent")


def extract_job_postings(soup: BeautifulSoup, source: str, url_fallback: str = "") -> list[Posting]:
    postings: list[Posting] = []
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except (ValueError, TypeError):
            continue

        for entry in _flatten(data):
            if not isinstance(entry, dict):
                continue
            if entry.get("@type") != "JobPosting":
                continue
            posting = _to_posting(entry, source, url_fallback)
            if posting:
                postings.append(posting)
    return postings


def _flatten(data):
    if isinstance(data, list):
        for item in data:
            yield from _flatten(item)
    elif isinstance(data, dict):
        if "@graph" in data:
            yield from _flatten(data["@graph"])
        else:
            yield data


def _to_posting(entry: dict, source: str, url_fallback: str) -> Posting | None:
    title = entry.get("title")
    if not title:
        return None

    org = entry.get("hiringOrganization") or {}
    company = org.get("name") if isinstance(org, dict) else None
    if not company:
        return None

    posted_at = _parse_date(entry.get("datePosted"))

    location = None
    job_location = entry.get("jobLocation")
    if isinstance(job_location, list) and job_location:
        job_location = job_location[0]
    if isinstance(job_location, dict):
        address = job_location.get("address") or {}
        location = ", ".join(
            filter(None, [address.get("addressLocality"), address.get("addressRegion")])
        ) or None

    remote = None
    if entry.get("jobLocationType") == "TELECOMMUTE" or entry.get("applicantLocationRequirements"):
        remote = True

    url = entry.get("url") or url_fallback

    return Posting(
        company=str(company).strip(),
        title=str(title).strip(),
        url=url,
        source=source,
        location=location,
        posted_at=posted_at,
        date_confidence="high",  # genuine structured-data date
        posting_id=entry.get("identifier", {}).get("value") if isinstance(entry.get("identifier"), dict) else None,
        remote=remote,
        raw=entry,
    )


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
