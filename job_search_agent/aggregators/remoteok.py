"""RemoteOK API: remoteok.com/api (JSON, structured, includes epoch timestamp)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..http_client import HttpClient
from ..models import Posting

logger = logging.getLogger("job_search_agent")

API_URL = "https://remoteok.com/api"


def fetch(client: HttpClient) -> list[Posting]:
    resp = client.get(API_URL)
    if resp is None:
        logger.error("[remoteok] request failed")
        return []
    if resp.status_code != 200:
        logger.error("[remoteok] HTTP %s", resp.status_code)
        return []
    try:
        data = resp.json()
    except ValueError:
        logger.error("[remoteok] invalid JSON")
        return []

    postings: list[Posting] = []
    for job in data:
        # The first array element is a legal/metadata notice, not a job.
        if not isinstance(job, dict) or "id" not in job or "position" not in job:
            continue

        posted_at = None
        epoch = job.get("epoch")
        if epoch:
            try:
                posted_at = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
            except (ValueError, OverflowError):
                posted_at = None

        postings.append(
            Posting(
                company=(job.get("company") or "").strip(),
                title=(job.get("position") or "").strip(),
                url=job.get("url", ""),
                source="remoteok",
                location=job.get("location") or "Remote",
                posted_at=posted_at,
                date_confidence="high",
                posting_id=str(job.get("id")),
                remote=True,
                raw=job,
            )
        )
    return postings
