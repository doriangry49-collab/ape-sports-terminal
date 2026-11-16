"""Unit tests for Telegram Notifier Engine."""

from telegram_notifier import format_coupon_telegram, send_telegram_message


def test_format_coupon_telegram():
    picks = [
        {
            "match": "E. Frankfurt vs Hamburg",
            "time": "19:30",
            "market": "1X2",
            "selection": "MS 1",
            "book_odd": 1.34,
            "prob": 0.844,
        },
        {
            "match": "Marsilya vs Toulouse",
            "time": "22:45",
            "market": "1X2",
            "selection": "MS 1",
            "book_odd": 1.68,
            "prob": 0.887,
        },
    ]

    msg = format_coupon_telegram(
        coupon_name="Kasa Kalkanı Kuponu",
        picks=picks,
        total_odds=2.25,
        stake=50.0,
        potential_return=112.56,
        strategy_note="Kasa Büyütme",
    )

    assert "Kasa Kalkanı Kuponu" in msg
    assert "E. Frankfurt vs Hamburg" in msg
    assert "Marsilya vs Toulouse" in msg
    assert "2.25" in msg
    assert "112.56 TL" in msg


def test_send_telegram_message_missing_credentials(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    success = send_telegram_message("Test message")
    assert success is False


def test_process_user_command(tmp_path, monkeypatch):
    """Test interactive Telegram commands in an isolated fixture environment."""
    import json

    import telegram_notifier
    from telegram_notifier import process_user_command

    test_bankroll_file = tmp_path / "active_bankroll.json"
    test_coupons_file = tmp_path / "active_coupons.json"

    # Decouple ledger files from live production directory
    monkeypatch.setattr(telegram_notifier, "BANKROLL_FILE", test_bankroll_file)
    monkeypatch.setattr(telegram_notifier, "COUPONS_FILE", test_coupons_file)
    monkeypatch.setattr(telegram_notifier, "ROOT_DIR", tmp_path)

    # 1. Test missing file / fallback handling
    res_kasa_default = process_user_command("/kasa")
    assert "GÜNCEL KASA BİLANÇOSU" in res_kasa_default
    assert "150.00 TL" in res_kasa_default

    res_kupon_default = process_user_command("/kuponlar")
    assert "Kasa Kalkanı" in res_kupon_default

    # 2. Test populated state
    mock_bankroll = {
        "initial_bankroll": 150.0,
        "total_staked": 150.0,
        "cash_balance": 0.0,
        "realized_pnl": 0.0,
        "status": "ALL_IN_PLAY",
    }
    test_bankroll_file.write_text(json.dumps(mock_bankroll), encoding="utf-8")

    mock_coupons = [
        {
            "id": "coupon_001_shield",
            "name": "Kasa Kalkanı",
            "status": "PENDING",
            "stake": 50.0,
            "potential_return": 147.0,
            "picks": [
                {
                    "match": "Marseille vs Toulouse",
                    "kickoff_trt": "22:45",
                    "selection": "MS 1",
                    "odds": 1.67,
                }
            ],
        }
    ]
    test_coupons_file.write_text(json.dumps(mock_coupons), encoding="utf-8")

    res_kasa = process_user_command("/kasa")
    assert "GÜNCEL KASA BİLANÇOSU" in res_kasa
    assert "150.00 TL" in res_kasa

    res_kupon = process_user_command("/kuponlar")
    assert "Marseille" in res_kupon or "Marsilya" in res_kupon
    assert "Kasa Kalkanı" in res_kupon

    res_yardim = process_user_command("/yardim")
    assert "KOMUTA MASASI" in res_yardim

    res_unknown = process_user_command("/bilinmeyen")
    assert "Bilinmeyen komut" in res_unknown


def test_process_user_command_group_bot_syntax(tmp_path, monkeypatch):
    """Verify group bot syntax /cmd@OddieroBot correctly resolves."""
    import telegram_notifier
    from telegram_notifier import process_user_command

    monkeypatch.setattr(telegram_notifier, "BANKROLL_FILE", tmp_path / "bankroll.json")
    monkeypatch.setattr(telegram_notifier, "COUPONS_FILE", tmp_path / "coupons.json")

    res_kasa = process_user_command("/kasa@OddieroBot")
    assert "GÜNCEL KASA BİLANÇOSU" in res_kasa

    res_kupon = process_user_command("/kuponlar@OddieroBot")
    assert "BEKLEYEN AKTİF KUPONLAR" in res_kupon

    res_durum = process_user_command("/durum@OddieroBot")
    assert "SİSTEM SAĞLIĞI" in res_durum

    res_maclar = process_user_command("/maclar@OddieroBot")
    assert "ODAK MAÇLARIMIZ" in res_maclar

    res_yardim = process_user_command("/yardim@OddieroBot")
    assert "KOMUTA MASASI" in res_yardim

    res_kasa_args = process_user_command("/kasa@OddieroBot detayli")
    assert "GÜNCEL KASA BİLANÇOSU" in res_kasa_args


def test_telegram_offset_persistence(tmp_path, monkeypatch):
    """Verify loading and saving Telegram offset to disk."""
    import telegram_notifier
    from telegram_notifier import load_telegram_offset, save_telegram_offset

    test_offset_file = tmp_path / "telegram_offset.txt"
    monkeypatch.setattr(telegram_notifier, "TELEGRAM_OFFSET_FILE", test_offset_file)

    # Missing file returns None
    assert load_telegram_offset() is None

    # Save and reload
    save_telegram_offset(10050)
    assert load_telegram_offset() == 10050

    save_telegram_offset(10051)
    assert load_telegram_offset() == 10051


def test_check_and_reply_telegram_commands_advances_and_persists_offset(tmp_path, monkeypatch):
    """Verify polling Telegram advances and persists offset on disk."""
    import json

    import telegram_notifier
    from telegram_notifier import check_and_reply_telegram_commands, load_telegram_offset

    test_offset_file = tmp_path / "telegram_offset.txt"
    test_offset_file.write_text("42", encoding="utf-8")
    monkeypatch.setattr(telegram_notifier, "TELEGRAM_OFFSET_FILE", test_offset_file)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "mock_token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    mock_updates = {
        "ok": True,
        "result": [
            {
                "update_id": 42,
                "message": {
                    "chat": {"id": 12345},
                    "text": "/durum",
                },
            }
        ],
    }

    class MockResp:
        def read(self):
            return json.dumps(mock_updates).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=5.0: MockResp())
    monkeypatch.setattr(telegram_notifier, "send_telegram_message", lambda *args, **kwargs: True)

    new_offset = check_and_reply_telegram_commands()
    assert new_offset == 43
    assert load_telegram_offset() == 43


