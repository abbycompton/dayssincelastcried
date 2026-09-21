"""Orchestrates one full run: crawl -> filter -> dedup -> verify -> send -> update store.

Usage:
    python -m job_search_agent.main
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

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
from .report import DetailCapture, RunReport
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


def crawl_companies(
    companies,
    client: HttpClient,
    renderer: Renderer | None = None,
    report: RunReport | None = None,
    detail_capture: DetailCapture | None = None,
) -> list[Posting]:
    postings: list[Posting] = []
    for company in companies:
        try:
            if company.ats == "tier2":
                if not company.careers_url:
                    logger.error("[crawl] %s: tier2 entry missing careers_url, skipping", company.name)
                    if report:
                        report.add_company_result(company.name, "tier2", 0, "missing careers_url in config")
                    continue
                company_postings = tier2_crawler.fetch(company.name, company.careers_url, client, renderer)
            else:
                fetcher = _ATS_FETCHERS.get(company.ats)
                if fetcher is None:
                    logger.error("[crawl] %s: unknown ATS %r, skipping", company.name, company.ats)
                    if report:
                        report.add_company_result(company.name, company.ats, 0, f"unknown ATS {company.ats!r}")
                    continue
                if not company.slug:
                    logger.error("[crawl] %s: %s entry missing slug, skipping", company.name, company.ats)
                    if report:
                        report.add_company_result(company.name, company.ats, 0, "missing slug in config")
                    continue
                company_postings = fetcher(company.name, company.slug, client)

            postings.extend(company_postings)
            if report:
                detail = "" if company_postings else (detail_capture.detail_for(company.name) if detail_capture else "")
                report.add_company_result(company.name, company.ats, len(company_postings), detail)
        except Exception as exc:
            logger.exception("[crawl] %s (%s): unhandled error", company.name, company.ats)
            if report:
                report.add_company_exception(company.name, company.ats, str(exc))
    return postings


def crawl_aggregators(
    settings: config_module.Settings,
    target_titles: list[str],
    client: HttpClient,
    report: RunReport | None = None,
) -> list[Posting]:
    postings: list[Posting] = []
    agg = settings.aggregators

    if agg.get("remoteok"):
        try:
            found = remoteok.fetch(client)
            postings.extend(found)
            if report:
                report.add_aggregator_result("remoteok", len(found))
        except Exception as exc:
            logger.exception("[crawl] remoteok: unhandled error")
            if report:
                report.add_aggregator_exception("remoteok", str(exc))

    if agg.get("weworkremotely"):
        try:
            found = weworkremotely.fetch(client)
            postings.extend(found)
            if report:
                report.add_aggregator_result("weworkremotely", len(found))
        except Exception as exc:
            logger.exception("[crawl] weworkremotely: unhandled error")
            if report:
                report.add_aggregator_exception("weworkremotely", str(exc))

    if agg.get("builtin"):
        builtin_total = 0
        builtin_errors: list[str] = []
        for title in target_titles:
            try:
                found = builtin.fetch(title, client)
                postings.extend(found)
                builtin_total += len(found)
            except Exception as exc:
                logger.exception("[crawl] builtin (%s): unhandled error", title)
                builtin_errors.append(f"{title}: {exc}")
        if report:
            if builtin_errors and builtin_total == 0:
                report.add_aggregator_exception("builtin", "; ".join(builtin_errors))
            else:
                detail = "; ".join(builtin_errors) if builtin_errors else ""
                report.add_aggregator_result("builtin", builtin_total, detail)

    if agg.get("indeed"):
        indeed_total = 0
        indeed_errors: list[str] = []
        for title in target_titles:
            try:
                found = indeed.fetch(title, client)
                postings.extend(found)
                indeed_total += len(found)
            except Exception as exc:
                logger.exception("[crawl] indeed (%s): unhandled error", title)
                indeed_errors.append(f"{title}: {exc}")
        if report:
            if indeed_errors and indeed_total == 0:
                report.add_aggregator_exception("indeed", "; ".join(indeed_errors))
            else:
                detail = "; ".join(indeed_errors) if indeed_errors else ""
                report.add_aggregator_result("indeed", indeed_total, detail)

    return postings


def run() -> None:
    settings = config_module.load_settings()
    setup_logging(settings.error_log_path)

    report = RunReport(started_at=datetime.now(timezone.utc))
    detail_capture = DetailCapture()
    logger.addHandler(detail_capture)

    try:
        _run_pipeline(settings, report, detail_capture)
    finally:
        logger.removeHandler(detail_capture)
        report.finished_at = datetime.now(timezone.utc)
        report_dir = settings.error_log_path.parent
        json_path, md_path = report.write(report_dir)
        logger.info("Run report written to %s and %s", json_path, md_path)


def _run_pipeline(settings: config_module.Settings, report: RunReport, detail_capture: DetailCapture) -> None:
    target_titles, fuzzy_threshold = config_module.load_titles()
    companies, excluded_names = config_module.load_companies()
    target_company_names = {c.name.strip().lower() for c in companies}

    rate_limiter = RateLimiter(settings.rate_limit_seconds_per_domain)
    client = HttpClient(rate_limiter, settings.request_timeout_seconds)

    logger.info("Crawling %d configured companies (Tier 1 + Tier 2)...", len(companies))
    with Renderer(rate_limiter) as renderer:
        all_postings = crawl_companies(companies, client, renderer, report, detail_capture)

    logger.info("Crawling Tier 3 aggregators...")
    all_postings.extend(crawl_aggregators(settings, target_titles, client, report))

    report.raw_postings = len(all_postings)
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
    report.after_filters = len(included)
    report.review_flagged = len(review_items)

    for item in review_items:
        logger.warning(
            "[review] ambiguous location, needs manual check: %s @ %s | %s | %s",
            item.posting.title, item.posting.company, item.reason, item.posting.url,
        )

    logger.info("%d postings passed title/company/freshness/location filters", len(included))

    with DedupStore(settings.dedup_store_path) as store:
        new_postings = store.filter_new(included)
        report.new_after_dedup = len(new_postings)
        logger.info("%d are new (not previously surfaced)", len(new_postings))

        try:
            verified = verify_postings(new_postings, client)
        except Exception:
            logger.exception("[verify] unhandled error during live-link verification")
            verified = []
        report.verified_live = len(verified)
        logger.info("%d verified live immediately before sending", len(verified))

        run_date = date.today()
        text_digest = build_text_digest(verified, run_date)
        html_digest = build_html_digest(verified, run_date)
        subject = f"{settings.email.subject_prefix} {run_date.isoformat()}"

        try:
            sender = get_sender(settings.email)
            sender.send(subject, text_digest, html_digest)
            report.email_sent = True
            logger.info("Digest sent (%d new postings)", len(verified))
        except Exception as exc:
            logger.exception("[email] failed to send digest")
            report.email_sent = False
            report.email_error = str(exc)
            return

        # Only mark as seen once the send succeeded, so a failed send doesn't
        # silently drop postings from tomorrow's digest.
        store.record_seen([v.posting for v in verified])


if __name__ == "__main__":
    run()
