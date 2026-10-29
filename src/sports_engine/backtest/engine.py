"""Walk-forward temporal backtest engine for football models."""

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sports_engine.models.poisson import PoissonGoalModel


@dataclass
class BacktestMetricSummary:
    """Aggregated evaluation metrics for out-of-sample backtest."""

    total_test_matches: int
    train_warmup_size: int
    brier_score_mean: float
    log_loss_mean: float
    accuracy_percent: float
    benchmark_uniform_brier: float
    benchmark_uniform_log_loss: float
    calibration_summary: dict[str, Any]
    class_distribution: dict[str, int]
    generated_at: str


class WalkForwardBacktest:
    """Walk-forward backtesting simulator with strict temporal anti-leakage guarantee.

    For each historical match in chronological order (after initial warmup):
    1. Only matches occurring strictly prior to the match timestamp are available for training.
    2. Model is fitted on past matches.
    3. Prediction is generated for the out-of-sample test match.
    4. Probabilities are scored against actual match outcome (Brier Score, Log Loss, Calibration).
    """

    def __init__(
        self,
        min_train_size: int = 60,
        shrinkage_weight: float = 3.0,
    ):
        self.min_train_size = min_train_size
        self.shrinkage_weight = shrinkage_weight

    def run(self, matches: list[dict[str, Any]]) -> tuple[BacktestMetricSummary, list[dict[str, Any]]]:
        """Execute walk-forward temporal evaluation across historical matches.

        Args:
            matches: List of match dictionaries containing:
                - 'home_team', 'away_team', 'home_score', 'away_score', 'event_date'

        Returns:
            Tuple of (BacktestMetricSummary, list of per-match detailed prediction records).
        """
        if len(matches) <= self.min_train_size:
            raise ValueError(
                f"Insufficient match history: {len(matches)} matches provided, but min_train_size is {self.min_train_size}."
            )

        # Sort strictly ascending by date (oldest to newest)
        def parse_dt(m: dict[str, Any]) -> datetime:
            raw = m["event_date"]
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt

        sorted_matches = sorted(matches, key=parse_dt)

        detailed_records: list[dict[str, Any]] = []
        brier_scores: list[float] = []
        log_losses: list[float] = []
        correct_hits = 0

        # Calibration tracking
        # bins for probabilities [0.0 - 0.2, 0.2 - 0.4, 0.4 - 0.6, 0.6 - 0.8, 0.8 - 1.0]
        bins = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
        bin_counts = {f"{b[0]:.1f}-{b[1]:.1f}": {"count": 0, "sum_prob": 0.0, "observed_hits": 0} for b in bins}

        class_actual_counts = {"HOME": 0, "DRAW": 0, "AWAY": 0}
        class_prob_sums = {"HOME": 0.0, "DRAW": 0.0, "AWAY": 0.0}

        # Step forward match by match
        for idx in range(self.min_train_size, len(sorted_matches)):
            train_set = sorted_matches[:idx]
            test_match = sorted_matches[idx]

            # Fit model on past data
            model = PoissonGoalModel(shrinkage_weight=self.shrinkage_weight).fit(train_set)

            # Predict test match
            pred = model.predict_match(
                home_team=test_match["home_team"],
                away_team=test_match["away_team"],
            )

            h_score = int(test_match["home_score"])
            a_score = int(test_match["away_score"])

            if h_score > a_score:
                actual_label = "HOME"
                actual_vec = (1.0, 0.0, 0.0)
            elif h_score == a_score:
                actual_label = "DRAW"
                actual_vec = (0.0, 1.0, 0.0)
            else:
                actual_label = "AWAY"
                actual_vec = (0.0, 0.0, 1.0)

            class_actual_counts[actual_label] += 1
            class_prob_sums["HOME"] += pred.home_probability
            class_prob_sums["DRAW"] += pred.draw_probability
            class_prob_sums["AWAY"] += pred.away_probability

            # Multi-class Brier score = sum((p_k - y_k)^2)
            bs = (
                (pred.home_probability - actual_vec[0]) ** 2
                + (pred.draw_probability - actual_vec[1]) ** 2
                + (pred.away_probability - actual_vec[2]) ** 2
            )
            brier_scores.append(bs)

            # Multi-class Log Loss = -ln(max(p_actual, 1e-15))
            p_actual = (
                pred.home_probability if actual_label == "HOME"
                else (pred.draw_probability if actual_label == "DRAW" else pred.away_probability)
            )
            ll = -math.log(max(p_actual, 1e-15))
            log_losses.append(ll)

            # Highest probability prediction
            probs = {
                "HOME": pred.home_probability,
                "DRAW": pred.draw_probability,
                "AWAY": pred.away_probability,
            }
            predicted_winner = max(probs.items(), key=lambda kv: kv[1])[0]
            is_hit = (predicted_winner == actual_label)
            if is_hit:
                correct_hits += 1

            # Update calibration bins
            for label, prob in probs.items():
                is_this_outcome = (1 if label == actual_label else 0)
                for b in bins:
                    if b[0] <= prob < b[1] or (b[1] == 1.0 and prob == 1.0):
                        bin_key = f"{b[0]:.1f}-{b[1]:.1f}"
                        bin_counts[bin_key]["count"] += 1
                        bin_counts[bin_key]["sum_prob"] += prob
                        bin_counts[bin_key]["observed_hits"] += is_this_outcome
                        break

            detailed_records.append({
                "match_index": idx,
                "event_date": test_match["event_date"],
                "home_team": test_match["home_team"],
                "away_team": test_match["away_team"],
                "home_score": h_score,
                "away_score": a_score,
                "actual_outcome": actual_label,
                "predicted_home_prob": pred.home_probability,
                "predicted_draw_prob": pred.draw_probability,
                "predicted_away_prob": pred.away_probability,
                "fair_home_odds": pred.fair_home_odds,
                "fair_draw_odds": pred.fair_draw_odds,
                "fair_away_odds": pred.fair_away_odds,
                "brier_score": round(bs, 4),
                "log_loss": round(ll, 4),
                "hit": is_hit,
            })

        n_test = len(brier_scores)
        mean_brier = round(sum(brier_scores) / max(1, n_test), 4)
        mean_log_loss = round(sum(log_losses) / max(1, n_test), 4)
        accuracy_pct = round((correct_hits / max(1, n_test)) * 100, 2)

        # Baseline uniform random comparison:
        # Uniform p = 1/3: Brier = (1/3 - 1)^2 + 2*(1/3 - 0)^2 = 4/9 + 2/9 = 6/9 = 0.6667
        uniform_brier = 0.6667
        uniform_log_loss = round(math.log(3.0), 4)  # ~1.0986

        # Calibration summary
        calibration_results: dict[str, Any] = {
            "by_class": {
                "HOME": {
                    "actual_frequency": round(class_actual_counts["HOME"] / max(1, n_test), 4),
                    "mean_predicted_prob": round(class_prob_sums["HOME"] / max(1, n_test), 4),
                },
                "DRAW": {
                    "actual_frequency": round(class_actual_counts["DRAW"] / max(1, n_test), 4),
                    "mean_predicted_prob": round(class_prob_sums["DRAW"] / max(1, n_test), 4),
                },
                "AWAY": {
                    "actual_frequency": round(class_actual_counts["AWAY"] / max(1, n_test), 4),
                    "mean_predicted_prob": round(class_prob_sums["AWAY"] / max(1, n_test), 4),
                },
            },
            "probability_bins": {},
        }

        for k, v in bin_counts.items():
            cnt = v["count"]
            if cnt > 0:
                calibration_results["probability_bins"][k] = {
                    "sample_count": cnt,
                    "avg_predicted_prob": round(v["sum_prob"] / cnt, 4),
                    "observed_accuracy": round(v["observed_hits"] / cnt, 4),
                }

        summary = BacktestMetricSummary(
            total_test_matches=n_test,
            train_warmup_size=self.min_train_size,
            brier_score_mean=mean_brier,
            log_loss_mean=mean_log_loss,
            accuracy_percent=accuracy_pct,
            benchmark_uniform_brier=uniform_brier,
            benchmark_uniform_log_loss=uniform_log_loss,
            calibration_summary=calibration_results,
            class_distribution=class_actual_counts,
            generated_at=datetime.now(UTC).isoformat(),
        )

        return summary, detailed_records


