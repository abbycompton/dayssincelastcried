"""One-time-per-company ATS discovery.

Tests common slug patterns for Greenhouse, Lever, Ashby, and SmartRecruiters
against a company name. Workday has no fixed URL pattern, so it always
requires manual devtools discovery (see ats/workday.py docstring); this tool
just tells you when none of the other four hit, which usually means Workday,
a custom site, or a company that needs the Tier 2 crawl fallback.

Usage:
    python -m job_search_agent.discover_ats "Figma"
    python -m job_search_agent.discover_ats "Figma" "figma-inc" "figma"

The mapping this finds should be hand-added to config/companies.yaml -- this
tool only probes and reports, it doesn't write the config for you.
"""

from __future__ import annotations

import sys

from .http_client import HttpClient, RateLimiter

CHECKS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
}


def slug_candidates(company_name: str) -> list[str]:
    base = company_name.strip().lower()
    candidates = {
        base.replace(" ", ""),
        base.replace(" ", "-"),
        base.replace(" ", "_"),
    }
    return sorted(candidates)


def discover(company_name: str, extra_slugs: list[str] | None = None) -> dict:
    client = HttpClient(RateLimiter(seconds_per_domain=0.5))
    candidates = slug_candidates(company_name) + (extra_slugs or [])
    hits = {}
    for ats, url_template in CHECKS.items():
        for slug in candidates:
            url = url_template.format(slug=slug)
            resp = client.get(url)
            if resp is not None and resp.status_code == 200:
                try:
                    payload = resp.json()
                except ValueError:
                    continue
                # A 200 with an empty/error-shaped body isn't a real match.
                if ats == "greenhouse" and "jobs" not in payload:
                    continue
                if ats == "smartrecruiters" and "content" not in payload:
                    continue
                hits[ats] = slug
                break
    return hits


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    company_name = sys.argv[1]
    extra_slugs = sys.argv[2:]
    hits = discover(company_name, extra_slugs)
    if hits:
        print(f"{company_name}: found {hits}")
        print("Add to config/companies.yaml under the matching ATS section, e.g.:")
        for ats, slug in hits.items():
            print(f"  - name: \"{company_name}\"\n    ats: {ats}\n    slug: \"{slug}\"")
    else:
        print(
            f"{company_name}: no Greenhouse/Lever/Ashby/SmartRecruiters match for "
            f"candidates {slug_candidates(company_name) + extra_slugs}.\n"
            "Check for a Workday CXS endpoint via browser devtools, or add it under "
            "`tier2` in config/companies.yaml with its careers_url."
        )


if __name__ == "__main__":
    main()
