"""Filter pipeline, applied in the order the spec specifies:
title match -> company match -> freshness -> location/remote.

Dedup (step 5) lives in dedup.py and live-link verification (step 6) in
verify.py, since both need state/IO the pure filtering steps here don't.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from rapidfuzz import fuzz

from .models import Posting


class Decision(Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    REVIEW = "review"  # ambiguous location: needs a human look, not a guess


@dataclass
class FilterResult:
    posting: Posting
    decision: Decision
    reason: str


def title_matches(title: str, target_titles: list[str], fuzzy_threshold: int = 85) -> bool:
    lowered = title.lower()
    for target in target_titles:
        target_lower = target.lower()
        if target_lower in lowered:
            return True
        if fuzz.partial_ratio(target_lower, lowered) >= fuzzy_threshold:
            return True
    return False


def company_matches(company: str, target_company_names: set[str]) -> bool:
    return company.strip().lower() in target_company_names


def is_excluded(company: str, excluded_names: set[str]) -> bool:
    company_lower = company.strip().lower()
    return any(excluded in company_lower or company_lower in excluded for excluded in excluded_names)


def freshness_ok(posted_at: datetime | None, lookback_days: int) -> bool:
    # "No date = excluded, not included-with-caveat" -- no exceptions, even
    # for high-confidence sources.
    if posted_at is None:
        return False
    now = datetime.now(timezone.utc) if posted_at.tzinfo else datetime.now()
    cutoff = now - timedelta(days=lookback_days)
    return posted_at >= cutoff


def location_decision(
    posting: Posting, accepted_onsite_locations: list[str]
) -> tuple[Decision, str]:
    if posting.remote is True:
        return Decision.INCLUDE, "explicitly remote"

    location = (posting.location or "").strip()
    if not location:
        return Decision.REVIEW, "location field missing"

    location_lower = location.lower()
    if "remote" in location_lower:
        return Decision.INCLUDE, "location text indicates remote"

    for accepted in accepted_onsite_locations:
        if accepted.lower() in location_lower:
            return Decision.INCLUDE, f"onsite match: {accepted}"

    if posting.remote is False and not any(
        accepted.lower() in location_lower for accepted in accepted_onsite_locations
    ):
        return Decision.EXCLUDE, f"onsite-only in non-target location: {location}"

    # Ambiguous: we have a location string but can't confidently classify it
    # as remote or as an accepted onsite metro. Per spec: flag, don't guess.
    return Decision.REVIEW, f"ambiguous location: {location}"


def apply_pipeline(
    postings: list[Posting],
    target_titles: list[str],
    fuzzy_threshold: int,
    target_company_names: set[str],
    excluded_names: set[str],
    lookback_days: int,
    accepted_onsite_locations: list[str],
) -> list[FilterResult]:
    results: list[FilterResult] = []

    for posting in postings:
        if is_excluded(posting.company, excluded_names):
            results.append(FilterResult(posting, Decision.EXCLUDE, "company on Not Interested list"))
            continue

        if not title_matches(posting.title, target_titles, fuzzy_threshold):
            results.append(FilterResult(posting, Decision.EXCLUDE, "title does not match target list"))
            continue

        if not company_matches(posting.company, target_company_names):
            results.append(FilterResult(posting, Decision.EXCLUDE, "company not in target seed list"))
            continue

        if not freshness_ok(posting.posted_at, lookback_days):
            reason = "no verified posted date" if posting.posted_at is None else "outside lookback window"
            results.append(FilterResult(posting, Decision.EXCLUDE, reason))
            continue

        decision, reason = location_decision(posting, accepted_onsite_locations)
        results.append(FilterResult(posting, decision, reason))

    return results
