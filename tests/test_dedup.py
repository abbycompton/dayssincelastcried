import tempfile
from pathlib import Path

from job_search_agent.dedup import DedupStore
from job_search_agent.models import Posting


def _posting(**overrides) -> Posting:
    base = dict(
        company="Figma",
        title="Senior Program Manager",
        url="https://example.com/job/1",
        source="greenhouse",
        posting_id="1",
    )
    base.update(overrides)
    return Posting(**base)


def test_new_postings_pass_through_until_recorded():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "seen.sqlite3"
        with DedupStore(db_path) as store:
            posting = _posting()
            assert store.filter_new([posting]) == [posting]
            store.record_seen([posting])
            assert store.filter_new([posting]) == []


def test_dedup_persists_across_instances():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "seen.sqlite3"
        posting = _posting()
        with DedupStore(db_path) as store:
            store.record_seen([posting])

        with DedupStore(db_path) as store2:
            assert store2.filter_new([posting]) == []
            assert store2.filter_new([_posting(posting_id="2")]) != []


def test_dedup_key_falls_back_to_title_when_no_id():
    posting_a = _posting(posting_id=None, title="Senior Program Manager")
    posting_b = _posting(posting_id=None, title="senior program manager")  # different case
    assert posting_a.dedup_key() == posting_b.dedup_key()


def test_dedup_key_differs_by_posting_id():
    a = _posting(posting_id="1")
    b = _posting(posting_id="2")
    assert a.dedup_key() != b.dedup_key()
