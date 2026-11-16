"""Unit tests for CLVAlphaAttributionEngine (Proposal 5)."""

from __future__ import annotations

import pytest

from clv_alpha_attribution import (
    CLVAlphaAttributionEngine,
    TradeAlphaDecomposition,
)


def test_alpha_decomposition_mathematical_identity():
    """Verify exact Wall Street identity (1 + Alpha_Stale) * (1 + Alpha_Info) - 1 == Alpha_Total."""
    engine = CLVAlphaAttributionEngine()

    # Soft book offered 2.10, sharp entry was 2.00 (+5.0% stale alpha)
    # Sharp closing dropped to 1.90 (+5.26% info alpha as line moved in our direction)
    decomp = engine.decompose_trade(
        trade_id="TR_001",
        fixture_id="FIX_101",
        match_name="Inter vs Como",
        selection="MS 1",
        market="1X2",
        soft_odds=2.10,
        sharp_entry_odds=2.00,
        sharp_closing_odds=1.90,
    )

    assert isinstance(decomp, TradeAlphaDecomposition)
    assert decomp.stale_alpha_pct == 5.0  # (2.10 / 2.00) - 1 = +5.0%
    assert pytest.approx(decomp.info_alpha_pct, abs=0.01) == 5.26  # (2.00 / 1.90) - 1 = +5.26%
    assert pytest.approx(decomp.total_clv_pct, abs=0.01) == 10.53  # (2.10 / 1.90) - 1 = +10.53%
    # Identity residual must be negligible
    assert decomp.synergy_identity_error < 1e-4
    assert decomp.beat_closing is True


def test_alpha_attribution_fail_closed_spec0012():
    """Verify SPEC-0012 fail-closed validation when odds are invalid or <= 1.0."""
    engine = CLVAlphaAttributionEngine()

    with pytest.raises(ValueError, match="SPEC-0012 Violation"):
        engine.decompose_trade(
            trade_id="TR_BAD",
            fixture_id="FIX_BAD",
            match_name="Bad Match",
            selection="1",
            market="1X2",
            soft_odds=1.00,  # Invalid
            sharp_entry_odds=1.50,
            sharp_closing_odds=1.45,
        )


def test_portfolio_alpha_report_aggregation(tmp_path):
    """Verify portfolio level aggregation of CLV metrics and JSON export."""
    engine = CLVAlphaAttributionEngine()

    trades = [
        {
            "id": "T1",
            "fixture_id": "F1",
            "match_name": "Arsenal vs Chelsea",
            "selection": "MS 1",
            "market": "1X2",
            "soft_odds": 1.80,
            "sharp_entry_odds": 1.70,
            "sharp_closing_odds": 1.65,
        },
        {
            "id": "T2",
            "fixture_id": "F2",
            "match_name": "Monza vs Atalanta",
            "selection": "2.5 ÜST",
            "market": "2.5 Gol",
            "soft_odds": 1.95,
            "sharp_entry_odds": 1.90,
            "sharp_closing_odds": 1.85,
        },
        {
            "id": "T3",
            "fixture_id": "F3",
            "match_name": "Lecce vs Torino",
            "selection": "X2",
            "market": "Çifte Şans",
            "soft_odds": 1.45,
            "sharp_entry_odds": 1.48,  # Negative stale
            "sharp_closing_odds": 1.50,
        },
    ]

    report = engine.evaluate_trades(trades)
    assert report.total_analyzed_trades == 3
    assert report.beat_closing_count == 2  # T1 and T2 beat closing
    assert pytest.approx(report.beat_closing_rate_pct, abs=0.1) == 66.67
    assert report.mean_total_clv_pct > 0.0

    # Test file export
    out_file = tmp_path / "clv_report_test.json"
    engine.generate_and_export_report(
        ledger_path=tmp_path / "non_existent.json",
        output_path=out_file,
    )
    assert out_file.exists()

