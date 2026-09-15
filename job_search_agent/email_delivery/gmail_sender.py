"""Gmail API delivery, using OAuth (send-only scope).

One-time setup: download an OAuth client ID (Desktop app) from Google Cloud
Console, save it as `config/gmail_credentials.json`. The first run opens a
browser to authorize; the resulting token is cached at `config/gmail_token.json`
so later runs (e.g. from cron) don't need interaction.
"""

from __future__ import annotations

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from ..config import CONFIG_DIR, EmailSettings
from .base import EmailSender

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CREDENTIALS_PATH = CONFIG_DIR / "gmail_credentials.json"
TOKEN_PATH = CONFIG_DIR / "gmail_token.json"


class GmailSender(EmailSender):
    def __init__(self, settings: EmailSettings):
        self.settings = settings

    def _get_credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDENTIALS_PATH.exists():
                    raise RuntimeError(
                        f"Gmail OAuth client not found at {CREDENTIALS_PATH}. "
                        "Download one from Google Cloud Console (Desktop app type) "
                        "and save it there."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
                creds = flow.run_local_server(port=0)
            TOKEN_PATH.write_text(creds.to_json())
        return creds

    def send(self, subject: str, text_body: str, html_body: str) -> None:
        from googleapiclient.discovery import build

        creds = self._get_credentials()
        service = build("gmail", "v1", credentials=creds)

        message = MIMEMultipart("alternative")
        message["To"] = self.settings.to_address
        message["From"] = self.settings.from_address
        message["Subject"] = subject
        message.attach(MIMEText(text_body, "plain"))
        message.attach(MIMEText(html_body, "html"))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
