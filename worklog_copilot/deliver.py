"""Send the digest somewhere people will read it.

Each channel is optional and configured by environment variables, so the
same code runs locally (write a file) and in GitHub Actions (open an issue,
send email). A failed channel is reported but does not stop the others.
"""
from __future__ import annotations

import json
import os
import smtplib
import urllib.request
from email.message import EmailMessage


def to_file(markdown: str, path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)
    return f"wrote {path}"


def to_github_issue(markdown: str, title: str, repo: str | None = None,
                    token: str | None = None) -> str:
    repo = repo or os.environ["DIGEST_ISSUE_REPO"]
    token = token or os.environ["GITHUB_TOKEN"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues", method="POST",
        data=json.dumps({"title": title, "body": markdown, "labels": ["weekly-digest"]}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return "opened issue " + json.loads(r.read())["html_url"]


def to_email(markdown: str, subject: str) -> str:
    """SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, DIGEST_TO (comma separated)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["DIGEST_TO"]
    msg.set_content(markdown)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
    return f"emailed {msg['To']}"


def to_sheet_webhook(rows: list[dict]) -> str:
    """POST one row per intern to a Google Apps Script web app (SHEET_WEBHOOK_URL).

    The Apps Script side is in examples/sheet_webhook.gs.
    """
    url = os.environ["SHEET_WEBHOOK_URL"]
    req = urllib.request.Request(url, method="POST", data=json.dumps(rows).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return f"sheet webhook: HTTP {r.status}"
