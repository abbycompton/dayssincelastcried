"""SendGrid delivery. Requires SENDGRID_API_KEY in .env."""

from __future__ import annotations

import os

from ..config import EmailSettings
from .base import EmailSender


class SendGridSender(EmailSender):
    def __init__(self, settings: EmailSettings):
        self.settings = settings
        self.api_key = os.environ.get("SENDGRID_API_KEY")
        if not self.api_key:
            raise RuntimeError("SENDGRID_API_KEY not set (see .env.example)")

    def send(self, subject: str, text_body: str, html_body: str) -> None:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=self.settings.from_address,
            to_emails=self.settings.to_address,
            subject=subject,
            plain_text_content=text_body,
            html_content=html_body,
        )
        client = SendGridAPIClient(self.api_key)
        response = client.send(message)
        if response.status_code >= 300:
            raise RuntimeError(f"SendGrid send failed: HTTP {response.status_code} {response.body!r}")
