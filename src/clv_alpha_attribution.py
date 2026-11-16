"""Closing Line Value (CLV) Decomposition & Alpha Attribution Engine (v1.0).

Wall Street standard quantitative performance attribution for algorithmic sports trading:
Decomposes realized and paper portfolio alpha into two orthogonal return drivers:
  1. Stale Line Execution Alpha (Alpha_Stale): Edge derived from soft bookmaker latency
     relative to Pinnacle sharp market consensus at bet placement time.
     Alpha_Stale = (O_soft / O_sharp_entry) - 1.0

  2. Information / Directional Alpha (Alpha_Info): Edge derived from post-bet market movement
     towards our quantitative predictions (Dixon-Coles & Negative Binomial agreement).
     Alpha_Info = (O_sharp_entry / O_sharp_close) - 1.0

Synergy Identity:
  (1 + Alpha_Stale) * (1 + Alpha_Info) - 1.0 == Alpha_Total_CLV

Enforces SPEC-0012 fail-closed validation on all odds and exports actionable JSON analytics.
"""

from __future__ import annotations

import csv
import json
import logging
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from atomic_io import atomic_write_json
except ImportError:
    from src.atomic_io import atomic_write_json

try:
    from closing_line_freeze import ClosingLineStore
except ImportError:
    from src.closing_line_freeze import ClosingLineStore

logger = logging.getLogger("CLVAlphaAttribution")

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REPORT_PATH = ROOT_DIR / "output" / "clv_alpha_report.json"
DEFAULT_LEDGER_PATH = ROOT_DIR / "output" / "paper_trading_ledger.json"
DEFAULT_LEDGER_CSV_PATH = ROOT_DIR / "output" / "paper_trading_ledger.csv"


@dataclass
class TradeAlphaDecomposition:
    """Individual trade alpha breakdown."""
    trade_id: str
    fixture_id: str
    match_name: str
    selection: str
    market: str
    soft_odds: float
    sharp_entry_odds: float
    sharp_closing_odds: float
    stale_alpha_pct: float
    info_alpha_pct: float
    total_clv_pct: float
    synergy_identity_error: float
    beat_closing: bool
    primary_driver: str
    placed_at_utc: str | None = None


@dataclass
class PortfolioAlphaReport:
    """Aggregated portfolio alpha attribution metrics."""
    total_analyzed_trades: int
    beat_closing_count: int
    beat_closing_rate_pct: float
    mean_total_clv_pct: float
    mean_stale_alpha_pct: float
    mean_info_alpha_pct: float
    stale_alpha_contribution_pct: float
    info_alpha_contribution_pct: float
    statistical_edge_verified: bool
    trades: list[TradeAlphaDecomposition]
    generated_at_utc: str