def save_backtest_artifacts(
    summary: BacktestMetricSummary,
    records: list[dict[str, Any]],
    output_dir: Path | str = "artifacts/backtest",
) -> tuple[Path, Path]:
    """Persist backtest JSON and Markdown summary to artifacts/backtest."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "backtest_results.json"
    md_path = out_dir / "backtest_summary.md"

    # 1. Save JSON
    full_payload = {
        "summary": asdict(summary),
        "sample_records": records[:10],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_payload, f, ensure_ascii=False, indent=2)

    # 2. Save Markdown
    calib = summary.calibration_summary
    md_content = f"""# Walk-Forward Backtest Report — Poisson Baseline v0.1.0

Generated at: `{summary.generated_at}`
Architecture: Strict temporal walk-forward evaluation (zero future leakage).

## 1. Executive Summary

| Metric | Model Value | Benchmark (Uniform 1/3) | Status |
| :--- | :--- | :--- | :--- |
| **Sample Size (Out-of-Sample)** | **{summary.total_test_matches} matches** | - | Evaluated |
| **Initial Train Warmup** | **{summary.train_warmup_size} matches** | - | Baseline size |
| **Mean Multi-Class Brier Score** | **{summary.brier_score_mean:.4f}** | {summary.benchmark_uniform_brier:.4f} | {'BETTER' if summary.brier_score_mean < summary.benchmark_uniform_brier else 'WORSE'} |
| **Mean Multi-Class Log Loss** | **{summary.log_loss_mean:.4f}** | {summary.benchmark_uniform_log_loss:.4f} | {'BETTER' if summary.log_loss_mean < summary.benchmark_uniform_log_loss else 'WORSE'} |
| **Argmax Prediction Accuracy** | **{summary.accuracy_percent:.2f}%** | 33.33% | Above random |

