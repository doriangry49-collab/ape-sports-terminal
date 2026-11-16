"""TASK-022: Canonical Script for Out-Of-Sample (OOS) Performance Audit.

Usage:
    python scripts/audit_oos_performance.py                  # Audit active live settlement ledger
    python scripts/audit_oos_performance.py --verify-sample  # End-to-end verification of multi-segment metrics & independence clustering
"""

import argparse
import random
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

from sports_engine.oos_audit.auditor import OOSPerformanceAuditor
from sports_engine.oos_audit.cli import print_oos_audit_table


def generate_verified_sample_records() -> tuple[list[dict], dict]:
    """Generate realistic finished match scenarios across 15 independent fixtures.

    Used strictly with --verify-sample for mathematical verification of segmentation,
    independence clustering, and Model vs Market calibration formulas.
    """
    rng = random.Random(1337)
    sample_records = []
    sample_lifecycle = {}

    fixtures = [
        f"Fixture_{i}_{teamA}_vs_{teamB}"
        for i, (teamA, teamB) in enumerate([
            ("Arsenal", "Leeds"),
            ("Chelsea", "Bournemouth"),
            ("ManCity", "Fulham"),
            ("Liverpool", "Everton"),
            ("Tottenham", "AstonVilla"),
            ("Newcastle", "Brighton"),
            ("WestHam", "Brentford"),
            ("Galatasaray", "Besiktas"),
            ("Fenerbahce", "Trabzonspor"),
            ("RealMadrid", "Barcelona"),
            ("Bayern", "Dortmund"),
            ("Inter", "Juventus"),
            ("PSG", "Marseille"),
            ("Porto", "Benfica"),
            ("Ajax", "Feyenoord"),
        ])
    ]

    markets_config = [
        ("1x2", ["Home", "Draw", "Away"], [2.10, 3.40, 3.60]),
        ("totals", ["Over 2.5", "Under 2.5"], [1.85, 1.95]),
        ("btts", ["Yes", "No"], [1.75, 2.05]),
        ("correct_score", ["1-0", "2-0", "2-1", "0-0", "1-1", "0-1", "0-2", "1-2"], [7.50, 9.00, 8.50, 11.0, 6.50, 12.0, 15.0, 14.0]),
        ("ht_ft", ["Home/Home", "Draw/Home", "Draw/Draw", "Away/Away"], [3.20, 5.50, 6.00, 7.00]),
    ]

    for fix_idx, fix in enumerate(fixtures):
        eid = f"event_{fix_idx:02d}_{fix.lower()}"

        for mkt, selections, base_odds in markets_config:
            # In mutually exclusive markets, exactly 1 selection wins
            winning_idx = rng.randint(0, len(selections) - 1)

            for s_idx, (sel_name, odds) in enumerate(zip(selections, base_odds)):
                is_won = (s_idx == winning_idx)
                st = "WON" if is_won else "LOST"
                stake = 1.0
                profit = (odds - 1.0) if is_won else -1.0

                # Model probability slightly differs from market implied
                mkt_prob = 1.0 / odds
                noise = rng.uniform(-0.04, 0.05)
                mod_prob = max(0.01, min(0.95, mkt_prob + noise))
                ev_pct = round(((mod_prob * odds) - 1.0) * 100.0, 2)

                rec = {
                    "settlement_id": f"settle_{eid}_{mkt}_{sel_name}",
                    "event_id": eid,
                    "match": fix,
                    "market": mkt,
                    "selection": sel_name,
                    "bookmaker": "Bet365",
                    "bookmaker_odds": odds,
                    "model_probability": round(mod_prob, 4),
                    "model_fair_odds": round(1.0 / mod_prob, 2),
                    "model_ev_percent": ev_pct,
                    "status": st,
                    "stake": stake,
                    "profit": round(profit, 2),
                    "realized_roi_percent": round((profit / stake) * 100.0, 2),
                }
                sample_records.append(rec)

                # Lifecycle movement
                move_dir = "SHORTENED" if rng.random() > 0.5 else "DRIFTED"
                sample_lifecycle[rec["settlement_id"]] = {
                    "event_id": eid,
                    "market": mkt,
                    "selection": sel_name,
                    "bookmaker": "Bet365",
                    "movement": {
                        "direction": move_dir,
                        "delta_odds": -0.10 if move_dir == "SHORTENED" else 0.10,
                    },
                }

    return sample_records, sample_lifecycle


def main() -> None:
    parser = argparse.ArgumentParser(description="Out-Of-Sample (OOS) Performance Auditor (TASK-022)")
    parser.add_argument(
        "--settlement-ledger",
        default="artifacts/performance/TASK-020-settlement-ledger.json",
        help="Path to settlement ledger JSON",
    )
    parser.add_argument(
        "--lifecycle-ledger",
        default="artifacts/odds/TASK-021-movement/lifecycle_ledger.json",
        help="Path to lifecycle ledger JSON",
    )
    parser.add_argument(
        "--min-events",
        type=int,
        default=10,
        help="Minimum independent events threshold to declare statistical sufficiency",
    )
    parser.add_argument(
        "--verify-sample",
        action="store_true",
        help="Run isolated verification mode with sample finished match results across 15 fixtures",
    )

    args = parser.parse_args()

    settle_path = _PROJECT_ROOT / args.settlement_ledger
    life_path = _PROJECT_ROOT / args.lifecycle_ledger

    auditor = OOSPerformanceAuditor(
        settlement_ledger_path=settle_path,
        lifecycle_ledger_path=life_path,
        min_independent_events_threshold=args.min_events,
    )

    if args.verify_sample:
        print("[*] Running in VERIFICATION MODE (--verify-sample) across 15 finished test fixtures...")
        sample_records, sample_lifecycle = generate_verified_sample_records()
        report = auditor.audit(
            settled_records_override=sample_records,
            lifecycle_ledger_override=sample_lifecycle,
        )
    else:
        print("[*] Running AUDIT on live settlement ledger...")
        report = auditor.audit()

    print_oos_audit_table(report)
    print(f"[+] Audit JSON artifact exported to: artifacts/performance/TASK-022-oos-audit.json")


if __name__ == "__main__":
    main()
