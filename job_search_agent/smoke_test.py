"""Offline end-to-end smoke test: runs the real crawl -> filter -> dedup ->
verify -> report pipeline against a handful of fake "companies" served by a
local HTTP server on localhost, instead of real company career sites.

Why this exists: it exercises the actual pipeline code (tier2_crawler's
JSON-LD/anchor-heuristic/ATS-sniff/render-fallback chain, the filter
pipeline, dedup, live-link verification, and RunReport) with zero
dependency on outside network access -- useful in a sandboxed dev
environment, and as a fast regression check any time (no rate limits, no
risk of hammering a real site, no waiting on 300+ real companies).

It is NOT a substitute for a real run against config/companies.yaml --
the fixture pages are hand-built to exercise specific code paths, not to
represent what any real company's site looks like.

Usage:
    python -m job_search_agent.smoke_test
"""

from __future__ import annotations

import logging
import tempfile
import threading
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import CompanyEntry
from .dedup import DedupStore
from .digest import build_text_digest
from .filters import Decision, apply_pipeline
from .http_client import HttpClient, RateLimiter
from .main import crawl_companies
from .render import Renderer
from .report import DetailCapture, RunReport
from .verify import verify_postings

SMOKE_TEST_TITLES = ["Senior Program Manager", "Director of Operations", "Lead Program Manager"]

logger = logging.getLogger("job_search_agent")

# path -> (status_code, content_type, body)
FIXTURE_ROUTES: dict[str, tuple[int, str, str]] = {
    "/robots.txt": (200, "text/plain", "User-agent: *\nAllow: /\n"),
    # A: static page with schema.org JobPosting JSON-LD -- should be found
    # on the first pass, no rendering needed, date_confidence "high".
    "/company-a/careers": (
        200, "text/html",
        """<html><body>
        <script type="application/ld+json">
        {"@type": "JobPosting", "title": "Senior Program Manager",
         "datePosted": "%(today)s", "hiringOrganization": {"name": "Company A"},
         "jobLocation": {"address": {"addressLocality": "Remote"}},
         "url": "%(base)s/company-a/jobs/1"}
        </script>
        </body></html>""",
    ),
    # B: plain HTML with a job-shaped anchor -- exercises the anchor
    # heuristic fallback (no JSON-LD present).
    "/company-b/careers": (
        200, "text/html",
        """<html><body>
        <nav><a href="/about">About</a><a href="/privacy">Privacy</a></nav>
        <div class="job-listing">
          <a href="/company-b/jobs/director-of-operations">Director of Operations</a>
          <span>Posted 2 days ago</span>
          <span>Remote, US</span>
        </div>
        </body></html>""",
    ),
    # C: empty shell statically, content injected by JS after load --
    # exercises the Playwright render fallback.
    "/company-c/careers": (
        200, "text/html",
        """<html><body>
        <div id="root">Loading...</div>
        <script>
        setTimeout(function() {
          document.getElementById('root').innerHTML =
            '<a href="/company-c/jobs/pm">Lead Program Manager</a>' +
            '<span>Posted 1 day ago</span><span>Remote</span>';
        }, 500);
        </script>
        </body></html>""",
    ),
    # D: server error -- exercises the HTTP-failure path.
    "/company-d/careers": (500, "text/html", "<html><body>Internal Server Error</body></html>"),
    # E: 404 -- a stale/wrong careers_url.
    "/company-e/careers": (404, "text/html", "<html><body>Not Found</body></html>"),
    # F: embeds a fake Greenhouse board -- exercises ats_sniff detecting an
    # embedded ATS and handing off to it (the handoff itself will fail here
    # since it targets the real boards-api.greenhouse.io, which is exactly
    # the point: it shows the failure surfaces cleanly in the report rather
    # than silently).
    "/company-f/careers": (
        200, "text/html",
        '<html><body><iframe src="https://boards.greenhouse.io/embed/job_board?for=totally-fake-smoketest-slug"></iframe></body></html>',
    ),
    # Job-detail pages, so live-link verification (which re-fetches each
    # posting's own URL) has something real to check against.
    "/company-a/jobs/1": (200, "text/html", "<html><body><h1>Senior Program Manager</h1><p>Apply now.</p></body></html>"),
    "/company-b/jobs/director-of-operations": (200, "text/html", "<html><body><h1>Director of Operations</h1></body></html>"),
    "/company-c/jobs/pm": (200, "text/html", "<html><body><h1>Lead Program Manager</h1></body></html>"),
}


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server's naming convention)
        route = FIXTURE_ROUTES.get(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        status, content_type, body_template = route
        base = f"http://127.0.0.1:{self.server.server_port}"
        body = body_template % {"base": base, "today": datetime.now(timezone.utc).isoformat()}
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):  # noqa: A002 (matches base class signature)
        pass  # silence the default per-request stderr logging


