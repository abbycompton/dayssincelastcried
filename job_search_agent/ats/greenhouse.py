"""Greenhouse Job Board API: boards-api.greenhouse.io/v1/boards/{slug}/jobs"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

from ..http_client import HttpClient
from ..models import Posting

logger = logging.getLogger("job_search_agent")

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def fetch(company_name: str, slug: str, client: HttpClient) -> list[Posting]:
    url = API_URL.format(slug=slug)
    resp = client.get(url)
    if resp is None:
        logger.error("[greenhouse] %s: request failed", company_name)
        return []
    if resp.status_code != 200:
        logger.error("[greenhouse] %s: HTTP %s for %s", company_name, resp.status_code, url)
        return []
    try:
        data = resp.json()
    except ValueError:
        logger.error("[greenhouse] %s: invalid JSON from %s", company_name, url)
        return []

    postings: list[Posting] = []
    for job in data.get("jobs", []):
        posted_at = _parse_date(job.get("updated_at"))
        location = (job.get("location") or {}).get("name")
        postings.append(
            Posting(
                company=company_name,
                title=job.get("title", "").strip(),
                url=job.get("absolute_url", ""),
                source="greenhouse",
                location=location,
                posted_at=posted_at,
                date_confidence="high",
                posting_id=str(job.get("id")) if job.get("id") is not None else None,
                raw=job,
            )
        )
    return postings


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        # Greenhouse uses ISO 8601 with timezone, e.g. "2026-09-10T12:00:00-04:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None
