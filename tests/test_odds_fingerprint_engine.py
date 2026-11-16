"""Unit tests for OddsFingerprintEngine & k-NN Market Twin System."""
from __future__ import annotations

import time

import pytest

from odds_fingerprint_engine import (
    FingerprintTwinReport,
    OddsFingerprintEngine,
    format_fingerprint_telegram_message,
)


@pytest.fixture(scope="module")
def engine():
    return OddsFingerprintEngine()


def test_engine_vectorization(engine):
    assert engine.matrix is not None
    assert engine.matrix.shape[0] > 25000
    assert engine.matrix.shape[1] == 8
    assert len(engine.df) == engine.matrix.shape[0]


def test_knn_speed_and_structure(engine):
    # Benchmark query speed
    start_t = time.perf_counter()
    report = engine.find_nearest_twins(
        open_1=1.35,
        open_x=5.20,
        open_2=8.50,
        open_o25=1.45,
        open_u25=2.65,
        steam_o25_pct=-3.5,
        k=50,
    )
    elapsed_ms = (time.perf_counter() - start_t) * 1000.0

    # Must complete in under 500 ms (NumPy vectorization + aggregation across varying CI/OS loads)
    assert elapsed_ms < 500.0, f"Query took {elapsed_ms:.2f}ms, expected < 500ms"
    assert isinstance(report, FingerprintTwinReport)
    assert report.k_neighbors == 50
    assert report.avg_similarity_pct > 70.0
    assert report.avg_corners > 8.0
    assert report.avg_ft_goals > 2.0
    assert len(report.sample_twins) == 4
    assert len(report.top_exact_scores) > 0


def test_knn_defensive_fixture_twins(engine):
    # Kısır maç örneği
    report = engine.find_nearest_twins(
        open_1=2.10,
        open_x=2.90,
        open_2=3.40,
        open_o25=2.45,
        open_u25=1.50,
        k=50,
    )
    # Kısır maç ikizlerinde 2.5 Alt veya 9.5 Alt güçlü çıkmalı
    assert report.pct_ft_o25 < 45.0
    assert report.pct_corners_12plus < 25.0


def test_scan_live_fixture(engine):
    mock_fix = {
        "home": "Porto",
        "away": "Napoli",
        "nesine_1x2": (1.69, 3.29, 3.44),
        "nesine_ou25": (1.51, 1.90),
    }
    report = engine.scan_fixture(mock_fix, k=40)
    assert report is not None
    assert report.k_neighbors == 40
    assert report.query_odds["MS 1"] == 1.69


def test_format_telegram_message(engine):
    report = engine.find_nearest_twins(
        open_1=1.40,
        open_x=4.50,
        open_2=7.00,
        open_o25=1.50,
        open_u25=2.50,
        k=50,
    )
    msg = format_fingerprint_telegram_message(
        fixture_name="Bayern Münih vs Augsburg",
        time_str="22:30",
        mbs=1,
        report=report,
    )
    assert "ORAN PARMAK İZİ" in msg
    assert "Bayern Münih vs Augsburg" in msg
    assert "Korner Dağılımı" in msg
    assert "Tarihten Birebir Örnek İkizler" in msg
