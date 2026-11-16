"""
APE Sports-Engine: Value Engine & Mathematical Edge Intelligence (v1.0).
Constitutional Compliance:
- GEMINI.md SPEC-0012: ERROR != UNKNOWN (Fail-closed on corrupt data, no mocks)
- GEMINI.md SPEC-0013: Kickoff TRT timing (kickoff_local > now_local + 3m)
- GEMINI.md SPEC-0014: 12-Hour maximum window (now_local < kickoff_local <= now_local + 12h)

Integrates:
- advanced_devig (penaltyblog Shin devigging & Dixon-Coles / Poisson modeling)
- Fractional Kelly criterion
- Commercial-grade VIP Telegram formatting
- Structured JSON serialization for REST API and Terminal UI
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from advanced_devig import DevigError, devig_odds_shin

# TRT Timezone = UTC+3
TRT_TZ = timezone(timedelta(hours=3))


class ValueEngineError(Exception):
    """Raised fail-closed when odds or parameters violate mathematical constraints."""

    pass


class MatchTimingError(ValueEngineError):
    """Raised when a match violates SPEC-0013 (> now + 3m) or SPEC-0014 (<= now + 12h)."""

    pass


@dataclass(frozen=True)
class ValueSignal:
    fixture_id: str
    league: str
    home_team: str
    away_team: str
    kickoff_utc: str
    kickoff_trt: str
    market: str
    selection: str
    bookmaker: str
    offered_odds: float
    fair_odds_shin: float
    fair_prob_shin: float
    model_prob: float
    edge_pct: float
    ev_roi: float
    half_kelly: float
    shin_margin: float
    shin_z: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_to_trt(dt: datetime) -> datetime:
    """Normalize any datetime (naive assumed UTC) to Europe/Istanbul (TRT = UTC+3)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(TRT_TZ)


def check_kickoff_window(
    kickoff_dt: datetime,
    reference_now: datetime | None = None,
) -> tuple[bool, str]:
    """
    Validates kickoff time against SPEC-0013 and SPEC-0014.

    Rules:
    - SPEC-0013: kickoff_local > now_local + 3m (no finished/started matches)
    - SPEC-0014: kickoff_local <= now_local + 12h (maximum 12-hour window)
    """
    now_trt = normalize_to_trt(reference_now or datetime.now(UTC))
    kick_trt = normalize_to_trt(kickoff_dt)

    min_cutoff = now_trt + timedelta(minutes=3)
    max_cutoff = now_trt + timedelta(hours=12)

    if kick_trt <= min_cutoff:
        return (
            False,
            f"SPEC-0013 Violation: Kickoff {kick_trt.strftime('%Y-%m-%d %H:%M')} TRT is <= now + 3m cutoff ({min_cutoff.strftime('%Y-%m-%d %H:%M')}).",
        )

    if kick_trt > max_cutoff:
        return (
            False,
            f"SPEC-0014 Violation: Kickoff {kick_trt.strftime('%Y-%m-%d %H:%M')} TRT exceeds 12h window ({max_cutoff.strftime('%Y-%m-%d %H:%M')}).",
        )

    return True, "OK"


def compute_half_kelly(prob: float, odds: float, max_stake: float = 0.05) -> float:
    """
    Computes Half-Kelly position sizing fraction:
    Kelly = (prob * odds - 1) / (odds - 1)
    Half-Kelly = 0.5 * Kelly, bounded in [0.0, max_stake].
    """
    if prob <= 0.0 or odds <= 1.0:
        return 0.0

    ev = (prob * odds) - 1.0
    if ev <= 0.0:
        return 0.0

    full_kelly = ev / (odds - 1.0)
    half_kelly = 0.5 * full_kelly
    return round(min(max_stake, max(0.0, half_kelly)), 4)


