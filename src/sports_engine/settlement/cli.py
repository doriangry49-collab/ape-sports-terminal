"""TASK-020: Terminal Dashboard for Settlement & Performance Tracking."""

from __future__ import annotations

from typing import Any


def print_settlement_dashboard(payload: dict[str, Any]) -> None:
    """Print clean, executive settlement and performance dashboard."""
    fix_sum = payload.get("fixtures_summary", {})
    perf = payload.get("performance", {})
    summary = perf.get("summary", {})
    by_mkt = perf.get("by_market", {})
    by_band = perf.get("by_odds_band", {})
    high_perf = perf.get("high_odds_performance", {})
    val_perf = perf.get("value_candidate_performance", {})
    calib = perf.get("model_c_calibration_1x2", {})

    print("\n" + "=" * 92)
    print(" 🎯 SPORTS INTELLIGENCE ENGINE — PREDICTION SETTLEMENT & REAL PERFORMANCE (TASK-020)")
    print(f" Run ID:          {payload.get('run_id')} | Generated: {payload.get('generated_at')}")
    print(f" Predictions:     {payload.get('predictions_source')}")
    print(f" Evaluation:      {summary.get('evaluation_stage')} | Zero-Cost Mode: ACTIVE")
    print("=" * 92)

    # 1. Fixture Resolution Status
    print("\n[FIXTURE STATUS SUMMARY]")
    print(f"  • Total Predicted Fixtures:       {fix_sum.get('total_fixtures')}")
    print(f"  • Finished Fixtures (FT):         {fix_sum.get('finished_fixtures')}")
    print(f"  • Upcoming / Pending Fixtures:    {fix_sum.get('upcoming_fixtures')}")
    print(f"  • Unresolved Fixtures:            {fix_sum.get('unresolved_fixtures')}")

    # 2. Executive Performance Summary
    print("\n[EXECUTIVE PERFORMANCE METRICS (1 UNIT FLAT STAKE)]")
    print(f"  • Total Predictions Tracked:      {summary.get('total_predictions')}")
    print(f"  • Settled Predictions:            {summary.get('settled_predictions')}")
    print(f"  • Pending Predictions:            {summary.get('pending_predictions')}")
    print(f"  • Wins:                           {summary.get('wins')}")
    print(f"  • Losses:                         {summary.get('losses')}")
    print(f"  • Pushes:                         {summary.get('pushes')}")
    print(f"  • Total Staked:                   {summary.get('total_stake'):.1f} units")
    profit_sign = "+" if summary.get("total_profit", 0) >= 0 else ""
    print(f"  • Realized Profit:                {profit_sign}{summary.get('total_profit', 0):.2f} units")
    roi_sign = "+" if summary.get("realized_roi_percent", 0) >= 0 else ""
    print(f"  • Realized ROI:                   {roi_sign}{summary.get('realized_roi_percent', 0):.2f}%")
    print(f"  • Win Rate:                       {summary.get('win_rate_percent', 0):.2f}%")
    print(f"  • Average Odds:                   {summary.get('average_bookmaker_odds', 0):.2f}")
    print(f"  • Average Model EV:               +{summary.get('average_model_ev_percent', 0):.2f}%")

    # 3. Market Breakdown Table
    print("\n" + "-" * 92)
    print(" 📊 PERFORMANCE BY BETTING MARKET")
    print("-" * 92)
    m_header = f"{'MARKET':<18} | {'PREDICTIONS':<12} | {'SETTLED':<9} | {'WINS':<6} | {'PROFIT':<10} | {'ROI %':<10} | {'STATUS'}"
    print(m_header)
    print("-" * 92)

    for mkt, m_data in by_mkt.items():
        p_sign = "+" if m_data.get("profit", 0) >= 0 else ""
        prof_str = f"{p_sign}{m_data.get('profit', 0):.2f}u"
        r_sign = "+" if m_data.get("roi_percent", 0) >= 0 else ""
        roi_str = f"{r_sign}{m_data.get('roi_percent', 0):.1f}%"
        stat_str = m_data.get("sample_status", "LOW_SAMPLE")
        print(f"{mkt:<18} | {m_data.get('total_predictions'):<12} | {m_data.get('settled'):<9} | {m_data.get('wins'):<6} | {prof_str:<10} | {roi_str:<10} | {stat_str}")

    # 4. Odds Band Table
    print("\n" + "-" * 92)
    print(" 📈 PERFORMANCE BY ODDS BAND")
    print("-" * 92)
    b_header = f"{'ODDS BAND':<14} | {'TOTAL':<8} | {'SETTLED':<9} | {'WINS':<6} | {'PROFIT':<10} | {'ROI %':<10} | {'STATUS'}"
    print(b_header)
    print("-" * 92)

    for band, b_data in by_band.items():
        p_sign = "+" if b_data.get("profit", 0) >= 0 else ""
        prof_str = f"{p_sign}{b_data.get('profit', 0):.2f}u"
        r_sign = "+" if b_data.get("roi", 0) >= 0 else ""
        roi_str = f"{r_sign}{b_data.get('roi', 0):.1f}%"
        stat_str = b_data.get("sample_status", "LOW_SAMPLE")
        print(f"{band:<14} | {b_data.get('total'):<8} | {b_data.get('settled'):<9} | {b_data.get('wins'):<6} | {prof_str:<10} | {roi_str:<10} | {stat_str}")

    # 5. Value Candidate Tiers
    print("\n" + "-" * 92)
    print(" 💎 VALUE CANDIDATE REALIZED PERFORMANCE (MODEL EV vs REALIZED ROI)")
    print("-" * 92)
    v_header = f"{'TIER':<14} | {'TOTAL':<8} | {'SETTLED':<9} | {'WINS':<6} | {'PROFIT':<10} | {'ROI %':<10} | {'STATUS'}"
    print(v_header)
    print("-" * 92)

    for tier, v_data in val_perf.items():
        p_sign = "+" if v_data.get("profit", 0) >= 0 else ""
        prof_str = f"{p_sign}{v_data.get('profit', 0):.2f}u"
        r_sign = "+" if v_data.get("roi_percent", 0) >= 0 else ""
        roi_str = f"{r_sign}{v_data.get('roi_percent', 0):.1f}%"
        stat_str = v_data.get("sample_status", "LOW_SAMPLE")
        print(f"{tier:<14} | {v_data.get('total_predictions'):<8} | {v_data.get('settled'):<9} | {v_data.get('wins'):<6} | {prof_str:<10} | {roi_str:<10} | {stat_str}")

    # 6. Model C 1X2 Calibration Benchmark
    print("\n" + "-" * 92)
    print(" ⚖️ MODEL C CALIBRATION vs MARKET IMPLIED PROBABILITY (1X2)")
    print("-" * 92)
    if calib.get("status") in ("CALCULATED", "EARLY_SAMPLE"):
        print(f"  • Sample Size:        {calib.get('sample_size')} settled selections")
        print(f"  • Model C Brier:      {calib.get('model_c_brier'):.4f}  |  Market Brier:    {calib.get('market_brier'):.4f}")
        print(f"  • Model C Log Loss:   {calib.get('model_c_log_loss'):.4f}  |  Market Log Loss: {calib.get('market_log_loss'):.4f}")
        print(f"  • Advantage:          {calib.get('advantage')} ({calib.get('status')})")
    else:
        print(f"  • Status:             {calib.get('status')} (Awaiting first finished 1X2 matches)")

    # 7. Footprint
    print("\n" + "=" * 92)
    print(" 💾 PERFORMANCE ARTIFACTS PERSISTED")
    print(f"  • Performance JSON:   artifacts/performance/TASK-020-performance.json")
    print(f"  • Settlement Ledger:  artifacts/performance/TASK-020-settlement-ledger.json")
    print(f"  • Predictions Kept:   IMMUTABLE (Zero overwrite of prediction snapshot)")
    print("=" * 92 + "\n")
