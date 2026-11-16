"""Empirical Bayes Poisson & Dixon-Coles Team Strength Engine (v1.0).

Trained on ground truth European and Turkish match databases (30,316+ matches).
Computes time-decayed attack ratings, defense ratings, and corner aggression parameters
with Empirical Bayes shrinkage towards league priors.

Provides independent, bookmaker-free expected goals, expected corners, Dixon-Coles
bivariate score distributions, and fair market odds (1X2, DC, DNB, Totals, BTTS, HT/FT,
and Corners) to discover true positive mathematical edges (+EV).
"""

from __future__ import annotations

import functools
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from high_odds_system_engine import price_htft_transitions
except ImportError:
    from src.high_odds_system_engine import price_htft_transitions

from team_normalizer import TeamNormalizer

ROOT_DIR = Path(__file__).resolve().parent.parent
GOLD_PARQUET = ROOT_DIR / "data" / "gold" / "ground_truth_matches_42k.parquet"
SILVER_CACHE = ROOT_DIR / "data" / "silver" / "team_strength_ratings.json"


LEAGUE_TIER_MAP: dict[str, int] = {
    "Premier League": 1,
    "La Liga": 1,
    "Serie A": 1,
    "Bundesliga": 1,
    "Ligue 1": 1,
    "Super Lig": 1,
    "Eredivisie": 1,
    "Primeira Liga": 1,
    "Pro League": 1,
    "Premiership": 1,
    "Championship": 2,
    "La Liga 2": 2,
    "Serie B": 2,
    "Bundesliga 2": 2,
    "Ligue 2": 2,
    "League One": 3,
    "Brasileirao Serie A": 1,
    "USA MLS": 1,
}

LEAGUE_COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "Premier League": ("england", "uk", "eng", "gb"),
    "Championship": ("england", "uk", "eng", "gb"),
    "League One": ("england", "uk", "eng", "gb"),
    "La Liga": ("spain", "esp", "es"),
    "La Liga 2": ("spain", "esp", "es"),
    "Serie A": ("italy", "ita", "it"),
    "Serie B": ("italy", "ita", "it"),
    "Bundesliga": ("germany", "ger", "de"),
    "Bundesliga 2": ("germany", "ger", "de"),
    "Ligue 1": ("france", "fra", "fr"),
    "Ligue 2": ("france", "fra", "fr"),
    "Super Lig": ("turkey", "turkiye", "tur", "tr"),
    "Eredivisie": ("netherlands", "holland", "ned", "nl"),
    "Primeira Liga": ("portugal", "por", "pt"),
    "Pro League": ("belgium", "bel", "be"),
    "Premiership": ("scotland", "sco", "uk"),
    "Brasileirao Serie A": ("brazil", "brasil", "bra", "br"),
    "USA MLS": ("usa", "united states", "us", "mls"),
}

MIN_SAMPLE_MATCHES = 6
MAX_ANOMALY_EDGE_PCT = 35.0


def _is_country_compatible(fixture_country: str | None, team_league: str | None) -> bool:
    """Reject cross-continent false team matches (e.g. 'Au' South Hobart vs England Southampton)."""
    if not fixture_country or not team_league:
        return True
    norm_country = str(fixture_country).strip().lower()
    if norm_country in {"", "unknown", "international", "europe", "uefa", "world"}:
        return True
    allowed = LEAGUE_COUNTRY_ALIASES.get(str(team_league).strip())
    if not allowed:
        return True
    return any(tok in norm_country or norm_country == tok for tok in allowed)


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0.0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam**k) / math.factorial(k)


def _dixon_coles_tau(x: int, y: int, lam: float, mu: float, rho: float = -0.06) -> float:
    """Low-score correlation adjustment factor per Dixon & Coles (1997) with dynamic safety bounds."""
    from sports_engine.models.poisson import dixon_coles_tau
    return dixon_coles_tau(x, y, lam, mu, rho)


def _neg_bin_pmf(k: int, lam: float, kappa: float = 0.14) -> float:
    """Negative Binomial PMF for overdispersed counts (corners)."""
    from sports_engine.models.negative_binomial import neg_binomial_pmf
    return neg_binomial_pmf(k, lam, kappa)