def start_fixture_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    return server, base_url


def build_fixture_companies(base_url: str) -> list[CompanyEntry]:
    return [
        CompanyEntry(name="Company A (JSON-LD)", ats="tier2", careers_url=f"{base_url}/company-a/careers", category="Smoke Test"),
        CompanyEntry(name="Company B (anchor heuristic)", ats="tier2", careers_url=f"{base_url}/company-b/careers", category="Smoke Test"),
        CompanyEntry(name="Company C (JS-rendered)", ats="tier2", careers_url=f"{base_url}/company-c/careers", category="Smoke Test"),
        CompanyEntry(name="Company D (HTTP 500)", ats="tier2", careers_url=f"{base_url}/company-d/careers", category="Smoke Test"),
        CompanyEntry(name="Company E (HTTP 404)", ats="tier2", careers_url=f"{base_url}/company-e/careers", category="Smoke Test"),
        CompanyEntry(name="Company F (embedded ATS, sniff-only)", ats="tier2", careers_url=f"{base_url}/company-f/careers", category="Smoke Test"),
    ]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    server, base_url = start_fixture_server()
    logger.info("Fixture server running at %s", base_url)

    report = RunReport(started_at=datetime.now(timezone.utc))
    detail_capture = DetailCapture()
    logger.addHandler(detail_capture)

    digest_text = None
    try:
        rate_limiter = RateLimiter(seconds_per_domain=0.1)
        client = HttpClient(rate_limiter, timeout=10)
        companies = build_fixture_companies(base_url)
        target_company_names = {c.name.strip().lower() for c in companies}

        with Renderer(rate_limiter) as renderer:
            logger.info("Playwright render fallback available: %s", renderer.available)
            postings = crawl_companies(companies, client, renderer, report, detail_capture)

        report.raw_postings = len(postings)
        logger.info("Crawled %d posting(s) total", len(postings))
        for p in postings:
            logger.info("  - %s @ %s (%s, date_confidence=%s)", p.title, p.company, p.source, p.date_confidence)

        # Full pipeline from here, same as main.run() -- filters, dedup,
        # live-link verification, digest -- just with a throwaway dedup
        # store and no real email send.
        results = apply_pipeline(
            postings,
            target_titles=SMOKE_TEST_TITLES,
            fuzzy_threshold=85,
            target_company_names=target_company_names,
            excluded_names=set(),
            lookback_days=7,
            accepted_onsite_locations=[],
        )
        included = [r.posting for r in results if r.decision == Decision.INCLUDE]
        report.after_filters = len(included)
        report.review_flagged = sum(1 for r in results if r.decision == Decision.REVIEW)
        logger.info("%d posting(s) passed the filter pipeline", len(included))

        with tempfile.TemporaryDirectory() as tmp_dir:
            with DedupStore(Path(tmp_dir) / "smoke_test_seen.sqlite3") as store:
                new_postings = store.filter_new(included)
                report.new_after_dedup = len(new_postings)

                verified = verify_postings(new_postings, client)
                report.verified_live = len(verified)
                logger.info("%d posting(s) verified live", len(verified))

                digest_text = build_text_digest(verified, date.today())

    finally:
        logger.removeHandler(detail_capture)
        report.finished_at = datetime.now(timezone.utc)
        server.shutdown()

    report_dir = Path("logs")
    json_path, md_path = report.write(report_dir)
    print("\n" + "=" * 72)
    print(report.to_markdown())
    print("=" * 72)
    if digest_text is not None:
        print("\n--- Sample digest (what an email would contain) ---\n")
        print(digest_text)
    print(f"\nFull report written to {json_path} and {md_path}")


if __name__ == "__main__":
    main()
