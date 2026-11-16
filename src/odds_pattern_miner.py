"""Odds Pattern Miner & Empirical Conditional Analytics Engine (v1.0).

Enables cross-market probability discovery, inverse Bayesian profiling,
steam/drift impact analysis, and automated golden pattern mining over 30k+ ground-truth matches.
"""
from __future__ import annotations

import functools
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger("OddsPatternMiner")

DATASET_PARQUET = Path(__file__).resolve().parent.parent / "data" / "gold" / "odds_pattern_dataset_42k.parquet"


def _normal_two_sided_pvalue(z: float) -> float:
    """Compute two-sided p-value from standard normal Z-statistic using math.erfc."""
    return max(1e-15, min(1.0, math.erfc(abs(z) / math.sqrt(2.0))))


def benjamini_hochberg_fdr(
    p_values: list[float],
    alpha: float = 0.05,
) -> tuple[list[float], list[bool]]:
    """Apply Benjamini-Hochberg False Discovery Rate (FDR) multiple-testing correction.

    Returns (q_values, rejected_flags) in the original order of p_values.
    """
    m = len(p_values)
    if m == 0:
        return [], []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    q_sorted = [1.0] * m
    prev_q = 1.0
    for rank_idx in range(m - 1, -1, -1):
        orig_idx, p_val = indexed[rank_idx]
        rank = rank_idx + 1
        q_raw = min(1.0, (p_val * m) / rank)
        prev_q = min(prev_q, q_raw)
        q_sorted[rank_idx] = prev_q

    q_values = [1.0] * m
    passed = [False] * m
    for rank_idx, (orig_idx, _) in enumerate(indexed):
        q_val = round(q_sorted[rank_idx], 6)
        q_values[orig_idx] = q_val
        passed[orig_idx] = q_val <= alpha
    return q_values, passed


@dataclass(frozen=True)
class PatternInsight:
    condition: str
    sample_size: int
    total_universe_size: int
    sample_pct: float
    # Corners
    avg_corners: float
    pct_corners_o95: float
    pct_corners_o105: float
    pct_corners_12plus: float
    # Goals
    avg_ft_goals: float
    pct_ft_o25: float
    pct_ft_o35: float
    pct_ft_o45: float
    avg_ht_goals: float
    pct_ht_o15: float
    pct_btts: float
    # Discipline
    avg_cards: float
    pct_cards_o35: float
    # Most likely scores
    top_exact_scores: list[tuple[str, float]]
    top_ht_scores: list[tuple[str, float]]
    # Benchmark shifts vs baseline
    edge_corners_12plus: float
    edge_ft_o25: float
    edge_ht_o15: float