def test_check_and_reply_telegram_commands_cold_start_skips_backlog(tmp_path, monkeypatch):
    """Verify cold start with no offset queries latest update and skips backlog."""
    import json

    import telegram_notifier
    from telegram_notifier import check_and_reply_telegram_commands, load_telegram_offset

    test_offset_file = tmp_path / "telegram_offset.txt"
    monkeypatch.setattr(telegram_notifier, "TELEGRAM_OFFSET_FILE", test_offset_file)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "mock_token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    mock_cold_start = {
        "ok": True,
        "result": [
            {
                "update_id": 99,
                "message": {
                    "chat": {"id": 12345},
                    "text": "/kasa",
                },
            }
        ],
    }

    class MockResp:
        def read(self):
            return json.dumps(mock_cold_start).encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    messages_sent = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=5.0: MockResp())
    monkeypatch.setattr(telegram_notifier, "send_telegram_message", lambda msg, **kwargs: messages_sent.append(msg))

    offset = check_and_reply_telegram_commands()
    # Cold start should set offset to 99 + 1 = 100 without executing commands
    assert offset == 100
    assert load_telegram_offset() == 100
    assert len(messages_sent) == 0


def test_format_in_play_sniper_alert_valid():
    """Verify In-Play Continuous Sniper alert formatting within the valid 10'-40' window."""
    from telegram_notifier import format_in_play_sniper_alert

    alert = {
        "home_team": "Galatasaray",
        "away_team": "Fenerbahce",
        "league": "Trendyol Süper Lig",
        "elapsed_min": 25,
        "score": "0-0",
        "target_market": "Canlı Korner 8.5 ÜST",
        "selection": "8.5 ÜST",
        "target_live_odds": 1.85,
        "fair_odds": 1.62,
        "expected_live_roi": 14.2,
        "prob": 0.617,
        "prematch_lambda": 9.85,
    }

    msg = format_in_play_sniper_alert(alert)
    assert "[APE IN-PLAY SNIPER — CANLI PUSU ALARMI]" in msg
    assert "Galatasaray vs Fenerbahce" in msg
    assert "25'" in msg
    assert "0-0" in msg
    assert "Canlı Korner 8.5 ÜST" in msg
    assert "1.85" in msg
    assert "+%14.2" in msg
    assert "%61.7" in msg
    assert "λ: `9.85`" in msg


