"""TASK-021: Canonical Script for Multi-Snapshot Odds Tracking & Prediction Lifecycle.

Usage:
    python scripts/track_odds_lifecycle.py                        # Standard snapshot tracking & ledger update
    python scripts/track_odds_lifecycle.py --capture-now          # Capture live odds from PropLine & track lifecycle
    python scripts/track_odds_lifecycle.py --simulate-time-lapse  # End-to-end multi-snapshot line movement verification
"""

import argparse
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Ensure project root and src are on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

# Fix Windows console encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from sports_engine.odds_lifecycle.cli import print_lifecycle_table
from sports_engine.odds_lifecycle.tracker import OddsLifecycleTracker, make_lifecycle_id


def build_simulated_time_series(
    predictions_path: Path,
) -> dict[str, list[dict[str, any]]]:
    """Generate realistic pre-match odds movement time-lapse for lifecycle verification."""
    with open(predictions_path, "r", encoding="utf-8") as f:
        pred_data = json.load(f)

    # Deterministic seed for reproducible testing
    rng = random.Random(42)
    time_series: dict[str, list[dict[str, any]]] = {}

    for fixture in pred_data.get("predictions", []):
        eid = fixture.get("event_id", "")
        kickoff_str = fixture.get("kickoff", "")
        try:
            ko_dt = datetime.fromisoformat(kickoff_str.replace("Z", "+00:00"))
        except Exception:
            ko_dt = datetime.now(UTC) + timedelta(days=2)

        for sel in fixture.get("selections", []):
            mkt = sel.get("market", "")
            s_name = sel.get("selection", "")
            bm = sel.get("bookmaker", "")
            init_odds = float(sel.get("bookmaker_odds", 1.0))
            m_ev = float(sel.get("expected_value_percent", 0.0))

            lid = make_lifecycle_id(eid, mkt, s_name, bm)

            # Generate 2 intermediate snapshot points: T-24h and T-2h
            # If EV > 0 (sharp value), market has higher tendency to shorten (smart money)
            drift_bias = -0.04 if m_ev > 5.0 else 0.02
            variation_1 = rng.uniform(-0.03, 0.03) + drift_bias
            variation_2 = rng.uniform(-0.02, 0.02) + (drift_bias * 1.2)

            odds_t24 = max(1.02, round(init_odds * (1.0 + variation_1), 2))
            odds_t2 = max(1.02, round(odds_t24 * (1.0 + variation_2), 2))

            t_24h_dt = ko_dt - timedelta(hours=24)
            t_2h_dt = ko_dt - timedelta(hours=2)

            time_series[lid] = [
                {
                    "snapshot_id": f"snap_t24_{eid[:10]}",
                    "timestamp": t_24h_dt.isoformat(),
                    "odds": odds_t24,
                },
                {
                    "snapshot_id": f"snap_t2_{eid[:10]}",
                    "timestamp": t_2h_dt.isoformat(),
                    "odds": odds_t2,
                },
            ]

    return time_series


def main() -> None:
    parser = argparse.ArgumentParser(description="Odds Lifecycle & Movement Tracker (TASK-021)")
    parser.add_argument(
        "--predictions",
        default="artifacts/predictions/TASK-019/predictions.json",
        help="Path to predictions JSON snapshot",
    )
    parser.add_argument(
        "--capture-now",
        action="store_true",
        help="Attempt live capture from PropLine for predicted events and link to ledger",
    )
    parser.add_argument(
        "--simulate-time-lapse",
        action="store_true",
        help="Simulate multi-snapshot pre-match odds movement to verify CLV and line movement tracking",
    )

    args = parser.parse_args()
    pred_path = _PROJECT_ROOT / args.predictions

    if not pred_path.exists():
        print(f"Error: Predictions file not found at {pred_path}")
        sys.exit(1)

    tracker = OddsLifecycleTracker(predictions_path=pred_path)

    fresh_records = None
    if args.capture_now:
        with open(pred_path, "r", encoding="utf-8") as f:
            pred_data = json.load(f)
        fixtures = pred_data.get("predictions", [])
        print(f"[*] Capturing live odds for {len(fixtures)} fixtures from PropLine...")
        fresh_records = tracker.capture_live_odds_for_predicted_events(
            predicted_fixtures=fixtures,
            captured_at=datetime.now(UTC),
        )
        print(f"[+] Captured {len(fresh_records)} live odds records.")

    sim_series = None
    if args.simulate_time_lapse:
        print("[*] Generating multi-snapshot time series (T-24h, T-2h) for line movement verification...")
        sim_series = build_simulated_time_series(pred_path)
        print(f"[+] Built time series for {len(sim_series)} selections.")

    payload = tracker.track_lifecycle(
        fresh_odds_records=fresh_records,
        simulated_time_series=sim_series,
    )

    # Display terminal table
    print_lifecycle_table(payload)
    print(f"[+] Artifact saved to: {tracker.movement_dir / 'TASK-021-lifecycle.json'}")


if __name__ == "__main__":
    main()
