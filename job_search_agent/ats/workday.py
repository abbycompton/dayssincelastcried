"""Workday CXS API fetcher.

Workday doesn't have one fixed API path like the other ATS providers — the
endpoint pattern is `https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`,
but `{tenant}`, `{dc}` and `{site}` vary per company and must be found once via
browser devtools (Network tab, filter for "cxs") while browsing that company's
careers site. Store the discovered full `cxs_url` as the company's `slug` field
in config/companies.yaml (ats: workday, slug: "<full cxs jobs URL>").
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..http_client import HttpClient
from ..models import Posting

logger = logging.getLogger("job_search_agent")

PAGE_SIZE = 20


def fetch(company_name: str, cxs_url: str, client: HttpClient) -> list[Posting]:
    postings: list[Posting] = []
    offset = 0
    while True:
        resp = client.post(
            cxs_url,
            json={"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": ""},
        )
        if resp is None:
            logger.error("[workday] %s: request failed", company_name)
            break
        if resp.status_code != 200:
            logger.error("[workday] %s: HTTP %s for %s", company_name, resp.status_code, cxs_url)
            break
        try:
            data = resp.json()
        except ValueError:
            logger.error("[workday] %s: invalid JSON from %s", company_name, cxs_url)
            break

        job_postings = data.get("jobPostings", [])
        if not job_postings:
            break

        base_url = cxs_url.split("/wday/cxs/")[0]
        for job in job_postings:
            posted_at = _parse_relative_or_none(job.get("postedOn"))
            postings.append(
                Posting(
                    company=company_name,
                    title=job.get("title", "").strip(),
                    url=base_url + job.get("externalPath", ""),
                    source="workday",
                    location=job.get("locationsText"),
                    posted_at=posted_at,
                    date_confidence="low",  # Workday only exposes relative strings like "Posted 3 Days Ago"
                    posting_id=job.get("bulletFields", [None])[0] if job.get("bulletFields") else None,
                    raw=job,
                )
            )

        total = data.get("total", 0)
        offset += PAGE_SIZE
        if offset >= total:
            break

    return postings


def _parse_relative_or_none(_value) -> datetime | None:
    # Workday's `postedOn` is a display string ("Posted Today", "Posted 3 Days Ago"),
    # not a machine-readable timestamp. Per spec ("never surface a posting without a
    # verified, machine-readable posted/updated date"), we deliberately do not guess
    # a datetime from it -- Workday postings rely on date_confidence="low" and get
    # held to the stricter Tier-2 manual-review bar instead of an assumed date.
    return None
