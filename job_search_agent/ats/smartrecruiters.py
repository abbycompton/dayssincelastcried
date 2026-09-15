"""SmartRecruiters Postings API: api.smartrecruiters.com/v1/companies/{slug}/postings"""

from __future__ import annotations

import logging
from datetime import datetime

from ..http_client import HttpClient
from ..models import Posting

logger = logging.getLogger("job_search_agent")

API_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"


def fetch(company_name: str, slug: str, client: HttpClient) -> list[Posting]:
    url = API_URL.format(slug=slug)
    resp = client.get(url)
    if resp is None:
        logger.error("[smartrecruiters] %s: request failed", company_name)
        return []
    if resp.status_code != 200:
        logger.error("[smartrecruiters] %s: HTTP %s for %s", company_name, resp.status_code, url)
        return []
    try:
        data = resp.json()
    except ValueError:
        logger.error("[smartrecruiters] %s: invalid JSON from %s", company_name, url)
        return []

    postings: list[Posting] = []
    for job in data.get("content", []):
        posted_at = _parse_date(job.get("releasedDate") or job.get("createdOn"))
        location_obj = job.get("location") or {}
        location = ", ".join(
            filter(None, [location_obj.get("city"), location_obj.get("region"), location_obj.get("country")])
        ) or None
        remote = bool(location_obj.get("remote")) if "remote" in location_obj else None
        job_ref = job.get("id")
        apply_url = job.get("applyUrl") or job.get("ref") or ""
        postings.append(
            Posting(
                company=company_name,
                title=job.get("name", "").strip(),
                url=apply_url,
                source="smartrecruiters",
                location=location,
                posted_at=posted_at,
                date_confidence="high",
                posting_id=job_ref,
                remote=remote,
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
