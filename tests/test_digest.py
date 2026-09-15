from datetime import date, datetime, timezone

from job_search_agent.digest import NO_MATCHES_TEXT, build_html_digest, build_text_digest
from job_search_agent.models import Posting
from job_search_agent.verify import VerifiedPosting


def test_empty_digest_says_no_new_matches():
    text = build_text_digest([], date(2026, 9, 15))
    assert NO_MATCHES_TEXT in text
    html = build_html_digest([], date(2026, 9, 15))
    assert NO_MATCHES_TEXT in html


def test_digest_groups_by_company():
    postings = [
        VerifiedPosting(
            posting=Posting(
                company="Figma",
                title="Senior Program Manager",
                url="https://example.com/1",
                source="greenhouse",
                location="Remote",
                posted_at=datetime.now(timezone.utc),
            ),
            verified_at=datetime.now(timezone.utc),
        ),
        VerifiedPosting(
            posting=Posting(
                company="Notion",
                title="Chief of Staff",
                url="https://example.com/2",
                source="lever",
                location="Portland, OR",
                posted_at=datetime.now(timezone.utc),
            ),
            verified_at=datetime.now(timezone.utc),
        ),
    ]
    text = build_text_digest(postings, date(2026, 9, 15))
    assert "Figma" in text
    assert "Notion" in text
    assert "Total new postings: 2" in text
