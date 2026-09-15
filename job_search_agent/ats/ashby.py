"""Ashby Job Board API: api.ashbyhq.com/posting-api/job-board/{slug}"""

from __future__ import annotations

import logging
from datetime import datetime

from ..http_client import HttpClient
from ..models import Posting

logger = logging.getLogger("job_search_agent")

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false"


def fetch(company_name: str, slug: str, client: HttpClient) -> list[Posting]:
    url = API_URL.format(slug=slug)
    resp = client.get(url)
    if resp is None:
        logger.error("[ashby] %s: request failed", company_name)
        return []
    if resp.status_code != 200:
        logger.error("[ashby] %s: HTTP %s for %s", company_name, resp.status_code, url)
        return []
    try:
        data = resp.json()
    except ValueError:
        logger.error("[ashby] %s: invalid JSON from %s", company_name, url)
        return []

    postings: list[Posting] = []
    for job in data.get("jobs", []):
        posted_at = _parse_date(job.get("publishedAt"))
        location = job.get("location") or job.get("locationName")
        is_remote = job.get("isRemote")
        postings.append(
            Posting(
                company=company_name,
                title=job.get("title", "").strip(),
                url=job.get("jobUrl") or job.get("applyUrl", ""),
                source="ashby",
                location=location,
                posted_at=posted_at,
                date_confidence="high",
                posting_id=job.get("id"),
                remote=is_remote,
                raw=job,
            )
        )
    return postings


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
