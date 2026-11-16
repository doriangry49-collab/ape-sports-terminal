"""Signals and Ledger API endpoints."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter

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
    from api.schemas import ActiveSignalsResponse, LedgerSummaryResponse, ValueSignalSchema
    from paper_trader import PaperTradingEngine
except ImportError:
    from src.api.schemas import ActiveSignalsResponse, LedgerSummaryResponse, ValueSignalSchema
    from src.paper_trader import PaperTradingEngine

router = APIRouter(prefix="/signals", tags=["Signals & Ledger"])


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "UNKNOWN" or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


@router.get(
    "/active",
    response_model=ActiveSignalsResponse,
    summary="Get active real-time +EV value betting signals",
)
def api_get_active_signals(min_edge: float = 3.0) -> ActiveSignalsResponse:
    """Returns all current positive expected value opportunities passing Shin devigging

    and Kelly criterion thresholds.
    """
    snapshot_file = SPORTS_ENGINE_ROOT / "ui" / "data" / "sports_intelligence_snapshot.json"
    if not snapshot_file.exists() and (ROOT_DIR / "ui" / "data" / "sports_intelligence_snapshot.json").exists():
        snapshot_file = ROOT_DIR / "ui" / "data" / "sports_intelligence_snapshot.json"
    elif not snapshot_file.exists() and (ROOT_DIR / "sports-engine" / "ui" / "data" / "sports_intelligence_snapshot.json").exists():
        snapshot_file = ROOT_DIR / "sports-engine" / "ui" / "data" / "sports_intelligence_snapshot.json"

    items: list[ValueSignalSchema] = []

    if snapshot_file.exists():
        try:
            data = json.loads(snapshot_file.read_text(encoding="utf-8"))
            fixtures = data.get("fixtures", []) if isinstance(data, dict) else []
            for f in fixtures:
                if not isinstance(f, dict):
                    continue
                for e in f.get("edges", []):
                    if not isinstance(e, dict):
                        continue
                    try:
                        edge_raw = e.get("edge_pct")
                        if edge_raw is None:
                            edge_val = _safe_float(e.get("raw_edge"), 0.0) * 100.0
                        else:
                            edge_val = _safe_float(edge_raw, 0.0)

                        ev_roi = _safe_float(e.get("ev_roi"), edge_val)
                        if ev_roi >= min_edge:
                            items.append(
                                ValueSignalSchema(
                                    fixture_id=str(f.get("fixture_id", "")),
                                    league=str(f.get("competition", "")),
                                    home_team=str(f.get("home_team", "")),
                                    away_team=str(f.get("away_team", "")),
                                    kickoff_trt=str(e.get("kickoff_trt", f.get("kickoff_trt", "TBD"))),
                                    market=str(e.get("market", "1X2")),
                                    selection=str(e.get("selection_display", e.get("selection", ""))),
                                    bookmaker=str(e.get("bookmaker", "NESINE")),
                                    offered_odds=_safe_float(e.get("entry_odds"), 0.0),
                                    fair_odds_shin=_safe_float(e.get("fair_odds_shin"), _safe_float(e.get("market_fair_odds"), 0.0)),
                                    fair_prob_shin=_safe_float(e.get("market_no_vig"), 0.0),
                                    model_prob=_safe_float(e.get("model_prob"), 0.0),
                                    edge_pct=round(edge_val, 2),
                                    ev_roi=round(ev_roi, 2),
                                    half_kelly=_safe_float(e.get("half_kelly"), 0.0),
                                    shin_margin=_safe_float(e.get("shin_margin"), 5.0),
                                )
                            )
                    except Exception:
                        continue
        except Exception:
            pass

    return ActiveSignalsResponse(
        count=len(items),
        signals=items,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/ledger",
    response_model=LedgerSummaryResponse,
    summary="Get verified paper-trading track record and PnL metrics",
)
def api_get_ledger_summary() -> LedgerSummaryResponse:
    """Returns official paper trading performance: total bets, settled win rate,

    net PnL units, ROI, and CLV beat ratio.
    """
    engine = PaperTradingEngine()
    summary = engine.compute_summary()

    return LedgerSummaryResponse(
        total_bets=int(summary.get("total_signals", 0)),
        pending_bets=int(summary.get("pending_count", 0)),
        settled_bets=int(summary.get("settled_count", 0)),
        won_bets=int(summary.get("won_count", 0)),
        win_rate_pct=float(summary.get("win_rate_pct", 0.0)),
        net_units=float(summary.get("net_units", 0.0)),
        roi_pct=float(summary.get("roi_pct", 0.0)),
        avg_clv_ratio=float(summary.get("avg_clv_ratio", 1.0)),
        beat_clv_pct=float(summary.get("beat_clv_pct", 0.0)),
    )
