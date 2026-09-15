import tempfile
from pathlib import Path

import yaml

from job_search_agent.bulk_upgrade import apply_upgrades


def test_apply_upgrades_moves_entry_and_preserves_others():
    initial = {
        "greenhouse": [],
        "lever": [],
        "ashby": [],
        "smartrecruiters": [],
        "workday": [],
        "tier2": [
            {"name": "Acme", "ats": "tier2", "careers_url": "https://acme.example/careers", "category": "Fintech"},
            {"name": "Other Co", "ats": "tier2", "careers_url": "https://other.example/jobs", "category": "Fintech"},
        ],
        "excluded": ["Meta"],
    }

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "companies.yaml"
        path.write_text(yaml.dump(initial))

        apply_upgrades(path, [("Acme", "greenhouse", "acme", "https://acme.example/careers", "Fintech")])

        result = yaml.safe_load(path.read_text())

    assert [e["name"] for e in result["tier2"]] == ["Other Co"]
    assert result["greenhouse"] == [
        {"name": "Acme", "ats": "greenhouse", "slug": "acme", "category": "Fintech"}
    ]
    assert result["excluded"] == ["Meta"]


def test_apply_upgrades_workday_stores_full_cxs_url_as_slug():
    initial = {"tier2": [{"name": "BigCo", "ats": "tier2", "careers_url": "https://bigco.com/careers", "category": None}]}

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "companies.yaml"
        path.write_text(yaml.dump(initial))

        cxs_url = "https://bigco.wd5.myworkdayjobs.com/wday/cxs/bigco/careers/jobs"
        apply_upgrades(path, [("BigCo", "workday", cxs_url, "https://bigco.com/careers", None)])

        result = yaml.safe_load(path.read_text())

    assert result["workday"][0]["slug"] == cxs_url
    assert result["tier2"] == []