class CLVAlphaAttributionEngine:
    """Quantitative CLV & Alpha Attribution Engine."""

    def __init__(self, closing_store: ClosingLineStore | None = None) -> None:
        self.closing_store = closing_store or ClosingLineStore()

    def decompose_trade(
        self,
        trade_id: str,
        fixture_id: str,
        match_name: str,
        selection: str,
        market: str,
        soft_odds: float,
        sharp_entry_odds: float,
        sharp_closing_odds: float,
        placed_at_utc: str | None = None,
    ) -> TradeAlphaDecomposition:
        """Decompose a single trade's Closing Line Value into Stale Alpha and Info Alpha.

        Constitutional Compliance:
        - SPEC-0012: Fail-closed if any odds <= 1.0 or non-finite.
        """
        for name, val in [
            ("soft_odds", soft_odds),
            ("sharp_entry_odds", sharp_entry_odds),
            ("sharp_closing_odds", sharp_closing_odds),
        ]:
            if not (isinstance(val, (int, float)) and math.isfinite(val) and val > 1.0):
                raise ValueError(f"SPEC-0012 Violation: {name} must be strictly > 1.0 and finite (got {val!r}).")

        # 1. Stale Line Alpha: (O_soft / O_sharp_entry) - 1.0
        stale_alpha = (soft_odds / sharp_entry_odds) - 1.0

        # 2. Information / Predictive Alpha: (O_sharp_entry / O_sharp_close) - 1.0
        info_alpha = (sharp_entry_odds / sharp_closing_odds) - 1.0

        # 3. Total CLV: (O_soft / O_sharp_close) - 1.0
        total_clv = (soft_odds / sharp_closing_odds) - 1.0

        # 4. Multiplicative Identity Verification: (1 + stale) * (1 + info) - 1 == total_clv
        identity_check = ((1.0 + stale_alpha) * (1.0 + info_alpha)) - 1.0
        synergy_error = round(abs(total_clv - identity_check), 6)

        beat_closing = bool(total_clv > 0.0)
        primary_driver = "STALE_LINE_LATENCY" if stale_alpha >= info_alpha else "INFORMATION_MODEL_ALPHA"

        return TradeAlphaDecomposition(
            trade_id=str(trade_id),
            fixture_id=str(fixture_id),
            match_name=str(match_name),
            selection=str(selection),
            market=str(market),
            soft_odds=round(float(soft_odds), 3),
            sharp_entry_odds=round(float(sharp_entry_odds), 3),
            sharp_closing_odds=round(float(sharp_closing_odds), 3),
            stale_alpha_pct=round(stale_alpha * 100.0, 2),
            info_alpha_pct=round(info_alpha * 100.0, 2),
            total_clv_pct=round(total_clv * 100.0, 2),
            synergy_identity_error=synergy_error,
            beat_closing=beat_closing,
            primary_driver=primary_driver,
            placed_at_utc=placed_at_utc,
        )

    def evaluate_trades(
        self,
        trades: list[dict[str, Any]],
    ) -> PortfolioAlphaReport:
        """Aggregate alpha attribution across a batch or historical ledger of trades."""
        decompositions: list[TradeAlphaDecomposition] = []

        for t in trades:
            tr_id = str(t.get("id") or t.get("trade_id") or t.get("signal_id") or "UNKNOWN")
            fix_id = str(t.get("fixture_id") or t.get("event_id") or "")
            m_name = str(t.get("match_name") or f"{t.get('home', '')} vs {t.get('away', '')}")
            sel = str(t.get("selection") or t.get("outcome") or "1")
            mkt = str(t.get("market") or "1X2")

            try:
                soft_odd = float(t.get("soft_odds") or t.get("odds") or 0.0)
            except (ValueError, TypeError):
                soft_odd = 0.0
            try:
                entry_sharp = float(
                    t.get("sharp_entry_odds")
                    or t.get("fair_odds")
                    or t.get("shin_fair_odds")
                    or t.get("pinnacle_odds_at_bet")
                    or 0.0
                )
            except (ValueError, TypeError):
                entry_sharp = 0.0
            try:
                close_sharp = float(
                    t.get("sharp_closing_odds")
                    or t.get("latest_pinnacle_fair_odds")
                    or 0.0
                )
            except (ValueError, TypeError):
                close_sharp = 0.0

            # If closing odds are not in trade dict, look up in immutable ClosingLineStore
            if close_sharp <= 1.0 and fix_id:
                rec = self.closing_store.get_record(fix_id, mkt)
                if rec and sel in rec.fair_closing_odds:
                    close_sharp = rec.fair_closing_odds[sel]
                elif rec and sel in rec.closing_odds:
                    close_sharp = rec.closing_odds[sel]

            # If entry sharp is not explicitly stored, derive from fair odds or bookmaker consensus
            if entry_sharp <= 1.0:
                try:
                    entry_sharp = float(t.get("fair_odds_shin") or t.get("fair_odds") or soft_odd)
                except (ValueError, TypeError):
                    entry_sharp = soft_odd

            # Skip incomplete trades (fail-closed)
            if soft_odd <= 1.0 or entry_sharp <= 1.0 or close_sharp <= 1.0:
                continue

            try:
                decomp = self.decompose_trade(
                    trade_id=tr_id,
                    fixture_id=fix_id,
                    match_name=m_name,
                    selection=sel,
                    market=mkt,
                    soft_odds=soft_odd,
                    sharp_entry_odds=entry_sharp,
                    sharp_closing_odds=close_sharp,
                    placed_at_utc=t.get("timestamp_utc") or t.get("placed_at_utc") or t.get("captured_at_utc"),
                )
                decompositions.append(decomp)
            except Exception as e:
                logger.debug(f"Could not decompose trade {tr_id}: {e}")

        total_trades = len(decompositions)
        if total_trades == 0:
            return PortfolioAlphaReport(
                total_analyzed_trades=0,
                beat_closing_count=0,
                beat_closing_rate_pct=0.0,
                mean_total_clv_pct=0.0,
                mean_stale_alpha_pct=0.0,
                mean_info_alpha_pct=0.0,
                stale_alpha_contribution_pct=0.0,
                info_alpha_contribution_pct=0.0,
                statistical_edge_verified=False,
                trades=[],
                generated_at_utc=datetime.now(UTC).isoformat(),
            )

        beat_count = sum(1 for d in decompositions if d.beat_closing)
        beat_rate = round((beat_count / total_trades) * 100.0, 2)

        mean_total = round(sum(d.total_clv_pct for d in decompositions) / total_trades, 2)
        mean_stale = round(sum(d.stale_alpha_pct for d in decompositions) / total_trades, 2)
        mean_info = round(sum(d.info_alpha_pct for d in decompositions) / total_trades, 2)

        # Relative contribution to net positive alpha
        denom = abs(mean_stale) + abs(mean_info)
        if denom > 0:
            stale_share = round((abs(mean_stale) / denom) * 100.0, 1)
            info_share = round((abs(mean_info) / denom) * 100.0, 1)
        else:
            stale_share, info_share = 50.0, 50.0

        # Verified edge if average CLV > +2.0% and Beat Closing Rate >= 55%
        is_verified = bool(mean_total >= 2.0 and beat_rate >= 55.0)

        return PortfolioAlphaReport(
            total_analyzed_trades=total_trades,
            beat_closing_count=beat_count,
            beat_closing_rate_pct=beat_rate,
            mean_total_clv_pct=mean_total,
            mean_stale_alpha_pct=mean_stale,
            mean_info_alpha_pct=mean_info,
            stale_alpha_contribution_pct=stale_share,
            info_alpha_contribution_pct=info_share,
            statistical_edge_verified=is_verified,
            trades=decompositions,
            generated_at_utc=datetime.now(UTC).isoformat(),
        )

    def generate_and_export_report(
        self,
        ledger_path: Path | None = None,
        output_path: Path | None = None,
    ) -> PortfolioAlphaReport:
        """Load trade ledger (JSON or CSV), compute alpha attribution, and atomically persist report to disk."""
        l_path = ledger_path or (
            DEFAULT_LEDGER_PATH if DEFAULT_LEDGER_PATH.exists() else DEFAULT_LEDGER_CSV_PATH
        )
        out_path = output_path or DEFAULT_REPORT_PATH

        trades: list[dict[str, Any]] = []
        if l_path.exists():
            try:
                if l_path.suffix.lower() == ".csv":
                    with open(l_path, encoding="utf-8") as fh:
                        trades = list(csv.DictReader(fh))
                else:
                    data = json.loads(l_path.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        trades = data
                    elif isinstance(data, dict):
                        trades = data.get("trades", []) or data.get("signals", [])
            except Exception as e:
                logger.warning(f"Failed to read trade ledger from {l_path}: {e}")

        report = self.evaluate_trades(trades)

        try:
            out_dict = asdict(report)
            atomic_write_json(out_path, out_dict)
            logger.info(f"Successfully generated CLV Alpha Attribution Report at {out_path}")
        except Exception as e:
            logger.error(f"Failed to write CLV Alpha report: {e}")

        return report

