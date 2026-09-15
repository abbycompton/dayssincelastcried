"""Indeed search results. Per spec: "usable via search but same staleness risk
as LinkedIn" -- so this source ONLY trusts a genuine structured-data date
(schema.org JobPosting JSON-LD), never a relative/visible-text date, and gets
excluded by the freshness filter's normal "no date = excluded" rule just like
everything else. It does not get a special allowance for "apparent age."

Indeed's robots.txt disallows automated fetching of most search paths for
most user agents; http_client.get(respect_robots=True) enforces that, so in
practice this frequently returns nothing. That's expected and correct
behavior, not a bug -- see the etiquette rules in the top-level spec.
"""

from __future__ import annotations

import logging
import urllib.parse

from bs4 import BeautifulSoup

from ..http_client import HttpClient
from ..jsonld import extract_job_postings
from ..models import Posting

logger = logging.getLogger("job_search_agent")

SEARCH_URL = "https://www.indeed.com/jobs?q={query}&l={location}"


def fetch(query: str, client: HttpClient, location: str = "Remote") -> list[Posting]:
    url = SEARCH_URL.format(query=urllib.parse.quote(query), location=urllib.parse.quote(location))
    resp = client.get(url, respect_robots=True)
    if resp is None:
        logger.info("[indeed] skipped %s (request failed or robots.txt disallowed)", url)
        return []
    if resp.status_code != 200:
        logger.error("[indeed] HTTP %s for %s", resp.status_code, url)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    postings: list[Posting] = extract_job_postings(soup, source="indeed", url_fallback=url)
    for posting in postings:
        posting.date_confidence = "high"  # only genuine structured-data dates reach here
    return postings
