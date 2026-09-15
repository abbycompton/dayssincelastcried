"""Formats the daily digest: grouped by company, one row per posting.
Company | Title | Location | Posted Date | Verified-Live (timestamp) | Link.

If there's nothing new, sends a short "no new matches today" note instead of
nothing, so silence never gets confused with the tool being broken.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .verify import VerifiedPosting

NO_MATCHES_TEXT = "No new matches today."


def build_text_digest(verified: list[VerifiedPosting], run_date: date) -> str:
    if not verified:
        return f"Job search digest for {run_date.isoformat()}\n\n{NO_MATCHES_TEXT}\n"

    by_company: dict[str, list[VerifiedPosting]] = defaultdict(list)
    for item in verified:
        by_company[item.posting.company].append(item)

    lines = [f"Job search digest for {run_date.isoformat()}", ""]
    for company in sorted(by_company):
        lines.append(company)
        lines.append("-" * len(company))
        for item in sorted(by_company[company], key=lambda v: v.posting.title):
            p = item.posting
            posted = p.posted_at.strftime("%Y-%m-%d") if p.posted_at else "unknown"
            verified_ts = item.verified_at.strftime("%Y-%m-%d %H:%M UTC")
            location = p.location or "unknown"
            date_flag = "" if p.date_confidence == "high" else " [low-confidence date]"
            lines.append(f"  * {p.title} | {location} | Posted {posted}{date_flag} | Verified {verified_ts}")
            lines.append(f"    {p.url}")
        lines.append("")

    lines.append(f"Total new postings: {len(verified)}")
    return "\n".join(lines)


def build_html_digest(verified: list[VerifiedPosting], run_date: date) -> str:
    if not verified:
        return f"<h2>Job search digest for {run_date.isoformat()}</h2><p>{NO_MATCHES_TEXT}</p>"

    by_company: dict[str, list[VerifiedPosting]] = defaultdict(list)
    for item in verified:
        by_company[item.posting.company].append(item)

    parts = [f"<h2>Job search digest for {run_date.isoformat()}</h2>"]
    for company in sorted(by_company):
        parts.append(f"<h3>{_escape(company)}</h3>")
        parts.append(
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<tr><th>Title</th><th>Location</th><th>Posted</th><th>Verified</th><th>Link</th></tr>"
        )
        for item in sorted(by_company[company], key=lambda v: v.posting.title):
            p = item.posting
            posted = p.posted_at.strftime("%Y-%m-%d") if p.posted_at else "unknown"
            if p.date_confidence != "high":
                posted += " (low-confidence)"
            verified_ts = item.verified_at.strftime("%Y-%m-%d %H:%M UTC")
            location = p.location or "unknown"
            parts.append(
                "<tr>"
                f"<td>{_escape(p.title)}</td>"
                f"<td>{_escape(location)}</td>"
                f"<td>{_escape(posted)}</td>"
                f"<td>{_escape(verified_ts)}</td>"
                f"<td><a href='{_escape(p.url)}'>Apply</a></td>"
                "</tr>"
            )
        parts.append("</table>")

    parts.append(f"<p>Total new postings: {len(verified)}</p>")
    return "\n".join(parts)


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
