"""Email Notification Engine for Sports-Engine.

Sends automated daily bulletins, settlement summaries, and high-value alerts
to configured subscriber emails using authenticated SMTP (e.g. Gmail App Password).
"""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def send_email(
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> dict[str, Any]:
    """Send an email using authenticated SMTP credentials from .env.

    Requires SMTP_USER and SMTP_PASSWORD in sports-engine/.env.
    For Gmail: SMTP_HOST='smtp.gmail.com', SMTP_PORT=587, and a 16-character Google App Password.
    """
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_password:
        return {
            "success": False,
            "error": "SMTP_USER veya SMTP_PASSWORD tanımlı değil. sports-engine/.env dosyasına Gmail Uygulama Şifresi eklenmelidir.",
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"APE Sports-Engine <{smtp_user}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        # Attach text part
        msg.attach(MIMEText(body_text, "plain", "utf-8"))

        # Attach HTML part if available
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15.0) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        return {
            "success": True,
            "to": to_email,
            "subject": subject,
            "message": f"E-posta başarıyla {to_email} adresine gönderildi.",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"SMTP Gönderim Hatası: {str(e)}",
        }


def format_bulletin_email_html(report_markdown: str) -> str:
    """Convert sports report to clean, readable HTML email styling."""
    try:
        import markdown
        content_html = markdown.markdown(report_markdown, extensions=["tables"])
    except Exception:
        # Fallback to simple paragraph wrapping if markdown lib is missing
        content_html = f"<pre style='white-space: pre-wrap; font-family: monospace;'>{report_markdown}</pre>"

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
        .container {{ max-width: 700px; margin: 0 auto; background: #1e293b; border-radius: 8px; padding: 24px; border: 1px solid #334155; }}
        h1, h2, h3 {{ color: #38bdf8; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 13px; }}
        th, td {{ border: 1px solid #334155; padding: 8px; text-align: left; }}
        th {{ background-color: #0f172a; color: #94a3b8; }}
        tr:nth-child(even) {{ background-color: #1e293b; }}
        .badge {{ background: #0284c7; color: #fff; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 11px; }}
      </style>
    </head>
    <body>
      <div class="container">
        {content_html}
      </div>
    </body>
    </html>
    """