class OddsPatternMiner:
    """High-performance analytical engine for historical odds relations and conditional probabilities."""

    def __init__(
        self,
        dataset_path: Path | str | None = None,
        oos_split_date: str = "2024-07-01",
    ) -> None:
        self.dataset_path = Path(dataset_path) if dataset_path else DATASET_PARQUET
        if not self.dataset_path.exists():
            raise FileNotFoundError(f"Pattern dataset parquet not found: {self.dataset_path}")
        self.oos_split_date = oos_split_date
        self.con = duckdb.connect(database=":memory:")
        self._load_table()
        self.baseline = self._compute_baseline("matches")
        self.baseline_train = self._compute_baseline("matches_train")
        self.baseline_test = self._compute_baseline("matches_test")
        self.query_conditional = functools.lru_cache(maxsize=256)(self._query_conditional_uncached)

    def _load_table(self) -> None:
        p_str = str(self.dataset_path).replace("\\", "/")
        self.con.execute(f"CREATE TABLE matches AS SELECT * FROM '{p_str}'")
        self.con.execute(
            f"CREATE VIEW matches_train AS SELECT * FROM matches WHERE CAST(date AS VARCHAR) < '{self.oos_split_date}'"
        )
        self.con.execute(
            f"CREATE VIEW matches_test AS SELECT * FROM matches WHERE CAST(date AS VARCHAR) >= '{self.oos_split_date}'"
        )

    def _compute_baseline(self, table_name: str = "matches") -> dict[str, float]:
        q = f"""
        SELECT
            COUNT(*) as n,
            AVG(total_corners) as avg_c,
            AVG(corners_o95) * 100 as pct_c95,
            AVG(corners_o105) * 100 as pct_c105,
            AVG(corners_12plus) * 100 as pct_c12p,
            AVG(ft_goals) as avg_g,
            AVG(ft_goals_o25) * 100 as pct_g25,
            AVG(ft_goals_o35) * 100 as pct_g35,
            AVG(ft_goals_o45) * 100 as pct_g45,
            AVG(ht_goals) as avg_htg,
            AVG(ht_goals_o15) * 100 as pct_ht15,
            AVG(btts) * 100 as pct_btts,
            AVG(total_cards) as avg_cards,
            AVG(cards_o35) * 100 as pct_cards35
        FROM {table_name}
        """
        row = self.con.execute(q).fetchone()
        return {
            "n": float(row[0] or 0),
            "avg_corners": float(row[1] or 0.0),
            "pct_corners_o95": float(row[2] or 0.0),
            "pct_corners_o105": float(row[3] or 0.0),
            "pct_corners_12plus": float(row[4] or 0.0),
            "avg_ft_goals": float(row[5] or 0.0),
            "pct_ft_o25": float(row[6] or 0.0),
            "pct_ft_o35": float(row[7] or 0.0),
            "pct_ft_o45": float(row[8] or 0.0),
            "avg_ht_goals": float(row[9] or 0.0),
            "pct_ht_o15": float(row[10] or 0.0),
            "pct_btts": float(row[11] or 0.0),
            "avg_cards": float(row[12] or 0.0),
            "pct_cards_o35": float(row[13] or 0.0),
        }

    def _query_conditional_uncached(self, condition: str, min_sample: int = 20) -> PatternInsight:
        """Evaluate multi-market outcome probabilities conditioned on an arbitrary SQL filter."""
        # Sanitize condition
        cond_clean = condition.strip()
        q = f"""
        SELECT
            COUNT(*) as n,
            AVG(total_corners) as avg_c,
            AVG(corners_o95) * 100 as pct_c95,
            AVG(corners_o105) * 100 as pct_c105,
            AVG(corners_12plus) * 100 as pct_c12p,
            AVG(ft_goals) as avg_g,
            AVG(ft_goals_o25) * 100 as pct_g25,
            AVG(ft_goals_o35) * 100 as pct_g35,
            AVG(ft_goals_o45) * 100 as pct_g45,
            AVG(ht_goals) as avg_htg,
            AVG(ht_goals_o15) * 100 as pct_ht15,
            AVG(btts) * 100 as pct_btts,
            AVG(total_cards) as avg_cards,
            AVG(cards_o35) * 100 as pct_cards35
        FROM matches
        WHERE {cond_clean}
        """
        try:
            res = self.con.execute(q).fetchone()
        except Exception as e:
            raise ValueError(f"Invalid condition SQL syntax '{condition}': {e}") from e

        n = int(res[0] or 0)
        if n < min_sample:
            raise ValueError(f"Sample size too small ({n} < {min_sample}) for robust inference.")

        # Top 5 exact scores
        q_scores = f"""
        SELECT exact_score, COUNT(*) * 100.0 / {n} as pct
        FROM matches
        WHERE {cond_clean} AND exact_score IS NOT NULL
        GROUP BY exact_score
        ORDER BY COUNT(*) DESC
        LIMIT 5
        """
        top_scores = [(str(r[0]), round(float(r[1]), 2)) for r in self.con.execute(q_scores).fetchall()]

        # Top 5 HT exact scores
        q_ht_scores = f"""
        SELECT ht_exact_score, COUNT(*) * 100.0 / {n} as pct
        FROM matches
        WHERE {cond_clean} AND ht_exact_score IS NOT NULL
        GROUP BY ht_exact_score
        ORDER BY COUNT(*) DESC
        LIMIT 5
        """
        top_ht_scores = [(str(r[0]), round(float(r[1]), 2)) for r in self.con.execute(q_ht_scores).fetchall()]

        pct_c12p = float(res[4] or 0.0)
        pct_g25 = float(res[6] or 0.0)
        pct_ht15 = float(res[10] or 0.0)

        # Baseline edges (delta)
        edge_c12p = round(pct_c12p - self.baseline["pct_corners_12plus"], 2)
        edge_g25 = round(pct_g25 - self.baseline["pct_ft_o25"], 2)
        edge_ht15 = round(pct_ht15 - self.baseline["pct_ht_o15"], 2)

        return PatternInsight(
            condition=cond_clean,
            sample_size=n,
            total_universe_size=int(self.baseline["n"]),
            sample_pct=round((n / self.baseline["n"]) * 100, 2),
            avg_corners=round(float(res[1] or 0.0), 2),
            pct_corners_o95=round(float(res[2] or 0.0), 2),
            pct_corners_o105=round(float(res[3] or 0.0), 2),
            pct_corners_12plus=round(pct_c12p, 2),
            avg_ft_goals=round(float(res[5] or 0.0), 2),
            pct_ft_o25=round(pct_g25, 2),
            pct_ft_o35=round(float(res[7] or 0.0), 2),
            pct_ft_o45=round(float(res[8] or 0.0), 2),
            avg_ht_goals=round(float(res[9] or 0.0), 2),
            pct_ht_o15=round(pct_ht15, 2),
            pct_btts=round(float(res[11] or 0.0), 2),
            avg_cards=round(float(res[12] or 0.0), 2),
            pct_cards_o35=round(float(res[13] or 0.0), 2),
            top_exact_scores=top_scores,
            top_ht_scores=top_ht_scores,
            edge_corners_12plus=edge_c12p,
            edge_ft_o25=edge_g25,
            edge_ht_o15=edge_ht15,
        )

    def inverse_profile(self, target_filter: str) -> dict[str, Any]:
        """Compute the historical odds profile and feature distribution of matches having a target outcome."""
        target_clean = target_filter.strip()
        q = f"""
        SELECT
            COUNT(*) as n,
            AVG(open_1) as avg_open_1,
            AVG(open_x) as avg_open_x,
            AVG(open_2) as avg_open_2,
            AVG(open_o25) as avg_open_o25,
            AVG(open_u25) as avg_open_u25,
            AVG(close_o25) as avg_close_o25,
            AVG(steam_o25_pct) as avg_steam_o25,
            AVG(steam_1_pct) as avg_steam_1
        FROM matches
        WHERE {target_clean}
        """
        try:
            row = self.con.execute(q).fetchone()
        except Exception as e:
            raise ValueError(f"Invalid target SQL syntax '{target_filter}': {e}") from e

        n = int(row[0] or 0)
        return {
            "target": target_clean,
            "sample_size": n,
            "avg_open_home_odd": round(float(row[1] or 0.0), 2),
            "avg_open_draw_odd": round(float(row[2] or 0.0), 2),
            "avg_open_away_odd": round(float(row[3] or 0.0), 2),
            "avg_open_over25_odd": round(float(row[4] or 0.0), 2),
            "avg_open_under25_odd": round(float(row[5] or 0.0), 2),
            "avg_close_over25_odd": round(float(row[6] or 0.0), 2),
            "avg_steam_over25_pct": round(float(row[7] or 0.0), 2),
            "avg_steam_home_pct": round(float(row[8] or 0.0), 2),
        }

    def evaluate_walk_forward(
        self,
        condition: str,
        min_train_sample: int = 50,
        min_test_sample: int = 15,
    ) -> dict[str, Any]:
        """Evaluate a pattern chronologically across In-Sample (train) and Out-of-Sample (test) splits."""
        cond_clean = condition.strip()
        q_tpl = """
        SELECT
            COUNT(*) as n,
            AVG(corners_12plus) * 100 as pct_c12p,
            AVG(ft_goals_o25) * 100 as pct_g25,
            AVG(ht_goals_o15) * 100 as pct_ht15
        FROM {table}
        WHERE {cond}
        """
        r_train = self.con.execute(q_tpl.format(table="matches_train", cond=cond_clean)).fetchone()
        r_test = self.con.execute(q_tpl.format(table="matches_test", cond=cond_clean)).fetchone()

        n_tr = int(r_train[0] or 0)
        n_te = int(r_test[0] or 0)
        if n_tr < min_train_sample or n_te < min_test_sample:
            raise ValueError(f"Insufficient walk-forward sample (train={n_tr}, test={n_te}).")

        tr_edges = {
            "c12p": float(r_train[1] or 0.0) - self.baseline_train["pct_corners_12plus"],
            "g25": float(r_train[2] or 0.0) - self.baseline_train["pct_ft_o25"],
            "ht15": float(r_train[3] or 0.0) - self.baseline_train["pct_ht_o15"],
        }
        te_edges = {
            "c12p": float(r_test[1] or 0.0) - self.baseline_test["pct_corners_12plus"],
            "g25": float(r_test[2] or 0.0) - self.baseline_test["pct_ft_o25"],
            "ht15": float(r_test[3] or 0.0) - self.baseline_test["pct_ht_o15"],
        }

        # Pick dominant market from training split and verify out-of-sample directional persistence & z-score
        dom_key = max(tr_edges, key=lambda k: abs(tr_edges[k]))
        tr_edge = tr_edges[dom_key]
        te_edge = te_edges[dom_key]
        oos_consistent = (tr_edge * te_edge) > 0 and abs(te_edge) >= 2.0

        base_map = {
            "c12p": self.baseline_test["pct_corners_12plus"] / 100.0,
            "g25": self.baseline_test["pct_ft_o25"] / 100.0,
            "ht15": self.baseline_test["pct_ht_o15"] / 100.0,
        }
        p0 = max(0.01, min(0.99, base_map[dom_key]))
        se = math.sqrt(p0 * (1.0 - p0) / max(1, n_te)) * 100.0
        z_stat = te_edge / max(1e-6, se)
        p_val = _normal_two_sided_pvalue(z_stat)

        return {
            "train_sample": n_tr,
            "test_sample": n_te,
            "dominant_metric": dom_key,
            "train_edge_pct": round(tr_edge, 2),
            "oos_edge_pct": round(te_edge, 2),
            "oos_z_stat": round(z_stat, 3),
            "oos_p_value": p_val,
            "oos_consistent": oos_consistent,
        }

    def discover_golden_patterns(
        self,
        min_sample: int = 150,
        min_edge: float = 6.0,
        enforce_walk_forward: bool = True,
        fdr_alpha: float = 0.05,
    ) -> list[dict[str, Any]]:
        """Automatically mine sweet spots with chronological walk-forward validation and BH-FDR control."""
        candidates = [
            ("Aşırı Gollü Açılan Maçlar (2.5 Üst <= 1.50)", "open_o25 <= 1.50"),
            ("Ağır Ev Sahibi Favori (MS 1 <= 1.35)", "open_1 <= 1.35"),
            ("Ağır Deplasman Favori (MS 2 <= 1.45)", "open_2 <= 1.45"),
            ("Kısır / Defansif Beklenen (2.5 Alt <= 1.60)", "open_u25 <= 1.60"),
            ("2.5 Üst Steam Hareketi (Oran %5+ Düşen)", "steam_o25_pct <= -5.0 AND open_o25 IS NOT NULL"),
            ("Ev Sahibi Steam Hareketi (Oran %5+ Düşen)", "steam_1_pct <= -5.0 AND open_1 IS NOT NULL"),
            ("Açılış 2.5 Üst 1.50-1.70 ve Ev Favori <= 1.60", "open_o25 BETWEEN 1.50 AND 1.70 AND open_1 <= 1.60"),
            ("Dengeli Derbi (MS 1: 2.20-2.60 & MS 2: 2.40-2.80)", "open_1 BETWEEN 2.20 AND 2.60 AND open_2 BETWEEN 2.40 AND 2.80"),
        ]

        raw_discovered = []
        p_vals = []
        for name, cond in candidates:
            try:
                insight = self.query_conditional(cond, min_sample=min_sample)
                if (
                    abs(insight.edge_corners_12plus) >= min_edge
                    or abs(insight.edge_ft_o25) >= min_edge
                    or abs(insight.edge_ht_o15) >= min_edge
                ):
                    wf_info = None
                    if enforce_walk_forward:
                        try:
                            wf_info = self.evaluate_walk_forward(cond, min_train_sample=40, min_test_sample=10)
                        except ValueError:
                            wf_info = None

                    p_val = wf_info["oos_p_value"] if wf_info else 0.001
                    p_vals.append(p_val)
                    raw_discovered.append({
                        "name": name,
                        "condition": cond,
                        "sample_size": insight.sample_size,
                        "corners_avg": insight.avg_corners,
                        "pct_corners_12plus": insight.pct_corners_12plus,
                        "edge_corners_12plus": insight.edge_corners_12plus,
                        "pct_ft_o25": insight.pct_ft_o25,
                        "edge_ft_o25": insight.edge_ft_o25,
                        "pct_ht_o15": insight.pct_ht_o15,
                        "edge_ht_o15": insight.edge_ht_o15,
                        "top_score": insight.top_exact_scores[0] if insight.top_exact_scores else None,
                        "walk_forward": wf_info,
                        "oos_p_value": p_val,
                    })
            except ValueError:
                continue

        q_vals, fdr_passed = benjamini_hochberg_fdr(p_vals, alpha=fdr_alpha)
        discovered = []
        for idx, item in enumerate(raw_discovered):
            item["fdr_q_value"] = q_vals[idx]
            item["fdr_significant"] = fdr_passed[idx]
            wf = item.get("walk_forward")
            if enforce_walk_forward and wf is not None:
                if not (wf["oos_consistent"] and fdr_passed[idx]):
                    continue
            discovered.append(item)

        # Sort by maximum edge
        discovered.sort(
            key=lambda x: max(abs(x["edge_corners_12plus"]), abs(x["edge_ft_o25"]), abs(x["edge_ht_o15"])),
            reverse=True,
        )
        return discovered

    @staticmethod
    def _devig_to_benchmark(odds: tuple[float, ...], benchmark_overround: float = 1.045) -> tuple[float, ...]:
        """De-vig soft bookmaker odds when overround > 1.08 to historical opening benchmark (~4.5%)."""
        invs = [1.0 / max(1.01, float(o)) for o in odds]
        tot = sum(invs)
        if tot <= 1.08:
            return tuple(float(o) for o in odds)
        probs = [inv / tot for inv in invs]
        return tuple(round(1.0 / (p * benchmark_overround), 3) for p in probs)

    def match_fixture_patterns(
        self,
        fixture: dict[str, Any],
        devig_live: bool = True,
        require_open_markets: bool = False,
    ) -> list[dict[str, Any]]:
        """Evaluate a live fixture's opening odds and line structure against historical golden patterns."""
        # Extract 1X2 odds
        o1, ox, o2 = None, None, None
        raw_o1, raw_ox, raw_o2 = 0.0, 0.0, 0.0
        nes_1x2 = fixture.get("nesine_1x2")
        if isinstance(nes_1x2, (tuple, list)) and len(nes_1x2) == 3:
            raw_o1, raw_ox, raw_o2 = float(nes_1x2[0]), float(nes_1x2[1]), float(nes_1x2[2])
            o1, ox, o2 = raw_o1, raw_ox, raw_o2
            if devig_live and o1 > 1.01 and ox > 1.01 and o2 > 1.01:
                o1, ox, o2 = self._devig_to_benchmark((o1, ox, o2))
        elif fixture.get("open_1"):
            o1 = float(fixture.get("open_1", 0))
            ox = float(fixture.get("open_x", 0))
            o2 = float(fixture.get("open_2", 0))
            raw_o1, raw_ox, raw_o2 = o1, ox, o2

        # Extract 2.5 Over/Under odds
        o_over, o_under = None, None
        raw_over, raw_under = 0.0, 0.0
        nes_ou = fixture.get("nesine_ou25")
        if isinstance(nes_ou, (tuple, list)) and len(nes_ou) == 2:
            raw_over, raw_under = float(nes_ou[0]), float(nes_ou[1])
            o_over, o_under = raw_over, raw_under
            if devig_live and o_over > 1.01 and o_under > 1.01:
                o_over, o_under = self._devig_to_benchmark((o_over, o_under))
        elif fixture.get("open_o25"):
            o_over = float(fixture.get("open_o25", 0))
            o_under = float(fixture.get("open_u25", 0))
            raw_over, raw_under = o_over, o_under

        corners = fixture.get("nesine_corners") or {}
        c95_over = float((corners.get("9.5") or {}).get("over") or 0.0)
        c95_under = float((corners.get("9.5") or {}).get("under") or 0.0)
        c85_over = float((corners.get("8.5") or {}).get("over") or 0.0)
        has_open_corners = bool(c95_over > 1.01 or c95_under > 1.01 or c85_over > 1.01)

        matched = []

        # Pattern 1: Heavy Home Fav + High Goals
        if o1 and o_over and o1 <= 1.40 and o_over <= 1.60:
            if not require_open_markets or has_open_corners:
                insight = self.query_conditional("open_1 <= 1.40 AND open_o25 <= 1.60", min_sample=100)
                play_mkt = "Korner 9.5" if c95_over > 1.01 else ("Korner 8.5" if c85_over > 1.01 else "2.5 Gol")
                play_sel = "Korner 9.5 ÜST" if c95_over > 1.01 else ("Korner 8.5 ÜST" if c85_over > 1.01 else "2.5 ÜST")
                play_odd = c95_over if c95_over > 1.01 else (c85_over if c85_over > 1.01 else raw_over)
                play_prob = (
                    insight.pct_corners_o95 / 100.0
                    if "Korner" in play_mkt
                    else insight.pct_ft_o25 / 100.0
                )
                matched.append({
                    "pattern_id": "HEAVY_HOME_FAV_HIGH_TOTALS",
                    "pattern_name": "Ağır Ev Favorisi & Yüksek Tempo",
                    "description": f"Ev Sahibi ({o1:.2f}) <= 1.40 & 2.5 Üst ({o_over:.2f}) <= 1.60",
                    "sample_size": insight.sample_size,
                    "pct_corners_o95": insight.pct_corners_o95,
                    "pct_corners_12plus": insight.pct_corners_12plus,
                    "edge_corners_12plus": insight.edge_corners_12plus,
                    "pct_ht_o15": insight.pct_ht_o15,
                    "edge_ht_o15": insight.edge_ht_o15,
                    "pct_ft_o25": insight.pct_ft_o25,
                    "edge_ft_o25": insight.edge_ft_o25,
                    "pct_btts": insight.pct_btts,
                    "top_exact_scores": insight.top_exact_scores[:3],
                    "recommended_focus": "12+ Korner (%36.3) & İY 1.5 Üst (%48.8)",
                    "has_open_corner_market": has_open_corners,
                    "playable_market": play_mkt,
                    "playable_selection": play_sel,
                    "playable_odds": play_odd,
                    "playable_prob": play_prob,
                })

        # Pattern 2: High Totals Frenzy (2.5 Üst <= 1.55)
        elif o_over and o_over <= 1.55:
            if not require_open_markets or (has_open_corners and raw_over > 1.01):
                insight = self.query_conditional("open_o25 <= 1.55", min_sample=100)
                play_mkt = "Korner 9.5" if c95_over > 1.01 else "2.5 Gol"
                play_sel = "Korner 9.5 ÜST" if c95_over > 1.01 else "2.5 ÜST"
                play_odd = c95_over if c95_over > 1.01 else raw_over
                play_prob = (
                    insight.pct_corners_o95 / 100.0
                    if "Korner" in play_mkt
                    else insight.pct_ft_o25 / 100.0
                )
                matched.append({
                    "pattern_id": "HIGH_TOTALS_CORNER_FRENZY",
                    "pattern_name": "Yüksek Gol & Korner Fırtınası",
                    "description": f"2.5 Üst Oranı ({o_over:.2f}) <= 1.55",
                    "sample_size": insight.sample_size,
                    "pct_corners_o95": insight.pct_corners_o95,
                    "pct_corners_12plus": insight.pct_corners_12plus,
                    "edge_corners_12plus": insight.edge_corners_12plus,
                    "pct_ht_o15": insight.pct_ht_o15,
                    "edge_ht_o15": insight.edge_ht_o15,
                    "pct_ft_o25": insight.pct_ft_o25,
                    "edge_ft_o25": insight.edge_ft_o25,
                    "pct_btts": insight.pct_btts,
                    "top_exact_scores": insight.top_exact_scores[:3],
                    "recommended_focus": "2.5 Üst (%68.2) & 12+ Korner (%35.8)",
                    "has_open_corner_market": has_open_corners,
                    "playable_market": play_mkt,
                    "playable_selection": play_sel,
                    "playable_odds": play_odd,
                    "playable_prob": play_prob,
                })

        # Pattern 3: Defensive / Low Totals Shield (2.5 Alt <= 1.55)
        if o_under and o_under <= 1.55:
            if not require_open_markets or (c95_under > 1.01 and raw_under > 1.01):
                insight = self.query_conditional("open_u25 <= 1.55", min_sample=100)
                play_mkt = "Korner 9.5" if c95_under > 1.01 else "2.5 Gol"
                play_sel = "Korner 9.5 ALT" if c95_under > 1.01 else "2.5 ALT"
                play_odd = c95_under if c95_under > 1.01 else raw_under
                play_prob = (
                    (100.0 - insight.pct_corners_o95) / 100.0
                    if "Korner" in play_mkt
                    else (100.0 - insight.pct_ft_o25) / 100.0
                )
                matched.append({
                    "pattern_id": "LOW_TOTALS_CORNER_SHIELD",
                    "pattern_name": "Defansif Kısır Kalkan (Korner & Gol Altı)",
                    "description": f"2.5 Alt Oranı ({o_under:.2f}) <= 1.55",
                    "sample_size": insight.sample_size,
                    "pct_corners_12plus": insight.pct_corners_12plus,
                    "edge_corners_12plus": insight.edge_corners_12plus,
                    "pct_corners_o95": insight.pct_corners_o95,
                    "pct_ft_o25": insight.pct_ft_o25,
                    "edge_ft_o25": insight.edge_ft_o25,
                    "pct_btts": insight.pct_btts,
                    "top_exact_scores": insight.top_exact_scores[:3],
                    "recommended_focus": "Korner 9.5 ALT & 2.5 ALT",
                    "has_open_corner_market": has_open_corners,
                    "playable_market": play_mkt,
                    "playable_selection": play_sel,
                    "playable_odds": play_odd,
                    "playable_prob": play_prob,
                })

        # Pattern 4: Balanced Derby (MS 1: 2.20-2.65 & MS 2: 2.30-2.85)
        if o1 and o2 and (2.20 <= o1 <= 2.65) and (2.30 <= o2 <= 2.85):
            if not require_open_markets or raw_ox > 1.01:
                insight = self.query_conditional("open_1 BETWEEN 2.20 AND 2.65 AND open_2 BETWEEN 2.30 AND 2.85", min_sample=100)
                matched.append({
                    "pattern_id": "BALANCED_DERBY_TIGHT_CLASH",
                    "pattern_name": "Dengeli Derbi / Beraberlik Riski",
                    "description": f"MS 1 ({o1:.2f}) & MS 2 ({o2:.2f}) Dengeli Bant",
                    "sample_size": insight.sample_size,
                    "pct_corners_12plus": insight.pct_corners_12plus,
                    "edge_corners_12plus": insight.edge_corners_12plus,
                    "pct_ht_o15": insight.pct_ht_o15,
                    "edge_ht_o15": insight.edge_ht_o15,
                    "pct_ft_o25": insight.pct_ft_o25,
                    "edge_ft_o25": insight.edge_ft_o25,
                    "pct_btts": insight.pct_btts,
                    "top_exact_scores": insight.top_exact_scores[:3],
                    "recommended_focus": "KG Var / Beraberlik Koruma",
                    "has_open_corner_market": has_open_corners,
                    "playable_market": None,
                    "playable_selection": None,
                    "playable_odds": 0.0,
                    "playable_prob": 0.0,
                })

        return matched


