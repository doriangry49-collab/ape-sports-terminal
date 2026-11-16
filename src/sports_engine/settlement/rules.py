"""TASK-020: Market Settlement Rules and Profit Calculation.

Pure, deterministic rule evaluator for supported betting markets.
Never guesses missing data; returns UNSETTLEABLE when data is incomplete.
"""

from __future__ import annotations

import re

from sports_engine.adapters.schema import CanonicalMarket
from sports_engine.settlement.domain import SettlementStatus


def calculate_flat_stake_profit(
    odds_decimal: float,
    status: SettlementStatus,
    stake: float = 1.0,
) -> tuple[float, float]:
    """Calculate realized profit and ROI on flat 1-unit stake.

    Returns:
        (profit, roi_percent)
        - WON: profit = (odds - 1) * stake
        - LOST: profit = -1.0 * stake
        - PUSH: profit = 0.0
        - PENDING/UNSETTLEABLE/CANCELLED: profit = 0.0
    """
    if status == SettlementStatus.WON:
        profit = round((odds_decimal - 1.0) * stake, 4)
        roi = round(((odds_decimal - 1.0) / 1.0) * 100.0, 2)
        return profit, roi
    elif status == SettlementStatus.LOST:
        profit = round(-1.0 * stake, 4)
        roi = -100.0
        return profit, roi
    elif status == SettlementStatus.PUSH:
        return 0.0, 0.0
    else:
        return 0.0, 0.0


def settle_1x2(
    selection: str,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
) -> SettlementStatus:
    """Evaluate Full-Time 1X2 market."""
    sel = selection.strip().upper()
    h_team = home_team.strip().upper()
    a_team = away_team.strip().upper()

    if home_score > away_score:
        actual_winner = "HOME"
    elif home_score == away_score:
        actual_winner = "DRAW"
    else:
        actual_winner = "AWAY"

    if sel in ("1", "HOME") or sel == h_team or h_team in sel:
        return SettlementStatus.WON if actual_winner == "HOME" else SettlementStatus.LOST
    elif sel in ("X", "DRAW") or "DRAW" in sel or "BERABER" in sel:
        return SettlementStatus.WON if actual_winner == "DRAW" else SettlementStatus.LOST
    elif sel in ("2", "AWAY") or sel == a_team or a_team in sel:
        return SettlementStatus.WON if actual_winner == "AWAY" else SettlementStatus.LOST

    return SettlementStatus.UNSETTLEABLE


def settle_correct_score(
    selection: str,
    home_score: int,
    away_score: int,
) -> SettlementStatus:
    """Evaluate Correct Score market. Strict exact score match."""
    sel = selection.strip().replace(":", "-").replace(" ", "")
    actual = f"{home_score}-{away_score}"

    # Match exact pattern x-y
    if sel == actual:
        return SettlementStatus.WON

    # Validate pattern
    if re.match(r"^\d+-\d+$", sel):
        return SettlementStatus.LOST

    return SettlementStatus.UNSETTLEABLE


def settle_totals(
    selection: str,
    home_score: int,
    away_score: int,
) -> SettlementStatus:
    """Evaluate Over/Under Totals market."""
    sel = selection.strip().lower()
    total_goals = home_score + away_score

    # Extract numerical line
    match = re.search(r"(\d+(\.\d+)?)", sel)
    if not match:
        return SettlementStatus.UNSETTLEABLE

    line = float(match.group(1))

    is_over = any(x in sel for x in ["over", "üst", "ust", ">"])
    is_under = any(x in sel for x in ["under", "alt", "<"])

    if not is_over and not is_under:
        return SettlementStatus.UNSETTLEABLE

    if total_goals > line:
        return SettlementStatus.WON if is_over else SettlementStatus.LOST
    elif total_goals < line:
        return SettlementStatus.WON if is_under else SettlementStatus.LOST
    else:
        # Integer line push
        return SettlementStatus.PUSH


def settle_btts(
    selection: str,
    home_score: int,
    away_score: int,
) -> SettlementStatus:
    """Evaluate Both Teams to Score (BTTS) market."""
    sel = selection.strip().lower()
    actual_btts = (home_score >= 1) and (away_score >= 1)

    is_yes = any(x in sel for x in ["yes", "var", "evet", "btts yes"])
    is_no = any(x in sel for x in ["no", "yok", "hayır", "btts no"])

    if not is_yes and not is_no:
        return SettlementStatus.UNSETTLEABLE

    if actual_btts:
        return SettlementStatus.WON if is_yes else SettlementStatus.LOST
    else:
        return SettlementStatus.WON if is_no else SettlementStatus.LOST


def settle_ht_1x2(
    selection: str,
    home_team: str,
    away_team: str,
    ht_home_score: int | None,
    ht_away_score: int | None,
) -> SettlementStatus:
    """Evaluate Half-Time 1X2 market."""
    if ht_home_score is None or ht_away_score is None:
        return SettlementStatus.UNSETTLEABLE

    return settle_1x2(selection, home_team, away_team, ht_home_score, ht_away_score)


def settle_ht_ft(
    selection: str,
    ht_home_score: int | None,
    ht_away_score: int | None,
    ft_home_score: int,
    ft_away_score: int,
) -> SettlementStatus:
    """Evaluate Half-Time / Full-Time (HT/FT) combination market."""
    if ht_home_score is None or ht_away_score is None:
        return SettlementStatus.UNSETTLEABLE

    sel = selection.strip().replace(" ", "").upper()

    ht_res = "1" if ht_home_score > ht_away_score else ("X" if ht_home_score == ht_away_score else "2")
    ft_res = "1" if ft_home_score > ft_away_score else ("X" if ft_home_score == ft_away_score else "2")
    actual_combo = f"{ht_res}/{ft_res}"

    if sel == actual_combo:
        return SettlementStatus.WON
    return SettlementStatus.LOST


def evaluate_selection_settlement(
    market: str,
    selection: str,
    home_team: str,
    away_team: str,
    home_score: int | None,
    away_score: int | None,
    ht_home_score: int | None = None,
    ht_away_score: int | None = None,
    is_finished: bool = False,
) -> SettlementStatus:
    """Master dispatcher to evaluate any supported market selection."""
    if not is_finished or home_score is None or away_score is None:
        return SettlementStatus.PENDING

    mkt = market.strip().upper()

    if mkt in (CanonicalMarket.H1X2.value, "1X2"):
        return settle_1x2(selection, home_team, away_team, home_score, away_score)

    elif mkt in (CanonicalMarket.CORRECT_SCORE.value, "CORRECT_SCORE"):
        return settle_correct_score(selection, home_score, away_score)

    elif mkt in (CanonicalMarket.TOTALS.value, "TOTALS"):
        return settle_totals(selection, home_score, away_score)

    elif mkt in (CanonicalMarket.BTTS.value, "BTTS"):
        return settle_btts(selection, home_score, away_score)

    elif mkt in (CanonicalMarket.H1_1X2.value, "H1_1X2"):
        return settle_ht_1x2(selection, home_team, away_team, ht_home_score, ht_away_score)

    elif mkt in (CanonicalMarket.HT_FT.value, "HT_FT"):
        return settle_ht_ft(selection, ht_home_score, ht_away_score, home_score, away_score)

    return SettlementStatus.UNSETTLEABLE
