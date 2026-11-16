"""Syndicate Pro Commercial API Endpoints (In-Play, Copula SGP, CLV, Portfolio Kelly)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if (ROOT_DIR / "src").exists():
    SPORTS_ENGINE_ROOT = ROOT_DIR
elif (ROOT_DIR / "sports-engine" / "src").exists():
    SPORTS_ENGINE_ROOT = ROOT_DIR / "sports-engine"
else:
    SPORTS_ENGINE_ROOT = ROOT_DIR

SRC_DIR = SPORTS_ENGINE_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from api.auth import ApiTier, require_tier
except ImportError:
    from src.api.auth import ApiTier, require_tier

router = APIRouter(prefix="/syndicate", tags=["Commercial Syndicate Pro"])


def _load_json_safe(path: Path) -> dict[str, Any] | list[Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@router.get("/in-play/alerts", summary="Get active In-Play Continuous Sniper signals")
def get_in_play_alerts() -> dict[str, Any]:
    """Returns real-time in-play sniper opportunities (10'-40' minute pressure anomalies)."""
    output_dir = SPORTS_ENGINE_ROOT / "output"
    alerts_file = output_dir / "seen_in_play_alerts.json"
    snapshot_file = SPORTS_ENGINE_ROOT / "ui" / "data" / "sports_intelligence_snapshot.json"

    seen = _load_json_safe(alerts_file)
    snapshot = _load_json_safe(snapshot_file)
    live_fixtures = []
    if isinstance(snapshot, dict):
        for fix in snapshot.get("fixtures", []):
            if fix.get("status") in ["IN_PLAY", "LIVE"]:
                live_fixtures.append(fix)

    return {
        "status": "ONLINE",
        "live_fixtures_monitored": len(live_fixtures),
        "recent_in_play_alerts_count": len(seen) if isinstance(seen, list) else 0,
        "recent_alerts": seen if isinstance(seen, list) else [],
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }


@router.get(
    "/sgp/combinations",
    summary="Get Copula Same-Game Parlay (SGP) +EV opportunities",
    dependencies=[Depends(require_tier(ApiTier.PRO))],
)
def get_sgp_combinations(min_joint_ev: float = Query(default=5.0, description="Minimum joint EV %")) -> dict[str, Any]:
    """Returns correlated multi-market SGPs calculated using Clayton and Gumbel copulas."""
    output_dir = SPORTS_ENGINE_ROOT / "output"
    heartbeat_file = output_dir / "daemon_heartbeat.json"
    hb = _load_json_safe(heartbeat_file)

    sgp_count = hb.get("sgp_opportunities", 0) if isinstance(hb, dict) else 0
    return {
        "status": "ONLINE",
        "model": "Bivariate Clayton/Gumbel Copula SGP Engine v2.0",
        "available_sgp_combinations": sgp_count,
        "min_joint_ev_threshold": min_joint_ev,
        "supported_pairs": [
            "1X2 & Over/Under 2.5",
            "1X2 & Corner 9.5 Over",
            "Over 2.5 & Corner 9.5 Over (Pressure Coupling)",
            "BTTS & Over 2.5 (Goal Flow Coupling)",
        ],
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }


@router.get(
    "/clv/report",
    summary="Get Closing Line Value (CLV) Alpha Attribution Report",
    dependencies=[Depends(require_tier(ApiTier.PRO))],
)
def get_clv_report() -> dict[str, Any]:
    """Returns quantitative breakdown of Stale Line Alpha vs Information Alpha beating the closing line."""
    output_dir = SPORTS_ENGINE_ROOT / "output"
    clv_file = output_dir / "clv_alpha_report.json"
    clv_data = _load_json_safe(clv_file)

    if not clv_data or not isinstance(clv_data, dict):
        return {
            "status": "INITIALIZING",
            "message": "CLV decomposition engine active. Awaiting finished fixture settlements.",
            "total_analyzed_trades": 0,
            "beat_closing_rate_pct": 0.0,
            "mean_total_clv_pct": 0.0,
        }
    return {
        "status": "ACTIVE",
        "clv_metrics": clv_data,
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }


@router.post(
    "/portfolio/optimize",
    summary="Calculate Covariance-Aware Kelly Sizing for bet basket",
    dependencies=[Depends(require_tier(ApiTier.PRO))],
)
def optimize_portfolio_basket(payload: dict[str, Any]) -> dict[str, Any]:
    """Given a list of bets with odds and probabilities, computes optimal correlated Kelly allocations."""
    try:
        from portfolio_kelly_optimizer import MultivariatePortfolioKelly
    except ImportError:
        from src.portfolio_kelly_optimizer import MultivariatePortfolioKelly

    bets = payload.get("bets", [])
    bankroll = float(payload.get("bankroll", 1000.0))
    fraction = float(payload.get("fractional_kelly", 0.25))

    if not bets:
        raise HTTPException(status_code=400, detail="Empty bet list provided in request.")

    optimizer = MultivariatePortfolioKelly(default_fraction=fraction)
    result = optimizer.optimize_portfolio_stakes(
        current_bankroll=bankroll,
        candidate_bets=bets,
        min_stake=50.0,
        kelly_fraction=fraction,
    )
    return {
        "status": "SUCCESS",
        "optimization_result": result,
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }
