"""Structured run report: per-company crawl health plus the digest funnel
(raw postings -> filtered -> new -> verified), written as both JSON and
Markdown after every run.

This is separate from the job digest email -- the digest is "here are your
new postings," this is "here's how the crawl itself is doing," meant to be
checked daily (or whenever something looks off) to see what's failing
before it quietly erodes coverage.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("job_search_agent")


@dataclass
class CompanyResult:
    name: str
    source: str  # ats name ("greenhouse", "tier2", ...) or aggregator name
    status: str  # "ok" | "empty" | "exception"
    posting_count: int = 0
    detail: str = ""  # human-readable reason, pulled from the log line if any


@dataclass
class RunReport:
    started_at: datetime
    finished_at: datetime | None = None
    company_results: list[CompanyResult] = field(default_factory=list)
    aggregator_results: list[CompanyResult] = field(default_factory=list)
    raw_postings: int = 0
    after_filters: int = 0
    review_flagged: int = 0
    new_after_dedup: int = 0
    verified_live: int = 0
    email_sent: bool = False
    email_error: str | None = None

    def add_company_result(self, name: str, source: str, postings_count: int, detail: str = "") -> None:
        status = "ok" if postings_count > 0 else "empty"
        self.company_results.append(CompanyResult(name, source, status, postings_count, detail))

    def add_company_exception(self, name: str, source: str, detail: str) -> None:
        self.company_results.append(CompanyResult(name, source, "exception", 0, detail))

    def add_aggregator_result(self, name: str, postings_count: int, detail: str = "") -> None:
        status = "ok" if postings_count > 0 else "empty"
        self.aggregator_results.append(CompanyResult(name, "aggregator", status, postings_count, detail))

    def add_aggregator_exception(self, name: str, detail: str) -> None:
        self.aggregator_results.append(CompanyResult(name, "aggregator", "exception", 0, detail))

    def _counts(self, results: list[CompanyResult]) -> dict:
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    def to_dict(self) -> dict:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        data["company_counts"] = self._counts(self.company_results)
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_markdown(self) -> str:
        counts = self._counts(self.company_results)
        total = len(self.company_results)
        lines = [
            f"# Job search crawl report — {self.started_at.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## Crawl health",
            f"- Companies attempted: {total}",
            f"- OK (found at least one posting): {counts.get('ok', 0)}",
            f"- Empty (zero postings found — see table below for why): {counts.get('empty', 0)}",
            f"- Exceptions (unhandled error): {counts.get('exception', 0)}",
            "",
            "## Digest pipeline",
            f"- Raw postings crawled (all sources): {self.raw_postings}",
            f"- Passed title/company/freshness/location filters: {self.after_filters}",
            f"- Flagged for manual location review: {self.review_flagged}",
            f"- New (not previously surfaced): {self.new_after_dedup}",
            f"- Verified live immediately before sending: {self.verified_live}",
            f"- Email sent: {'yes' if self.email_sent else 'NO' + (f' — {self.email_error}' if self.email_error else '')}",
            "",
        ]

        problems = [r for r in self.company_results if r.status != "ok"]
        if problems:
            lines.append("## Companies needing attention")
            lines.append("")
            lines.append("| Company | Source | Status | Detail |")
            lines.append("|---|---|---|---|")
            for r in sorted(problems, key=lambda r: (r.status, r.name)):
                detail = (r.detail or "").replace("|", "\\|")
                lines.append(f"| {r.name} | {r.source} | {r.status} | {detail} |")
            lines.append("")

        agg_problems = [r for r in self.aggregator_results if r.status != "ok"]
        if agg_problems:
            lines.append("## Aggregators needing attention")
            lines.append("")
            lines.append("| Source | Status | Detail |")
            lines.append("|---|---|---|")
            for r in agg_problems:
                detail = (r.detail or "").replace("|", "\\|")
                lines.append(f"| {r.name} | {r.status} | {detail} |")
            lines.append("")

        return "\n".join(lines)

    def write(self, directory: Path) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        date_str = self.started_at.strftime("%Y-%m-%d")
        json_path = directory / f"run_report_{date_str}.json"
        md_path = directory / f"run_report_{date_str}.md"
        json_path.write_text(self.to_json())
        md_path.write_text(self.to_markdown())
        (directory / "latest_run_report.json").write_text(self.to_json())
        (directory / "latest_run_report.md").write_text(self.to_markdown())
        return json_path, md_path


class DetailCapture(logging.Handler):
    """Captures the most recent WARNING/ERROR log message per company during
    a run, so the report can show *why* a company came back empty without
    duplicating any of the fetchers' own error-classification logic.

    Relies on the existing convention (true of every fetcher in ats/,
    tier2_crawler.py, and aggregators/) that a per-company log call's first
    %-format argument is the company or source name -- e.g.
    logger.error("[greenhouse] %s: HTTP %s for %s", company_name, ...).
    """

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.by_name: dict[str, str] = {}

    def emit(self, record: logging.LogRecord) -> None:
        if not record.args:
            return
        first_arg = record.args[0] if isinstance(record.args, tuple) else record.args
        if not isinstance(first_arg, str):
            return
        self.by_name[first_arg] = record.getMessage()

    def detail_for(self, name: str) -> str:
        return self.by_name.get(name, "")
