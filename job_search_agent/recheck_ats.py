"""Monthly ATS-mapping health check (per spec: "re-verify the ATS-slug mapping
in case a company migrates career-site platforms").

Usage:
    python -m job_search_agent.recheck_ats

Prints any company whose configured ATS endpoint no longer resolves, so you
know which ones need re-discovery (python -m job_search_agent.discover_ats).
Doesn't modify config/companies.yaml -- it only reports.
"""

from __future__ import annotations

from . import config as config_module
from .ats import ashby, greenhouse, lever, smartrecruiters
from .http_client import HttpClient, RateLimiter

_ATS_FETCHERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "smartrecruiters": smartrecruiters.fetch,
}


def main() -> None:
    companies, _ = config_module.load_companies()
    client = HttpClient(RateLimiter(seconds_per_domain=1.0))

    stale = []
    for company in companies:
        if company.ats == "tier2":
            resp = client.get(company.careers_url, respect_robots=True)
            if resp is None or resp.status_code != 200:
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
        print("All configured ATS mappings still resolve.")
        return

    print(f"{len(stale)} companies need re-checking (empty/failed result):")
    for name, ats, ref in stale:
        print(f"  - {name} ({ats}): {ref}")
    print("\nRe-run: python -m job_search_agent.discover_ats \"<company name>\"")


if __name__ == "__main__":
    main()
