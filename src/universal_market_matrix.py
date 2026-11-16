"""Universal Market Association & Odds Archetype Lookup Engine (v1.0).

Encapsulates empirical conditional distributions across 30,315 historical matches.
Maps any match's odds structure (1X2, Totals, Steam) into empirical expectations for:
- 1X2 probabilities
- Totals (2.5, 3.5, 6+)
- BTTS (KG Var / KG Yok)
- First Half (İY 0.5, İY 1.5)
- Corners (8.5, 9.5, 12+, Average)
- Cards (3.5, Average)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
MATRIX_JSON = ROOT_DIR / "output" / "universal_market_matrix.json"


@dataclass(frozen=True)
class UniversalOddsProfile:
    archetype: str
    home_band: str
    tempo_band: str
    steam_event: str
    # 1X2 Empirical %
    p_1: float
    p_x: float
    p_2: float
    # Goals Empirical %
    p_o25: float
    p_o35: float
    p_tg6: float
    p_btts: float
    p_iy05: float
    p_iy15: float
    avg_goals: float
    # Corners Empirical %
    avg_corners: float
    p_c85: float
    p_c95: float
    p_c12p: float
    # Cards Empirical %
    avg_cards: float


class UniversalMarketMatrix:
    """In-memory fast lookup engine for universal cross-market distributions with margin removal."""

    def __init__(self, matrix_path: Path | str | None = None) -> None:
        self.matrix_path = Path(matrix_path) if matrix_path else MATRIX_JSON
        self.data: dict[str, Any] = {}
        if self.matrix_path.exists():
            try:
                self.data = json.loads(self.matrix_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    @staticmethod
    def devig_1x2(o1: float, ox: float, o2: float) -> tuple[float, float, float]:
        """De-vig 3-way 1X2 odds to fair odds (margin = 0%)."""
        inv1 = 1.0 / max(1.01, float(o1))
        invx = 1.0 / max(1.01, float(ox))
        inv2 = 1.0 / max(1.01, float(o2))
        tot = inv1 + invx + inv2
        if tot <= 0:
            return o1, ox, o2
        return round(tot / inv1, 3), round(tot / invx, 3), round(tot / inv2, 3)

    @staticmethod
    def devig_2way(o_over: float, o_under: float) -> tuple[float, float]:
        """De-vig 2-way Over/Under odds to fair odds (margin = 0%)."""
        invo = 1.0 / max(1.01, float(o_over))
        invu = 1.0 / max(1.01, float(o_under))
        tot = invo + invu
        if tot <= 0:
            return o_over, o_under
        return round(tot / invo, 3), round(tot / invu, 3)

    @staticmethod
    def get_home_band(o1: float) -> str:
        if o1 <= 1.40:
            return "1. Ağır Favori (1.10-1.40)"
        if o1 <= 1.75:
            return "2. Güçlü Favori (1.41-1.75)"
        if o1 <= 2.20:
            return "3. Orta Favori (1.76-2.20)"
        if o1 <= 3.00:
            return "4. Dengeli Maç (2.21-3.00)"
        return "5. Ev Sürpriz / Plase (3.01+)"

    @staticmethod
    def get_tempo_band(o_o25: float) -> str:
        if o_o25 <= 1.40:
            return "1. Aşırı Yüksek Tempo (O2.5 <= 1.40)"
        if o_o25 <= 1.65:
            return "2. Yüksek Tempo (1.41-1.65)"
        if o_o25 <= 1.95:
            return "3. Standart Dengeli (1.66-1.95)"
        if o_o25 <= 2.30:
            return "4. Kısır / Alt Meyilli (1.96-2.30)"
        return "5. Aşırı Kısır (O2.5 > 2.30)"

    @staticmethod
    def get_archetype(o1: float, o2: float, o_o25: float) -> str:
        if o1 <= 1.45 and o_o25 <= 1.55:
            return "A. Büyük Takım Evinde & Tempolu (1 <= 1.45 & O2.5 <= 1.55)"
        if o1 <= 1.45 and o_o25 > 1.85:
            return "B. Büyük Takım Evinde & Savunmacı (1 <= 1.45 & O2.5 > 1.85)"
        if o1 >= 2.30 and o2 >= 2.30 and o_o25 <= 1.75:
            return "C. Denk İki Tempolu Takım (1X2 Dengeli & O2.5 <= 1.75)"
        if o1 >= 2.30 and o2 >= 2.30 and o_o25 >= 2.10:
            return "D. Denk İki Defansif Takım (1X2 Dengeli & O2.5 >= 2.10)"
        if o2 <= 1.50 and o_o25 <= 1.60:
            return "E. Güçlü Deplasman Baskısı (2 <= 1.50 & O2.5 <= 1.60)"
        return "F. Diğer Standart Eşleşmeler"

    @staticmethod
    def get_steam_event(steam_o25: float, steam_1: float, steam_2: float = 0.0) -> str:
        if steam_o25 <= -5.0:
            return "1. Üst Oranı Çöktü (Steam O2.5 <= -5%)"
        if steam_o25 >= 5.0:
            return "2. Üst Oranı Şişti / Alt Çöktü (Steam O2.5 >= +5%)"
        if steam_1 <= -7.0:
            return "3. Ev Sahibi Oranı Çöktü (Steam MS1 <= -7%)"
        if steam_2 <= -7.0:
            return "4. Deplasman Oranı Çöktü (Steam MS2 <= -7%)"
        return "5. Stabil Oranlar"

    def profile_fixture(
        self,
        o1: float,
        ox: float,
        o2: float,
        o_o25: float,
        o_u25: float = 2.0,
        steam_o25: float = 0.0,
        steam_1: float = 0.0,
        devig: bool = True,
    ) -> UniversalOddsProfile:
        """Lookup multi-market empirical profile for a fixture, de-vigging high-margin soft book odds first."""
        lookup_o1, lookup_ox, lookup_o2 = float(o1), float(ox), float(o2)
        lookup_o25, lookup_u25 = float(o_o25), float(o_u25)

        if devig:
            overround_1x2 = (1.0 / max(1.01, lookup_o1)) + (1.0 / max(1.01, lookup_ox)) + (1.0 / max(1.01, lookup_o2))
            if overround_1x2 > 1.08:
                f1, fx, f2 = self.devig_1x2(lookup_o1, lookup_ox, lookup_o2)
                # Scale to historical European opening benchmark (~4.5% overround)
                lookup_o1 = round(f1 / 1.045, 3)
                lookup_ox = round(fx / 1.045, 3)
                lookup_o2 = round(f2 / 1.045, 3)

            overround_ou = (1.0 / max(1.01, lookup_o25)) + (1.0 / max(1.01, lookup_u25))
            if overround_ou > 1.08:
                fo, fu = self.devig_2way(lookup_o25, lookup_u25)
                lookup_o25 = round(fo / 1.045, 3)
                lookup_u25 = round(fu / 1.045, 3)

        h_band = self.get_home_band(lookup_o1)
        t_band = self.get_tempo_band(lookup_o25)
        arch = self.get_archetype(lookup_o1, lookup_o2, lookup_o25)
        st_ev = self.get_steam_event(steam_o25, steam_1)

        # Baseline fallback values
        p_1, p_x, p_2 = 45.0, 27.0, 28.0
        p_o25, p_o35, p_tg6 = 50.0, 28.0, 5.5
        p_btts, p_iy05, p_iy15 = 52.0, 70.0, 33.0
        avg_goals = 2.70
        avg_corners = 9.80
        p_c85, p_c95, p_c12p = 63.0, 51.0, 29.0
        avg_cards = 4.40

        # Refine from tempo band
        for tb in self.data.get("ou_bands", []):
            if tb.get("tempo_band") == t_band:
                avg_goals = float(tb.get("avg_goals", avg_goals))
                p_o25 = float(tb.get("o25_pct", p_o25))
                p_o35 = float(tb.get("o35_pct", p_o35))
                p_tg6 = float(tb.get("tg6_pct", p_tg6))
                p_btts = float(tb.get("btts_pct", p_btts))
                p_iy15 = float(tb.get("iy15_pct", p_iy15))
                avg_corners = float(tb.get("avg_corners", avg_corners))
                p_c85 = float(tb.get("c85_pct", p_c85))
                p_c95 = float(tb.get("c95_pct", p_c95))
                p_c12p = float(tb.get("c12_pct", p_c12p))
                avg_cards = float(tb.get("avg_cards", avg_cards))
                break

        # Refine 1X2 from home band
        for hb in self.data.get("home_bands", []):
            if hb.get("home_band") == h_band:
                p_1 = float(hb.get("ms_1_pct", p_1))
                p_x = float(hb.get("ms_x_pct", p_x))
                p_2 = float(hb.get("ms_2_pct", p_2))
                p_iy05 = float(hb.get("iy05_pct", p_iy05))
                break

        # Refine from archetype if specific
        for cb in self.data.get("combos", []):
            if cb.get("archetype") == arch and not arch.startswith("F."):
                p_1 = float(cb.get("ms_1_pct", p_1))
                p_2 = float(cb.get("ms_2_pct", p_2))
                p_x = round(100.0 - (p_1 + p_2), 1)
                p_o25 = float(cb.get("o25_pct", p_o25))
                p_btts = float(cb.get("btts_pct", p_btts))
                p_iy15 = float(cb.get("iy15_pct", p_iy15))
                avg_corners = float(cb.get("avg_corners", avg_corners))
                p_c95 = float(cb.get("c95_pct", p_c95))
                p_c12p = float(cb.get("c12_pct", p_c12p))
                avg_cards = float(cb.get("avg_cards", avg_cards))
                break

        return UniversalOddsProfile(
            archetype=arch,
            home_band=h_band,
            tempo_band=t_band,
            steam_event=st_ev,
            p_1=p_1,
            p_x=p_x,
            p_2=p_2,
            p_o25=p_o25,
            p_o35=p_o35,
            p_tg6=p_tg6,
            p_btts=p_btts,
            p_iy05=p_iy05,
            p_iy15=p_iy15,
            avg_goals=avg_goals,
            avg_corners=avg_corners,
            p_c85=p_c85,
            p_c95=p_c95,
            p_c12p=p_c12p,
            avg_cards=avg_cards,
        )

