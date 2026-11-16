"""Unit tests for Commercial Syndicate Pro REST API endpoints."""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)
VALID_API_KEY = "ape_test_key_master"
FREE_API_KEY = "ape_test_key_free"
PRO_API_KEY = "ape_test_key_pro"
VIP_API_KEY = "ape_test_key_vip"


def test_api_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ONLINE"
    assert "daemon_status" in data


def test_auth_rejection():
    # Missing API Key
    response = client.get("/api/v1/syndicate/in-play/alerts")
    assert response.status_code == 401

    # Invalid API Key
    response = client.get(
        "/api/v1/syndicate/in-play/alerts",
        headers={"X-API-Key": "invalid_random_key_123"},
    )
    assert response.status_code == 403


def test_in_play_alerts_endpoint():
    response = client.get(
        "/api/v1/syndicate/in-play/alerts",
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ONLINE"
    assert "live_fixtures_monitored" in data
    assert "recent_in_play_alerts_count" in data


def test_sgp_combinations_endpoint():
    response = client.get(
        "/api/v1/syndicate/sgp/combinations?min_joint_ev=5.0",
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ONLINE"
    assert "model" in data
    assert "available_sgp_combinations" in data


def test_clv_report_endpoint():
    response = client.get(
        "/api/v1/syndicate/clv/report",
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["ACTIVE", "INITIALIZING"]


def test_portfolio_optimize_endpoint():
    payload = {
        "bankroll": 1000.0,
        "fractional_kelly": 0.25,
        "bets": [
            {
                "id": "bet_1",
                "match": "Team A vs Team B",
                "market": "1X2",
                "selection": "MS 1",
                "odds": 2.0,
                "prob": 0.55,
                "edge_pct": 10.0,
            },
            {
                "id": "bet_2",
                "match": "Team C vs Team D",
                "market": "1X2",
                "selection": "MS 1",
                "odds": 1.80,
                "prob": 0.60,
                "edge_pct": 8.0,
            },
        ],
    }
    response = client.post(
        "/api/v1/syndicate/portfolio/optimize",
        headers={"X-API-Key": VALID_API_KEY},
        json=payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "optimization_result" in data
    res = data["optimization_result"]
    assert "allocations" in res
    assert "total_staked_tl" in res


def test_free_tier_denied_sgp_combinations():
    """Verify FREE tier API key receives 403 Tier Upgrade Required for SGP combinations."""
    response = client.get(
        "/api/v1/syndicate/sgp/combinations?min_joint_ev=5.0",
        headers={"X-API-Key": FREE_API_KEY},
    )
    assert response.status_code == 403
    detail = response.json().get("detail", "")
    assert "Tier Upgrade Required" in detail


def test_free_tier_denied_clv_report():
    """Verify FREE tier API key receives 403 Tier Upgrade Required for CLV report."""
    response = client.get(
        "/api/v1/syndicate/clv/report",
        headers={"X-API-Key": FREE_API_KEY},
    )
    assert response.status_code == 403
    detail = response.json().get("detail", "")
    assert "Tier Upgrade Required" in detail


def test_free_tier_denied_portfolio_optimize():
    """Verify FREE tier API key receives 403 Tier Upgrade Required for Portfolio Kelly optimization."""
    payload = {
        "bankroll": 1000.0,
        "fractional_kelly": 0.25,
        "bets": [
            {
                "id": "bet_1",
                "match": "Team A vs Team B",
                "market": "1X2",
                "selection": "MS 1",
                "odds": 2.0,
                "prob": 0.55,
                "edge_pct": 10.0,
            }
        ],
    }
    response = client.post(
        "/api/v1/syndicate/portfolio/optimize",
        headers={"X-API-Key": FREE_API_KEY},
        json=payload,
    )
    assert response.status_code == 403
    detail = response.json().get("detail", "")
    assert "Tier Upgrade Required" in detail


def test_pro_tier_allowed_access():
    """Verify PRO tier API key is granted access to SGP and CLV endpoints."""
    # SGP allowed
    resp_sgp = client.get(
        "/api/v1/syndicate/sgp/combinations?min_joint_ev=5.0",
        headers={"X-API-Key": PRO_API_KEY},
    )
    assert resp_sgp.status_code == 200

    # CLV allowed
    resp_clv = client.get(
        "/api/v1/syndicate/clv/report",
        headers={"X-API-Key": PRO_API_KEY},
    )
    assert resp_clv.status_code == 200


def test_vip_tier_allowed_all_endpoints():
    """Verify VIP tier API key has full access to all endpoints."""
    resp_sgp = client.get(
        "/api/v1/syndicate/sgp/combinations",
        headers={"X-API-Key": VIP_API_KEY},
    )
    assert resp_sgp.status_code == 200

    resp_clv = client.get(
        "/api/v1/syndicate/clv/report",
        headers={"X-API-Key": VIP_API_KEY},
    )
    assert resp_clv.status_code == 200


def test_master_key_preserves_full_vip_access():
    """SPEC-0012 constraint: ape_test_key_master must retain full unrestricted VIP access across all endpoints."""
    resp_health = client.get("/api/v1/health")
    assert resp_health.status_code == 200

    resp_inplay = client.get(
        "/api/v1/syndicate/in-play/alerts",
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert resp_inplay.status_code == 200

    resp_sgp = client.get(
        "/api/v1/syndicate/sgp/combinations",
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert resp_sgp.status_code == 200

    resp_clv = client.get(
        "/api/v1/syndicate/clv/report",
        headers={"X-API-Key": VALID_API_KEY},
    )
    assert resp_clv.status_code == 200


def test_ui_static_mount_endpoint():
    """Verify that /ui/ serves index.html and root / redirects to /ui/."""
    resp_root = client.get("/", follow_redirects=False)
    assert resp_root.status_code in (307, 302, 301, 200)

    resp_ui = client.get("/ui/")
    assert resp_ui.status_code == 200
    assert "text/html" in resp_ui.headers.get("content-type", "")
    assert "Sports Intelligence Terminal" in resp_ui.text

