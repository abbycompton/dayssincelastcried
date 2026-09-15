"""We Work Remotely RSS feeds. Titles come as "Company: Job Title"; WWR's feed
includes a pubDate (RFC 822) and a custom <region> tag for location."""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from ..http_client import HttpClient
from ..models import Posting

logger = logging.getLogger("job_search_agent")

# Category feeds relevant to the target titles (program/ops/management-shaped
# roles rarely land in the "programming"/"design" feeds WWR is best known for).
FEED_URLS = [
    "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
]


def fetch(client: HttpClient) -> list[Posting]:
    postings: list[Posting] = []
    for feed_url in FEED_URLS:
        postings.extend(_fetch_feed(feed_url, client))
    return postings


def _fetch_feed(feed_url: str, client: HttpClient) -> list[Posting]:
    resp = client.get(feed_url)
    if resp is None:
        logger.error("[weworkremotely] request failed for %s", feed_url)
        return []
    if resp.status_code != 200:
        logger.error("[weworkremotely] HTTP %s for %s", resp.status_code, feed_url)
        return []

    soup = BeautifulSoup(resp.content, "xml")
    postings: list[Posting] = []
    for item in soup.find_all("item"):
        raw_title = item.find("title").get_text(strip=True) if item.find("title") else ""
        company, _, title = raw_title.partition(": ")
        if not title:
            title, company = company, ""

        link = item.find("link").get_text(strip=True) if item.find("link") else ""
        pub_date_tag = item.find("pubDate")
        posted_at = None
        if pub_date_tag and pub_date_tag.get_text(strip=True):
            try:
                posted_at = dateutil_parser.parse(pub_date_tag.get_text(strip=True))
            except (ValueError, OverflowError):
                posted_at = None

        region_tag = item.find("region")
        location = region_tag.get_text(strip=True) if region_tag else "Remote"

        guid_tag = item.find("guid")
        posting_id = guid_tag.get_text(strip=True) if guid_tag else None

        postings.append(
            Posting(
                company=company.strip(),
                title=title.strip(),
                url=link,
                source="wwr",
                location=location,
                posted_at=posted_at,
                date_confidence="high",
                posting_id=posting_id,
                remote=True,
                raw={"title": raw_title},
            )
        )
    return postings
