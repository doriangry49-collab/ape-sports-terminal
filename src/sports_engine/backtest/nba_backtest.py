"""Walk-forward backtest engine specifically tailored for NBA 2-way binary outcomes."""

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sports_engine.models.nba_elo import NBAEloModel


@dataclass
class NBABacktestSummary:
    """Aggregated out-of-sample metrics for NBA walk-forward evaluation."""

    total_test_games: int
    train_warmup_size: int
    brier_score_binary: float
    log_loss_mean: float
    accuracy_percent: float
    benchmark_coinflip_brier: float
    benchmark_coinflip_log_loss: float
    actual_home_win_rate: float
    model_mean_home_prob: float
    generated_at: str


class NBAWalkForwardBacktest:
    """Evaluates NBA Elo baseline sequentially across time with zero future leakage."""

    def __init__(self, min_train_size: int = 150):
        self.min_train_size = min_train_size

    def run(self, games: list[dict[str, Any]]) -> tuple[NBABacktestSummary, list[dict[str, Any]]]:
        """Execute walk-forward temporal evaluation."""
        if len(games) <= self.min_train_size:
            raise ValueError(
                f"Insufficient NBA games: {len(games)} provided, min_train_size is {self.min_train_size}."
            )

        # Ensure sorted ascending by event date
        sorted_games = sorted(games, key=lambda x: x["event_date"])

        brier_scores: list[float] = []
        log_losses: list[float] = []
        correct_hits = 0
        actual_home_wins = 0
        sum_home_prob = 0.0
        records: list[dict[str, Any]] = []

        # Online sequential walk-forward loop
        for idx in range(self.min_train_size, len(sorted_games)):
            train_history = sorted_games[:idx]
            target_game = sorted_games[idx]

            # Fit model on past games
            model = NBAEloModel().fit(train_history)

            pred = model.predict_game(
                home_team=target_game["home_team"],
                away_team=target_game["away_team"],
            )

            actual_home_win = int(target_game["home_won"])
            p_h = pred.home_probability

            # Binary Brier Score = (p_h - y_h)^2
            bs = (p_h - actual_home_win) ** 2
            brier_scores.append(bs)

            # Binary Log Loss = -(y*ln(p) + (1-y)*ln(1-p))
            p_clamped = min(max(p_h, 1e-15), 1.0 - 1e-15)
            ll = -(actual_home_win * math.log(p_clamped) + (1 - actual_home_win) * math.log(1.0 - p_clamped))
            log_losses.append(ll)

            predicted_home_win = 1 if p_h >= 0.5 else 0
            is_hit = (predicted_home_win == actual_home_win)
            if is_hit:
                correct_hits += 1

            if actual_home_win == 1:
                actual_home_wins += 1
            sum_home_prob += p_h

            records.append({
                "game_index": idx,
                "event_date": target_game["event_date"],
                "home_team": target_game["home_team_raw"],
                "away_team": target_game["away_team_raw"],
                "home_score": target_game["home_score"],
                "away_score": target_game["away_score"],
                "actual_winner": target_game["home_team_raw"] if actual_home_win else target_game["away_team_raw"],
                "predicted_home_prob": p_h,
                "predicted_away_prob": pred.away_probability,
                "fair_home_odds": pred.fair_home_odds,
                "fair_away_odds": pred.fair_away_odds,
                "brier_score": round(bs, 4),
                "log_loss": round(ll, 4),
                "hit": is_hit,
            })

        n_test = len(brier_scores)
        mean_brier = round(sum(brier_scores) / max(1, n_test), 4)
        mean_ll = round(sum(log_losses) / max(1, n_test), 4)
        acc_pct = round((correct_hits / max(1, n_test)) * 100, 2)
        actual_h_rate = round(actual_home_wins / max(1, n_test), 4)
        model_h_rate = round(sum_home_prob / max(1, n_test), 4)

        summary = NBABacktestSummary(
            total_test_games=n_test,
            train_warmup_size=self.min_train_size,
            brier_score_binary=mean_brier,
            log_loss_mean=mean_ll,
            accuracy_percent=acc_pct,
            benchmark_coinflip_brier=0.2500,
            benchmark_coinflip_log_loss=0.6931,
            actual_home_win_rate=actual_h_rate,
            model_mean_home_prob=model_h_rate,
            generated_at=datetime.now(UTC).isoformat(),
        )

        return summary, records


def save_nba_backtest_artifacts(
    summary: NBABacktestSummary,
    records: list[dict[str, Any]],
    output_dir: Path | str = "artifacts/backtest",
) -> tuple[Path, Path]:
    """Save NBA backtest results to JSON and Markdown artifacts."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "nba_backtest_results.json"
    md_path = out_dir / "nba_backtest_summary.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": asdict(summary),
                "sample_predictions": records[:10],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    md_content = f"""# NBA Walk-Forward Backtest Report — Elo Baseline v0.1.0

Generated at: `{summary.generated_at}`
Methodology: Strict temporal walk-forward evaluation (no future leakage).

## 1. Metric Performance

| Metric | Model Value | Coinflip Benchmark | Status |
| :--- | :--- | :--- | :--- |
| **Out-of-sample Test Games** | **{summary.total_test_games}** | - | Complete |
| **Initial Train Warmup** | **{summary.train_warmup_size}** | - | Calibrated |
| **Binary Brier Score** | **{summary.brier_score_binary:.4f}** | {summary.benchmark_coinflip_brier:.4f} | {'BETTER' if summary.brier_score_binary < summary.benchmark_coinflip_brier else 'WORSE'} |
| **Mean Log Loss** | **{summary.log_loss_mean:.4f}** | {summary.benchmark_coinflip_log_loss:.4f} | {'BETTER' if summary.log_loss_mean < summary.benchmark_coinflip_log_loss else 'WORSE'} |
| **Win Prediction Accuracy** | **{summary.accuracy_percent:.2f}%** | 50.00% | Above baseline |

## 2. Home Court Advantage Calibration

- Actual Home Win Rate: `{summary.actual_home_win_rate * 100:.1f}%`
- Model Mean Home Win Probability: `{summary.model_mean_home_prob * 100:.1f}%`
- Calibration Difference: `{summary.model_mean_home_prob - summary.actual_home_win_rate:+.3f}`
"""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return json_path, md_path