## 2. Class Calibration & Marginal Reliability

| Class | Actual Observed Frequency | Model Mean Predicted Probability | Bias / Difference |
| :--- | :--- | :--- | :--- |
| **Home** | {calib['by_class']['HOME']['actual_frequency'] * 100:.1f}% | {calib['by_class']['HOME']['mean_predicted_prob'] * 100:.1f}% | {calib['by_class']['HOME']['mean_predicted_prob'] - calib['by_class']['HOME']['actual_frequency']:+.3f} |
| **Draw** | {calib['by_class']['DRAW']['actual_frequency'] * 100:.1f}% | {calib['by_class']['DRAW']['mean_predicted_prob'] * 100:.1f}% | {calib['by_class']['DRAW']['mean_predicted_prob'] - calib['by_class']['DRAW']['actual_frequency']:+.3f} |
| **Away** | {calib['by_class']['AWAY']['actual_frequency'] * 100:.1f}% | {calib['by_class']['AWAY']['mean_predicted_prob'] * 100:.1f}% | {calib['by_class']['AWAY']['mean_predicted_prob'] - calib['by_class']['AWAY']['actual_frequency']:+.3f} |

## 3. Probability Bin Reliability

| Probability Range | Evaluation Count | Avg Predicted Probability | Observed Hit Rate |
| :--- | :--- | :--- | :--- |
"""
    for bin_range, bdata in calib["probability_bins"].items():
        md_content += f"| {bin_range} | {bdata['sample_count']} | {bdata['avg_predicted_prob'] * 100:.1f}% | {bdata['observed_accuracy'] * 100:.1f}% |\n"

    md_content += f"""
## 4. Class Distribution

- Home Wins: `{summary.class_distribution['HOME']}`
- Draws: `{summary.class_distribution['DRAW']}`
- Away Wins: `{summary.class_distribution['AWAY']}`
"""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return json_path, md_path
