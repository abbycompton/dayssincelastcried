"""Loads YAML config + .env secrets into typed settings objects."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so we don't require python-dotenv as a hard dependency."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(REPO_ROOT / ".env")


@dataclass
class CompanyEntry:
    name: str
    ats: str  # greenhouse | lever | ashby | smartrecruiters | workday | tier2
    slug: Optional[str] = None
    careers_url: Optional[str] = None
    category: Optional[str] = None


@dataclass
class EmailSettings:
    provider: str
    from_address: str
    to_address: str
    subject_prefix: str = "[Job Search Digest]"


@dataclass
class Settings:
    lookback_days: int
    accepted_onsite_locations: list
    rate_limit_seconds_per_domain: float
    request_timeout_seconds: int
    dedup_store_path: Path
    error_log_path: Path
    aggregators: dict
    email: EmailSettings


def load_titles(path: Path = CONFIG_DIR / "titles.yaml") -> tuple[list, int]:
    data = yaml.safe_load(path.read_text()) or {}
    titles = data.get("target_titles", [])
    threshold = int(data.get("fuzzy_threshold", 85))
    return titles, threshold


def load_companies(path: Path = CONFIG_DIR / "companies.yaml") -> tuple[list, set]:
    """Returns (companies, excluded_names_lowercased)."""
    data = yaml.safe_load(path.read_text()) or {}
    companies: list = []
    for ats in ("greenhouse", "lever", "ashby", "smartrecruiters", "workday", "tier2"):
        for entry in data.get(ats, []) or []:
            companies.append(
                CompanyEntry(
                    name=entry["name"],
                    ats=ats,
                    slug=entry.get("slug"),
                    careers_url=entry.get("careers_url"),
                    category=entry.get("category"),
                )
            )
    excluded = {name.strip().lower() for name in data.get("excluded", []) or []}
    return companies, excluded


def load_settings(path: Path = CONFIG_DIR / "settings.yaml") -> Settings:
    data = yaml.safe_load(path.read_text()) or {}
    email_data = data.get("email", {})
    email = EmailSettings(
        provider=os.environ.get("EMAIL_PROVIDER", email_data.get("provider", "sendgrid")),
        from_address=os.environ.get("EMAIL_FROM", email_data.get("from_address", "")),
        to_address=os.environ.get("EMAIL_TO", email_data.get("to_address", "")),
        subject_prefix=email_data.get("subject_prefix", "[Job Search Digest]"),
    )
    dedup_path = data.get("dedup_store_path", "data/seen_postings.sqlite3")
    error_log_path = data.get("error_log_path", "logs/errors.log")
    return Settings(
        lookback_days=int(data.get("lookback_days", 7)),
        accepted_onsite_locations=data.get("accepted_onsite_locations", []),
        rate_limit_seconds_per_domain=float(data.get("rate_limit_seconds_per_domain", 1.0)),
        request_timeout_seconds=int(data.get("request_timeout_seconds", 15)),
        dedup_store_path=(REPO_ROOT / dedup_path) if not os.path.isabs(dedup_path) else Path(dedup_path),
        error_log_path=(REPO_ROOT / error_log_path) if not os.path.isabs(error_log_path) else Path(error_log_path),
        aggregators=data.get("aggregators", {}),
        email=email,
    )
