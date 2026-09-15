"""Built In (builtin.com and city sites like buildinsf.com): searched by title,
per-listing dates extracted from embedded JobPosting structured data.

Built In has no documented public JSON API, so this fetches search-results
pages and relies on schema.org JSON-LD for a genuine posted date (see
jsonld.py) rather than scraping visible page text/CSS, which is fragile and
changes without notice. If a given search page doesn't embed JSON-LD, that
page yields nothing rather than a guessed date.
"""

from __future__ import annotations

import logging
import urllib.parse

from bs4 import BeautifulSoup

from ..http_client import HttpClient
from ..jsonld import extract_job_postings
from ..models import Posting

logger = logging.getLogger("job_search_agent")

SITES = [
    "https://builtin.com",
    "https://www.builtinsf.com",
]


def fetch(query: str, client: HttpClient) -> list[Posting]:
    postings: list[Posting] = []
    for site in SITES:
        search_url = f"{site}/jobs?search={urllib.parse.quote(query)}"
        resp = client.get(search_url, respect_robots=True)
        if resp is None:
            logger.info("[builtin] skipped %s (request failed or robots.txt disallowed)", search_url)
            continue
        if resp.status_code != 200:
            logger.error("[builtin] HTTP %s for %s", resp.status_code, search_url)
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        found = extract_job_postings(soup, source="builtin", url_fallback=search_url)
        for posting in found:
            posting.date_confidence = "high"  # genuine structured-data date
        postings.extend(found)

    return postings
