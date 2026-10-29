"""TASK-022: Terminal Table Formatter for OOS Performance Audit."""

from __future__ import annotations

import sys
from typing import Any

from sports_engine.oos_audit.domain import OOSAuditReport, SegmentStatus


def format_oos_audit_table(report: OOSAuditReport) -> str:
    """Format OOSAuditReport into scientific terminal dashboard table."""
    lines: list[str] = []
    lines.append("=" * 105)
    lines.append("  TASK-022: OUT-OF-SAMPLE (OOS) PERFORMANCE & MARKET CALIBRATION AUDIT")
    lines.append("=" * 105)
    lines.append(f"  Audit Status:              {report.audit_status.value}")
    lines.append(f"  Generated At:              {report.generated_at}")
    lines.append(f"  Total Predictions:         {report.total_predictions_in_snapshot:,}")
    lines.append(f"  Settled Records:           {report.total_settled_records:,}")
    lines.append(f"  Pending Kickoff:           {report.total_pending_records:,}")
    lines.append(f"  Independent Fixtures:      {report.unique_settled_fixtures_count} settled / {report.unique_fixtures_count} total")
    lines.append(f"  Min Indep Events Threshold: {report.min_independent_events_threshold} matches (underpowered flagged INSUFFICIENT_SAMPLE)")
    lines.append("-" * 105)
    lines.append("")

    lines.append("[ SEGMENT-BY-SEGMENT PERFORMANCE & MARKET BENCHMARK ]")
    header = (
        f"{'Segment':<32} | {'Status':<16} | {'Raw N':>6} | {'Indep N':>7} | "
        f"{'Win%':>6} | {'ROI%':>8} | {'Mod Brier':>9} | {'Mkt Brier':>9} | {'Advantage':>9}"
    )
    lines.append(header)
    lines.append("-" * 115)

    for name, res in report.segments.items():
        st = res.status.value[:16]
        raw_n = res.raw_selections_count
        indep_n = res.independent_events_count
        win_p = f"{res.win_rate_percent:.1f}%" if res.status != SegmentStatus.NO_DATA else "N/A"
        roi_p = f"{res.realized_roi_percent:+.1f}%" if res.status != SegmentStatus.NO_DATA else "N/A"
        m_br = f"{res.model_brier_score:.4f}" if res.model_brier_score is not None else "N/A"
        k_br = f"{res.market_brier_score:.4f}" if res.market_brier_score is not None else "N/A"
        adv = f"{res.brier_advantage:+.4f}" if res.brier_advantage is not None else "N/A"

        row = (
            f"{name:<32} | {st:<16} | {raw_n:>6} | {indep_n:>7} | "
            f"{win_p:>6} | {roi_p:>8} | {m_br:>9} | {k_br:>9} | {adv:>9}"
        )
        lines.append(row)

    lines.append("-" * 115)
    lines.append("")
    lines.append("[ SCIENTIFIC AUDIT FINDINGS & GUARDRAILS ]")
    for f in report.summary_findings:
        lines.append(f"  * {f}")
    lines.append("=" * 105)

    return "\n".join(lines)


def print_oos_audit_table(report: OOSAuditReport) -> None:
    """Safely print the audit report to stdout."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(format_oos_audit_table(report))
