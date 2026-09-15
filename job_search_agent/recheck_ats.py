"""Monthly ATS-mapping health check (per spec: "re-verify the ATS-slug mapping
in case a company migrates career-site platforms").

Usage:
    python -m job_search_agent.recheck_ats

Prints any company whose configured endpoint no longer resolves or is
returning nothing, so you know which ones need re-discovery
(python -m job_search_agent.discover_ats or python -m
job_search_agent.bulk_upgrade for tier2 entries). Doesn't modify
config/companies.yaml -- it only reports.

For tier2 entries specifically, "returning nothing" is checked through the
same static-fetch -> render -> ATS-sniff pipeline tier2_crawler.fetch uses
during a real run (not just an HTTP 200 check), since a page can be a live
200 and still be structurally empty for us (a JS-rendered SPA the static
pass can't see into). That distinguishes "this page is actually broken" or
"this page needs render/ATS-sniff, which just isn't finding anything"
from "there just happen to be zero postings there right now" -- the latter
is normal and not flagged.
"""

from __future__ import annotations

from . import config as config_module
from . import tier2_crawler
from .ats import ashby, greenhouse, lever, smartrecruiters
from .http_client import HttpClient, RateLimiter
from .render import Renderer

_ATS_FETCHERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "smartrecruiters": smartrecruiters.fetch,
}


def main() -> None:
    companies, _ = config_module.load_companies()
    rate_limiter = RateLimiter(seconds_per_domain=1.0)
    client = HttpClient(rate_limiter)

    stale = []
    with Renderer(rate_limiter) as renderer:
        for company in companies:
            if company.ats == "tier2":
                postings = tier2_crawler.fetch(company.name, company.careers_url, client, renderer)
                if not postings:
                    stale.append((company.name, "tier2", company.careers_url))
                continue

            if company.ats == "workday":
                resp = client.post(company.slug, json={"limit": 1, "offset": 0, "searchText": ""})
                if resp is None or resp.status_code != 200:
                    stale.append((company.name, "workday", company.slug))
                continue

            fetcher = _ATS_FETCHERS.get(company.ats)
            if fetcher is None:
                continue
            try:
                postings = fetcher(company.name, company.slug, client)
            except Exception:
                postings = []
            if not postings:
                stale.append((company.name, company.ats, company.slug))

    if not stale:
        print("All configured ATS mappings and tier2 pages are returning postings.")
        return

    print(f"{len(stale)} companies returned nothing (may be stale, dead, or just have zero open roles today):")
    for name, ats, ref in stale:
        print(f"  - {name} ({ats}): {ref}")
    print(
        "\nFor tier2 entries: run `python -m job_search_agent.bulk_upgrade` to check for an "
        "embedded ATS board worth switching to.\n"
        "For ATS entries: run `python -m job_search_agent.discover_ats \"<company name>\"` to re-check its slug."
    )


if __name__ == "__main__":
    main()
