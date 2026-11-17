"""Tests for scripts/send_daily_telegram_digest.py."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from send_daily_telegram_digest import build_digest_message  # noqa: E402

TRT_TZ = timezone(timedelta(hours=3))


def test_build_digest_filters_past_kickoffs_and_sorts_by_margin() -> None:
    now_trt = datetime(2026, 11, 15, 19, 30, tzinfo=TRT_TZ)
    report = {
        "generated_at_trt": "2026-11-15 19:30 TRT",
        "summary": {
            "bulletin_total_matches": 100,
            "sharp_nesine_matched": 40,
            "signals_count": 0,
        },
        "signals": [],
        "fair_odds_comparison": [
            {
                "kickoff_trt": "2026-11-15 18:00 TRT",
                "match": "Past Match A vs B",
                "selection": "MS 1",
                "nesine_odd": 2.0,
                "fair_odd": 2.1,
                "nesine_overround_pct": 115.0,
                "edge_pct": -4.76,
            },
            {
                "kickoff_trt": "2026-11-15 22:00 TRT",
                "match": "High Margin C vs D",
                "selection": "MS 2",
                "nesine_odd": 2.4,
                "fair_odd": 2.6,
                "nesine_overround_pct": 124.5,
                "edge_pct": -7.69,
            },
            {
                "kickoff_trt": "2026-11-15 23:00 TRT",
                "match": "Low Margin E vs F",
                "selection": "MS 1",
                "nesine_odd": 1.95,
                "fair_odd": 2.0,
                "nesine_overround_pct": 116.2,
                "edge_pct": -2.5,
            },
        ],
    }

    msg = build_digest_message(report, now_trt=now_trt)
    assert "Past Match A vs B" not in msg
    assert "Gerçek +EV Sinyali Yok (0)" in msg
    assert msg.index("Low Margin E vs F") < msg.index("High Margin C vs D")


def test_main_passive_mode_skips_telegram_by_default(tmp_path, monkeypatch) -> None:
    import json

    import send_daily_telegram_digest as mod

    report_file = tmp_path / "daily_prototype_report.json"
    report_file.write_text(
        json.dumps({"generated_at_trt": "2026-11-17 12:00 TRT", "summary": {}, "signals": []}),
        encoding="utf-8",
    )

    called: list[str] = []
    monkeypatch.delenv("APE_ENABLE_TELEGRAM_SIGNALS", raising=False)
    monkeypatch.setattr(mod, "send_telegram_message", lambda msg: called.append(msg) or True)

    # Default passive mode: should exit 0 without sending
    monkeypatch.setattr(sys, "argv", ["send_daily_telegram_digest.py", "--report-path", str(report_file)])
    assert mod.main() == 0
    assert called == []

    # Explicit opt-in flag: sends message
    monkeypatch.setattr(
        sys,
        "argv",
        ["send_daily_telegram_digest.py", "--report-path", str(report_file), "--enable-send"],
    )
    assert mod.main() == 0
    assert len(called) == 1
