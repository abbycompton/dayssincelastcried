"""Common interface every email provider implements."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmailSender(ABC):
    @abstractmethod
    def send(self, subject: str, text_body: str, html_body: str) -> None:
        """Sends the digest email. Raises on failure -- the orchestrator
        decides what to do (e.g. don't mark postings as seen if this fails)."""
        raise NotImplementedError
