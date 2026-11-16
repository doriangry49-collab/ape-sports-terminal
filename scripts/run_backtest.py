"""Script to execute Walk-Forward Backtesting for Poisson Baseline Model."""

import argparse
import sys
from pathlib import Path

# Ensure project root and src are on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from sports_engine.backtest.engine import WalkForwardBacktest, save_backtest_artifacts
from sports_engine.features.dataset import fetch_or_load_historical_matches


def run_backtest_cli(sample_limit: int = 300, min_train: int = 60) -> None:
    """Run walk-forward evaluation and output results."""
    print("\n" + "=" * 76)
    print(f" EXECUTING WALK-FORWARD BACKTEST (Poisson Baseline v0.1.0)")
    print(f" Sample Target: {sample_limit} historical matches | Warmup Size: {min_train}")
    print("=" * 76)

    # 1. Fetch/load matches
    matches = fetch_or_load_historical_matches(league_id=11, limit=sample_limit)
    print(f" Loaded {len(matches)} historical matches from Bzzoiro.")

    # 2. Run walk-forward simulation
    backtest = WalkForwardBacktest(min_train_size=min_train)
    summary, records = backtest.run(matches)

    # 3. Save artifacts
    json_path, md_path = save_backtest_artifacts(summary, records, output_dir="artifacts/backtest")

    # 4. Print clean CLI report
    calib = summary.calibration_summary
    print("\n" + "-" * 76)
    print(" [BACKTEST RESULTS SUMMARY]")
    print(f"  Out-of-sample Test Matches: {summary.total_test_matches}")
    print(f"  Initial Train Warmup:       {summary.train_warmup_size} matches")
    print(f"  Mean Brier Score:           {summary.brier_score_mean:.4f}  (Uniform Baseline: {summary.benchmark_uniform_brier:.4f})")
    print(f"  Mean Log Loss:              {summary.log_loss_mean:.4f}  (Uniform Baseline: {summary.benchmark_uniform_log_loss:.4f})")
    print(f"  Argmax Hit Accuracy:        {summary.accuracy_percent:.2f}% (Random Benchmark: 33.33%)")
    print("-" * 76)

    print("\n [CALIBRATION & RELIABILITY (By Class)]")
    for cls_name, cdata in calib["by_class"].items():
        diff = cdata["mean_predicted_prob"] - cdata["actual_frequency"]
        sign = "+" if diff >= 0 else ""
        print(f"  {cls_name:<6} Observed: {cdata['actual_frequency'] * 100:>5.1f}% | Model Mean Prob: {cdata['mean_predicted_prob'] * 100:>5.1f}% | Bias: {sign}{diff * 100:>5.1f}%")

    print("\n [PROBABILITY BIN RELIABILITY]")
    for b_range, bdata in calib["probability_bins"].items():
        print(f"  Bin {b_range:<8} Count: {bdata['sample_count']:>3} | Avg Prob: {bdata['avg_predicted_prob'] * 100:>5.1f}% | Observed Accuracy: {bdata['observed_accuracy'] * 100:>5.1f}%")

    print("\n [SAVED ARTIFACTS]")
    print(f"  JSON Report: {json_path}")
    print(f"  Markdown:    {md_path}")
    print("=" * 76 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run walk-forward backtest on historical Süper Lig matches")
    parser.add_argument("--limit", type=int, default=300, help="Number of historical matches to load")
    parser.add_argument("--min-train", type=int, default=60, help="Initial warmup training size")
    args = parser.parse_args()

    run_backtest_cli(sample_limit=args.limit, min_train=args.min_train)


if __name__ == "__main__":
    main()
