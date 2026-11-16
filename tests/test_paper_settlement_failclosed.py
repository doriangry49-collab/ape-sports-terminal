"""Regression: unsupported markets must not crash settlement (SPEC-0012 fail-closed)."""

from paper_trader import PaperTradingEngine, evaluate_outcome_win


def test_double_chance_turkish_case_is_supported():
    assert evaluate_outcome_win("Çifte Şans", "1X (Ev & Beraberlik)", 1, 1) is True
    assert evaluate_outcome_win("Çifte Şans", "X2 (Beraberlik & Deplasman)", 2, 0) is False


def test_total_goals_threshold():
    assert evaluate_outcome_win("Toplam Gol", "TG 6+", 3, 3) is True
    assert evaluate_outcome_win("Toplam Gol", "TG 6+", 2, 1) is False


def test_unsupported_market_left_pending_not_crash(tmp_path):
    eng = PaperTradingEngine(ledger_path=tmp_path / "ledger.csv")
    base = {
        "event_id": "e1", "home": "Alpha", "away": "Beta", "soft_odds": "3.0",
        "shin_fair_prob": "0.4", "status": "PENDING", "kickoff": "2026-11-05T20:00:00Z",
    }
    eng.save_rows([
        {**base, "signal_id": "a|İY/MS|İY/MS X/2", "market": "İY/MS", "outcome": "İY/MS X/2"},
        {**base, "signal_id": "a|1X2|MS 1", "market": "1X2", "outcome": "MS 1"},
    ])
    res = eng.settle_with_scores([{"home": "Alpha", "away": "Beta", "hg": 2, "ag": 0, "done": True}])
    rows = {r["signal_id"]: r for r in eng.load_rows()}
    assert res["settled_now"] == 1
    assert res["unsettleable"] == 1
    assert rows["a|İY/MS|İY/MS X/2"]["status"] == "PENDING"
    assert rows["a|1X2|MS 1"]["status"] == "WON"


def test_corner_and_htft_settle_when_stats_present_and_failclosed_when_missing(tmp_path):
    eng = PaperTradingEngine(ledger_path=tmp_path / "ledger_stats.csv")
    base = {
        "event_id": "e2", "home": "Palmeiras SP", "away": "Clube do Remo", "soft_odds": "2.10",
        "shin_fair_prob": "0.55", "status": "PENDING", "kickoff": "2026-11-05T22:30:00Z",
    }
    eng.save_rows([
        {**base, "signal_id": "p|Korner 9.5|Korner 9.5 ÜST", "market": "Korner 9.5", "outcome": "Korner 9.5 ÜST"},
        {**base, "signal_id": "p|İY/MS|İY/MS 1/1", "market": "İY/MS", "outcome": "İY/MS 1/1"},
    ])
    # 1. Without corners / HT scores -> must stay PENDING (SPEC-0012 fail-closed)
    res_missing = eng.settle_with_scores([
        {"home": "Palmeiras", "away": "Remo", "hg": 2, "ag": 1, "done": True}
    ])
    assert res_missing["settled_now"] == 0
    assert res_missing["unsettleable"] == 2

    # 2. With corners=13 and ht_hg=1, ht_ag=0 -> both must settle WON
    res_present = eng.settle_with_scores([
        {"home": "Palmeiras", "away": "Remo", "hg": 2, "ag": 1, "ht_hg": 1, "ht_ag": 0, "corners": 13, "done": True}
    ])
    assert res_present["settled_now"] == 2
    rows = {r["signal_id"]: r for r in eng.load_rows()}
    assert rows["p|Korner 9.5|Korner 9.5 ÜST"]["status"] == "WON"
    assert "K:13" in rows["p|Korner 9.5|Korner 9.5 ÜST"]["result_score"]
    assert rows["p|İY/MS|İY/MS 1/1"]["status"] == "WON"
    assert "İY:1-0" in rows["p|İY/MS|İY/MS 1/1"]["result_score"]
