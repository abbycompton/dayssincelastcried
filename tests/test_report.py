import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from job_search_agent.report import DetailCapture, RunReport


def test_add_company_result_classifies_ok_vs_empty():
    report = RunReport(started_at=datetime.now(timezone.utc))
    report.add_company_result("Acme", "greenhouse", 3)
    report.add_company_result("Ghost Co", "tier2", 0, detail="zero postings found")

    assert report.company_results[0].status == "ok"
    assert report.company_results[1].status == "empty"
    assert report.company_results[1].detail == "zero postings found"


def test_add_company_exception():
    report = RunReport(started_at=datetime.now(timezone.utc))
    report.add_company_exception("Acme", "tier2", "boom")
    assert report.company_results[0].status == "exception"


def test_markdown_includes_problem_table_and_omits_ok_only():
    report = RunReport(started_at=datetime(2026, 9, 21, 7, 0, tzinfo=timezone.utc))
    report.add_company_result("Good Co", "greenhouse", 2)
    report.add_company_result("Bad Co", "tier2", 0, detail="HTTP 404")
    report.raw_postings = 5
    report.after_filters = 2
    report.new_after_dedup = 2
    report.verified_live = 2
    report.email_sent = True

    md = report.to_markdown()
    assert "Bad Co" in md
    assert "HTTP 404" in md
    assert "Companies needing attention" in md
    assert "Email sent: yes" in md


def test_markdown_all_ok_has_no_problem_table():
    report = RunReport(started_at=datetime.now(timezone.utc))
    report.add_company_result("Good Co", "greenhouse", 2)
    md = report.to_markdown()
    assert "Companies needing attention" not in md


def test_json_roundtrip_has_expected_keys():
    report = RunReport(started_at=datetime.now(timezone.utc))
    report.add_company_result("Acme", "greenhouse", 1)
    data = report.to_dict()
    assert data["company_counts"] == {"ok": 1}
    assert "started_at" in data


def test_write_creates_dated_and_latest_files():
    report = RunReport(started_at=datetime(2026, 9, 21, tzinfo=timezone.utc))
    report.add_company_result("Acme", "greenhouse", 1)
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        json_path, md_path = report.write(directory)
        assert json_path.exists()
        assert md_path.exists()
        assert (directory / "latest_run_report.json").exists()
        assert (directory / "latest_run_report.md").exists()
        assert "run_report_2026-09-21" in json_path.name


def test_detail_capture_picks_up_company_name_from_first_arg():
    logger = logging.getLogger("job_search_agent")
    capture = DetailCapture()
    logger.addHandler(capture)
    try:
        logger.error("[tier2] %s: HTTP %s for %s", "Acme", 404, "https://acme.example/careers")
        logger.info("[tier2] %s: this should be ignored (below WARNING)", "Other Co")
    finally:
        logger.removeHandler(capture)

    assert capture.detail_for("Acme") == "[tier2] Acme: HTTP 404 for https://acme.example/careers"
    assert capture.detail_for("Other Co") == ""


def test_detail_capture_ignores_records_with_no_args():
    logger = logging.getLogger("job_search_agent")
    capture = DetailCapture()
    logger.addHandler(capture)
    try:
        logger.warning("a message with no args")
    finally:
        logger.removeHandler(capture)
    assert capture.by_name == {}
