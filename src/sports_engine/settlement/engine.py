"""TASK-020: Prediction Settlement Engine Orchestrator.

Loads immutable predictions, resolves real match results, evaluates market settlements,
computes flat-stake ROI, protects against duplicate settlements (idempotent ledger),
and emits performance metrics artifacts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sports_engine.settlement.domain import (
    MatchResult,
    MatchStatus,
    SettlementRecord,
    SettlementStatus,
)
from sports_engine.settlement.metrics import aggregate_settlement_metrics
from sports_engine.settlement.resolver import ScoreResolver
from sports_engine.settlement.rules import (
    calculate_flat_stake_profit,
    evaluate_selection_settlement,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def make_settlement_id(event_id: str, market: str, selection: str, bookmaker: str) -> str:
    """Generate deterministic unique ID for an individual prediction settlement."""
    raw = f"{event_id}|{market}|{selection}|{bookmaker}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class PredictionSettlementEngine:
    """Orchestrates prediction settlement and real performance tracking."""

    def __init__(
        self,
        predictions_path: Path | None = None,
        performance_dir: Path | None = None,
        score_resolver: ScoreResolver | None = None,
    ):
        self.predictions_path = predictions_path or (PROJECT_ROOT / "artifacts" / "predictions" / "TASK-019" / "predictions.json")
        self.performance_dir = performance_dir or (PROJECT_ROOT / "artifacts" / "performance")
        self.performance_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.performance_dir / "TASK-020-settlement-ledger.json"
        self.resolver = score_resolver or ScoreResolver()
        self.settlement_ledger: dict[str, dict[str, Any]] = self._load_ledger()

    def _load_ledger(self) -> dict[str, dict[str, Any]]:
        if self.ledger_path.exists():
            try:
                with open(self.ledger_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_ledger(self) -> None:
        with open(self.ledger_path, "w", encoding="utf-8") as f:
            json.dump(self.settlement_ledger, f, indent=2, ensure_ascii=False)

    def run_settlement(
        self,
        manual_results_override: dict[str, MatchResult] | None = None,
        now_dt: datetime | None = None,
    ) -> dict[str, Any]:
        """Execute settlement across all predictions in the active snapshot."""
        now = now_dt or datetime.now(UTC)
        now_iso = now.isoformat()

        if not self.predictions_path.exists():
            raise FileNotFoundError(f"Prediction file not found: {self.predictions_path}")

        with open(self.predictions_path, encoding="utf-8") as f:
            pred_data = json.load(f)

        predictions_list = pred_data.get("predictions", [])
        all_settlement_records: list[SettlementRecord] = []
        resolved_matches: dict[str, MatchResult] = {}
        sports_to_check = ["soccer_epl", "soccer_turkey_super_lig", "soccer_uefa_nations_league"]

        # 1. Resolve match results per fixture
        for p in predictions_list:
            eid = p.get("event_id", "")
            h_team = p.get("home_team", "")
            a_team = p.get("away_team", "")
            kickoff = p.get("kickoff", "")
            fixture_name = p.get("fixture", f"{h_team} vs {a_team}")

            # Check manual override (for testing or confirmed external feeds)
            if manual_results_override and (eid in manual_results_override or fixture_name in manual_results_override):
                m_res = manual_results_override.get(eid) or manual_results_override.get(fixture_name)
            else:
                m_res = self.resolver.resolve_match_result(
                    event_id=eid,
                    provider_event_id=None,
                    home_team=h_team,
                    away_team=a_team,
                    kickoff_iso=kickoff,
                    sports=sports_to_check,
                    now_dt=now,
                )

            resolved_matches[eid] = m_res

            # 2. Evaluate all selections for this event
            selections = p.get("selections", [])
            for sel_obj in selections:
                mkt = sel_obj.get("market", "")
                sel_name = sel_obj.get("selection", "")
                bm = sel_obj.get("bookmaker", "")
                bm_odds = float(sel_obj.get("bookmaker_odds", 1.0))
                m_prob = float(sel_obj.get("model_probability", 0.0))
                m_fair = float(sel_obj.get("model_fair_odds", 0.0))
                m_ev = float(sel_obj.get("expected_value_percent", 0.0))
                comp = p.get("competition", "")

                sid = make_settlement_id(eid, mkt, sel_name, bm)

                # Check if already settled in ledger (Idempotency)
                existing = self.settlement_ledger.get(sid)
                if existing and existing.get("status") in (
                    SettlementStatus.WON.value,
                    SettlementStatus.LOST.value,
                    SettlementStatus.PUSH.value,
                ):
                    rec = SettlementRecord(
                        settlement_id=sid,
                        event_id=eid,
                        match=fixture_name,
                        competition=comp,
                        kickoff=kickoff,
                        market=mkt,
                        selection=sel_name,
                        bookmaker=bm,
                        bookmaker_odds=bm_odds,
                        model_probability=m_prob,
                        model_fair_odds=m_fair,
                        model_ev_percent=m_ev,
                        status=SettlementStatus(existing["status"]),
                        final_score=existing.get("final_score"),
                        halftime_score=existing.get("halftime_score"),
                        stake=float(existing.get("stake", 1.0)),
                        profit=float(existing.get("profit", 0.0)),
                        realized_roi_percent=float(existing.get("realized_roi_percent", 0.0)),
                        result_source=existing.get("result_source", "LEDGER_PRIOR_SETTLEMENT"),
                        settled_at=existing.get("settled_at", now_iso),
                        notes=existing.get("notes"),
                    )
                    all_settlement_records.append(rec)
                    continue

                # Settle using rules
                is_finished = m_res.status == MatchStatus.FINISHED
                h_score = m_res.home_score
                a_score = m_res.away_score
                ht_h_score = m_res.ht_home_score
                ht_a_score = m_res.ht_away_score

                status = evaluate_selection_settlement(
                    market=mkt,
                    selection=sel_name,
                    home_team=h_team,
                    away_team=a_team,
                    home_score=h_score,
                    away_score=a_score,
                    ht_home_score=ht_h_score,
                    ht_away_score=ht_a_score,
                    is_finished=is_finished,
                )

                profit, roi_pct = calculate_flat_stake_profit(bm_odds, status, stake=1.0)

                rec = SettlementRecord(
                    settlement_id=sid,
                    event_id=eid,
                    match=fixture_name,
                    competition=comp,
                    kickoff=kickoff,
                    market=mkt,
                    selection=sel_name,
                    bookmaker=bm,
                    bookmaker_odds=bm_odds,
                    model_probability=m_prob,
                    model_fair_odds=m_fair,
                    model_ev_percent=m_ev,
                    status=status,
                    final_score=m_res.final_score_str,
                    halftime_score=m_res.ht_score_str,
                    stake=1.0,
                    profit=profit,
                    realized_roi_percent=roi_pct,
                    result_source=m_res.result_source,
                    settled_at=now_iso,
                    notes=f"Evaluated against {m_res.result_source}",
                )

                all_settlement_records.append(rec)
                self.settlement_ledger[sid] = asdict(rec)

        # 3. Save updated ledger (Idempotent)
        self._save_ledger()

        # 4. Compute performance metrics
        metrics = aggregate_settlement_metrics(all_settlement_records)

        # 5. Build final payload
        payload = {
            "task_id": "TASK-020",
            "run_id": f"settlement_{now.strftime('%Y%m%d_%H%M%S')}",
            "generated_at": now_iso,
            "predictions_source": str(self.predictions_path),
            "total_predictions_evaluated": len(all_settlement_records),
            "fixtures_summary": {
                "total_fixtures": len(resolved_matches),
                "finished_fixtures": sum(1 for m in resolved_matches.values() if m.status == MatchStatus.FINISHED),
                "upcoming_fixtures": sum(1 for m in resolved_matches.values() if m.status == MatchStatus.UPCOMING),
                "unresolved_fixtures": sum(1 for m in resolved_matches.values() if m.status == MatchStatus.UNKNOWN),
            },
            "performance": metrics,
            "settlements_sample": [asdict(r) for r in all_settlement_records[:50]],
        }

        # 6. Save performance JSON artifact
        perf_file = self.performance_dir / "TASK-020-performance.json"
        with open(perf_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        return payload
