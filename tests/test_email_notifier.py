"""Tests for Email Notification Engine."""

from email_notifier import format_bulletin_email_html, send_email


def test_send_email_missing_credentials():
    res = send_email("test@example.com", "Test Subject", "Test Body")
    assert not res["success"]
    assert "SMTP_USER" in res["error"]


def test_format_bulletin_email_html():
    html = format_bulletin_email_html("# Test Header\nSome content")
    assert "<!DOCTYPE html>" in html
    assert "Test Header" in html
