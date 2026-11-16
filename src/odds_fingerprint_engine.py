"""Universal Odds Fingerprint & k-NN Market Twin Engine (v1.0).

Transforms multi-market betting odds into an 8-dimensional normalized fingerprint vector,
scans 30,315+ ground-truth matches in milliseconds using vectorized NumPy Euclidean/Cosine geometry,
and extracts the empirical multi-market outcome distribution of the nearest historical match twins.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("OddsFingerprintEngine")

DATASET_PARQUET = Path(__file__).resolve().parent.parent / "data" / "gold" / "odds_pattern_dataset_42k.parquet"


@dataclass(frozen=True)
class FingerprintTwinReport:
    query_odds: dict[str, float]
    k_neighbors: int
    avg_similarity_pct: float
    # Corners
    avg_corners: float
    pct_corners_o85: float
    pct_corners_o95: float
    pct_corners_o105: float
    pct_corners_12plus: float
    # Goals
    avg_ft_goals: float
    pct_ft_o15: float
    pct_ft_o25: float
    pct_ft_o35: float
    pct_ft_o45: float
    pct_ht_o15: float
    pct_btts: float
    # Exact Scores
    top_exact_scores: list[tuple[str, float]]
    top_htft_outcomes: list[tuple[str, float]]
    # Twin match examples
    sample_twins: list[dict[str, Any]]
    # Strongest Consensus Edge
    top_consensus_market: str
    top_consensus_prob: float


class OddsFingerprintEngine:
    """High-performance vectorized k-NN engine for odds fingerprinting."""

    FEATURE_WEIGHTS = np.array([
        1.5,  # p_home (implied prob)
        1.0,  # p_draw
        1.5,  # p_away
        2.5,  # p_over25 (critical goal tempo)
        2.5,  # p_under25
        1.8,  # goal_intensity_log_ratio
        1.2,  # favorite_skew_ratio
        0.8,  # steam_o25_norm
    ], dtype=np.float32)

    def __init__(self, dataset_path: Path | str | None = None) -> None:
        self.dataset_path = Path(dataset_path) if dataset_path else DATASET_PARQUET
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"Parquet dataset not found at: {self.dataset_path}")

        self._load_and_vectorize_dataset()

    def _load_and_vectorize_dataset(self) -> None:
        """Load parquet and build vectorized feature matrix."""
        df = pd.read_parquet(self.dataset_path)

        # Filter rows with valid essential odds
        valid_mask = (
            df["open_1"].notna() & (df["open_1"] > 1.01) &
            df["open_x"].notna() & (df["open_x"] > 1.01) &
            df["open_2"].notna() & (df["open_2"] > 1.01) &
            df["open_o25"].notna() & (df["open_o25"] > 1.01) &
            df["open_u25"].notna() & (df["open_u25"] > 1.01)
        )
        self.df = df[valid_mask].copy().reset_index(drop=True)

        # Construct vector columns
        o1 = self.df["open_1"].to_numpy(dtype=np.float32)
        ox = self.df["open_x"].to_numpy(dtype=np.float32)
        o2 = self.df["open_2"].to_numpy(dtype=np.float32)
        o_o25 = self.df["open_o25"].to_numpy(dtype=np.float32)
        o_u25 = self.df["open_u25"].to_numpy(dtype=np.float32)
        steam = self.df["steam_o25_pct"].fillna(0.0).to_numpy(dtype=np.float32)

        # Implied probabilities (devigged proxy)
        p1 = 1.0 / o1
        px = 1.0 / ox
        p2 = 1.0 / o2
        po = 1.0 / o_o25
        pu = 1.0 / o_u25

        # Normalization
        tot_1x2 = p1 + px + p2
        p1 /= tot_1x2
        px /= tot_1x2
        p2 /= tot_1x2

        tot_ou = po + pu
        po /= tot_ou
        pu /= tot_ou

        # Compute ratios from de-vigged fair odds (fair_u25 / fair_o25 == po / pu, fair_2 / fair_1 == p1 / p2)
        goal_intensity = np.log(np.clip(po / (pu + 1e-6), 0.2, 5.0))
        skew_ratio = np.clip(p1 / (p2 + 1e-4), 0.1, 15.0) / 10.0
        steam_norm = np.clip(steam / 15.0, -1.0, 1.0)

        # Feature matrix: shape (N, 8)
        self.matrix = np.column_stack([
            p1, px, p2, po, pu, goal_intensity, skew_ratio, steam_norm
        ]).astype(np.float32)

        # Pre-apply feature weights for fast Euclidean broadcast
        self.weighted_matrix = self.matrix * np.sqrt(self.FEATURE_WEIGHTS)
        logger.info(f"OddsFingerprintEngine initialized with {len(self.df)} vectorized matches.")

    @staticmethod
    def devig_odds(
        open_1: float,
        open_x: float,
        open_2: float,
        open_o25: float,
        open_u25: float,
    ) -> dict[str, float]:
        """Remove bookmaker margin from 1X2 and 2.5 O/U odds to return fair probabilities and fair odds."""
        p1 = 1.0 / max(1.01, float(open_1))
        px = 1.0 / max(1.01, float(open_x))
        p2 = 1.0 / max(1.01, float(open_2))
        tot_1x2 = p1 + px + p2
        p1, px, p2 = p1 / tot_1x2, px / tot_1x2, p2 / tot_1x2

        po = 1.0 / max(1.01, float(open_o25))
        pu = 1.0 / max(1.01, float(open_u25))
        tot_ou = po + pu
        po, pu = po / tot_ou, pu / tot_ou

        return {
            "p_1": round(p1, 4),
            "p_x": round(px, 4),
            "p_2": round(p2, 4),
            "p_o25": round(po, 4),
            "p_u25": round(pu, 4),
            "fair_1": round(1.0 / p1, 3),
            "fair_x": round(1.0 / px, 3),
            "fair_2": round(1.0 / p2, 3),
            "fair_o25": round(1.0 / po, 3),
            "fair_u25": round(1.0 / pu, 3),
        }

    def build_query_vector(
        self,
        open_1: float,
        open_x: float,
        open_2: float,
        open_o25: float,
        open_u25: float,
        steam_o25_pct: float = 0.0,
    ) -> np.ndarray:
        """Convert a set of match odds into a margin-invariant (de-vigged) weighted 8D feature vector."""
        devigged = self.devig_odds(open_1, open_x, open_2, open_o25, open_u25)
        p1 = devigged["p_1"]
        px = devigged["p_x"]
        p2 = devigged["p_2"]
        po = devigged["p_o25"]
        pu = devigged["p_u25"]

        goal_intensity = float(np.log(np.clip(po / (pu + 1e-6), 0.2, 5.0)))
        skew_ratio = float(np.clip(p1 / (p2 + 1e-4), 0.1, 15.0) / 10.0)
        steam_norm = float(np.clip(steam_o25_pct / 15.0, -1.0, 1.0))

        raw_vec = np.array([p1, px, p2, po, pu, goal_intensity, skew_ratio, steam_norm], dtype=np.float32)
        return raw_vec * np.sqrt(self.FEATURE_WEIGHTS)

    def find_nearest_twins(
        self,
        open_1: float,
        open_x: float,
        open_2: float,
        open_o25: float,
        open_u25: float,
        steam_o25_pct: float = 0.0,
        k: int = 50,
    ) -> FingerprintTwinReport:
        """Find top k nearest historical match twins and aggregate empirical outcomes."""
        q_vec = self.build_query_vector(
            open_1=open_1,
            open_x=open_x,
            open_2=open_2,
            open_o25=open_o25,
            open_u25=open_u25,
            steam_o25_pct=steam_o25_pct,
        )

        # Vectorized Euclidean distances: sqrt(sum((matrix - q)^2, axis=1))
        diff = self.weighted_matrix - q_vec
        dist_sq = np.sum(diff * diff, axis=1)
        distances = np.sqrt(dist_sq)

        # Top k smallest distance indices
        top_indices = np.argpartition(distances, k)[:k]
        # Sort these top k precisely
        top_indices = top_indices[np.argsort(distances[top_indices])]

        matched_subset = self.df.iloc[top_indices].copy()
        matched_dists = distances[top_indices]

        # Convert distance to a 0-100% similarity score
        # Using exponential decay: similarity = 100 * exp(-dist)
        similarities = np.clip(100.0 * np.exp(-1.5 * matched_dists), 40.0, 99.9)
        avg_sim = float(np.mean(similarities))

        # 1. Corners
        c_series = matched_subset["total_corners"].dropna()
        avg_corners = float(c_series.mean()) if len(c_series) > 0 else 0.0
        pct_c85 = float((c_series > 8.5).mean() * 100) if len(c_series) > 0 else 0.0
        pct_c95 = float((c_series > 9.5).mean() * 100) if len(c_series) > 0 else 0.0
        pct_c105 = float((c_series > 10.5).mean() * 100) if len(c_series) > 0 else 0.0
        pct_c12p = float((c_series >= 12.0).mean() * 100) if len(c_series) > 0 else 0.0

        # 2. Goals
        g_series = matched_subset["ft_goals"]
        avg_goals = float(g_series.mean())
        pct_g15 = float((g_series > 1.5).mean() * 100)
        pct_g25 = float((g_series > 2.5).mean() * 100)
        pct_g35 = float((g_series > 3.5).mean() * 100)
        pct_g45 = float((g_series > 4.5).mean() * 100)

        # Half time goals
        htg = matched_subset["ht_goals"].dropna()
        pct_ht15 = float((htg > 1.5).mean() * 100) if len(htg) > 0 else 0.0

        # BTTS
        pct_btts = float((matched_subset["btts"] == 1).mean() * 100)

        # 3. Exact Scores
        score_counts = matched_subset["exact_score"].value_counts(normalize=True) * 100
        top_scores = [(str(s), round(float(pct), 1)) for s, pct in score_counts.head(5).items()]

        # 4. HT/FT Transitions
        htft_types = []
        for _, r in matched_subset.iterrows():
            hthg, htag, fthg, ftag = r.get("hthg"), r.get("htag"), r.get("fthg"), r.get("ftag")
            if pd.notna(hthg) and pd.notna(htag):
                ht_res = "1" if hthg > htag else ("2" if htag > hthg else "X")
                ft_res = "1" if fthg > ftag else ("2" if ftag > fthg else "X")
                htft_types.append(f"{ht_res}/{ft_res}")
        htft_series = pd.Series(htft_types).value_counts(normalize=True) * 100 if htft_types else pd.Series()
        top_htft = [(str(s), round(float(pct), 1)) for s, pct in htft_series.head(4).items()]

        # Sample Twins (Top 3 closest matches in history)
        sample_twins = []
        for i in range(min(4, len(matched_subset))):
            row = matched_subset.iloc[i]
            sample_twins.append({
                "match": f"{row.get('home_team')} {int(row.get('fthg', 0))}-{int(row.get('ftag', 0))} {row.get('away_team')}",
                "date": str(row.get("date")),
                "league": str(row.get("div_code")),
                "corners": f"{int(row.get('total_corners', 0))}" if pd.notna(row.get("total_corners")) else "N/A",
                "similarity": round(float(similarities[i]), 1),
            })

        # Consensus market determination (includes both Over and Under for corners/goals/BTTS)
        candidate_markets = [
            ("2.5 Üst", pct_g25),
            ("2.5 Alt", 100.0 - pct_g25),
            ("KG Var", pct_btts),
            ("KG Yok", 100.0 - pct_btts),
            ("9.5 Korner Üst", pct_c95),
            ("9.5 Korner Alt", 100.0 - pct_c95),
            ("8.5 Korner Üst", pct_c85),
            ("8.5 Korner Alt", 100.0 - pct_c85),
            ("İY 1.5 Üst", pct_ht15),
            ("12+ Korner", pct_c12p),
        ]
        candidate_markets.sort(key=lambda x: x[1], reverse=True)
        top_mkt, top_p = candidate_markets[0]

        return FingerprintTwinReport(
            query_odds={
                "MS 1": open_1,
                "MS X": open_x,
                "MS 2": open_2,
                "2.5 Üst": open_o25,
                "2.5 Alt": open_u25,
                "Steam 2.5": steam_o25_pct,
            },
            k_neighbors=k,
            avg_similarity_pct=round(avg_sim, 1),
            avg_corners=round(avg_corners, 2),
            pct_corners_o85=round(pct_c85, 1),
            pct_corners_o95=round(pct_c95, 1),
            pct_corners_o105=round(pct_c105, 1),
            pct_corners_12plus=round(pct_c12p, 1),
            avg_ft_goals=round(avg_goals, 2),
            pct_ft_o15=round(pct_g15, 1),
            pct_ft_o25=round(pct_g25, 1),
            pct_ft_o35=round(pct_g35, 1),
            pct_ft_o45=round(pct_g45, 1),
            pct_ht_o15=round(pct_ht15, 1),
            pct_btts=round(pct_btts, 1),
            top_exact_scores=top_scores,
            top_htft_outcomes=top_htft,
            sample_twins=sample_twins,
            top_consensus_market=top_mkt,
            top_consensus_prob=round(top_p, 1),
        )

    def scan_fixture(self, fixture: dict[str, Any], k: int = 50) -> FingerprintTwinReport | None:
        """Scan a live Nesine fixture dictionary and produce its fingerprint twin report."""
        nes_1x2 = fixture.get("nesine_1x2")
        nes_ou = fixture.get("nesine_ou25")

        o1, ox, o2 = None, None, None
        if isinstance(nes_1x2, (tuple, list)) and len(nes_1x2) == 3:
            o1, ox, o2 = float(nes_1x2[0]), float(nes_1x2[1]), float(nes_1x2[2])
        elif fixture.get("open_1"):
            o1 = float(fixture.get("open_1", 0))
            ox = float(fixture.get("open_x", 0))
            o2 = float(fixture.get("open_2", 0))

        o_over, o_under = None, None
        if isinstance(nes_ou, (tuple, list)) and len(nes_ou) == 2:
            o_over, o_under = float(nes_ou[0]), float(nes_ou[1])
        elif fixture.get("open_o25"):
            o_over = float(fixture.get("open_o25", 0))
            o_under = float(fixture.get("open_u25", 0))

        if not (o1 and ox and o2 and o_over and o_under):
            return None

        steam = float(fixture.get("steam_o25_pct", 0.0))
        return self.find_nearest_twins(
            open_1=o1,
            open_x=ox,
            open_2=o2,
            open_o25=o_over,
            open_u25=o_under,
            steam_o25_pct=steam,
            k=k,
        )


def format_fingerprint_telegram_message(
    fixture_name: str,
    time_str: str,
    mbs: int,
    report: FingerprintTwinReport,
) -> str:
    """Format a fingerprint twin report into an ultra-actionable Telegram VIP card."""
    odds = report.query_odds
    top_scores = ", ".join([f"{sc} (%{p})" for sc, p in report.top_exact_scores[:3]])
    top_htft = ", ".join([f"{t} (%{p})" for t, p in report.top_htft_outcomes[:2]])

    twin_lines = []
    for tw in report.sample_twins[:3]:
        twin_lines.append(f"  • {tw['match']} [{tw['date']}] (🚩 {tw['corners']} korner | %{tw['similarity']} benzerlik)")
    twins_block = "\n".join(twin_lines)

    return (
        f"🧬 *[ORAN PARMAK İZİ — EN YAKIN {report.k_neighbors} TARİHSEL İKİZ]*\n"
        f"⚽ *{fixture_name}* (MBS-{mbs})\n"
        f"⏰ Başlama: `{time_str} TRT` | Benzerlik: *%{report.avg_similarity_pct}*\n"
        f"📊 *Oranlar:* MS `1:{odds['MS 1']} X:{odds['MS X']} 2:{odds['MS 2']}` | 2.5 `Ü:{odds['2.5 Üst']} A:{odds['2.5 Alt']}`\n"
        f"───────────────────────────────\n"
        f"🏆 *En Güçlü Tarihsel Konsensüs:* *{report.top_consensus_market}* (*%{report.top_consensus_prob}*)\n"
        f"───────────────────────────────\n"
        f"🚩 *Korner Dağılımı:* (Ort: `{report.avg_corners:.2f}`)\n"
        f"• 8.5 Üst: *%{report.pct_corners_o85}* | 9.5 Üst: *%{report.pct_corners_o95}*\n"
        f"• 10.5 Üst: *%{report.pct_corners_o105}* | 12+ Korner: *%{report.pct_corners_12plus}*\n"
        f"⚽ *Gol Dağılımı:* (Ort: `{report.avg_ft_goals:.2f}`)\n"
        f"• KG Var: *%{report.pct_btts}* | İY 1.5 Üst: *%{report.pct_ht_o15}*\n"
        f"• 2.5 Üst: *%{report.pct_ft_o25}* | 3.5 Üst: *%{report.pct_ft_o35}*\n"
        f"🎯 *Tarihte En Sık Biten Skorlar:* `{top_scores}`\n"
        f"🔄 *En Sık İY/MS:* `{top_htft}`\n"
        f"───────────────────────────────\n"
        f"📚 *Tarihten Birebir Örnek İkizler:*\n"
        f"{twins_block}\n"
        f"───────────────────────────────\n"
        f"🔒 _APE Quant k-NN Engine: 30k Match Geometry_"
    )
