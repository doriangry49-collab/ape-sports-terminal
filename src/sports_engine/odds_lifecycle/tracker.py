"""TASK-021: Multi-Snapshot Odds Tracker & Prediction Lifecycle Engine.

Tracks the full temporal lifecycle of predictions:
1. Captures and links multiple pre-match odds snapshots across time.
2. Computes line movements (delta, pct_change, SHORTENED, DRIFTED, STABLE).
3. Evaluates preliminary Closing Line Value (CLV ratio: initial_odds / last_prematch_odds).
4. Strictly distinguishes LAST_PREMATCH_SNAPSHOT from official closing odds (no synthetic claims).
5. Maintains idempotent lifecycle ledger and generates performance-ready metadata.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

from sports_engine.adapters.propline_adapter import normalize_propline_event
from sports_engine.adapters.schema import NormalizedOddsRecord
from sports_engine.odds_lifecycle.domain import (
    KickoffProximity,
    LifecycleState,
    MovementDirection,
    OddsMovementSummary,
    SelectionLifecycleRecord,
    SnapshotPoint,
    calculate_kickoff_proximity,
)
from sports_engine.storage.historical_odds_archive import (
    HistoricalOddsArchive,
    HistoricalOddsRecord,
    ProvenanceType,
    SnapshotLabel,
    make_snapshot_id,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def make_lifecycle_id(event_id: str, market: str, selection: str, bookmaker: str) -> str:
    """Generate deterministic ID for a specific selection lifecycle."""
    raw = f"{event_id}|{market}|{selection}|{bookmaker}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class OddsLifecycleTracker:
    """Manages multi-snapshot odds tracking and prediction lifecycles."""

    def __init__(
        self,
        predictions_path: Optional[Path] = None,
        movement_dir: Optional[Path] = None,
        propline_key: Optional[str] = None,
    ):
        self.predictions_path = predictions_path or (
            PROJECT_ROOT / "artifacts" / "predictions" / "TASK-019" / "predictions.json"
        )
        self.movement_dir = movement_dir or (PROJECT_ROOT / "artifacts" / "odds" / "TASK-021-movement")
        self.movement_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir = self.movement_dir / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.movement_dir / "lifecycle_ledger.json"
        self.propline_key = propline_key or os.getenv("PROPLINE_KEY")
        self.ledger: dict[str, dict[str, Any]] = self._load_ledger()
        self.archive = HistoricalOddsArchive(PROJECT_ROOT / "artifacts" / "odds" / "historical")

    def _load_ledger(self) -> dict[str, dict[str, Any]]:
        if self.ledger_path.exists():
            try:
                with open(self.ledger_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_ledger(self) -> None:
        with open(self.ledger_path, "w", encoding="utf-8") as f:
            json.dump(self.ledger, f, indent=2, ensure_ascii=False)

    def capture_live_odds_for_predicted_events(
        self,
        predicted_fixtures: list[dict[str, Any]],
        captured_at: datetime,
    ) -> list[NormalizedOddsRecord]:
        """Fetch fresh live odds specifically for active predicted fixtures."""
        if not self.propline_key:
            return []

        fresh_records: list[NormalizedOddsRecord] = []
        headers = {"x-api-key": self.propline_key}

        # Map by source_event_id / canonical event_id
        with httpx.Client(timeout=15.0) as client:
            for p in predicted_fixtures[:10]:  # focus on top fixtures for fast capture
                eid = p.get("event_id", "")
                comp = p.get("competition", "")
                sport_key = "soccer_epl" if "Premier" in comp else ("soccer_turkey_super_lig" if "Süper" in comp else "soccer_uefa_nations_league")
                h_team = p.get("home_team", "")
                a_team = p.get("away_team", "")
                commence = p.get("kickoff")

                # Extract raw numeric source ID if available in event_id
                source_id = eid.split("_")[-1] if "_" in eid else eid
                if not source_id.isdigit():
                    continue

                try:
                    r = client.get(
                        f"https://api.prop-line.com/v1/sports/{sport_key}/events/{source_id}/odds",
                        headers=headers,
                        params={"markets": "h2h,totals,correct_score", "regions": "eu,us"},
                    )
                    if r.status_code == 200:
                        d_odds = r.json()
                        d_odds["id"] = source_id
                        d_odds["home_team"] = h_team
                        d_odds["away_team"] = a_team
                        d_odds["commence_time"] = commence
                        norm_res = normalize_propline_event(
                            d_odds, sport_key, comp, "International", captured_at
                        )
                        fresh_records.extend(norm_res.accepted)
                except Exception:
                    pass

        return fresh_records

    def track_lifecycle(
        self,
        fresh_odds_records: Optional[list[NormalizedOddsRecord]] = None,
        simulated_time_series: Optional[dict[str, list[dict[str, Any]]]] = None,
        now_dt: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Execute lifecycle tracking across active predictions."""
        now = now_dt or datetime.now(UTC)
        now_iso = now.isoformat()
        snapshot_id = f"snapshot_{now.strftime('%Y%m%d_%H%M%S')}"

        if not self.predictions_path.exists():
            raise FileNotFoundError(f"Prediction file not found: {self.predictions_path}")

        with open(self.predictions_path, "r", encoding="utf-8") as f:
            pred_payload = json.load(f)

        predictions_list = pred_payload.get("predictions", [])

        # Index fresh odds if available: (event_id, market, selection, bookmaker) -> odds
        fresh_odds_index: dict[tuple[str, str, str, str], float] = {}
        if fresh_odds_records:
            for r in fresh_odds_records:
                fresh_odds_index[(r.event_id, r.market, r.selection, r.bookmaker)] = r.odds_decimal

        updated_records: list[SelectionLifecycleRecord] = []
        hist_records_to_archive: list[HistoricalOddsRecord] = []

        for p in predictions_list:
            eid = p.get("event_id", "")
            fixture = p.get("fixture", "")
            comp = p.get("competition", "")
            kickoff = p.get("kickoff", "")
            selections = p.get("selections", [])

            for sel in selections:
                mkt = sel.get("market", "")
                sel_name = sel.get("selection", "")
                bm = sel.get("bookmaker", "")
                init_odds = float(sel.get("bookmaker_odds", 1.0))
                m_prob = float(sel.get("model_probability", 0.0))
                m_fair = float(sel.get("model_fair_odds", 0.0))
                m_ev = float(sel.get("expected_value_percent", 0.0))

                lid = make_lifecycle_id(eid, mkt, sel_name, bm)
                existing = self.ledger.get(lid)

                # Initialize or retrieve timeline
                timeline: list[SnapshotPoint] = []
                if existing and "snapshots_timeline" in existing:
                    for pt in existing["snapshots_timeline"]:
                        timeline.append(
                            SnapshotPoint(
                                snapshot_id=pt["snapshot_id"],
                                timestamp=pt["timestamp"],
                                odds=float(pt["odds"]),
                                implied_probability=float(pt["implied_probability"]),
                                proximity=KickoffProximity(pt["proximity"]),
                            )
                        )
                else:
                    # Initial prediction snapshot point
                    init_ts = sel.get("prediction_timestamp", now_iso)
                    init_prox = calculate_kickoff_proximity(kickoff, datetime.fromisoformat(init_ts.replace("Z", "+00:00")))
                    timeline.append(
                        SnapshotPoint(
                            snapshot_id=f"init_{eid[:12]}",
                            timestamp=init_ts,
                            odds=init_odds,
                            implied_probability=round(1.0 / init_odds, 4) if init_odds > 0 else 0.0,
                            proximity=init_prox,
                        )
                    )

                # Check if simulated time series provided
                sim_points = simulated_time_series.get(lid, []) if simulated_time_series else []
                for sp in sim_points:
                    s_ts = sp["timestamp"]
                    s_odds = float(sp["odds"])
                    s_prox = calculate_kickoff_proximity(kickoff, datetime.fromisoformat(s_ts.replace("Z", "+00:00")))
                    timeline.append(
                        SnapshotPoint(
                            snapshot_id=sp.get("snapshot_id", f"sim_{s_ts[:19]}"),
                            timestamp=s_ts,
                            odds=s_odds,
                            implied_probability=round(1.0 / s_odds, 4) if s_odds > 0 else 0.0,
                            proximity=s_prox,
                        )
                    )

                # Check if fresh live odds captured
                fresh_odds = fresh_odds_index.get((eid, mkt, sel_name, bm))
                if fresh_odds and fresh_odds > 1.0:
                    f_prox = calculate_kickoff_proximity(kickoff, now)
                    timeline.append(
                        SnapshotPoint(
                            snapshot_id=snapshot_id,
                            timestamp=now_iso,
                            odds=fresh_odds,
                            implied_probability=round(1.0 / fresh_odds, 4),
                            proximity=f_prox,
                        )
                    )

                # Sort timeline chronologically
                timeline.sort(key=lambda x: x.timestamp)

                # Compute line movement
                o_first = timeline[0].odds
                o_latest = timeline[-1].odds
                p_first = timeline[0].implied_probability
                p_latest = timeline[-1].implied_probability

                # Last prematch snapshot (latest snapshot prior to kickoff)
                last_prematch_pt = timeline[-1]
                for pt in reversed(timeline):
                    if pt.proximity != KickoffProximity.POST_KICKOFF:
                        last_prematch_pt = pt
                        break
                o_last_prematch = last_prematch_pt.odds

                delta_o = round(o_latest - o_first, 4)
                pct_chg = round((delta_o / o_first) * 100.0, 2) if o_first > 0 else 0.0
                delta_p = round(p_latest - p_first, 4)

                if abs(pct_chg) >= 5.0:
                    direction = MovementDirection.SIGNIFICANT_MOVE
                    is_sig = True
                elif delta_o < -0.01 and abs(pct_chg) >= 1.0:
                    direction = MovementDirection.SHORTENED
                    is_sig = False
                elif delta_o > 0.01 and abs(pct_chg) >= 1.0:
                    direction = MovementDirection.DRIFTED
                    is_sig = False
                else:
                    direction = MovementDirection.STABLE
                    is_sig = False

                # Preliminary CLV ratio: O_first / O_last_prematch
                # E.g. If initial odds were 8.25 and market dropped to 7.50 -> CLV ratio = 1.10 (Beat the closing market!)
                clv_ratio = round(o_first / o_last_prematch, 4) if o_last_prematch > 0 else 1.0

                current_prox = calculate_kickoff_proximity(kickoff, now)

                # Determine lifecycle state
                if current_prox == KickoffProximity.POST_KICKOFF:
                    state = LifecycleState.KICKOFF_PASSED
                elif current_prox in (KickoffProximity.T_1H, KickoffProximity.T_2H):
                    state = LifecycleState.LAST_PREMATCH_CAPTURED
                elif len(timeline) > 1:
                    state = LifecycleState.SNAPSHOT_TRACKED
                else:
                    state = LifecycleState.PREDICTED

                movement = OddsMovementSummary(
                    initial_odds=o_first,
                    latest_odds=o_latest,
                    last_prematch_odds=o_last_prematch,
                    delta_odds=delta_o,
                    pct_change=pct_chg,
                    initial_implied_prob=p_first,
                    latest_implied_prob=p_latest,
                    delta_implied_prob=delta_p,
                    direction=direction,
                    is_significant=is_sig,
                    snapshots_count=len(timeline),
                    preliminary_clv_ratio=clv_ratio,
                    clv_label="PRE_CLOSING_LINE_VALUE",
                )

                rec = SelectionLifecycleRecord(
                    lifecycle_id=lid,
                    event_id=eid,
                    fixture=fixture,
                    competition=comp,
                    kickoff=kickoff,
                    market=mkt,
                    selection=sel_name,
                    bookmaker=bm,
                    model_probability=m_prob,
                    model_fair_odds=m_fair,
                    model_ev_percent=m_ev,
                    lifecycle_state=state,
                    kickoff_proximity=current_prox,
                    movement=movement,
                    snapshots_timeline=timeline,
                    last_updated=now_iso,
                )

                updated_records.append(rec)
                self.ledger[lid] = asdict(rec)

        # Save updated ledger
        self._save_ledger()

        # Compute aggregate movement statistics
        total_tracked = len(updated_records)
        shortened = sum(1 for r in updated_records if r.movement.direction in (MovementDirection.SHORTENED, MovementDirection.SIGNIFICANT_MOVE) and r.movement.delta_odds < 0)
        drifted = sum(1 for r in updated_records if r.movement.direction in (MovementDirection.DRIFTED, MovementDirection.SIGNIFICANT_MOVE) and r.movement.delta_odds > 0)
        stable = sum(1 for r in updated_records if r.movement.direction == MovementDirection.STABLE)
        sig_moves = sum(1 for r in updated_records if r.movement.is_significant)

        # Value candidates CLV beat rate (do positive EV picks beat closing line?)
        val_picks = [r for r in updated_records if r.model_ev_percent > 0]
        val_clv_beat = sum(1 for r in val_picks if r.movement.preliminary_clv_ratio > 1.0)
        val_clv_beat_pct = round((val_clv_beat / len(val_picks)) * 100.0, 2) if val_picks else 0.0

        payload = {
            "task_id": "TASK-021",
            "run_id": f"movement_{now.strftime('%Y%m%d_%H%M%S')}",
            "generated_at": now_iso,
            "predictions_source": str(self.predictions_path),
            "summary": {
                "total_selections_tracked": total_tracked,
                "multi_snapshot_selections": sum(1 for r in updated_records if r.movement.snapshots_count > 1),
                "shortened_count": shortened,
                "drifted_count": drifted,
                "stable_count": stable,
                "significant_moves_count": sig_moves,
                "value_candidates_tracked": len(val_picks),
                "value_candidates_beat_closing_market": val_clv_beat,
                "value_clv_beat_rate_percent": val_clv_beat_pct,
                "clv_standard_note": "CLV ratio = initial_odds / last_prematch_odds. Strict rule: never claim last prematch snapshot is official confirmed closing odds.",
            },
            "top_shortened_selections": [
                asdict(r) for r in sorted(updated_records, key=lambda x: x.movement.pct_change)[:15]
            ],
            "top_drifted_selections": [
                asdict(r) for r in sorted(updated_records, key=lambda x: x.movement.pct_change, reverse=True)[:15]
            ],
            "sample_lifecycle_records": [asdict(r) for r in updated_records[:30]],
        }

        # Save movement snapshot & JSON artifact
        json_out = self.movement_dir / "TASK-021-lifecycle.json"
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        return payload