def test_format_in_play_sniper_alert_escapes_markdown():
    """Verify dynamic team names with markdown characters are properly escaped."""
    from telegram_notifier import format_in_play_sniper_alert

    alert = {
        "home": "Real_Madrid [ESP]",
        "away": "Man_City *UCL*",
        "league": "UEFA_Champions [Group A]",
        "minute": 15,
        "current_score": "0-0",
        "target_market": "Korner 9.5_ÜST",
        "selection": "ÜST",
        "soft_odds": 1.90,
        "expected_live_roi": 8.5,
    }

    msg = format_in_play_sniper_alert(alert)
    assert "Real\\_Madrid \\[ESP\\]" in msg
    assert "Man\\_City \\*UCL\\*" in msg
    assert "UEFA\\_Champions \\[Group A\\]" in msg


def test_format_in_play_sniper_alert_rejects_outside_window():
    """Verify in-play alerts outside the 10'-40' window raise ValueError."""
    import pytest

    from telegram_notifier import format_in_play_sniper_alert

    # Too early (minute 5)
    with pytest.raises(ValueError, match="outside valid 10'-40' window"):
        format_in_play_sniper_alert({
            "home": "Arsenal",
            "away": "Chelsea",
            "elapsed_min": 5,
        })

    # Too late (minute 45)
    with pytest.raises(ValueError, match="outside valid 10'-40' window"):
        format_in_play_sniper_alert({
            "home": "Arsenal",
            "away": "Chelsea",
            "elapsed_min": 45,
        })

    # Edge cases: 10 and 40 must succeed
    msg_10 = format_in_play_sniper_alert({"home": "Arsenal", "away": "Chelsea", "elapsed_min": 10})
    assert "10'" in msg_10
    msg_40 = format_in_play_sniper_alert({"home": "Arsenal", "away": "Chelsea", "elapsed_min": 40})
    assert "40'" in msg_40


def test_format_copula_sgp_alert_valid():
    """Verify Copula SGP combination formatting with valid future kickoff."""
    from datetime import UTC, datetime, timedelta

    from telegram_notifier import format_copula_sgp_alert

    valid_ko = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    sgp = {
        "home_team": "Liverpool",
        "away_team": "Everton",
        "league": "Premier League",
        "kickoff_iso": valid_ko,
        "kickoff_trt": "21:00 TRT",
        "leg_1": "MS 1 (Ev Sahibi)",
        "leg_2": "Korner 9.5 ÜST",
        "copula_family": "Gumbel Upper-Tail (θ=1.42)",
        "book_sgp_odds": 2.65,
        "fair_joint_odds": 2.30,
        "joint_prob": 0.435,
        "joint_ev_roi": 15.2,
    }

    msg = format_copula_sgp_alert(sgp)
    assert "[APE COPULA SGP — KOMBİNASYON SİNYALİ]" in msg
    assert "Liverpool vs Everton" in msg
    assert "Gumbel Upper-Tail" in msg
    assert "MS 1 (Ev Sahibi)" in msg
    assert "Korner 9.5 ÜST" in msg
    assert "2.65" in msg
    assert "2.30" in msg
    assert "%43.5" in msg
    assert "+%15.2" in msg


