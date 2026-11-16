"""Pytest configuration and shared fixtures for sports-engine test suite."""

import sys
from pathlib import Path

import pytest

# Ensure src and project root are on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    """Provides an isolated temporary data directory with bronze/silver/gold subfolders."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def mock_ledger_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provides isolated, temporary ledger files for active coupons and bankroll."""
    import json
    coupons_file = tmp_path / "active_coupons.json"
    bankroll_file = tmp_path / "active_bankroll.json"

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
                    "status": "PENDING",
                }
            ],
        }
    ]
    coupons_file.write_text(json.dumps(mock_coupons), encoding="utf-8")

    mock_bankroll = {
        "initial_bankroll": 150.0,
        "total_staked": 150.0,
        "cash_balance": 0.0,
        "realized_pnl": 0.0,
        "total_portfolio_value": 150.0,
        "settled_tickets_count": 0,
        "active_tickets_count": 1,
        "status": "ALL_IN_PLAY",
    }
    bankroll_file.write_text(json.dumps(mock_bankroll), encoding="utf-8")

    try:
        import live_settlement_engine
        monkeypatch.setattr(live_settlement_engine, "COUPONS_FILE", coupons_file)
        monkeypatch.setattr(live_settlement_engine, "BANKROLL_FILE", bankroll_file)
    except ImportError:
        pass

    try:
        import telegram_notifier
        monkeypatch.setattr(telegram_notifier, "COUPONS_FILE", coupons_file)
        monkeypatch.setattr(telegram_notifier, "BANKROLL_FILE", bankroll_file)
        monkeypatch.setattr(telegram_notifier, "ROOT_DIR", tmp_path)
    except ImportError:
        pass

    return {
        "coupons_file": coupons_file,
        "bankroll_file": bankroll_file,
        "coupons": mock_coupons,
        "bankroll": mock_bankroll,
    }
