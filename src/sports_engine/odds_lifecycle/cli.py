"""TASK-021: CLI formatting and visual summary for Odds Lifecycle & Movement."""

from __future__ import annotations

import sys
from typing import Any


def format_lifecycle_table(payload: dict[str, Any]) -> str:
    """Format odds lifecycle payload into human-readable terminal tables."""
    summary = payload.get("summary", {})
    lines: list[str] = []

    lines.append("=" * 86)
    lines.append("  TASK-021: MULTI-SNAPSHOT ODDS LIFECYCLE & MOVEMENT REPORT")
    lines.append("=" * 86)
    lines.append(f"  Generated At:          {payload.get('generated_at', 'N/A')}")
    lines.append(f"  Source Predictions:    {payload.get('predictions_source', 'N/A')}")
    lines.append("-" * 86)
    lines.append(f"  Total Selections:      {summary.get('total_selections_tracked', 0):,}")
    lines.append(f"  Multi-Snapshot Linked: {summary.get('multi_snapshot_selections', 0):,}")
    lines.append(f"  Shortened (Odds Drop): {summary.get('shortened_count', 0):,}")
    lines.append(f"  Drifted (Odds Rise):   {summary.get('drifted_count', 0):,}")
    lines.append(f"  Stable (<1% Move):     {summary.get('stable_count', 0):,}")
    lines.append(f"  Significant (>=5%):    {summary.get('significant_moves_count', 0):,}")
    lines.append("-" * 86)
    lines.append(f"  Value Candidates (EV>0): {summary.get('value_candidates_tracked', 0):,}")
    lines.append(f"  Value Beat Closing:     {summary.get('value_candidates_beat_closing_market', 0):,} ({summary.get('value_clv_beat_rate_percent', 0.0)}%)")
    lines.append(f"  CLV Standard Label:     PRE_CLOSING_LINE_VALUE (Non-synthetic)")
    lines.append("=" * 86)
    lines.append("")

    # Top shortened selections (drop in odds -> market agreeing with value)
    top_short = payload.get("top_shortened_selections", [])
    if top_short:
        lines.append("[ TOP SHORTENED SELECTIONS (MARKET CONVERGENCE) ]")
        lines.append(f"{'Fixture':<24} | {'Selection':<16} | {'Init':>6} | {'Latest':>6} | {'Delta':>7} | {'%Chg':>7} | {'CLV':>6} | {'State':<12}")
        lines.append("-" * 96)
        for r in top_short[:10]:
            fixt = r.get("fixture", "")[:23]
            sel = f"{r.get('market', '')} {r.get('selection', '')}"[:15]
            m = r.get("movement", {})
            init_o = m.get("initial_odds", 0.0)
            lat_o = m.get("latest_odds", 0.0)
            delta = m.get("delta_odds", 0.0)
            pct = m.get("pct_change", 0.0)
            clv = m.get("preliminary_clv_ratio", 1.0)
            st = r.get("lifecycle_state", "")[:12]
            lines.append(f"{fixt:<24} | {sel:<16} | {init_o:>6.2f} | {lat_o:>6.2f} | {delta:>+7.2f} | {pct:>+6.1f}% | {clv:>6.2f} | {st:<12}")
        lines.append("")

    # Top drifted selections
    top_drift = payload.get("top_drifted_selections", [])
    if top_drift:
        lines.append("[ TOP DRIFTED SELECTIONS (ODDS EXPANDED) ]")
        lines.append(f"{'Fixture':<24} | {'Selection':<16} | {'Init':>6} | {'Latest':>6} | {'Delta':>7} | {'%Chg':>7} | {'CLV':>6} | {'State':<12}")
        lines.append("-" * 96)
        for r in top_drift[:10]:
            fixt = r.get("fixture", "")[:23]
            sel = f"{r.get('market', '')} {r.get('selection', '')}"[:15]
            m = r.get("movement", {})
            init_o = m.get("initial_odds", 0.0)
            lat_o = m.get("latest_odds", 0.0)
            delta = m.get("delta_odds", 0.0)
            pct = m.get("pct_change", 0.0)
            clv = m.get("preliminary_clv_ratio", 1.0)
            st = r.get("lifecycle_state", "")[:12]
            lines.append(f"{fixt:<24} | {sel:<16} | {init_o:>6.2f} | {lat_o:>6.2f} | {delta:>+7.2f} | {pct:>+6.1f}% | {clv:>6.2f} | {st:<12}")
        lines.append("")

    return "\n".join(lines)


def print_lifecycle_table(payload: dict[str, Any]) -> None:
    """Print the table safely to stdout with utf-8 reconfigure."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(format_lifecycle_table(payload))