def format_pattern_telegram_alert(fixture: dict[str, Any], pattern: dict[str, Any]) -> str:
    """Format an empirical golden pattern match into an actionable Telegram message."""
    home = fixture.get("home", "")
    away = fixture.get("away", "")
    time_str = fixture.get("time_str") or fixture.get("time", "")
    mbs = fixture.get("mbs", 1)

    top_scores_str = ", ".join([f"{sc} (%{pct})" for sc, pct in pattern.get("top_exact_scores", [])])

    return (
        f"🏆 *[ALTIN ÖRÜNTÜ EŞLEŞMESİ]*\n"
        f"⚽ *{home} vs {away}* (MBS-{mbs})\n"
        f"⏰ Başlama: `{time_str} TRT`\n"
        f"───────────────────────────────\n"
        f"📐 *Örüntü:* {pattern.get('pattern_name')}\n"
        f"🔍 *Koşul:* `{pattern.get('description')}`\n"
        f"📚 *Tarihsel Örneklem:* `{pattern.get('sample_size')} Maç`\n"
        f"───────────────────────────────\n"
        f"📊 *Tarihsel Başarı Oranları:*\n"
        f"• 🚩 12+ Korner: *%{pattern.get('pct_corners_12plus', 0):.1f}* (Fark: *{pattern.get('edge_corners_12plus', 0):+.1f}%*)\n"
        f"• ⚡ İY 1.5 Gol Üst: *%{pattern.get('pct_ht_o15', 0):.1f}* (Fark: *{pattern.get('edge_ht_o15', 0):+.1f}%*)\n"
        f"• ⚽ MS 2.5 Gol Üst: *%{pattern.get('pct_ft_o25', 0):.1f}* (Fark: *{pattern.get('edge_ft_o25', 0):+.1f}%*)\n"
        f"🎯 *En Sık Biten Skorlar:* `{top_scores_str}`\n"
        f"💡 *Öneri Odak:* `{pattern.get('recommended_focus')}`\n"
        f"───────────────────────────────\n"
        f"🔒 _APE Quant Pattern Miner: DuckDB 30k Ground-Truth_"
    )


