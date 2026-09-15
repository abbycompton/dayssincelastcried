"""Detects a known ATS embedded in a careers page's HTML -- an iframe,
redirect target, or a plain link pointing at a Greenhouse/Lever/Ashby/
SmartRecruiters/Workday board.

Many companies' marketing "careers" page is just a thin wrapper embedding
their real job board. Spotting that board's URL directly is far more
reliable than guessing a slug from the company name (discover_ats.py's
approach), and it's what actually fixes a Tier 2 page that renders zero
postings because the real listings live on a different host entirely.
"""

from __future__ import annotations

import re

_SLUG_PATTERNS = {
    "greenhouse": re.compile(r"boards\.greenhouse\.io/(?:embed/job_board\?for=)?([a-zA-Z0-9_-]+)"),
    "lever": re.compile(r"jobs\.lever\.co/([a-zA-Z0-9_-]+)"),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)"),
    "smartrecruiters": re.compile(r"careers\.smartrecruiters\.com/([a-zA-Z0-9_-]+)"),
}

# Workday external job-site URLs look like:
#   https://{tenant}.{dc}.myworkdayjobs.com/{locale/}{site}
# and the CXS search API is a fixed transform of that:
#   https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
_WORKDAY_HOST_RE = re.compile(r"https://([a-zA-Z0-9-]+)\.([a-zA-Z0-9]+)\.myworkdayjobs\.com(/[a-zA-Z0-9_/-]*)?")
_LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")


def sniff(html: str) -> tuple[str, str] | None:
    """Returns (ats, slug_or_url) for the first known ATS pattern found, or
    None. For workday, the returned "slug" is actually the full CXS jobs
    URL, ready to pass straight to ats/workday.py's fetch()."""
    for ats, pattern in _SLUG_PATTERNS.items():
        match = pattern.search(html)
        if match:
            return ats, match.group(1)

    workday_match = _WORKDAY_HOST_RE.search(html)
    if workday_match:
        cxs_url = _build_workday_cxs_url(workday_match)
        if cxs_url:
            return "workday", cxs_url

    return None


def _build_workday_cxs_url(match: re.Match) -> str | None:
    tenant, dc, path = match.group(1), match.group(2), match.group(3) or ""
    segments = [s for s in path.split("/") if s and not _LOCALE_SEGMENT_RE.match(s)]
    if not segments:
        return None
    site = segments[0]
    return f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
