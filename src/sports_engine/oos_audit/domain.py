"""TASK-022: Out-Of-Sample (OOS) Performance Audit Domain Models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class AuditStatus(str, Enum):
    """Overall status of the OOS evaluation."""

    AWAITING_KICKOFF_AND_SETTLEMENT = "AWAITING_KICKOFF_AND_SETTLEMENT"
    PARTIAL_SETTLEMENT = "PARTIAL_SETTLEMENT"
    COMPLETE_SETTLEMENT = "COMPLETE_SETTLEMENT"


class SegmentStatus(str, Enum):
    """Statistical sample sufficiency status of a specific segment."""

    SUFFICIENT_SAMPLE = "SUFFICIENT_SAMPLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    NO_DATA = "NO_DATA"


class ConfidenceTier(str, Enum):
    """Sample confidence tiers defined by statistical reliability."""

    INSUFFICIENT = "INSUFFICIENT (<10)"
    EARLY_SIGNAL = "EARLY_SIGNAL (10-49)"
    MODERATE = "MODERATE (50-99)"
    SIGNIFICANT = "SIGNIFICANT (100-249)"
    HIGH_ODDS_ROBUST = "ROBUST (250+)"


@dataclass
class SegmentAuditResult:
    """Scientific performance and calibration evaluation for a specific slice."""

    segment_name: str
    status: SegmentStatus
    confidence_tier: ConfidenceTier = ConfidenceTier.INSUFFICIENT
    raw_selections_count: int = 0
    independent_events_count: int = 0
    won_count: int = 0
    lost_count: int = 0
    push_count: int = 0
    win_rate_percent: float = 0.0
    total_staked: float = 0.0
    total_profit: float = 0.0
    realized_roi_percent: float = 0.0
    avg_model_ev_percent: float = 0.0
    model_brier_score: Optional[float] = None
    market_brier_score: Optional[float] = None
    brier_advantage: Optional[float] = None  # Market Brier - Model Brier (>0 is Model C outperforming)
    model_log_loss: Optional[float] = None
    market_log_loss: Optional[float] = None
    log_loss_advantage: Optional[float] = None  # Market LL - Model LL (>0 is Model C outperforming)
    notes: str = ""


@dataclass
class OOSAuditReport:
    """Complete Out-Of-Sample performance audit report."""

    task_id: str = "TASK-022"
    generated_at: str = ""
    audit_status: AuditStatus = AuditStatus.AWAITING_KICKOFF_AND_SETTLEMENT
    total_predictions_in_snapshot: int = 0
    total_settled_records: int = 0
    total_pending_records: int = 0
    unique_fixtures_count: int = 0
    unique_settled_fixtures_count: int = 0
    min_independent_events_threshold: int = 10
    segments: dict[str, SegmentAuditResult] = field(default_factory=dict)
    summary_findings: list[str] = field(default_factory=list)
