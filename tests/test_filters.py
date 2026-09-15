from datetime import datetime, timedelta, timezone

import pytest

from job_search_agent.filters import (
    Decision,
    apply_pipeline,
    company_matches,
    freshness_ok,
    is_excluded,
    location_decision,
    title_matches,
)
from job_search_agent.models import Posting

TARGET_TITLES = ["Senior Program Manager", "Chief of Staff", "Strategic Program Management"]


def test_title_matches_exact_substring():
    assert title_matches("Senior Program Manager, Platform", TARGET_TITLES)


def test_title_matches_fuzzy_variant():
    assert title_matches("Sr. Program Manager - Platform Team", TARGET_TITLES, fuzzy_threshold=80)


def test_title_matches_phrase_anywhere():
    assert title_matches("Head of Strategic Program Management", TARGET_TITLES)


def test_title_does_not_match_unrelated():
    assert not title_matches("Backend Software Engineer", TARGET_TITLES)


def test_company_matches_case_insensitive():
    assert company_matches("Figma", {"figma", "notion"})
    assert not company_matches("Adobe", {"figma", "notion"})


def test_is_excluded_matches_not_interested_list():
    assert is_excluded("Meta", {"meta"})
    assert is_excluded("META", {"meta"})
    assert not is_excluded("Figma", {"meta"})


def test_freshness_no_date_excludes():
    assert freshness_ok(None, 7) is False


def test_freshness_within_window():
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    assert freshness_ok(recent, 7) is True


def test_freshness_outside_window():
    old = datetime.now(timezone.utc) - timedelta(days=30)
    assert freshness_ok(old, 7) is False


def _posting(**overrides) -> Posting:
    base = dict(
        company="Figma",
        title="Senior Program Manager",
        url="https://example.com/job/1",
        source="greenhouse",
        location="Remote",
        posted_at=datetime.now(timezone.utc),
        posting_id="1",
    )
    base.update(overrides)
    return Posting(**base)


def test_location_decision_explicit_remote():
    posting = _posting(remote=True, location=None)
    decision, _ = location_decision(posting, [])
    assert decision == Decision.INCLUDE


def test_location_decision_missing_location_is_review():
    posting = _posting(remote=None, location=None)
    decision, _ = location_decision(posting, [])
    assert decision == Decision.REVIEW


def test_location_decision_accepted_onsite_metro():
    posting = _posting(remote=False, location="Portland, OR")
    decision, _ = location_decision(posting, ["Portland, OR"])
    assert decision == Decision.INCLUDE


def test_location_decision_onsite_elsewhere_excluded():
    posting = _posting(remote=False, location="New York, NY")
    decision, _ = location_decision(posting, ["Portland, OR"])
    assert decision == Decision.EXCLUDE


def test_apply_pipeline_full_flow():
    postings = [
        _posting(title="Senior Program Manager", company="Figma", remote=True),  # include
        _posting(title="Software Engineer", company="Figma"),  # title fails
        _posting(title="Senior Program Manager", company="Not A Target Co"),  # company fails
        _posting(title="Senior Program Manager", company="Figma", posted_at=None),  # no date
        _posting(title="Senior Program Manager", company="Meta", remote=True),  # excluded co
    ]
    results = apply_pipeline(
        postings,
        target_titles=TARGET_TITLES,
        fuzzy_threshold=85,
        target_company_names={"figma"},
        excluded_names={"meta"},
        lookback_days=7,
        accepted_onsite_locations=[],
    )
    decisions = [r.decision for r in results]
    assert decisions == [
        Decision.INCLUDE,
        Decision.EXCLUDE,
        Decision.EXCLUDE,
        Decision.EXCLUDE,
        Decision.EXCLUDE,
    ]
