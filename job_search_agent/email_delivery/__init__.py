"""Pluggable email delivery. Pick one provider via config/settings.yaml's
`email.provider` and set its credentials in .env (see .env.example)."""

from __future__ import annotations

from ..config import EmailSettings
from .base import EmailSender


def get_sender(settings: EmailSettings) -> EmailSender:
    if settings.provider == "sendgrid":
        from .sendgrid_sender import SendGridSender

        return SendGridSender(settings)
    if settings.provider == "postmark":
        from .postmark_sender import PostmarkSender

        return PostmarkSender(settings)
    if settings.provider == "gmail":
        from .gmail_sender import GmailSender

        return GmailSender(settings)
    raise ValueError(f"Unknown email provider: {settings.provider!r} (expected sendgrid, postmark, or gmail)")
