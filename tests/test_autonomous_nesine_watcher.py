"""Unit tests for autonomous_nesine_watcher.py (SPEC-0012/0013/0014, MBS 1-2, dedup)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import autonomous_nesine_watcher as watcher

TRT = timezone(timedelta(hours=3))


def _make_payload(now_trt: datetime) -> dict:
    ok_dt = now_trt + timedelta(hours=2)
    started_dt = now_trt - timedelta(minutes=10)
    far_dt = now_trt + timedelta(hours=14)

    def _mk_item(eid, dt, mbs, home, away, o1, ox, o2, u25, ov25):
        return {
            "TYPE": 1,
            "EID": eid,
            "D": dt.strftime("%d.%m.%Y"),
            "T": dt.strftime("%H:%M"),
            "HN": home,
            "AN": away,
            "EMBS": mbs,
            "LC": 1,
            "MA": [
                {
                    "MTID": 1,
                    "MBS": mbs,
                    "OCA": [{"N": 1, "O": o1}, {"N": 2, "O": ox}, {"N": 3, "O": o2}],
                },
                {
                    "MTID": 12,
                    "SOV": 2.5,
                    "OCA": [{"N": 1, "O": u25}, {"N": 2, "O": ov25}],
                },
            ],
        }

    return {
        "sg": {
            "LA": [{"LID": 1, "N": "UEFA Uluslar Ligi"}],
            "EA": [
                _mk_item(101, ok_dt, 1, "HeavyFav", "Underdog", 1.15, 6.00, 12.0, 2.40, 1.35),
                _mk_item(102, started_dt, 1, "AlreadyStarted", "TeamB", 1.20, 5.00, 9.0, 2.10, 1.50),
                _mk_item(103, far_dt, 1, "TooFar", "TeamC", 1.20, 5.00, 9.0, 2.10, 1.50),
                _mk_item(104, ok_dt, 3, "MbsThree", "TeamD", 1.15, 6.00, 12.0, 2.40, 1.35),
            ],
        }
    }


def test_extract_enforces_spec0013_0014_and_mbs12():
    now_trt = datetime(2026, 11, 13, 17, 30, tzinfo=TRT)
    payload = _make_payload(now_trt)
    candidates = watcher.extract_mbs12_candidates(payload, now_trt=now_trt)
    assert len(candidates) == 1
    assert candidates[0]["home"] == "HeavyFav"
    assert candidates[0]["mbs"] == 1


def test_evaluate_filters_above_65_percent_and_blocks_low_odds():
    now_trt = datetime(2026, 11, 13, 17, 30, tzinfo=TRT)
    payload = _make_payload(now_trt)
    candidates = watcher.extract_mbs12_candidates(payload, now_trt=now_trt)
    # 1.15 / 1.35 heavy favorite legs in _make_payload must be rejected by min_odds=1.45
    assert watcher.evaluate_high_prob_signals(candidates, min_prob=0.65) == []

    # Value-range favorite (>= 1.45) with high implied probability passes only within bounds
    candidates[0]["mkts"]["1X2"] = (1.50, 4.20, 6.50)
    signals = watcher.evaluate_high_prob_signals(candidates, min_prob=0.60, min_odds=1.45)
    assert len(signals) >= 1
    assert all(1.45 <= s["odds"] <= 6.50 for s in signals)


def test_deduplication_and_ev_mode_prevents_low_odds_and_repeats(tmp_path: Path):
    now_trt = datetime(2026, 11, 13, 17, 30, tzinfo=TRT)
    seen_path = tmp_path / "seen.json"
    hb_path = tmp_path / "hb.json"

    fake_report = {
        "summary": {"window_valid_matches": 12},
        "signals": [
            {
                "nesine_code": "101",
                "home": "TrashFav",
                "away": "Underdog",
                "league": "UEFA",
                "mbs": 1,
                "market": "1X2",
                "selection": "MS 1",
                "book_odd": 1.18,
                "fair_odd": 1.12,
                "prob": 0.89,
                "edge_pct": 5.3,
                "stake": 50.0,
                "kickoff_trt": "2026-11-13 21:00 TRT",
                "source_engine": "team_strength",
            },
            {
                "nesine_code": "102",
                "home": "Leganes",
                "away": "Burgos",
                "league": "La Liga 2",
                "mbs": 1,
                "market": "1X2",
                "selection": "MS 1",
                "book_odd": 2.15,
                "fair_odd": 1.90,
                "prob": 0.526,
                "edge_pct": 13.1,
                "stake": 75.0,
                "kickoff_trt": "2026-11-13 22:30 TRT",
                "source_engine": "sharp_market",
            },
        ],
    }

    with (
        patch("scripts.run_daily_prototype.run_daily_pipeline", return_value=fake_report),
        patch.object(watcher, "send_telegram_message", return_value=True) as mock_tg,
    ):
        res1 = watcher.run_watcher_cycle(
            seen_path=seen_path,
            heartbeat_path=hb_path,
            enable_telegram=True,
            enable_inplay=False,
            now_trt=now_trt,
        )
        assert res1["mode"] == "dual_engine_ev"
        assert res1["qualified_signals"] == 1
        assert res1["new_signals"] == 1
        assert res1["telegram_dispatched"] is True
        assert mock_tg.call_count == 1
        sent_msg = mock_tg.call_args[0][0]
        assert "Leganes vs Burgos" in sent_msg
        assert "TrashFav" not in sent_msg

        # Second cycle for the same matches must send 0 new signals
        res2 = watcher.run_watcher_cycle(
            seen_path=seen_path,
            heartbeat_path=hb_path,
            enable_telegram=True,
            enable_inplay=False,
            now_trt=now_trt,
        )
        assert res2["new_signals"] == 0
        assert res2["telegram_dispatched"] is False
        assert mock_tg.call_count == 1
        assert json.loads(hb_path.read_text(encoding="utf-8"))["total_seen"] == 1


def test_fetch_fail_closed_on_network_error():
    with patch("urllib.request.urlopen", side_effect=OSError("network down")):
        with pytest.raises(RuntimeError, match="Nesine CDN fetch failed"):
            watcher.fetch_nesine_pre_bulletin()


def test_adaptive_polling_interval_2m_live_vs_5m_idle():
    assert watcher.compute_adaptive_interval_sec({"inplay_matches": 3}) == 120
    assert watcher.compute_adaptive_interval_sec({"inplay_matches": 0}) == 300
    assert watcher.compute_adaptive_interval_sec(None) == 300

    sleeps: list[int] = []
    cycles = [
        {"inplay_matches": 2},
        {"inplay_matches": 0},
        {"inplay_matches": 1},
    ]

    with (
        patch.object(watcher, "run_watcher_cycle", side_effect=cycles),
        patch("time.sleep", side_effect=lambda sec: sleeps.append(sec)),
    ):
        watcher.run_watcher_loop(
            interval_sec=300,
            live_interval_sec=120,
            max_cycles=3,
            enable_telegram=False,
        )

    assert sleeps == [120, 300]

