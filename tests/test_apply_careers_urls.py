import tempfile
from pathlib import Path

import yaml

from job_search_agent.apply_careers_urls import apply_updates, parse_lines


def test_parse_lines_ignores_comments_and_blanks():
    text = """
    # a comment
    Acme | https://acme.example/careers

    Blank Url |
    NoDelimiter here
    Other Co |   https://other.example/jobs
    """
    result = parse_lines(text)
    assert result == {
        "Acme": "https://acme.example/careers",
        "Other Co": "https://other.example/jobs",
    }


def test_apply_updates_moves_needs_url_entry_into_tier2():
    initial = {
        "tier2": [],
        "needs_url": [{"name": "Acme", "category": "Fintech", "note": "unconfirmed"}],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "companies.yaml"
        path.write_text(yaml.dump(initial))

        applied, not_found = apply_updates(path, {"Acme": "https://acme.example/careers"})

        result = yaml.safe_load(path.read_text())

    assert applied == ["Acme"]
    assert not_found == []
    assert result["needs_url"] == []
    assert result["tier2"] == [
        {"name": "Acme", "ats": "tier2", "careers_url": "https://acme.example/careers", "category": "Fintech"}
    ]


def test_apply_updates_overwrites_existing_tier2_url_and_clears_verified_flag():
    initial = {
        "tier2": [
            {"name": "Acme", "ats": "tier2", "careers_url": "https://old.example/careers",
             "category": "Fintech", "verified": False}
        ],
        "needs_url": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "companies.yaml"
        path.write_text(yaml.dump(initial))

        applied, not_found = apply_updates(path, {"Acme": "https://new.example/careers"})

        result = yaml.safe_load(path.read_text())

    assert applied == ["Acme"]
    assert result["tier2"][0]["careers_url"] == "https://new.example/careers"
    assert "verified" not in result["tier2"][0]


def test_apply_updates_reports_unmatched_names():
    initial = {"tier2": [], "needs_url": []}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "companies.yaml"
        path.write_text(yaml.dump(initial))

        applied, not_found = apply_updates(path, {"Ghost Co": "https://ghost.example/careers"})

    assert applied == []
    assert not_found == ["Ghost Co"]
