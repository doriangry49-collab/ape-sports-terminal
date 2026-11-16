"""Unit and integration tests for APE Sports-Engine B2B REST API Gateway."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)
VALID_API_KEY = "ape_test_key_master"
AUTH_HEADERS = {"X-API-Key": VALID_API_KEY}


def test_health_check_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ONLINE"
    assert "daemon_status" in data
    assert "timestamp_utc" in data


def test_missing_api_key_returns_401():
    response = client.post("/api/v1/pricing/devig", json={"odds": [2.10, 3.40, 3.80]})
    assert response.status_code == 401
    assert "Missing required authentication" in response.json()["detail"]


def test_invalid_api_key_returns_403():
    response = client.post(
        "/api/v1/pricing/devig",
        json={"odds": [2.10, 3.40, 3.80]},
        headers={"X-API-Key": "invalid_fraudulent_key"},
    )
    assert response.status_code == 403
    assert "Invalid or expired API Key" in response.json()["detail"]


def test_pricing_devig_shin_success():
    payload = {"odds": [2.00, 3.40, 4.00], "method": "shin"}
    response = client.post("/api/v1/pricing/devig", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["method"] == "shin"
    assert len(data["probabilities"]) == 3
    assert pytest.approx(sum(data["probabilities"]), abs=1e-3) == 1.0
    assert data["z_parameter"] is not None
    assert data["margin"] > 0


def test_pricing_devig_power_and_multiplicative():
    for method in ["power", "multiplicative", "additive", "logarithmic"]:
        payload = {"odds": [1.90, 3.50, 4.20], "method": method}
        response = client.post("/api/v1/pricing/devig", json=payload, headers=AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert pytest.approx(sum(data["probabilities"]), abs=1e-3) == 1.0


def test_pricing_devig_invalid_odds_fails():
    payload = {"odds": [0.90, 3.40, 4.00], "method": "shin"}
    response = client.post("/api/v1/pricing/devig", json=payload, headers=AUTH_HEADERS)
    assert response.status_code == 422


def test_get_active_signals_authenticated():
    response = client.get("/api/v1/signals/active", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "count" in data
    assert isinstance(data["signals"], list)


def test_get_ledger_summary_authenticated():
    response = client.get("/api/v1/signals/ledger", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert "total_bets" in data
    assert "win_rate_pct" in data
    assert "net_units" in data

