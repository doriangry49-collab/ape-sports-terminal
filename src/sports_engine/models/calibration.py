"""Model Probability Calibration Engine (TASK-016 & Milestone 2 Feature F6).

Corrects favorite-longshot bias and overconfidence in raw Poisson models:
- Underdog probabilities ([0.0, 0.2]) are recalibrated upwards (empirical win rate 24.8% vs 15.6% raw).
- Heavy favorite probabilities ([0.6, 0.8]) are compressed downwards (empirical win rate 56.6% vs 67.8% raw).
- Provides:
  1. LogisticProbabilityCalibrator (Platt Scaling & Logit Shrinkage)
  2. TemperatureScalingCalibrator (Softmax Entropy Smoothing)
  3. IsotonicProbabilityCalibrator (Pure-Python PAVA + Piecewise Linear Interpolation)
  4. Convenience pipeline functions for 1X2, Binary markets, and Score Grids.

Zero external dependencies: Pure Python (math, typing, dataclasses). No scipy/sklearn required.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


def _clamp(val: float, low: float = 1e-6, high: float = 1.0 - 1e-6) -> float:
    return max(low, min(high, float(val)))


def _logit(p: float) -> float:
    p_c = _clamp(p)
    return math.log(p_c / (1.0 - p_c))


def _sigmoid(z: float) -> float:
    if z >= 35.0:
        return 1.0
    if z <= -35.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


class LogisticProbabilityCalibrator:
    """Platt scaling and logit shrinkage calibrator for probabilities."""

    def __init__(
        self,
        shrinkage_a: float = 0.68,
        draw_bias_b: float = 0.08,
        home_bias_b: float = 0.0,
        away_bias_b: float = 0.0,
    ) -> None:
        self.a = float(shrinkage_a)
        self.b_draw = float(draw_bias_b)
        self.b_home = float(home_bias_b)
        self.b_away = float(away_bias_b)

    def calibrate_1x2(
        self, p_home: float, p_draw: float, p_away: float
    ) -> tuple[float, float, float]:
        """Recalibrate 1X2 probabilities using class-adjusted Platt scaling.

        Returns normalized tuple (p_home_cal, p_draw_cal, p_away_cal) summing strictly to 1.0.
        """
        z_h = self.a * _logit(p_home) + self.b_home
        z_d = self.a * _logit(p_draw) + self.b_draw
        z_a = self.a * _logit(p_away) + self.b_away

        s_h = _sigmoid(z_h)
        s_d = _sigmoid(z_d)
        s_a = _sigmoid(z_a)

        tot = s_h + s_d + s_a
        if tot <= 0.0:
            return round(1.0 / 3.0, 4), round(1.0 / 3.0, 4), round(1.0 / 3.0, 4)

        return round(s_h / tot, 4), round(s_d / tot, 4), round(s_a / tot, 4)

    def calibrate_binary(self, p: float, bias: float = 0.0) -> float:
        """Recalibrate single or binary outcome probability (Totals, BTTS, etc.)."""
        z = self.a * _logit(p) + bias
        return round(_sigmoid(z), 4)


class TemperatureScalingCalibrator:
    """Softmax temperature scaling calibrator for multi-class probability vectors."""

    def __init__(self, temperature: float = 1.40) -> None:
        if temperature <= 0.0:
            raise ValueError(f"Temperature must be strictly positive, got {temperature}")
        self.temperature = float(temperature)

    def calibrate_1x2(
        self, p_home: float, p_draw: float, p_away: float
    ) -> tuple[float, float, float]:
        """Apply temperature scaling to 1X2 probabilities."""
        t = self.temperature
        zh = math.exp(math.log(_clamp(p_home)) / t)
        zd = math.exp(math.log(_clamp(p_draw)) / t)
        za = math.exp(math.log(_clamp(p_away)) / t)

        tot = zh + zd + za
        if tot <= 0.0:
            return 0.3333, 0.3333, 0.3334
        return round(zh / tot, 4), round(zd / tot, 4), round(za / tot, 4)


@dataclass(frozen=True)
class CalibrationKnot:
    x: float  # Uncalibrated raw probability
    y: float  # Empirical calibrated probability


class IsotonicProbabilityCalibrator:
    """Pure-Python monotonic Isotonic Calibrator using PAVA and piecewise linear interpolation."""

    # Default empirical knots established from TASK-016 out-of-sample Süper Lig audit
    DEFAULT_EMPIRICAL_KNOTS: tuple[CalibrationKnot, ...] = (
        CalibrationKnot(0.0000, 0.0200),
        CalibrationKnot(0.1556, 0.2479),
        CalibrationKnot(0.2836, 0.2797),
        CalibrationKnot(0.4854, 0.4690),
        CalibrationKnot(0.6784, 0.5660),
        CalibrationKnot(0.8500, 0.7200),
        CalibrationKnot(1.0000, 0.9500),
    )

    def __init__(self, knots: Sequence[CalibrationKnot] | None = None) -> None:
        if knots is not None:
            self.knots = tuple(sorted(knots, key=lambda k: k.x))
        else:
            self.knots = self.DEFAULT_EMPIRICAL_KNOTS

    @classmethod
    def fit_pava(
        cls,
        predicted_probs: Sequence[float],
        binary_outcomes: Sequence[float],
    ) -> IsotonicProbabilityCalibrator:
        """Fit isotonic regression from raw data using pure-Python PAVA without scikit-learn."""
        if len(predicted_probs) != len(binary_outcomes):
            raise ValueError("predicted_probs and binary_outcomes must have equal length.")
        if len(predicted_probs) == 0:
            return cls()

        # Sort by predicted probability
        sorted_pairs = sorted(zip(predicted_probs, binary_outcomes, strict=True), key=lambda item: item[0])
        x_vals = [p[0] for p in sorted_pairs]
        y_vals = [float(p[1]) for p in sorted_pairs]

        # PAVA block representation: [start_idx, end_idx, mean_y, count]
        blocks: list[list[float]] = [[i, i, y_vals[i], 1.0] for i in range(len(y_vals))]
        i = 0
        while i < len(blocks) - 1:
            if blocks[i][2] > blocks[i + 1][2]:
                w_new = blocks[i][3] + blocks[i + 1][3]
                y_new = (blocks[i][2] * blocks[i][3] + blocks[i + 1][2] * blocks[i + 1][3]) / w_new
                blocks[i] = [blocks[i][0], blocks[i + 1][1], y_new, w_new]
                blocks.pop(i + 1)
                while i > 0 and blocks[i - 1][2] > blocks[i][2]:
                    w_prev = blocks[i - 1][3] + blocks[i][3]
                    y_prev = (blocks[i - 1][2] * blocks[i - 1][3] + blocks[i][2] * blocks[i][3]) / w_prev
                    blocks[i - 1] = [blocks[i - 1][0], blocks[i][1], y_prev, w_prev]
                    blocks.pop(i)
                    i -= 1
            else:
                i += 1

        # Extract knot points
        knots = []
        for b in blocks:
            start_i = int(b[0])
            end_i = int(b[1])
            x_rep = (x_vals[start_i] + x_vals[end_i]) / 2.0
            knots.append(CalibrationKnot(round(x_rep, 4), round(b[2], 4)))

        # Ensure boundaries [0, 1]
        if not knots or knots[0].x > 0.0:
            first_y = knots[0].y if knots else 0.0
            knots.insert(0, CalibrationKnot(0.0, max(0.0, first_y)))
        if knots[-1].x < 1.0:
            last_y = knots[-1].y
            knots.append(CalibrationKnot(1.0, min(1.0, last_y)))

        return cls(knots=knots)

    def calibrate(self, p: float) -> float:
        """Recalibrate single probability via piecewise linear interpolation across knots."""
        p_c = max(0.0, min(1.0, float(p)))
        if p_c <= self.knots[0].x:
            return self.knots[0].y
        if p_c >= self.knots[-1].x:
            return self.knots[-1].y

        # Binary search or scan for interval [x_i, x_{i+1}]
        for i in range(len(self.knots) - 1):
            k1 = self.knots[i]
            k2 = self.knots[i + 1]
            if k1.x <= p_c <= k2.x:
                dx = k2.x - k1.x
                if dx <= 1e-9:
                    return k1.y
                t = (p_c - k1.x) / dx
                interp = k1.y + t * (k2.y - k1.y)
                return round(max(0.0, min(1.0, interp)), 4)

        return round(p_c, 4)

    def calibrate_1x2(
        self, p_home: float, p_draw: float, p_away: float
    ) -> tuple[float, float, float]:
        """Calibrate each component monotonically and re-normalize."""
        c_h = self.calibrate(p_home)
        c_d = self.calibrate(p_draw)
        c_a = self.calibrate(p_away)
        tot = c_h + c_d + c_a
        if tot <= 0.0:
            return 0.3333, 0.3333, 0.3334
        return round(c_h / tot, 4), round(c_d / tot, 4), round(c_a / tot, 4)


# Global default calibrators
_DEFAULT_LOGISTIC_CALIBRATOR = LogisticProbabilityCalibrator()
_DEFAULT_ISOTONIC_CALIBRATOR = IsotonicProbabilityCalibrator()
_DEFAULT_TEMP_CALIBRATOR = TemperatureScalingCalibrator()


def recalibrate_1x2(
    p_home: float,
    p_draw: float,
    p_away: float,
    method: str = "logistic",
) -> tuple[float, float, float]:
    """Recalibrate 1X2 match probabilities using the specified method ('logistic', 'temperature', 'isotonic')."""
    m = method.lower().strip()
    if m == "isotonic":
        return _DEFAULT_ISOTONIC_CALIBRATOR.calibrate_1x2(p_home, p_draw, p_away)
    if m == "temperature":
        return _DEFAULT_TEMP_CALIBRATOR.calibrate_1x2(p_home, p_draw, p_away)
    return _DEFAULT_LOGISTIC_CALIBRATOR.calibrate_1x2(p_home, p_draw, p_away)


def recalibrate_binary(p: float, method: str = "logistic") -> float:
    """Recalibrate a binary market probability (Over/Under, BTTS, etc.)."""
    m = method.lower().strip()
    if m == "isotonic":
        return _DEFAULT_ISOTONIC_CALIBRATOR.calibrate(p)
    return _DEFAULT_LOGISTIC_CALIBRATOR.calibrate_binary(p)


def recalibrate_score_grid(
    score_matrix: dict[tuple[int, int], float],
    temperature: float = 1.25,
) -> dict[tuple[int, int], float]:
    """Smooth joint scoreline probabilities with temperature scaling, preserving sum = 1.0."""
    t = max(0.1, float(temperature))
    scaled = {}
    for score, prob in score_matrix.items():
        scaled[score] = math.exp(math.log(_clamp(prob)) / t)

    tot = sum(scaled.values())
    if tot <= 0.0:
        return score_matrix
    return {score: round(val / tot, 6) for score, val in scaled.items()}
