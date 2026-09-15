"""Core data model shared by every source, filter, and output stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Posting:
    """A single job posting, normalized to a common shape regardless of source."""

    company: str
    title: str
    url: str
    source: str  # e.g. "greenhouse", "lever", "ashby", "smartrecruiters", "tier2", "remoteok", "wwr", "builtin", "indeed"
    location: Optional[str] = None
    posted_at: Optional[datetime] = None  # None means "no verified date"
    date_confidence: str = "high"  # "high" | "low" (Tier 2 / relative-date sources)
    posting_id: Optional[str] = None  # stable ID from the source system, if any
    remote: Optional[bool] = None  # True/False when explicitly known, None if ambiguous
    raw: dict = field(default_factory=dict)  # original source payload, for debugging

    def dedup_key(self) -> str:
        """Stable key for the dedup store: prefer a real posting ID, fall back to
        normalized company+title (per spec: 'fuzzy-matched title+company if no stable ID')."""
        if self.posting_id:
            return f"{self.source}:{self.company.strip().lower()}:{self.posting_id}"
        normalized_title = " ".join(self.title.strip().lower().split())
        return f"{self.source}:{self.company.strip().lower()}:{normalized_title}"

    def verified_key(self) -> str:
        # timestamp is filled in at verification time; not part of identity
        return self.dedup_key()
