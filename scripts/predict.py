"""Live Prediction Engine & Canonical CLI Interface (TASK-019).

Usage:
    python scripts/predict.py                  # Full live prediction product across all eligible competitions
    python scripts/predict.py --propline-only  # Run PropLine provider only (independent of Xiddaa)
    python scripts/predict.py --single         # Single fixture legacy mode
"""

import argparse
import sys
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

from sports_engine.prediction_product.cli import print_prediction_product_dashboard
from sports_engine.prediction_product.engine import LivePredictionProduct, LivePredictionProductConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Prediction Product Engine (TASK-019)")
    parser.add_argument("--propline-only", action="store_true", help="Execute PropLine only (disable Xiddaa)")
    parser.add_argument("--xiddaa-only", action="store_true", help="Execute Xiddaa only (disable PropLine)")
    parser.add_argument("--max-events", type=int, default=10, help="Max events to scan per competition")
    parser.add_argument("--decay-half-life", type=float, default=180.0, help="Model C time decay half life days")
    parser.add_argument("--single", action="store_true", help="Single fixture test mode")
    parser.add_argument("--home", default=None, help="Home team name for single fixture mode")
    parser.add_argument("--away", default=None, help="Away team name for single fixture mode")

    args = parser.parse_args()

    cfg = LivePredictionProductConfig(
        decay_half_life_days=args.decay_half_life,
        max_events_per_comp=args.max_events,
        enable_propline=not args.xiddaa_only,
        enable_xiddaa=not args.propline_only,
    )

    engine = LivePredictionProduct(config=cfg)
    payload = engine.execute_live_product_pipeline()
    print_prediction_product_dashboard(payload)


if __name__ == "__main__":
    main()
