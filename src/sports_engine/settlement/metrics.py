"""TASK-020: Settlement Performance and Calibration Metrics.

Computes:
- Flat-stake ROI, Total Profit, Win Rate
- Model EV vs Realized ROI separation
- Market-level & Odds-band breakdowns
- High-Odds (>=5, >=10, >=20, >=50, >=100) tracking with LOW_SAMPLE guard
- Value Candidate tiers (EV > 0, >= 5%, >= 10%, >= 20%)
- Model C Brier Score, Log Loss, and Market Implied comparison
"""

from __future__ import annotations

import math
from typing import Any

from sports_engine.settlement.domain import SettlementRecord, SettlementStatus


def compute_brier_score_and_log_loss(settled_1x2_records: list[SettlementRecord]) -> dict[str, Any]:
    """Compute Brier Score and Log Loss for Model C vs Market on 1X2 market."""
    if not settled_1x2_records:
        return {
            "status": "NO_SETTLED_1X2_YET",
            "model_c_brier": None,
            "market_brier": None,
            "model_c_log_loss": None,
            "market_log_loss": None,
            "sample_size": 0,
        }

    brier_c_sum = 0.0
    brier_m_sum = 0.0
    ll_c_sum = 0.0
    ll_m_sum = 0.0
    count = 0

    for r in settled_1x2_records:
        if r.status not in (SettlementStatus.WON, SettlementStatus.LOST):
            continue

        y = 1.0 if r.status == SettlementStatus.WON else 0.0
        p_c = max(0.0001, min(0.9999, r.model_probability))
        p_m = max(0.0001, min(0.9999, 1.0 / r.bookmaker_odds if r.bookmaker_odds > 0 else 0.33))

        brier_c_sum += (p_c - y) ** 2
        brier_m_sum += (p_m - y) ** 2

        # Binary log loss per selection
        ll_c_sum -= (y * math.log(p_c) + (1.0 - y) * math.log(1.0 - p_c))
        ll_m_sum -= (y * math.log(p_m) + (1.0 - y) * math.log(1.0 - p_m))
        count += 1

    if count == 0:
        return {
            "status": "NO_BINARY_OUTCOMES_YET",
            "model_c_brier": None,
            "market_brier": None,
            "model_c_log_loss": None,
            "market_log_loss": None,
            "sample_size": 0,
        }

    return {
        "status": "CALCULATED" if count >= 30 else "EARLY_SAMPLE",
        "sample_size": count,
        "model_c_brier": round(brier_c_sum / count, 4),
        "market_brier": round(brier_m_sum / count, 4),
        "model_c_log_loss": round(ll_c_sum / count, 4),
        "market_log_loss": round(ll_m_sum / count, 4),
        "advantage": "MODEL_C_BETTER" if (brier_c_sum < brier_m_sum) else "MARKET_BETTER",
    }


