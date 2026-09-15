"""Orchestrates one full run: crawl -> filter -> dedup -> verify -> send -> update store.

Usage:
    python -m job_search_agent.main
"""

from __future__ import annotations

import logging
from datetime import date

from . import config as config_module
from .ats import ashby, greenhouse, lever, smartrecruiters, workday
from .aggregators import builtin, indeed, remoteok, weworkremotely
from .dedup import DedupStore
from .digest import build_html_digest, build_text_digest
from .email_delivery import get_sender
from .filters import Decision, apply_pipeline
from .http_client import HttpClient, RateLimiter
from .models import Posting
from .render import Renderer
from .verify import verify_postings
from . import tier2_crawler

logger = logging.getLogger("job_search_agent")

_ATS_FETCHERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "smartrecruiters": smartrecruiters.fetch,
    "workday": workday.fetch,
}


def setup_logging(error_log_path) -> None:
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(console_handler)

    # Per-company/per-source failures land here too, per spec: "so silent
    # failures don't quietly shrink the crawl coverage over time."
    error_log_path.parent.mkdir(parents=True, exist_ok=True)
    error_handler = logging.FileHandler(error_log_path)
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(error_handler)


def crawl_companies(companies, client: HttpClient, renderer: Renderer | None = None) -> list[Posting]:
    postings: list[Posting] = []
    for company in companies:
        try:
            if company.ats == "tier2":
                if not company.careers_url:
                    logger.error("[crawl] %s: tier2 entry missing careers_url, skipping", company.name)
                    continue
                postings.extend(tier2_crawler.fetch(company.name, company.careers_url, client, renderer))
            else:
                fetcher = _ATS_FETCHERS.get(company.ats)
                if fetcher is None:
                    logger.error("[crawl] %s: unknown ATS %r, skipping", company.name, company.ats)
                    continue
                if not company.slug:
                    logger.error("[crawl] %s: %s entry missing slug, skipping", company.name, company.ats)
                    continue
                postings.extend(fetcher(company.name, company.slug, client))
        except Exception:
            logger.exception("[crawl] %s (%s): unhandled error", company.name, company.ats)
    return postings


def crawl_aggregators(settings: config_module.Settings, target_titles: list[str], client: HttpClient) -> list[Posting]:
    postings: list[Posting] = []
    agg = settings.aggregators

    if agg.get("remoteok"):
        try:
            postings.extend(remoteok.fetch(client))
        except Exception:
            logger.exception("[crawl] remoteok: unhandled error")

    if agg.get("weworkremotely"):
        try:
            postings.extend(weworkremotely.fetch(client))
        except Exception:
            logger.exception("[crawl] weworkremotely: unhandled error")

    if agg.get("builtin"):
        for title in target_titles:
            try:
                postings.extend(builtin.fetch(title, client))
            except Exception:
                logger.exception("[crawl] builtin (%s): unhandled error", title)

    if agg.get("indeed"):
        for title in target_titles:
            try:
                postings.extend(indeed.fetch(title, client))
            except Exception:
                logger.exception("[crawl] indeed (%s): unhandled error", title)

    return postings


def run() -> None:
    settings = config_module.load_settings()
    setup_logging(settings.error_log_path)

    target_titles, fuzzy_threshold = config_module.load_titles()
    companies, excluded_names = config_module.load_companies()
    target_company_names = {c.name.strip().lower() for c in companies}

    rate_limiter = RateLimiter(settings.rate_limit_seconds_per_domain)
    client = HttpClient(rate_limiter, settings.request_timeout_seconds)

    logger.info("Crawling %d configured companies (Tier 1 + Tier 2)...", len(companies))
    with Renderer(rate_limiter) as renderer:
        all_postings = crawl_companies(companies, client, renderer)

    logger.info("Crawling Tier 3 aggregators...")
    all_postings.extend(crawl_aggregators(settings, target_titles, client))

    logger.info("Crawled %d raw postings total; applying filters...", len(all_postings))
    results = apply_pipeline(
        all_postings,
        target_titles=target_titles,
        fuzzy_threshold=fuzzy_threshold,
        target_company_names=target_company_names,
        excluded_names=excluded_names,
        lookback_days=settings.lookback_days,
        accepted_onsite_locations=settings.accepted_onsite_locations,
    )

    included = [r.posting for r in results if r.decision == Decision.INCLUDE]
    review_items = [r for r in results if r.decision == Decision.REVIEW]

    for item in review_items:
        logger.warning(
            "[review] ambiguous location, needs manual check: %s @ %s | %s | %s",
            item.posting.title, item.posting.company, item.reason, item.posting.url,
        )

    logger.info("%d postings passed title/company/freshness/location filters", len(included))

    with DedupStore(settings.dedup_store_path) as store:
        new_postings = store.filter_new(included)
        logger.info("%d are new (not previously surfaced)", len(new_postings))

        try:
            verified = verify_postings(new_postings, client)
        except Exception:
            logger.exception("[verify] unhandled error during live-link verification")
            verified = []
        logger.info("%d verified live immediately before sending", len(verified))

        run_date = date.today()
        text_digest = build_text_digest(verified, run_date)
        html_digest = build_html_digest(verified, run_date)
        subject = f"{settings.email.subject_prefix} {run_date.isoformat()}"

        sender = get_sender(settings.email)
        sender.send(subject, text_digest, html_digest)
        logger.info("Digest sent (%d new postings)", len(verified))

        # Only mark as seen once the send succeeded, so a failed send doesn't
        # silently drop postings from tomorrow's digest.
        store.record_seen([v.posting for v in verified])


if __name__ == "__main__":
    run()
