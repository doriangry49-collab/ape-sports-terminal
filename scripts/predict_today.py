"""Daily Prediction Operations: Multi-sport discovery and active prediction pipeline (TASK-005)."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure project root and src are on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from config.settings import get_settings
from sports_engine.collectors.discovery import (
    check_sport_scores_availability,
    discover_all_sports,
    fetch_sport_upcoming_events,
)
from scripts.predict_batch import run_live_prediction_operations


def run_today_operations(sample_size: int = 300) -> dict[str, Any]:
    """Execute multi-sport discovery and trigger active models for today's prediction universe."""
    today_dt = datetime.now(UTC)
    date_str = today_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    # 1. Discover all sports
    sports = discover_all_sports(force_refresh=False)
    total_sports_count = len(sports)

    # Key representative sport keys to inspect for live events
    target_sports = {
        "Football": "soccer_turkey_super_lig",
        "Baseball": "baseball_mlb",
        "Basketball": "basketball_nba",
        "Tennis": "tennis",
    }

    sport_summaries: list[dict[str, Any]] = []
    total_upcoming_events = 0
    total_model_eligible = 0
    total_no_model = 0

    for cat_name, sport_key in target_sports.items():
        events = fetch_sport_upcoming_events(sport_key, limit=50)
        n_events = len(events)
        total_upcoming_events += n_events

        if cat_name == "Football" and sport_key == "soccer_turkey_super_lig":
            model_status = "MODEL_AVAILABLE"
            pred_count = n_events
            no_model_count = 0
            total_model_eligible += pred_count
        else:
            model_status = "NO_MODEL_YET"
            pred_count = 0
            no_model_count = n_events
            total_no_model += no_model_count

        sport_summaries.append({
            "category": cat_name,
            "sport_key": sport_key,
            "upcoming_events": n_events,
            "model_status": model_status,
            "prediction_count": pred_count,
            "no_model_count": no_model_count,
        })

    # 2. Run prediction pipeline for model-ready events (Football / Süper Lig)
    prediction_result = run_live_prediction_operations(sample_size=sample_size)

    # 3. Check result tracking (/scores) availability for post-match verification
    scores_status = check_sport_scores_availability(list(target_sports.values()))

    return {
        "date": date_str,
        "total_supported_sports": total_sports_count,
        "sport_summaries": sport_summaries,
        "total_upcoming_events": total_upcoming_events,
        "total_predictions_generated": len(prediction_result["predictions"]),
        "total_no_model_events": total_no_model,
        "prediction_operations": prediction_result,
        "scores_tracking_status": scores_status,
    }


def print_today_cli(result: dict[str, Any]) -> None:
    """Print readable terminal output conforming to TASK-005 specification."""
    print("\n" + "=" * 90)
    print(f" PREDICTION UNIVERSE DISCOVERY & LIVE OPERATIONS (TASK-005)")
    print(f" DATE:                 {result['date']}")
    print(f" SUPPORTED SPORTS:     {result['total_supported_sports']} total sports cataloged (PropLine API)")
    print(f" TOTAL UPCOMING:       {result['total_upcoming_events']} events across examined core sports")
    print(f" MODEL READY PREDICTIONS: {result['total_predictions_generated']} events predicted with active model")
    print(f" NO MODEL YET:         {result['total_no_model_events']} events awaiting future sport models")
    print("=" * 90)

    print("\n[SPORT UNIVERSE BREAKDOWN]")
    header = f"{'SPORT':<15} | {'UPCOMING EVENTS':<17} | {'MODEL STATUS':<16} | {'MODEL READY':<14} | {'NO MODEL'}"
    print(header)
    print("-" * 90)

    for s in result["sport_summaries"]:
        cat = s["category"]
        evs = f"{s['upcoming_events']} events"
        status = s["model_status"]
        ready = f"{s['prediction_count']} model-ready"
        no_mod = f"{s['no_model_count']} pending"
        print(f"{cat:<15} | {evs:<17} | {status:<16} | {ready:<14} | {no_mod}")

    print("-" * 90)

    # Show live predictions
    preds = result["prediction_operations"]["predictions"]
    print(f"\n[ACTIVE MODEL PREDICTIONS — FOOTBALL (poisson_bivariate_baseline v0.1.0)]")
    pred_header = f"{'MATCH':<32} | {'1X2 PROBABILITIES':<22} | {'FAIR ODDS':<18} | {'CURRENT ODDS (Pinnacle)'}"
    print(pred_header)
    print("-" * 90)

    for p in preds:
        fix = p["fixture"]
        match_str = f"{fix['home_team']} vs {fix['away_team']}"
        prob_str = f"H:{p['home_probability']*100:>4.1f}% D:{p['draw_probability']*100:>4.1f}% A:{p['away_probability']*100:>4.1f}%"
        fair_str = f"H:{p['fair_home_odds']:>4.2f} D:{p['fair_draw_odds']:>4.2f} A:{p['fair_away_odds']:>4.2f}"
        cur = p["current_odds"]
        cur_str = f"H:{cur['home']:>4.2f} D:{cur['draw']:>4.2f} A:{cur['away']:>4.2f}"
        print(f"{match_str:<32} | {prob_str:<22} | {fair_str:<18} | {cur_str}")

    print("-" * 90)

    # Result tracking check
    scores_res = result["scores_tracking_status"]["results"]
    print("\n[RESULT TRACKING AVAILABILITY (/scores endpoint)]")
    for skey, sdata in scores_res.items():
        print(f"  {skey:<28} Status: {sdata['status']:<12} Event Count: {sdata['event_count']}")

    print("\n[IMMUTABLE SNAPSHOT ARTIFACTS]")
    print(f"  JSON Snapshot:    {result['prediction_operations']['snapshot_json_path']}")
    print(f"  Parquet Snapshot: {result['prediction_operations']['snapshot_parquet_path']}")
    print(f"  Sports Catalog:   artifacts/sports_discovery/sports_list.json")
    print(f"  Scores Registry:  artifacts/sports_discovery/scores_availability.json")
    print("=" * 90 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Sport Universe Discovery and Daily Prediction Operations")
    parser.add_argument("--limit", type=int, default=300, help="Historical training sample size for football model")
    args = parser.parse_args()

    res = run_today_operations(sample_size=args.limit)
    print_today_cli(res)


if __name__ == "__main__":
    main()