def aggregate_settlement_metrics(records: list[SettlementRecord]) -> dict[str, Any]:
    """Aggregate comprehensive performance metrics across settled and pending records."""
    total_predictions = len(records)
    settled_records = [r for r in records if r.status in (SettlementStatus.WON, SettlementStatus.LOST, SettlementStatus.PUSH)]
    pending_records = [r for r in records if r.status == SettlementStatus.PENDING]
    unsettleable_records = [r for r in records if r.status == SettlementStatus.UNSETTLEABLE]

    wins = sum(1 for r in settled_records if r.status == SettlementStatus.WON)
    losses = sum(1 for r in settled_records if r.status == SettlementStatus.LOST)
    pushes = sum(1 for r in settled_records if r.status == SettlementStatus.PUSH)

    total_staked = len(settled_records) * 1.0  # 1 unit flat stake
    total_profit = round(sum(r.profit for r in settled_records), 4)
    roi_pct = round((total_profit / total_staked) * 100.0, 2) if total_staked > 0 else 0.0
    win_rate = round((wins / len(settled_records)) * 100.0, 2) if settled_records else 0.0

    avg_odds = round(sum(r.bookmaker_odds for r in records) / total_predictions, 2) if total_predictions else 0.0
    avg_model_prob = round(sum(r.model_probability for r in records) / total_predictions, 4) if total_predictions else 0.0
    avg_ev = round(sum(r.model_ev_percent for r in records) / total_predictions, 2) if total_predictions else 0.0

    # 1. By Market
    market_groups: dict[str, list[SettlementRecord]] = {}
    for r in records:
        market_groups.setdefault(r.market, []).append(r)

    by_market = {}
    for mkt, m_recs in market_groups.items():
        m_settled = [r for r in m_recs if r.status in (SettlementStatus.WON, SettlementStatus.LOST, SettlementStatus.PUSH)]
        m_wins = sum(1 for r in m_settled if r.status == SettlementStatus.WON)
        m_losses = sum(1 for r in m_settled if r.status == SettlementStatus.LOST)
        m_stake = len(m_settled) * 1.0
        m_profit = round(sum(r.profit for r in m_settled), 4)
        m_roi = round((m_profit / m_stake) * 100.0, 2) if m_stake > 0 else 0.0
        by_market[mkt] = {
            "total_predictions": len(m_recs),
            "settled": len(m_settled),
            "pending": sum(1 for r in m_recs if r.status == SettlementStatus.PENDING),
            "wins": m_wins,
            "losses": m_losses,
            "pushes": sum(1 for r in m_settled if r.status == SettlementStatus.PUSH),
            "profit": m_profit,
            "roi_percent": m_roi,
            "win_rate": round((m_wins / len(m_settled)) * 100.0, 2) if m_settled else 0.0,
            "sample_status": "SUFFICIENT" if len(m_settled) >= 30 else "LOW_SAMPLE",
        }

    # 2. By Odds Band
    bands = ["<2", "2-5", "5-10", "10-20", "20-50", "50-100", "100+"]
    by_band: dict[str, dict[str, Any]] = {b: {"total": 0, "settled": 0, "wins": 0, "profit": 0.0, "roi": 0.0} for b in bands}

    for r in records:
        o = r.bookmaker_odds
        if o < 2.0:
            b_key = "<2"
        elif o < 5.0:
            b_key = "2-5"
        elif o < 10.0:
            b_key = "5-10"
        elif o < 20.0:
            b_key = "10-20"
        elif o < 50.0:
            b_key = "20-50"
        elif o < 100.0:
            b_key = "50-100"
        else:
            b_key = "100+"

        by_band[b_key]["total"] += 1
        if r.status in (SettlementStatus.WON, SettlementStatus.LOST, SettlementStatus.PUSH):
            by_band[b_key]["settled"] += 1
            if r.status == SettlementStatus.WON:
                by_band[b_key]["wins"] += 1
            by_band[b_key]["profit"] = round(by_band[b_key]["profit"] + r.profit, 4)

    for b_key, b_val in by_band.items():
        stk = b_val["settled"] * 1.0
        b_val["roi"] = round((b_val["profit"] / stk) * 100.0, 2) if stk > 0 else 0.0
        b_val["sample_status"] = "SUFFICIENT" if b_val["settled"] >= 30 else "LOW_SAMPLE"

    # 3. High-Odds Thresholds (>=5, >=10, >=20, >=50, >=100)
    high_thresholds = [5.0, 10.0, 20.0, 50.0, 100.0]
    high_odds_perf = {}
    for th in high_thresholds:
        th_key = f">={int(th)}"
        th_recs = [r for r in records if r.bookmaker_odds >= th]
        th_settled = [r for r in th_recs if r.status in (SettlementStatus.WON, SettlementStatus.LOST, SettlementStatus.PUSH)]
        th_wins = sum(1 for r in th_settled if r.status == SettlementStatus.WON)
        th_profit = round(sum(r.profit for r in th_settled), 4)
        th_stake = len(th_settled) * 1.0
        th_roi = round((th_profit / th_stake) * 100.0, 2) if th_stake > 0 else 0.0
        high_odds_perf[th_key] = {
            "threshold": th,
            "total_predictions": len(th_recs),
            "settled": len(th_settled),
            "pending": sum(1 for r in th_recs if r.status == SettlementStatus.PENDING),
            "wins": th_wins,
            "losses": sum(1 for r in th_settled if r.status == SettlementStatus.LOST),
            "profit": th_profit,
            "roi_percent": th_roi,
            "win_rate": round((th_wins / len(th_settled)) * 100.0, 2) if th_settled else 0.0,
            "sample_status": "SUFFICIENT" if len(th_settled) >= 30 else "LOW_SAMPLE",
        }

    # 4. Value Candidate Performance (EV > 0, EV >= 5%, EV >= 10%, EV >= 20%)
    ev_tiers = [("EV>0", 0.0), ("EV>=5%", 5.0), ("EV>=10%", 10.0), ("EV>=20%", 20.0)]
    val_cand_perf = {}
    for tier_name, min_ev in ev_tiers:
        t_recs = [r for r in records if r.model_ev_percent >= min_ev]
        t_settled = [r for r in t_recs if r.status in (SettlementStatus.WON, SettlementStatus.LOST, SettlementStatus.PUSH)]
        t_wins = sum(1 for r in t_settled if r.status == SettlementStatus.WON)
        t_profit = round(sum(r.profit for r in t_settled), 4)
        t_stake = len(t_settled) * 1.0
        t_roi = round((t_profit / t_stake) * 100.0, 2) if t_stake > 0 else 0.0
        val_cand_perf[tier_name] = {
            "min_ev_percent": min_ev,
            "total_predictions": len(t_recs),
            "settled": len(t_settled),
            "pending": sum(1 for r in t_recs if r.status == SettlementStatus.PENDING),
            "wins": t_wins,
            "profit": t_profit,
            "roi_percent": t_roi,
            "win_rate": round((t_wins / len(t_settled)) * 100.0, 2) if t_settled else 0.0,
            "sample_status": "SUFFICIENT" if len(t_settled) >= 30 else "LOW_SAMPLE",
        }

    # 5. Model C Calibration on 1X2
    recs_1x2 = [r for r in settled_records if r.market in ("1X2", "H1X2")]
    calibration_1x2 = compute_brier_score_and_log_loss(recs_1x2)

    return {
        "summary": {
            "total_predictions": total_predictions,
            "settled_predictions": len(settled_records),
            "pending_predictions": len(pending_records),
            "unsettleable_predictions": len(unsettleable_records),
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "total_stake": total_staked,
            "total_profit": total_profit,
            "realized_roi_percent": roi_pct,
            "win_rate_percent": win_rate,
            "average_bookmaker_odds": avg_odds,
            "average_model_probability": avg_model_prob,
            "average_model_ev_percent": avg_ev,
            "evaluation_stage": "EARLY_SAMPLE" if len(settled_records) < 50 else "ESTABLISHED_SAMPLE",
        },
        "by_market": by_market,
        "by_odds_band": by_band,
        "high_odds_performance": high_odds_perf,
        "value_candidate_performance": val_cand_perf,
        "model_c_calibration_1x2": calibration_1x2,
    }
