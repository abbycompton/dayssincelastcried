"""Lever Postings API: api.lever.co/v0/postings/{slug}?mode=json"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..http_client import HttpClient
from ..models import Posting

logger = logging.getLogger("job_search_agent")

API_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


def fetch(company_name: str, slug: str, client: HttpClient) -> list[Posting]:
    url = API_URL.format(slug=slug)
    resp = client.get(url)
    if resp is None:
        logger.error("[lever] %s: request failed", company_name)
        return []
    if resp.status_code != 200:
        logger.error("[lever] %s: HTTP %s for %s", company_name, resp.status_code, url)
        return []
    try:
        data = resp.json()
    except ValueError:
        logger.error("[lever] %s: invalid JSON from %s", company_name, url)
        return []

    postings: list[Posting] = []
    for job in data:
        created_at_ms = job.get("createdAt")
        posted_at = None
        if created_at_ms is not None:
            try:
                posted_at = datetime.fromtimestamp(int(created_at_ms) / 1000, tz=timezone.utc)
            except (ValueError, OverflowError):
                posted_at = None
        categories = job.get("categories") or {}
        location = categories.get("location")
        postings.append(
            Posting(
                company=company_name,
                title=job.get("text", "").strip(),
                url=job.get("hostedUrl", ""),
                source="lever",
                location=location,
                posted_at=posted_at,
                date_confidence="high",
                posting_id=job.get("id"),
                raw=job,
            )
        )
    return postings