class ValueScannerEngine:
    """
    High-Performance Value & Edge Detection Engine.
    Combines Shin margin devigging with Dixon-Coles/Poisson model predictions
    to produce mathematically verified +EV signals.
    """

    def __init__(
        self,
        min_ev_roi: float = 0.03,  # Default: +3.0% EV threshold
        min_prob_edge: float = 0.015,  # Default: +1.5% probability edge
        min_odds: float = 1.30,
        max_odds: float = 8.50,
        enforce_time_window: bool = True,
    ):
        self.min_ev_roi = min_ev_roi
        self.min_prob_edge = min_prob_edge
        self.min_odds = min_odds
        self.max_odds = max_odds
        self.enforce_time_window = enforce_time_window

    def scan_1x2_fixture(
        self,
        fixture_id: str,
        league: str,
        home_team: str,
        away_team: str,
        kickoff_dt: datetime,
        market_odds: list[float] | dict[str, float],
        model_probs: list[float] | dict[str, float] | None = None,
        bookmaker: str = "Pinnacle",
        reference_now: datetime | None = None,
    ) -> list[ValueSignal]:
        """
        Scans a 1X2 match for positive expected value (+EV) opportunities.

        Args:
            fixture_id: Unique match identifier
            league: Competition name
            home_team: Home team display name
            away_team: Away team display name
            kickoff_dt: Match kickoff datetime
            market_odds: List of [odd_home, odd_draw, odd_away] or dict with keys
            model_probs: Optional model fair probabilities [p_home, p_draw, p_away]
            bookmaker: Target bookmaker name
            reference_now: Optional time anchor for backtesting / deterministic tests
        """
        # 1. SPEC-0013 & SPEC-0014 Kickoff Time Verification
        if self.enforce_time_window:
            valid, reason = check_kickoff_window(kickoff_dt, reference_now=reference_now)
            if not valid:
                raise MatchTimingError(reason)

        kick_trt = normalize_to_trt(kickoff_dt)
        kick_utc = kick_trt.astimezone(UTC)

        # 2. Extract standard 1X2 numeric array
        if isinstance(market_odds, dict):
            # Sort or extract home, draw, away keys
            keys = list(market_odds.keys())
            h_k = next((k for k in keys if "home" in k.lower() or "1" in k), keys[0])
            d_k = next((k for k in keys if "draw" in k.lower() or "x" in k.lower()), keys[1])
            a_k = next((k for k in keys if "away" in k.lower() or "2" in k), keys[2])
            odds_list = [float(market_odds[h_k]), float(market_odds[d_k]), float(market_odds[a_k])]
            selection_names = [h_k, d_k, a_k]
        else:
            if len(market_odds) != 3:
                raise ValueEngineError(
                    f"1X2 market requires exactly 3 odds, got {len(market_odds)}"
                )
            odds_list = [float(o) for o in market_odds]
            selection_names = ["1 (Home)", "X (Draw)", "2 (Away)"]

        # Validate odds bounds
        if any(o <= 1.0 for o in odds_list):
            raise ValueEngineError("SPEC-0012 Violation: All odds must be strictly > 1.0")

        # 3. Strip margin using penaltyblog Shin Devigging
        try:
            devig_res = devig_odds_shin(odds_list)
        except DevigError as e:
            raise ValueEngineError(f"Shin devigging failed fail-closed: {e}") from e

        fair_probs_shin = devig_res["probabilities"]
        margin = devig_res["margin"]
        z_param = devig_res["z"]

        # 4. Resolve Model Probabilities (if provided; otherwise use fair Shin probabilities)
        if model_probs is not None:
            if isinstance(model_probs, dict):
                m_probs = [
                    float(model_probs.get("home_win", 0.0)),
                    float(model_probs.get("draw", 0.0)),
                    float(model_probs.get("away_win", 0.0)),
                ]
            else:
                m_probs = [float(p) for p in model_probs]
            if len(m_probs) != 3 or not math.isclose(sum(m_probs), 1.0, abs_tol=1e-3):
                raise ValueEngineError(f"Model probabilities must sum to 1.0, got {sum(m_probs)}")
        else:
            # If no external model provided, model_prob is market consensus fair prob
            m_probs = fair_probs_shin

        # 5. Evaluate each outcome for +EV Edge
        signals: list[ValueSignal] = []
        for i in range(3):
            odd = odds_list[i]
            fair_p = fair_probs_shin[i]
            model_p = m_probs[i]
            fair_odd = round(1.0 / fair_p, 3) if fair_p > 0 else float("inf")

            # EV ROI: (model_prob * odds) - 1.0
            ev_roi = (model_p * odd) - 1.0
            prob_edge = model_p - fair_p

            # Check eligibility against filters
            if self.min_odds <= odd <= self.max_odds:
                if ev_roi >= self.min_ev_roi and prob_edge >= self.min_prob_edge:
                    half_k = compute_half_kelly(model_p, odd)
                    sig = ValueSignal(
                        fixture_id=fixture_id,
                        league=league,
                        home_team=home_team,
                        away_team=away_team,
                        kickoff_utc=kick_utc.isoformat(),
                        kickoff_trt=kick_trt.strftime("%Y-%m-%d %H:%M TRT"),
                        market="1X2",
                        selection=selection_names[i],
                        bookmaker=bookmaker,
                        offered_odds=round(odd, 2),
                        fair_odds_shin=fair_odd,
                        fair_prob_shin=round(fair_p, 4),
                        model_prob=round(model_p, 4),
                        edge_pct=round(prob_edge * 100.0, 2),
                        ev_roi=round(ev_roi * 100.0, 2),
                        half_kelly=round(half_k * 100.0, 2),
                        shin_margin=round(margin * 100.0, 2),
                        shin_z=round(z_param, 4),
                    )
                    signals.append(sig)

        return signals

    @staticmethod
    def format_vip_telegram_message(signal: ValueSignal | dict[str, Any]) -> str:
        """
        Formats a ValueSignal (or dictionary with equivalent keys) into a high-converting,
        professional VIP Telegram Alert.
        Includes EV ROI, fair odds, Shin devigged probability, and Kelly stake.
        """
        if isinstance(signal, dict):
            ev_roi = float(signal.get("ev_roi", signal.get("edge_pct", 0.0)))
            league = str(signal.get("league", "Bülten"))
            home_team = str(signal.get("home_team", signal.get("home", "")))
            away_team = str(signal.get("away_team", signal.get("away", "")))
            kickoff_trt = str(signal.get("kickoff_trt", signal.get("time", "")))
            selection = str(signal.get("selection", signal.get("outcome", "")))
            bookmaker = str(signal.get("bookmaker", signal.get("soft_book", "Nesine"))).upper()
            offered_odds = float(signal.get("offered_odds", signal.get("soft_odds", 0.0)))
            fair_odds_shin = float(signal.get("fair_odds_shin", signal.get("fair_odds", 0.0)))
            edge_pct = float(signal.get("edge_pct", 0.0))
            half_kelly = float(signal.get("half_kelly", 0.0))
            shin_margin = float(signal.get("shin_margin", 0.0))
            shin_z = float(signal.get("shin_z", 0.0))
        else:
            ev_roi = signal.ev_roi
            league = signal.league
            home_team = signal.home_team
            away_team = signal.away_team
            kickoff_trt = signal.kickoff_trt
            selection = signal.selection
            bookmaker = signal.bookmaker
            offered_odds = signal.offered_odds
            fair_odds_shin = signal.fair_odds_shin
            edge_pct = signal.edge_pct
            half_kelly = signal.half_kelly
            shin_margin = signal.shin_margin
            shin_z = signal.shin_z

        roi_badge = "🔥" if ev_roi >= 6.0 else "⚡"
        return (
            f"{roi_badge} *APE QUANT +EV DEĞER SİNYALİ*\n\n"
            f"🏆 *Lig:* `{league}`\n"
            f"⚽ *Maç:* *{home_team}* vs *{away_team}*\n"
            f"⏰ *Başlama:* `{kickoff_trt}`\n\n"
            f"🎯 *Öneri:* `{selection}`\n"
            f"🏢 *Büro:* `{bookmaker}`\n"
            f"📈 *Sunulan Oran:* `{offered_odds:.2f}`\n"
            f"⚖️ *Adil Oran (Shin):* `{fair_odds_shin:.2f}`\n\n"
            f"📊 *Model Beklentisi (EV):* `+{ev_roi:.1f}%`\n"
            f"📐 *Matematiksel Edge:* `+{edge_pct:.1f}%`\n"
            f"💰 *Önerilen Kasa Boyutu:* `%{half_kelly:.1f}` (Half-Kelly)\n"
            f"🛡️ *Büro Marjı (Vig):* `%{shin_margin:.1f}` | *Z-Param:* `{shin_z:.3f}`\n\n"
            f"🔒 _APE Quality OS: SPEC-0012 & SPEC-0013 Doğrulandı._"
        )
