"""TASK-022: Out-Of-Sample (OOS) Performance Auditor.

Rigorous scientific performance evaluation for settled model predictions:
1. Multi-segment ROI & win rate analysis (EV bands, Odds bands, Market types, CLV movement alignment).
2. Independent event clustering (treats correlated selections in 1 match as 1 observation cluster).
3. Sample size sufficiency enforcement (INSUFFICIENT_SAMPLE for underpowered segments).
4. Model C vs Market Baseline benchmark (Brier Score, Log Loss comparison).
5. Zero synthetic results, zero continuous daemons, strict predictions immutability.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sports_engine.oos_audit.domain import (
    AuditStatus,
    ConfidenceTier,
    OOSAuditReport,
    SegmentAuditResult,
    SegmentStatus,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def compute_binary_metrics(
    eval_records: list[dict[str, Any]],
) -> tuple[float | None, float | None, float | None, float | None]:
    """Compute Brier Score and Log Loss for Model C vs Market Implied.

    y = 1 if WON, y = 0 if LOST. PUSH/VOID excluded.
    Returns: (model_brier, market_brier, model_log_loss, market_log_loss)
    """
    valid_points: list[tuple[float, float, int]] = []
    for r in eval_records:
        st = r.get("status", "")
        if st == "WON":
            y = 1
        elif st == "LOST":
            y = 0
        else:
            continue

        p_mod = float(r.get("model_probability", 0.0))
        odds = float(r.get("bookmaker_odds", 1.0))
        p_mkt = (1.0 / odds) if odds > 1.0 else 0.0

        p_mod_clamped = max(1e-5, min(1.0 - 1e-5, p_mod))
        p_mkt_clamped = max(1e-5, min(1.0 - 1e-5, p_mkt))

        valid_points.append((p_mod_clamped, p_mkt_clamped, y))

    if not valid_points:
        return None, None, None, None

    n = len(valid_points)
    mod_brier = sum((p_m - y) ** 2 for p_m, _, y in valid_points) / n
    mkt_brier = sum((p_k - y) ** 2 for _, p_k, y in valid_points) / n

    mod_ll = -sum(y * math.log(p_m) + (1 - y) * math.log(1.0 - p_m) for p_m, _, y in valid_points) / n
    mkt_ll = -sum(y * math.log(p_k) + (1 - y) * math.log(1.0 - p_k) for _, p_k, y in valid_points) / n

    return (
        round(mod_brier, 4),
        round(mkt_brier, 4),
        round(mod_ll, 4),
        round(mkt_ll, 4),
    )


class OOSPerformanceAuditor:
    """Evaluates Out-Of-Sample prediction performance across segments."""

    def __init__(
        self,
        settlement_ledger_path: Path | None = None,
        lifecycle_ledger_path: Path | None = None,
        min_independent_events_threshold: int = 10,
    ):
        self.settlement_ledger_path = settlement_ledger_path or (
            PROJECT_ROOT / "artifacts" / "performance" / "TASK-020-settlement-ledger.json"
        )
        self.lifecycle_ledger_path = lifecycle_ledger_path or (
            PROJECT_ROOT / "artifacts" / "odds" / "TASK-021-movement" / "lifecycle_ledger.json"
        )
        self.min_events_threshold = min_independent_events_threshold

    def _load_json(self, path: Path) -> dict[str, Any]:
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def audit(
        self,
        settled_records_override: list[dict[str, Any]] | None = None,
        lifecycle_ledger_override: dict[str, Any] | None = None,
    ) -> OOSAuditReport:
        """Execute full OOS performance audit across all segments."""
        now_iso = datetime.now(UTC).isoformat()

        # Load settlement records
        if settled_records_override is not None:
            raw_settlement_data = {f"rec_{i}": r for i, r in enumerate(settled_records_override)}
        else:
            raw_settlement_data = self._load_json(self.settlement_ledger_path)

        # Load lifecycle ledger (for pre-closing movement direction)
        lifecycle_data = lifecycle_ledger_override if lifecycle_ledger_override is not None else self._load_json(self.lifecycle_ledger_path)

        all_records = list(raw_settlement_data.values())
        settled_records = [r for r in all_records if r.get("status") in ("WON", "LOST", "PUSH")]
        pending_records = [r for r in all_records if r.get("status") == "PENDING"]

        total_records = len(all_records)
        total_settled = len(settled_records)
        total_pending = len(pending_records)

        unique_fixtures = {r.get("event_id") for r in all_records if r.get("event_id")}
        unique_settled_fixtures = {r.get("event_id") for r in settled_records if r.get("event_id")}

        # Determine overall audit status
        if total_settled == 0:
            audit_status = AuditStatus.AWAITING_KICKOFF_AND_SETTLEMENT
        elif total_pending > 0:
            audit_status = AuditStatus.PARTIAL_SETTLEMENT
        else:
            audit_status = AuditStatus.COMPLETE_SETTLEMENT

        # Define segments to evaluate
        def has_movement_dir(rec: dict[str, Any], direction: str) -> bool:
            # Match via lifecycle_id or (event_id, market, selection, bookmaker)
            eid = rec.get("event_id", "")
            mkt = rec.get("market", "")
            sel = rec.get("selection", "")
            bm = rec.get("bookmaker", "")
            for l_rec in lifecycle_data.values():
                if (
                    l_rec.get("event_id") == eid
                    and l_rec.get("market") == mkt
                    and l_rec.get("selection") == sel
                    and l_rec.get("bookmaker") == bm
                ):
                    mov = l_rec.get("movement", {})
                    d = mov.get("direction", "")
                    if direction == "SHORTENED" and (d == "SHORTENED" or (d == "SIGNIFICANT" and mov.get("delta_odds", 0) < 0)):
                        return True
                    if direction == "DRIFTED" and (d == "DRIFTED" or (d == "SIGNIFICANT" and mov.get("delta_odds", 0) > 0)):
                        return True
            return False

        segment_definitions: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
            ("All Selections", lambda r: True),
            ("EV > 0%", lambda r: float(r.get("model_ev_percent", 0.0)) > 0.0),
            ("EV > 5%", lambda r: float(r.get("model_ev_percent", 0.0)) > 5.0),
            ("EV > 10%", lambda r: float(r.get("model_ev_percent", 0.0)) > 10.0),
            ("EV > 20%", lambda r: float(r.get("model_ev_percent", 0.0)) > 20.0),
            ("Odds >= 2.0", lambda r: float(r.get("bookmaker_odds", 1.0)) >= 2.0),
            ("Odds >= 5.0", lambda r: float(r.get("bookmaker_odds", 1.0)) >= 5.0),
            ("Odds >= 10.0", lambda r: float(r.get("bookmaker_odds", 1.0)) >= 10.0),
            ("Odds >= 20.0", lambda r: float(r.get("bookmaker_odds", 1.0)) >= 20.0),
            ("Odds >= 50.0", lambda r: float(r.get("bookmaker_odds", 1.0)) >= 50.0),
            ("Odds >= 100.0", lambda r: float(r.get("bookmaker_odds", 1.0)) >= 100.0),
            ("Market: 1X2", lambda r: r.get("market", "").lower() in ("1x2", "h2h")),
            ("Market: Correct Score", lambda r: "correct" in r.get("market", "").lower()),
            ("Market: Totals", lambda r: "totals" in r.get("market", "").lower()),
            ("Market: BTTS", lambda r: "btts" in r.get("market", "").lower()),
            ("Market: HT 1X2", lambda r: "halftime" in r.get("market", "").lower() or "ht 1x2" in r.get("market", "").lower()),
            ("Market: HT/FT", lambda r: "ht/ft" in r.get("market", "").lower() or "ht_ft" in r.get("market", "").lower()),
            (
                "Model EV > 0 & Pre-Closing Shortened",
                lambda r: float(r.get("model_ev_percent", 0.0)) > 0.0 and has_movement_dir(r, "SHORTENED"),
            ),
            (
                "Model EV > 0 & Pre-Closing Drifted",
                lambda r: float(r.get("model_ev_percent", 0.0)) > 0.0 and has_movement_dir(r, "DRIFTED"),
            ),
        ]

        evaluated_segments: dict[str, SegmentAuditResult] = {}

        for seg_name, predicate in segment_definitions:
            seg_records = [r for r in settled_records if predicate(r)]
            raw_n = len(seg_records)
            indep_events = len({r.get("event_id") for r in seg_records if r.get("event_id")})

            if raw_n == 0:
                evaluated_segments[seg_name] = SegmentAuditResult(
                    segment_name=seg_name,
                    status=SegmentStatus.NO_DATA,
                    notes="No settled selections in this segment.",
                )
                continue

            # Determine sample sufficiency & confidence tier based on INDEPENDENT events
            if indep_events < 10:
                seg_status = SegmentStatus.INSUFFICIENT_SAMPLE
                tier = ConfidenceTier.INSUFFICIENT
                note = f"Underpowered sample: {indep_events} independent events < threshold 10."
            elif indep_events < 50:
                seg_status = SegmentStatus.SUFFICIENT_SAMPLE
                tier = ConfidenceTier.EARLY_SIGNAL
                note = "Early signal only; reporting threshold reached but insufficient for model iteration."
            elif indep_events < 100:
                seg_status = SegmentStatus.SUFFICIENT_SAMPLE
                tier = ConfidenceTier.MODERATE
                note = "Moderate sample size; initial meaningful statistical signal."
            elif indep_events < 250:
                seg_status = SegmentStatus.SUFFICIENT_SAMPLE
                tier = ConfidenceTier.SIGNIFICANT
                note = "Significant sample size; solid foundation for calibration evaluation."
            else:
                seg_status = SegmentStatus.SUFFICIENT_SAMPLE
                tier = ConfidenceTier.HIGH_ODDS_ROBUST
                note = "Robust sample size (250+ matches); fully reliable for high odds / correct score iteration."

            won = sum(1 for r in seg_records if r.get("status") == "WON")
            lost = sum(1 for r in seg_records if r.get("status") == "LOST")
            push = sum(1 for r in seg_records if r.get("status") == "PUSH")
            win_rate = round((won / (won + lost + push)) * 100.0, 2) if (won + lost + push) > 0 else 0.0

            staked = sum(float(r.get("stake", 1.0)) for r in seg_records)
            profit = sum(float(r.get("profit", 0.0)) for r in seg_records)
            roi = round((profit / staked) * 100.0, 2) if staked > 0 else 0.0
            avg_ev = round(sum(float(r.get("model_ev_percent", 0.0)) for r in seg_records) / raw_n, 2)

            mod_brier, mkt_brier, mod_ll, mkt_ll = compute_binary_metrics(seg_records)
            brier_adv = round(mkt_brier - mod_brier, 4) if (mkt_brier is not None and mod_brier is not None) else None
            ll_adv = round(mkt_ll - mod_ll, 4) if (mkt_ll is not None and mod_ll is not None) else None

            evaluated_segments[seg_name] = SegmentAuditResult(
                segment_name=seg_name,
                status=seg_status,
                confidence_tier=tier,
                raw_selections_count=raw_n,
                independent_events_count=indep_events,
                won_count=won,
                lost_count=lost,
                push_count=push,
                win_rate_percent=win_rate,
                total_staked=round(staked, 2),
                total_profit=round(profit, 2),
                realized_roi_percent=roi,
                avg_model_ev_percent=avg_ev,
                model_brier_score=mod_brier,
                market_brier_score=mkt_brier,
                brier_advantage=brier_adv,
                model_log_loss=mod_ll,
                market_log_loss=mkt_ll,
                log_loss_advantage=ll_adv,
                notes=note,
            )

        # Generate summary findings
        findings: list[str] = []
        if audit_status == AuditStatus.AWAITING_KICKOFF_AND_SETTLEMENT:
            findings.append(
                f"STATUS: AWAITING KICKOFF & SETTLEMENT. All {total_pending} predictions across {len(unique_fixtures)} fixtures are pending real kickoff."
            )
            findings.append("Zero synthetic match scores generated (strict anti-fabrication enforcement).")
            findings.append("Scientific audit framework is ready to compute OOS metrics immediately once scores resolve.")
        else:
            findings.append(
                f"STATUS: {audit_status.value}. {total_settled} selections settled across {len(unique_settled_fixtures)} fixtures."
            )
            overall = evaluated_segments.get("All Selections")
            if overall and overall.status == SegmentStatus.SUFFICIENT_SAMPLE:
                findings.append(
                    f"Overall Realized ROI: {overall.realized_roi_percent}% across {overall.independent_events_count} independent fixtures."
                )
                if overall.brier_advantage is not None:
                    adv_str = "OUTPERFORMING" if overall.brier_advantage > 0 else "UNDERPERFORMING"
                    findings.append(
                        f"Model vs Market Brier Delta: {overall.brier_advantage:+.4f} ({adv_str} market baseline)."
                    )
            else:
                findings.append("Sample size currently below statistical threshold for reliable overall ROI inference.")

        report = OOSAuditReport(
            task_id="TASK-022",
            generated_at=now_iso,
            audit_status=audit_status,
            total_predictions_in_snapshot=total_records,
            total_settled_records=total_settled,
            total_pending_records=total_pending,
            unique_fixtures_count=len(unique_fixtures),
            unique_settled_fixtures_count=len(unique_settled_fixtures),
            min_independent_events_threshold=self.min_events_threshold,
            segments=evaluated_segments,
            summary_findings=findings,
        )

        # Save JSON artifact
        out_dir = PROJECT_ROOT / "artifacts" / "performance"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "TASK-022-oos-audit.json"

        # Serialize report dataclass cleanly
        report_dict = asdict(report)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, indent=2, ensure_ascii=False)

        return report
