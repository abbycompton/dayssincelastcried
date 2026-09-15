"""Postmark delivery via their HTTP API. Requires POSTMARK_SERVER_TOKEN in .env."""

from __future__ import annotations

import os

import requests

from ..config import EmailSettings
from .base import EmailSender

POSTMARK_API_URL = "https://api.postmarkapp.com/email"


class PostmarkSender(EmailSender):
    def __init__(self, settings: EmailSettings):
        self.settings = settings
        self.token = os.environ.get("POSTMARK_SERVER_TOKEN")
        if not self.token:
            raise RuntimeError("POSTMARK_SERVER_TOKEN not set (see .env.example)")

    def send(self, subject: str, text_body: str, html_body: str) -> None:
        resp = requests.post(
            POSTMARK_API_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": self.token,
            },
            json={
                "From": self.settings.from_address,
                "To": self.settings.to_address,
                "Subject": subject,
                "TextBody": text_body,
                "HtmlBody": html_body,
                "MessageStream": "outbound",
            },
            timeout=15,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"Postmark send failed: HTTP {resp.status_code} {resp.text}")