class TeamStrengthEngine:
    """Empirical Bayes Team Strength & Market Pricing Engine."""

    def __init__(
        self,
        parquet_path: Path = GOLD_PARQUET,
        cache_path: Path = SILVER_CACHE,
        time_decay_xi: float = 0.0018,
        shrinkage_tau0: float = 8.0,
        home_adv_goals: float = 0.22,
        home_adv_corners: float = 0.16,
    ) -> None:
        self.parquet_path = parquet_path
        self.cache_path = cache_path
        self.xi = time_decay_xi
        self.tau_0 = shrinkage_tau0
        self.home_adv_goals = home_adv_goals
        self.home_adv_corners = home_adv_corners
        self.normalizer = TeamNormalizer()

        self.team_ratings: dict[str, dict[str, Any]] = {}
        self.avg_goal_rate: float = 1.36
        self.avg_corner_rate: float = 4.90
        self.total_matches_trained: int = 0
        self.max_training_date: str = ""
        self.get_team_rating = functools.lru_cache(maxsize=4096)(self._get_team_rating_uncached)

    def fit_from_data(self) -> None:
        """Train ratings from the ground truth parquet dataset plus supplemental CSVs."""
        import duckdb
        import pandas as pd

        if not self.parquet_path.exists():
            raise FileNotFoundError(f"Ground truth dataset not found at {self.parquet_path}")

        con = duckdb.connect()
        query = (
            f"SELECT date, league, div_code, home_team, away_team, fthg, ftag, "
            f"home_corners, away_corners, home_shots, away_shots, home_shots_target, away_shots_target "
            f"FROM read_parquet('{self.parquet_path.as_posix()}') "
            f"WHERE fthg IS NOT NULL AND ftag IS NOT NULL"
        )
        df = con.execute(query).df()
        con.close()

        # Ingest supplemental multi-season archives (BRA.csv & USA.csv up to late 2026) if available
        raw_odds_dir = self.parquet_path.parent.parent / "raw_odds"
        extra_frames = [df]
        for fname, league_lbl, div_code in (
            ("BRA.csv", "Brasileirao Serie A", "BRA"),
            ("USA.csv", "USA MLS", "USA"),
        ):
            csv_path = raw_odds_dir / fname
            if not csv_path.exists():
                continue
            try:
                raw_df = pd.read_csv(csv_path)
                if not {"Date", "Home", "Away", "HG", "AG"}.issubset(raw_df.columns):
                    continue
                sub = raw_df[["Date", "Home", "Away", "HG", "AG"]].dropna().copy()
                sub["date"] = pd.to_datetime(sub["Date"], dayfirst=True, errors="coerce").dt.strftime("%Y-%m-%d")
                sub = sub.dropna(subset=["date"])
                sub = sub.rename(columns={"Home": "home_team", "Away": "away_team", "HG": "fthg", "AG": "ftag"})
                sub["league"] = league_lbl
                sub["div_code"] = div_code
                for col in ("home_corners", "away_corners", "home_shots", "away_shots", "home_shots_target", "away_shots_target"):
                    sub[col] = None
                extra_frames.append(sub[df.columns])
            except Exception:
                continue

        if len(extra_frames) > 1:
            df = pd.concat(extra_frames, ignore_index=True)

        self.total_matches_trained = len(df)
        max_date_str = str(df["date"].max())
        self.max_training_date = max_date_str[:10]
        ref_date = datetime.strptime(max_date_str[:10], "%Y-%m-%d")

        # Empirical conversion rate from Shots on Target (HST/AST) to Goals for xG-proxy blending
        raw_goal_mean = float((df["fthg"].sum() + df["ftag"].sum()) / max(1, 2 * len(df)))
        st_valid = df.dropna(subset=["home_shots_target", "away_shots_target"])
        avg_hst = (
            float((st_valid["home_shots_target"].sum() + st_valid["away_shots_target"].sum()) / max(1, 2 * len(st_valid)))
            if len(st_valid) > 0
            else 4.40
        )
        goal_per_hst = raw_goal_mean / max(avg_hst, 1.0)

        team_stats: dict[str, dict[str, Any]] = {}

        for _, row in df.iterrows():
            m_date = datetime.strptime(str(row["date"])[:10], "%Y-%m-%d")
            days_ago = max(0, (ref_date - m_date).days)
            w = math.exp(-self.xi * days_ago)

            ht = str(row["home_team"]).strip()
            at = str(row["away_team"]).strip()
            hg = float(row["fthg"])
            ag = float(row["ftag"])
            hst_val = row.get("home_shots_target")
            ast_val = row.get("away_shots_target")
            if hst_val is not None and ast_val is not None and not (math.isnan(float(hst_val)) or math.isnan(float(ast_val))):
                eff_hg = 0.55 * hg + 0.45 * (float(hst_val) * goal_per_hst)
                eff_ag = 0.55 * ag + 0.45 * (float(ast_val) * goal_per_hst)
            else:
                eff_hg, eff_ag = hg, ag

            hc = float(row["home_corners"]) if row["home_corners"] is not None and not math.isnan(row["home_corners"]) else None
            ac = float(row["away_corners"]) if row["away_corners"] is not None and not math.isnan(row["away_corners"]) else None
            hs_val = row.get("home_shots")
            as_val = row.get("away_shots")

            for t, l_name in ((ht, row["league"]), (at, row["league"])):
                if t not in team_stats:
                    team_stats[t] = {
                        "w_sum": 0.0,
                        "gf_w": 0.0,
                        "ga_w": 0.0,
                        "corn_w_sum": 0.0,
                        "corn_f_w": 0.0,
                        "corn_a_w": 0.0,
                        "matches": 0,
                        "league": str(l_name),
                    }

            team_stats[ht]["w_sum"] += w
            team_stats[ht]["gf_w"] += w * eff_hg
            team_stats[ht]["ga_w"] += w * eff_ag
            team_stats[ht]["matches"] += 1

            team_stats[at]["w_sum"] += w
            team_stats[at]["gf_w"] += w * eff_ag
            team_stats[at]["ga_w"] += w * eff_hg
            team_stats[at]["matches"] += 1

            if hc is not None and ac is not None:
                if hs_val is not None and as_val is not None and not (math.isnan(float(hs_val)) or math.isnan(float(as_val))):
                    eff_hc = 0.75 * hc + 0.25 * (float(hs_val) * 0.38)
                    eff_ac = 0.75 * ac + 0.25 * (float(as_val) * 0.38)
                else:
                    eff_hc, eff_ac = hc, ac
                team_stats[ht]["corn_w_sum"] += w
                team_stats[ht]["corn_f_w"] += w * eff_hc
                team_stats[ht]["corn_a_w"] += w * eff_ac

                team_stats[at]["corn_w_sum"] += w
                team_stats[at]["corn_f_w"] += w * eff_ac
                team_stats[at]["corn_a_w"] += w * eff_hc

        tot_w = sum(s["w_sum"] for s in team_stats.values())
        tot_gf = sum(s["gf_w"] for s in team_stats.values())
        self.avg_goal_rate = tot_gf / tot_w if tot_w > 0 else 1.36

        tot_c_w = sum(s["corn_w_sum"] for s in team_stats.values())
        tot_c = sum(s["corn_f_w"] for s in team_stats.values())
        self.avg_corner_rate = tot_c / tot_c_w if tot_c_w > 0 else 4.90

        # Calculate shrunk ratings
        ratings: dict[str, dict[str, Any]] = {}
        for t, s in team_stats.items():
            w_sum = s["w_sum"]
            if w_sum <= 0.0:
                continue

            obs_att = s["gf_w"] / (w_sum * self.avg_goal_rate)
            obs_def = s["ga_w"] / (w_sum * self.avg_goal_rate)

            shrink = w_sum / (w_sum + self.tau_0)
            alpha = shrink * math.log(max(obs_att, 0.2))
            beta = shrink * math.log(max(obs_def, 0.2))

            if s["corn_w_sum"] > 3.0:
                c_shrink = s["corn_w_sum"] / (s["corn_w_sum"] + self.tau_0)
                c_obs_att = s["corn_f_w"] / (s["corn_w_sum"] * self.avg_corner_rate)
                c_obs_def = s["corn_a_w"] / (s["corn_w_sum"] * self.avg_corner_rate)
                c_alpha = c_shrink * math.log(max(c_obs_att, 0.2))
                c_beta = c_shrink * math.log(max(c_obs_def, 0.2))
            else:
                c_alpha, c_beta = 0.0, 0.0

            ratings[t] = {
                "team": t,
                "league": s["league"],
                "matches": s["matches"],
                "alpha": round(alpha, 4),
                "beta": round(beta, 4),
                "corner_alpha": round(c_alpha, 4),
                "corner_beta": round(c_beta, 4),
                "net_rating": round(alpha - beta, 4),
            }

        self.team_ratings = ratings
        self.get_team_rating.cache_clear()
        self._save_cache()

    def _save_cache(self) -> None:
        """Persist computed parameters to silver cache for instantaneous reloading."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "meta": {
                "updated_at": datetime.now(UTC).isoformat(),
                "total_matches_trained": self.total_matches_trained,
                "max_training_date": self.max_training_date,
                "avg_goal_rate": self.avg_goal_rate,
                "avg_corner_rate": self.avg_corner_rate,
                "teams_count": len(self.team_ratings),
            },
            "ratings": self.team_ratings,
        }
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def load_or_train(self, force_recompute: bool = False) -> None:
        """Load from cache if available, or train from parquet."""
        if not force_recompute and self.cache_path.exists():
            try:
                with open(self.cache_path, encoding="utf-8") as f:
                    payload = json.load(f)
                meta = payload.get("meta", {})
                self.team_ratings = payload.get("ratings", {})
                self.avg_goal_rate = float(meta.get("avg_goal_rate", 1.36))
                self.avg_corner_rate = float(meta.get("avg_corner_rate", 4.90))
                self.total_matches_trained = int(meta.get("total_matches_trained", 0))
                self.max_training_date = str(meta.get("max_training_date", ""))
                self.get_team_rating.cache_clear()
                return
            except Exception:
                pass  # Fall back to training
        self.fit_from_data()

    def _get_team_rating_uncached(self, team_name: str) -> dict[str, Any]:
        """Fetch team rating with alias resolution and fallback to neutral average."""
        if team_name in self.team_ratings:
            return self.team_ratings[team_name]

        # Fuzzy match via TeamNormalizer
        best_match = None
        best_score = 0.0
        for t_key in self.team_ratings:
            sim = self.normalizer.compute_similarity(team_name, t_key)
            if sim > best_score:
                best_score = sim
                best_match = t_key

        if best_match and best_score >= 0.70:
            return self.team_ratings[best_match]

        # Neutral fallback
        return {
            "team": team_name,
            "league": "Unknown",
            "matches": 0,
            "alpha": 0.0,
            "beta": 0.0,
            "corner_alpha": 0.0,
            "corner_beta": 0.0,
            "net_rating": 0.0,
        }

    def predict_lambdas(
        self, home_team: str, away_team: str
    ) -> tuple[float, float, float, float]:
        """Compute (lambda_h, lambda_a, corn_lambda_h, corn_lambda_a)."""
        h_r = self.get_team_rating(home_team)
        a_r = self.get_team_rating(away_team)

        # Cross-league division quality tier adjustment
        h_tier = LEAGUE_TIER_MAP.get(str(h_r.get("league", "")))
        a_tier = LEAGUE_TIER_MAP.get(str(a_r.get("league", "")))
        tier_adj = (a_tier - h_tier) * 0.55 if (h_tier and a_tier and h_tier != a_tier) else 0.0
        c_tier_adj = (a_tier - h_tier) * 0.30 if (h_tier and a_tier and h_tier != a_tier) else 0.0

        mu_g = math.log(self.avg_goal_rate)
        # lambda_h = exp(mu + home_adv + alpha_h + beta_a + tier_adj)
        # If opponent has leaky defense (beta > 0) or is lower tier, home team scores more
        lam_h = math.exp(mu_g + self.home_adv_goals + h_r["alpha"] + a_r["beta"] + tier_adj)
        lam_a = math.exp(mu_g + a_r["alpha"] + h_r["beta"] - tier_adj)

        mu_c = math.log(self.avg_corner_rate)
        c_lam_h = math.exp(mu_c + self.home_adv_corners + h_r["corner_alpha"] + a_r["corner_beta"] + c_tier_adj)
        c_lam_a = math.exp(mu_c + a_r["corner_alpha"] + h_r["corner_beta"] - c_tier_adj)

        # Safety clamps
        lam_h = max(0.20, min(5.0, lam_h))
        lam_a = max(0.15, min(4.5, lam_a))
        c_lam_h = max(1.5, min(12.0, c_lam_h))
        c_lam_a = max(1.0, min(10.0, c_lam_a))

        return lam_h, lam_a, c_lam_h, c_lam_a

    def predict_match(self, home_team: str, away_team: str) -> dict[str, Any]:
        """Comprehensive market pricing from Dixon-Coles and Negative Binomial distributions."""
        lam_h, lam_a, c_lam_h, c_lam_a = self.predict_lambdas(home_team, away_team)

        # 1. Bivariate Goal Matrix (0 to 8 goals each)
        max_g = 8
        joint_scores: dict[tuple[int, int], float] = {}
        for x in range(max_g + 1):
            px = _poisson_pmf(x, lam_h)
            for y in range(max_g + 1):
                py = _poisson_pmf(y, lam_a)
                tau = _dixon_coles_tau(x, y, lam_h, lam_a, rho=-0.06)
                joint_scores[(x, y)] = max(0.0, px * py * tau)

        # Re-normalize matrix to 1.0
        tot_p = sum(joint_scores.values())
        if tot_p > 0.0:
            for k in joint_scores:
                joint_scores[k] /= tot_p

        p_h = sum(p for (x, y), p in joint_scores.items() if x > y)
        p_d = sum(p for (x, y), p in joint_scores.items() if x == y)
        p_a = sum(p for (x, y), p in joint_scores.items() if x < y)

        # 2. Double Chance
        p_1x = p_h + p_d
        p_x2 = p_d + p_a
        p_12 = p_h + p_a

        # 3. Draw No Bet (void on draw)
        dnb_denom = p_h + p_a
        p_dnb1 = p_h / dnb_denom if dnb_denom > 0 else 0.5
        p_dnb2 = p_a / dnb_denom if dnb_denom > 0 else 0.5

        # 4. Totals Over / Under
        p_o15 = sum(p for (x, y), p in joint_scores.items() if (x + y) > 1.5)
        p_o25 = sum(p for (x, y), p in joint_scores.items() if (x + y) > 2.5)
        p_o35 = sum(p for (x, y), p in joint_scores.items() if (x + y) > 3.5)
        p_tg6 = sum(p for (x, y), p in joint_scores.items() if (x + y) >= 6)

        # 5. Both Teams To Score (BTTS)
        p_btts = sum(p for (x, y), p in joint_scores.items() if x > 0 and y > 0)

        # 6. Correct Scores Top Picks
        sorted_scores = sorted(joint_scores.items(), key=lambda item: item[1], reverse=True)
        top_scores = [
            {"score": f"{x}:{y}", "prob": round(p, 4), "fair_odd": round(1.0 / p, 2) if p > 0 else 999.0}
            for (x, y), p in sorted_scores[:5]
        ]

        # 7. Corner Distribution via Negative Binomial
        tot_c_lam = c_lam_h + c_lam_a
        # Over/Under lines for 7.5, 8.5, 9.5, 10.5, 11.5
        corner_lines: dict[str, dict[str, float]] = {}
        for line in (7.5, 8.5, 9.5, 10.5, 11.5):
            threshold = int(line)
            p_under = sum(_neg_bin_pmf(k, tot_c_lam, kappa=0.14) for k in range(threshold + 1))
            p_under = max(0.01, min(0.99, p_under))
            p_over = 1.0 - p_under
            corner_lines[f"{line}"] = {
                "p_under": round(p_under, 4),
                "p_over": round(p_over, 4),
                "fair_under": round(1.0 / p_under, 2),
                "fair_over": round(1.0 / p_over, 2),
            }

        # 8. HT/FT Transitions via Bivariate Poisson / Dixon-Coles Markov Transition Matrix
        htft_transitions = price_htft_transitions(lam_h, lam_a)
        htft_probs: dict[str, float] = {
            lbl: float(val["prob"]) for lbl, val in htft_transitions.items()
        }

        tot_htft = sum(htft_probs.values())
        if tot_htft > 0:
            for k in htft_probs:
                htft_probs[k] /= tot_htft

        return {
            "home_team": home_team,
            "away_team": away_team,
            "lambdas": {
                "goal_home": round(lam_h, 3),
                "goal_away": round(lam_a, 3),
                "goal_total": round(lam_h + lam_a, 3),
                "corner_home": round(c_lam_h, 2),
                "corner_away": round(c_lam_a, 2),
                "corner_total": round(tot_c_lam, 2),
            },
            "p_1x2": {"1": round(p_h, 4), "X": round(p_d, 4), "2": round(p_a, 4)},
            "fair_1x2": {
                "1": round(1.0 / p_h, 2) if p_h > 0 else 99.0,
                "X": round(1.0 / p_d, 2) if p_d > 0 else 99.0,
                "2": round(1.0 / p_a, 2) if p_a > 0 else 99.0,
            },
            "double_chance": {
                "1X": {"prob": round(p_1x, 4), "fair_odd": round(1.0 / p_1x, 2)},
                "X2": {"prob": round(p_x2, 4), "fair_odd": round(1.0 / p_x2, 2)},
                "12": {"prob": round(p_12, 4), "fair_odd": round(1.0 / p_12, 2)},
            },
            "dnb": {
                "DNB_1": {"prob": round(p_dnb1, 4), "fair_odd": round(1.0 / p_dnb1, 2)},
                "DNB_2": {"prob": round(p_dnb2, 4), "fair_odd": round(1.0 / p_dnb2, 2)},
            },
            "totals": {
                "over_15": {"prob": round(p_o15, 4), "fair_odd": round(1.0 / p_o15, 2)},
                "under_15": {"prob": round(1.0 - p_o15, 4), "fair_odd": round(1.0 / (1.0 - p_o15), 2)},
                "over_25": {"prob": round(p_o25, 4), "fair_odd": round(1.0 / p_o25, 2)},
                "under_25": {"prob": round(1.0 - p_o25, 4), "fair_odd": round(1.0 / (1.0 - p_o25), 2)},
                "over_35": {"prob": round(p_o35, 4), "fair_odd": round(1.0 / p_o35, 2)},
                "under_35": {"prob": round(1.0 - p_o35, 4), "fair_odd": round(1.0 / (1.0 - p_o35), 2)},
                "tg6": {"prob": round(p_tg6, 4), "fair_odd": round(1.0 / p_tg6, 2) if p_tg6 > 0 else 99.0},
            },
            "btts": {
                "yes": {"prob": round(p_btts, 4), "fair_odd": round(1.0 / p_btts, 2)},
                "no": {"prob": round(1.0 - p_btts, 4), "fair_odd": round(1.0 / (1.0 - p_btts), 2)},
            },
            "corners": corner_lines,
            "expected_corners": round(tot_c_lam, 2),
            "htft": {k: {"prob": round(v, 4), "fair_odd": round(1.0 / v, 2)} for k, v in htft_probs.items()},
            "top_correct_scores": top_scores,
        }

    def evaluate_live_fixture(
        self,
        fixture: dict[str, Any],
        min_edge_pct: float = 4.0,
        min_matches: int = MIN_SAMPLE_MATCHES,
        max_edge_pct: float = MAX_ANOMALY_EDGE_PCT,
        min_odds: float = 1.45,
    ) -> list[dict[str, Any]]:
        """Compare bookmaker odds against quantitative fair odds with low-sample & anomaly vetoes."""
        h_name = fixture.get("home", "")
        a_name = fixture.get("away", "")
        time_str = fixture.get("time_str", "")
        mbs = fixture.get("mbs", 1)
        f_country = fixture.get("country")

        # Fail-closed (SPEC-0012): Do not price teams below minimum sample threshold or mismatched country
        h_r = self.get_team_rating(h_name)
        a_r = self.get_team_rating(a_name)
        if int(h_r.get("matches", 0)) < min_matches or int(a_r.get("matches", 0)) < min_matches:
            return []
        if not _is_country_compatible(f_country, h_r.get("league")) or not _is_country_compatible(
            f_country, a_r.get("league")
        ):
            return []

        preds = self.predict_match(h_name, a_name)
        signals: list[dict[str, Any]] = []

        # 1. 1X2 Evaluation
        odds_1x2 = fixture.get("nesine_1x2")
        if odds_1x2 and len(odds_1x2) == 3:
            h_odd, d_odd, a_odd = odds_1x2
            for side, odd, p_key in (("MS 1", h_odd, "1"), ("MS X", d_odd, "X"), ("MS 2", a_odd, "2")):
                if odd and odd > 1.01:
                    prob = preds["p_1x2"][p_key]
                    edge = (prob * odd - 1.0) * 100
                    if edge >= min_edge_pct:
                        signals.append({
                            "match": f"{h_name} vs {a_name}",
                            "time": time_str,
                            "mbs": mbs,
                            "market": "1X2",
                            "selection": side,
                            "book_odd": odd,
                            "fair_odd": preds["fair_1x2"][p_key],
                            "prob": prob,
                            "edge_pct": round(edge, 1),
                            "tier": "TIER_1_SHIELD" if prob >= 0.68 else "TIER_2_VALUE",
                        })

        # 2. Double Chance Evaluation — strictly requires real Nesine MTID=3 odds (no synthetic fallback)
        dc_odds = fixture.get("nesine_dc") or {}
        if isinstance(dc_odds, dict) and dc_odds:
            for dc_key, dc_label in (
                ("1X", "1X (Ev & Beraberlik)"),
                ("X2", "X2 (Beraberlik & Deplasman)"),
            ):
                odd_dc = dc_odds.get(dc_key)
                if odd_dc and float(odd_dc) > 1.01:
                    odd_dc_f = float(odd_dc)
                    prob_dc = preds["double_chance"][dc_key]["prob"]
                    edge_dc = (prob_dc * odd_dc_f - 1.0) * 100.0
                    if edge_dc >= min_edge_pct:
                        signals.append({
                            "match": f"{h_name} vs {a_name}",
                            "time": time_str,
                            "mbs": mbs,
                            "market": "Çifte Şans",
                            "selection": dc_label,
                            "book_odd": odd_dc_f,
                            "fair_odd": preds["double_chance"][dc_key]["fair_odd"],
                            "prob": prob_dc,
                            "edge_pct": round(edge_dc, 1),
                            "tier": "TIER_1_SHIELD" if prob_dc >= 0.70 else "TIER_2_VALUE",
                            "is_synthetic": False,
                        })

        # 3. Totals 2.5 Evaluation (nesine_ou25 is (over_odd, under_odd))
        ou25 = fixture.get("nesine_ou25")
        if ou25 and len(ou25) == 2:
            o_odd, u_odd = ou25
            if u_odd and u_odd > 1.01:
                p_u = preds["totals"]["under_25"]["prob"]
                e_u = (p_u * u_odd - 1.0) * 100
                if e_u >= min_edge_pct:
                    signals.append({
                        "match": f"{h_name} vs {a_name}",
                        "time": time_str,
                        "mbs": mbs,
                        "market": "2.5 Gol",
                        "selection": "2.5 ALT",
                        "book_odd": u_odd,
                        "fair_odd": preds["totals"]["under_25"]["fair_odd"],
                        "prob": p_u,
                        "edge_pct": round(e_u, 1),
                        "tier": "TIER_1_SHIELD" if p_u >= 0.68 else "TIER_2_VALUE",
                    })
            if o_odd and o_odd > 1.01:
                p_o = preds["totals"]["over_25"]["prob"]
                e_o = (p_o * o_odd - 1.0) * 100
                if e_o >= min_edge_pct:
                    signals.append({
                        "match": f"{h_name} vs {a_name}",
                        "time": time_str,
                        "mbs": mbs,
                        "market": "2.5 Gol",
                        "selection": "2.5 ÜST",
                        "book_odd": o_odd,
                        "fair_odd": preds["totals"]["over_25"]["fair_odd"],
                        "prob": p_o,
                        "edge_pct": round(e_o, 1),
                        "tier": "TIER_1_SHIELD" if p_o >= 0.68 else "TIER_2_VALUE",
                    })

        # 4. Corner Markets
        corners = fixture.get("nesine_corners") or {}
        exp_corners = preds.get("expected_corners") or preds.get("lambdas", {}).get("corner_total")
        for line_str, c_data in corners.items():
            if line_str in preds["corners"]:
                p_eval = preds["corners"][line_str]
                u_odd = c_data.get("under")
                o_odd = c_data.get("over")
                if u_odd and u_odd > 1.01:
                    e_cu = (p_eval["p_under"] * u_odd - 1.0) * 100
                    if e_cu >= min_edge_pct:
                        signals.append({
                            "match": f"{h_name} vs {a_name}",
                            "home": h_name,
                            "away": a_name,
                            "time": time_str,
                            "mbs": mbs,
                            "market": f"Korner {line_str}",
                            "selection": f"Korner {line_str} ALT",
                            "outcome": f"Korner {line_str} ALT",
                            "book_odd": u_odd,
                            "soft_odds": u_odd,
                            "fair_odd": p_eval["fair_under"],
                            "fair_odds": p_eval["fair_under"],
                            "prob": p_eval["p_under"],
                            "edge_pct": round(e_cu, 1),
                            "tier": "TIER_1_SHIELD" if p_eval["p_under"] >= 0.68 else "TIER_2_VALUE",
                            "expected_corners": exp_corners,
                            "distribution": "NegativeBinomial",
                            "line": line_str,
                            "side": "ALT",
                            "is_corner": True,
                        })
                if o_odd and o_odd > 1.01:
                    e_co = (p_eval["p_over"] * o_odd - 1.0) * 100
                    if e_co >= min_edge_pct:
                        signals.append({
                            "match": f"{h_name} vs {a_name}",
                            "home": h_name,
                            "away": a_name,
                            "time": time_str,
                            "mbs": mbs,
                            "market": f"Korner {line_str}",
                            "selection": f"Korner {line_str} ÜST",
                            "outcome": f"Korner {line_str} ÜST",
                            "book_odd": o_odd,
                            "soft_odds": o_odd,
                            "fair_odd": p_eval["fair_over"],
                            "fair_odds": p_eval["fair_over"],
                            "prob": p_eval["p_over"],
                            "edge_pct": round(e_co, 1),
                            "tier": "TIER_1_SHIELD" if p_eval["p_over"] >= 0.68 else "TIER_2_VALUE",
                            "expected_corners": exp_corners,
                            "distribution": "NegativeBinomial",
                            "line": line_str,
                            "side": "ÜST",
                            "is_corner": True,
                        })

        # 5. HT/FT Transitions (High-Odds Value)
        htft_odds = fixture.get("nesine_htft") or {}
        for tr_label, tr_odd in htft_odds.items():
            if tr_label in preds["htft"] and tr_odd and tr_odd >= 3.5:
                p_tr = preds["htft"][tr_label]["prob"]
                e_tr = (p_tr * tr_odd - 1.0) * 100
                if e_tr >= 8.0:  # Minimum +8% edge required for high odds
                    signals.append({
                        "match": f"{h_name} vs {a_name}",
                        "time": time_str,
                        "mbs": mbs,
                        "market": "İY/MS",
                        "selection": f"İY/MS {tr_label}",
                        "book_odd": tr_odd,
                        "fair_odd": preds["htft"][tr_label]["fair_odd"],
                        "prob": p_tr,
                        "edge_pct": round(e_tr, 1),
                        "tier": "TIER_2_VALUE",
                    })

        # 6. Total Goals 6+
        tg6_odd = fixture.get("nesine_tg6")
        if tg6_odd and tg6_odd >= 3.0:
            p_tg6 = preds["totals"]["tg6"]["prob"]
            e_tg6 = (p_tg6 * tg6_odd - 1.0) * 100
            if e_tg6 >= 10.0:
                signals.append({
                    "match": f"{h_name} vs {a_name}",
                    "time": time_str,
                    "mbs": mbs,
                    "market": "Toplam Gol",
                    "selection": "TG 6+",
                    "book_odd": tg6_odd,
                    "fair_odd": preds["totals"]["tg6"]["fair_odd"],
                    "prob": p_tg6,
                    "edge_pct": round(e_tg6, 1),
                    "tier": "TIER_2_VALUE",
                })

        return [
            s for s in signals
            if float(s.get("book_odd") or 0.0) >= min_odds
            and float(s.get("edge_pct") or 0.0) <= max_edge_pct
        ]
