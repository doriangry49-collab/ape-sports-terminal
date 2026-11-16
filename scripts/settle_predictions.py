"""TASK-020: Canonical Prediction Settlement & Performance Script.

Usage:
    python scripts/settle_predictions.py                     # Settle active predictions against live scores
    python scripts/settle_predictions.py --simulate-sample   # Run end-to-end verification with sample finished scores
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

from sports_engine.settlement.cli import print_settlement_dashboard
from sports_engine.settlement.domain import MatchResult, MatchStatus
from sports_engine.settlement.engine import PredictionSettlementEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Prediction Settlement & Real Performance Tracker (TASK-020)")
    parser.add_argument(
        "--predictions",
        default="artifacts/predictions/TASK-019/predictions.json",
        help="Path to predictions JSON snapshot",
    )
    parser.add_argument(
        "--simulate-sample",
        action="store_true",
        help="Simulate finished match results on sample fixtures for end-to-end verification",
    )

    args = parser.parse_args()
    pred_path = _PROJECT_ROOT / args.predictions

    engine = PredictionSettlementEngine(predictions_path=pred_path)

    manual_overrides = None
    if args.simulate_sample:
        # Provide real-world finished score scenarios for testing calibration and settlement math
        manual_overrides = {
            "Arsenal vs Leeds": MatchResult(
                event_id="propline_soccer_epl_20261010_arsenal_vs_leeds",
                home_team="Arsenal",
                away_team="Leeds",
                kickoff="2026-10-10T11:30:00Z",
                home_score=2,
                away_score=0,
                ht_home_score=1,
                ht_away_score=0,
                status=MatchStatus.FINISHED,
                result_source="SIMULATED_VERIFICATION_SAMPLE",
            ),
            "Sunderland vs Brighton": MatchResult(
                event_id="propline_soccer_epl_20261010_sunderland_vs_brighton",
                home_team="Sunderland",
                away_team="Brighton",
                kickoff="2026-10-10T14:00:00Z",
                home_score=1,
                away_score=1,
                ht_home_score=0,
                ht_away_score=1,
                status=MatchStatus.FINISHED,
                result_source="SIMULATED_VERIFICATION_SAMPLE",
            ),
            "Galatasaray vs Kasimpasa": MatchResult(
                event_id="propline_soccer_turkey_super_lig_20261010_galatasaray_vs_kasimpasa",
                home_team="Galatasaray",
                away_team="Kasimpasa",
                kickoff="2026-10-10T17:00:00Z",
                home_score=3,
                away_score=1,
                ht_home_score=2,
                ht_away_score=0,
                status=MatchStatus.FINISHED,
                result_source="SIMULATED_VERIFICATION_SAMPLE",
            ),
        }

    payload = engine.run_settlement(manual_results_override=manual_overrides)
    print_settlement_dashboard(payload)


if __name__ == "__main__":
    main()
