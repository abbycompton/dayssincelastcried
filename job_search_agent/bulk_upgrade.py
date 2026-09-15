"""Scans every `tier2` company in config/companies.yaml and flags any whose
careers_url embeds a known ATS board (via ats_sniff, using the same
static-then-rendered pass tier2_crawler.fetch uses) -- then, with --apply,
moves that company to the matching Tier 1 section.

This is the practical fix for "why do results keep coming back blank": a
Tier 1 API call is far more reliable than scraping a marketing page, so
baking a discovered ATS into config/companies.yaml permanently beats
re-discovering it from scratch (and possibly missing it) on every run.

Usage:
    python -m job_search_agent.bulk_upgrade            # dry run, prints suggestions
    python -m job_search_agent.bulk_upgrade --apply     # rewrites config/companies.yaml

Needs real internet access to do anything useful -- run it from wherever
this tool actually crawls from, not a sandboxed dev environment.
"""

from __future__ import annotations

import argparse
import logging

import yaml

from . import ats_sniff
from . import config as config_module
from .http_client import HttpClient, RateLimiter
from .render import Renderer

logger = logging.getLogger("job_search_agent")


def scan(companies, client: HttpClient, renderer: Renderer) -> list[tuple[str, str, str, str, str | None]]:
    """Returns (company_name, ats, slug_or_url, careers_url, category) for
    every tier2 company whose page embeds a known ATS board."""
    upgrades = []
    for company in companies:
        if company.ats != "tier2" or not company.careers_url:
            continue
        html = _fetch_html(company.careers_url, client, renderer)
        if not html:
            continue
        result = ats_sniff.sniff(html)
        if result:
            ats, slug_or_url = result
            upgrades.append((company.name, ats, slug_or_url, company.careers_url, company.category))
    return upgrades


def _fetch_html(url: str, client: HttpClient, renderer: Renderer) -> str | None:
    resp = client.get(url, respect_robots=True)
    static_html = resp.text if (resp is not None and resp.status_code == 200) else None
    if static_html and ats_sniff.sniff(static_html):
        return static_html
    if renderer.available:
        rendered_html = renderer.render(url)
        if rendered_html:
            return rendered_html
    return static_html


def apply_upgrades(config_path, upgrades: list[tuple[str, str, str, str, str | None]]) -> None:
    with open(config_path) as f:
        data = yaml.safe_load(f)

    tier2_names = {name for name, *_ in upgrades}
    data["tier2"] = [e for e in data.get("tier2", []) if e["name"] not in tier2_names]

    for name, ats, slug_or_url, _careers_url, category in upgrades:
        data.setdefault(ats, []).append(
            {"name": name, "ats": ats, "slug": slug_or_url, "category": category}
        )

    with open(config_path, "w") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True, width=100)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true",
        help="Rewrite config/companies.yaml with the discovered upgrades instead of just printing them.",
    )
    args = parser.parse_args()

    companies, _ = config_module.load_companies()
    rate_limiter = RateLimiter(seconds_per_domain=1.0)
    client = HttpClient(rate_limiter)

    tier2_count = sum(1 for c in companies if c.ats == "tier2")
    print(f"Scanning {tier2_count} tier2 companies for embedded ATS boards (this can take a while)...")

    with Renderer(rate_limiter) as renderer:
        upgrades = scan(companies, client, renderer)

    if not upgrades:
        print("No tier2 companies found embedding a known ATS board.")
        return

    print(f"\n{len(upgrades)} companies can be upgraded from tier2 to a Tier 1 ATS:")
    for name, ats, slug_or_url, careers_url, _category in upgrades:
        print(f"  - {name}: {ats} ({slug_or_url})  [was tier2: {careers_url}]")

    if args.apply:
        apply_upgrades(config_module.CONFIG_DIR / "companies.yaml", upgrades)
        print(f"\nApplied {len(upgrades)} upgrades to config/companies.yaml")
    else:
        print("\nRe-run with --apply to update config/companies.yaml.")


if __name__ == "__main__":
    main()
