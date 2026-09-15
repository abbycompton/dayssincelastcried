"""Persistent dedup store (SQLite) of previously-surfaced posting keys.

Key is Posting.dedup_key(): source+company+posting_id when a stable ID
exists, else source+company+normalized-title as a fuzzy-ish fallback (per
spec: "fuzzy-matched title+company if no stable ID").
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Posting

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_postings (
    dedup_key TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
);
"""


class DedupStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def filter_new(self, postings: list[Posting]) -> list[Posting]:
        """Returns only postings not already in the store. Does NOT record
        them -- call record_seen() after the digest is successfully sent, so
        a failed send doesn't silently swallow postings."""
        new_postings = []
        for posting in postings:
            if not self._is_seen(posting.dedup_key()):
                new_postings.append(posting)
        return new_postings

    def record_seen(self, postings: list[Posting]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.executemany(
            "INSERT OR IGNORE INTO seen_postings (dedup_key, company, title, first_seen_at) VALUES (?, ?, ?, ?)",
            [(p.dedup_key(), p.company, p.title, now) for p in postings],
        )
        self._conn.commit()

    def _is_seen(self, dedup_key: str) -> bool:
        cursor = self._conn.execute(
            "SELECT 1 FROM seen_postings WHERE dedup_key = ?", (dedup_key,)
        )
        return cursor.fetchone() is not None

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DedupStore":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