def test_format_copula_sgp_alert_rejects_spec0013_started_or_past():
    """Verify SGP combinations scheduled in the past or under 3 minutes are rejected."""
    from datetime import UTC, datetime, timedelta

    import pytest

    from telegram_notifier import format_copula_sgp_alert

    # In the past
    past_ko = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError, match="SPEC-0013"):
        format_copula_sgp_alert({
            "home": "Inter",
            "away": "Milan",
            "kickoff": past_ko,
        })

    # Under 3 minutes lead time
    imminent_ko = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    with pytest.raises(ValueError, match="SPEC-0013"):
        format_copula_sgp_alert({
            "home": "Inter",
            "away": "Milan",
            "kickoff": imminent_ko,
        })


def test_format_copula_sgp_alert_rejects_spec0014_beyond_12h():
    """Verify SGP combinations scheduled beyond the 12-hour window are rejected."""
    from datetime import UTC, datetime, timedelta

    import pytest

    from telegram_notifier import format_copula_sgp_alert

    # 15 hours from now
    distant_ko = (datetime.now(UTC) + timedelta(hours=15)).isoformat()
    with pytest.raises(ValueError, match="SPEC-0014"):
        format_copula_sgp_alert({
            "home": "Bayern",
            "away": "Dortmund",
            "kickoff": distant_ko,
        })


def test_format_copula_sgp_alert_escapes_markdown():
    """Verify SGP dynamic fields are escaped to protect Telegram markdown parsing."""
    from telegram_notifier import format_copula_sgp_alert

    sgp = {
        "home": "PSG_Paris [FRA]",
        "away": "Lyon_Olympique *L1*",
        "league": "Ligue_1 [France]",
        "leg_1": "1X2 [1_Home]",
        "leg_2": "Totals [Over_2.5]",
        "copula_family": "Clayton_Lower [θ=1.2]",
        "book_sgp_odds": 2.40,
        "fair_joint_odds": 2.10,
        "joint_prob": 0.476,
        "joint_ev_roi": 14.3,
    }

    msg = format_copula_sgp_alert(sgp)
    assert "PSG\\_Paris \\[FRA\\]" in msg
    assert "Lyon\\_Olympique \\*L1\\*" in msg
    assert "Ligue\\_1 \\[France\\]" in msg
    assert "1X2 \\[1\\_Home\\]" in msg
    assert "Clayton\\_Lower \\[θ=1.2\\]" in msg


def test_process_user_command_oruntu_and_parmakizi_no_import_errors(monkeypatch):
    """Verify /oruntu and /parmakizi commands execute without 'No module named' errors."""
    from datetime import UTC, datetime, timedelta

    import telegram_notifier
    from telegram_notifier import process_user_command

    now_utc = datetime.now(UTC)
    mock_fixture = {
        "date_str": (now_utc + timedelta(hours=3)).strftime("%d.%m.%Y"),
        "time_str": (now_utc + timedelta(hours=3)).strftime("%H:%M"),
        "home": "Galatasaray",
        "away": "Fenerbahce",
        "league": "Trendyol Süper Lig",
        "mbs": 1,
        "nesine_1x2": [2.10, 3.20, 2.80],
        "nesine_ou25": [1.85, 1.75],
    }

    monkeypatch.setattr(telegram_notifier, "fetch_nesine_live_bulletin", lambda: [mock_fixture])

    res_oruntu = process_user_command("/oruntu")
    assert "No module named" not in res_oruntu
    assert "Örüntü analizi hatası: No module named" not in res_oruntu
    assert "ALTIN ÖRÜNTÜ" in res_oruntu or "altın örüntü eşleşmesi bulunan maç bulunamadı" in res_oruntu

    res_parmakizi = process_user_command("/parmakizi Galatasaray")
    assert "No module named" not in res_parmakizi
    assert "Parmak izi analiz hatası: No module named" not in res_parmakizi



