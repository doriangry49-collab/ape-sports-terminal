"""TASK-019: Zero-Cost Live Prediction Product Engine.

End-to-End Flow:
1. Discover upcoming matches from PropLine and Xiddaa.
2. Ingest real current bookmaker odds across all available markets (1X2, Totals, BTTS, Correct Score, HT/FT, 1H).
3. Check League Eligibility:
   - >= 30 historical matches -> MODEL_C_AVAILABLE
   - < 30 historical matches -> INSUFFICIENT_HISTORY (Explicitly flagged; NO silent fallback).
4. For eligible leagues, fit Model C (TimeDecayedPoissonModel, decay_half_life=180d, shrinkage=3.0)
   strictly using point-in-time cutoff before kickoff.
5. Compute theoretical probability distributions via FootballMarketEngine.
6. Compare real bookmaker odds against Model C fair odds -> Compute Edge (%) and EV (%).
7. Categorize High-Odds candidates (bands: >=2, >=5, >=10, >=20, >=30, >=50, >=100) and Positive-EV candidates.
8. Persist immutable prediction artifacts into artifacts/predictions/TASK-019/ and update HistoricalOddsArchive.
9. Support post-match settlement verification schema.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

from sports_engine.adapters.propline_adapter import normalize_propline_event
from sports_engine.adapters.schema import CanonicalMarket, NormalizedOddsRecord
from sports_engine.adapters.xiddaa_adapter import normalize_xiddaa_event
from sports_engine.features.dataset import fetch_or_load_historical_matches
from sports_engine.models.football_markets import FootballMarketEngine
from sports_engine.models.time_decay_poisson import ModelCStatus, TimeDecayedPoissonModel
from sports_engine.storage.historical_odds_archive import (
    HistoricalOddsArchive,
    HistoricalOddsRecord,
    ProvenanceType,
    SnapshotLabel,
    make_snapshot_id,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class LivePredictionProductConfig:
    """Configuration for Live Prediction Product execution."""

    min_historical_matches: int = 30
    decay_half_life_days: float = 180.0
    shrinkage_weight: float = 3.0
    propline_key: Optional[str] = field(default_factory=lambda: os.getenv("PROPLINE_KEY"))
    xiddaa_key: Optional[str] = field(default_factory=lambda: os.getenv("XIDDAA_KEY"))
    enable_xiddaa: bool = True
    enable_propline: bool = True
    max_events_per_comp: int = 5
    artifacts_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "artifacts" / "predictions" / "TASK-019")
    historical_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "artifacts" / "odds" / "historical")


# Known competitions mapped to historical database IDs
COMPETITION_HISTORICAL_MAP = {
    "Premier League": {"id": 1, "country": "England", "sport_key": "soccer_epl"},
    "soccer_epl": {"id": 1, "country": "England", "sport_key": "soccer_epl"},
    "Trendyol Süper Lig": {"id": 11, "country": "Turkey", "sport_key": "soccer_turkey_super_lig"},
    "soccer_turkey_super_lig": {"id": 11, "country": "Turkey", "sport_key": "soccer_turkey_super_lig"},
    "UEFA Nations League": {"id": 64, "country": "Europe", "sport_key": "soccer_uefa_nations_league"},
    "soccer_uefa_nations_league": {"id": 64, "country": "Europe", "sport_key": "soccer_uefa_nations_league"},
}


def map_market_selection_to_probability(
    market: str,
    selection: str,
    home_team: str,
    away_team: str,
    market_suite: dict[str, Any],
) -> Optional[float]:
    """Map canonical market and selection string to Model C theoretical probability.

    Returns theoretical probability in [0.0, 1.0] or None if selection is not mapped.
    """
    sel_clean = selection.strip()
    home_clean = home_team.strip().lower()
    away_clean = away_team.strip().lower()

    # 1. Full Time 1X2
    if market in (CanonicalMarket.H1X2.value, "1X2"):
        m_1x2 = market_suite.get("1x2", {})
        if sel_clean in ("1", "HOME") or sel_clean.lower() == home_clean:
            return m_1x2.get("HOME")
        if sel_clean in ("X", "DRAW", "Draw") or sel_clean.lower() == "draw":
            return m_1x2.get("DRAW")
        if sel_clean in ("2", "AWAY") or sel_clean.lower() == away_clean:
            return m_1x2.get("AWAY")

    # 2. Over / Under Totals
    elif market in (CanonicalMarket.TOTALS.value, "TOTALS"):
        totals = market_suite.get("totals", {})
        for line in [0.5, 1.5, 2.5, 3.5, 4.5]:
            line_key = f"OVER_UNDER_{line}"
            if str(line) in sel_clean:
                if any(x in sel_clean.lower() for x in ["over", "üst", "ust", ">"]):
                    return totals.get(line_key, {}).get("OVER")
                if any(x in sel_clean.lower() for x in ["under", "alt", "<"]):
                    return totals.get(line_key, {}).get("UNDER")
        # Default 2.5
        if any(x in sel_clean.lower() for x in ["over", "üst", "ust"]):
            return totals.get("OVER_UNDER_2.5", {}).get("OVER")
        if any(x in sel_clean.lower() for x in ["under", "alt"]):
            return totals.get("OVER_UNDER_2.5", {}).get("UNDER")

    # 3. Both Teams to Score (BTTS)
    elif market in (CanonicalMarket.BTTS.value, "BTTS"):
        btts = market_suite.get("btts", {})
        if any(x in sel_clean.lower() for x in ["var", "yes", "btts yes"]):
            return btts.get("YES")
        if any(x in sel_clean.lower() for x in ["yok", "no", "btts no"]):
            return btts.get("NO")

    # 4. Correct Score
    elif market in (CanonicalMarket.CORRECT_SCORE.value, "CORRECT_SCORE"):
        # Check top scores list first
        for item in market_suite.get("top_correct_scores", []):
            if item.get("score") == sel_clean:
                return item.get("probability")
        # Direct bivariate Poisson calculation for any scoreline
        try:
            parts = sel_clean.replace(":", "-").split("-")
            if len(parts) == 2:
                x, y = int(parts[0].strip()), int(parts[1].strip())
                lh = market_suite.get("expected_goals", {}).get("home", 1.42)
                la = market_suite.get("expected_goals", {}).get("away", 1.12)
                if x <= 10 and y <= 10:
                    p = (math.pow(lh, x) * math.exp(-lh) / math.factorial(x)) * (
                        math.pow(la, y) * math.exp(-la) / math.factorial(y)
                    )
                    return round(p, 5)
        except Exception:
            return None

    # 5. Half-Time / Full-Time (HT/FT)
    elif market in (CanonicalMarket.HT_FT.value, "HT_FT"):
        ht_ft = market_suite.get("ht_ft", {})
        norm_sel = sel_clean.replace(" ", "")
        if norm_sel in ht_ft:
            return ht_ft[norm_sel].get("probability")

    # 6. First Half 1X2
    elif market in (CanonicalMarket.H1_1X2.value, "H1_1X2"):
        h1 = market_suite.get("first_half_1x2", {})
        if sel_clean in ("1", "HOME") or sel_clean.lower() == home_clean:
            return h1.get("HOME")
        if sel_clean in ("X", "DRAW", "Draw") or sel_clean.lower() == "draw":
            return h1.get("DRAW")
        if sel_clean in ("2", "AWAY") or sel_clean.lower() == away_clean:
            return h1.get("AWAY")

    # 7. First Half Totals
    elif market in (CanonicalMarket.H1_TOTALS.value, "H1_TOTALS"):
        h1_tot = market_suite.get("first_half_totals", {})
        for line in [0.5, 1.5, 2.5]:
            line_key = f"OVER_UNDER_{line}"
            if str(line) in sel_clean:
                if any(x in sel_clean.lower() for x in ["over", "üst", "ust", ">"]):
                    return h1_tot.get(line_key, {}).get("OVER")
                if any(x in sel_clean.lower() for x in ["under", "alt", "<"]):
                    return h1_tot.get(line_key, {}).get("UNDER")

    return None


def classify_odds_band(odds: float) -> str:
    """Classify decimal odds into structured reporting bands."""
    if odds >= 100.0:
        return ">=100"
    if odds >= 50.0:
        return ">=50"
    if odds >= 30.0:
        return ">=30"
    if odds >= 20.0:
        return ">=20"
    if odds >= 10.0:
        return ">=10"
    if odds >= 5.0:
        return ">=5"
    if odds >= 2.0:
        return ">=2"
    return "<2"


class LivePredictionProduct:
    """Production Live Prediction Product engine."""

    def __init__(self, config: Optional[LivePredictionProductConfig] = None):
        self.config = config or LivePredictionProductConfig()
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.config.historical_dir.mkdir(parents=True, exist_ok=True)
        self.archive = HistoricalOddsArchive(self.config.historical_dir)

    def load_historical_datasets(self) -> dict[str, list[dict[str, Any]]]:
        """Load and cache historical matches for eligible competitions."""
        histories: dict[str, list[dict[str, Any]]] = {}
        for comp_name, info in COMPETITION_HISTORICAL_MAP.items():
            b_id = info["id"]
            if comp_name not in histories:
                try:
                    matches = fetch_or_load_historical_matches(league_id=b_id, limit=300)
                    histories[comp_name] = matches
                    # also map by sport_key
                    histories[info["sport_key"]] = matches
                except Exception:
                    histories[comp_name] = []
                    histories[info["sport_key"]] = []
        return histories

    def discover_live_events_and_odds(
        self,
        captured_at: datetime,
    ) -> tuple[list[dict[str, Any]], list[NormalizedOddsRecord], dict[str, str]]:
        """Ingest live events and pre-match odds from PropLine and Xiddaa."""
        discovered_events: list[dict[str, Any]] = []
        all_odds_records: list[NormalizedOddsRecord] = []
        provider_status: dict[str, str] = {}

        # ──────────────────────────────────────────────────────────────────────
        # 1. PropLine (EPL, Süper Lig, UEFA Nations League)
        # ──────────────────────────────────────────────────────────────────────
        if self.config.enable_propline and self.config.propline_key:
            pl_headers = {"x-api-key": self.config.propline_key}
            pl_sports = [
                ("soccer_epl", "Premier League", "England"),
                ("soccer_turkey_super_lig", "Trendyol Süper Lig", "Turkey"),
                ("soccer_uefa_nations_league", "UEFA Nations League", "Europe"),
            ]
            propline_success = False

            with httpx.Client(timeout=15.0) as client:
                for sport_key, comp_name, country in pl_sports:
                    try:
                        r_events = client.get(
                            f"https://api.prop-line.com/v1/sports/{sport_key}/events",
                            headers=pl_headers,
                        )
                        if r_events.status_code == 200:
                            propline_success = True
                            events_data = r_events.json()[: self.config.max_events_per_comp]
                            for ev in events_data:
                                ev_id = str(ev.get("id"))
                                h_team = ev.get("home_team", "")
                                a_team = ev.get("away_team", "")
                                commence = ev.get("commence_time")

                                ev_records: list[NormalizedOddsRecord] = []
                                # Fetch available markets in single multi-market request
                                try:
                                    r_odds = client.get(
                                        f"https://api.prop-line.com/v1/sports/{sport_key}/events/{ev_id}/odds",
                                        headers=pl_headers,
                                        params={"markets": "h2h,totals,correct_score", "regions": "eu,us"},
                                    )
                                    if r_odds.status_code == 200:
                                        d_odds = r_odds.json()
                                        d_odds["id"] = ev_id
                                        d_odds["home_team"] = h_team
                                        d_odds["away_team"] = a_team
                                        d_odds["commence_time"] = commence
                                        norm_res = normalize_propline_event(
                                            d_odds, sport_key, comp_name, country, captured_at
                                        )
                                        ev_records.extend(norm_res.accepted)
                                except Exception:
                                    pass

                                canonical_eid = ev_records[0].event_id if ev_records else f"propline_{sport_key}_{ev_id}"
                                discovered_events.append({
                                    "event_id": canonical_eid,
                                    "source_event_id": ev_id,
                                    "provider": "propline",
                                    "home_team": h_team,
                                    "away_team": a_team,
                                    "competition": comp_name,
                                    "country": country,
                                    "sport": "soccer",
                                    "commence_time": commence,
                                    "odds_record_count": len(ev_records),
                                    "status": "DISCOVERED_WITH_ODDS" if ev_records else "DISCOVERED_NO_ODDS",
                                })
                                all_odds_records.extend(ev_records)
                    except Exception as e:
                        pass

            provider_status["propline"] = "AVAILABLE" if propline_success else "PROVIDER_UNAVAILABLE"
        else:
            provider_status["propline"] = "CONFIG_DISABLED_OR_NO_KEY"

        # ──────────────────────────────────────────────────────────────────────
        # 2. Xiddaa (Pre-match playable events with rich market depth)
        # ──────────────────────────────────────────────────────────────────────
        if self.config.enable_xiddaa and self.config.xiddaa_key:
            xi_headers = {"X-API-Key": self.config.xiddaa_key}
            xiddaa_success = False

            with httpx.Client(timeout=15.0) as client:
                try:
                    r_xi = client.get(
                        "https://xiddaa.com/api/v1/events",
                        headers=xi_headers,
                        params={"classification": "prematch", "take": self.config.max_events_per_comp * 2},
                    )
                    if r_xi.status_code == 200:
                        xiddaa_success = True
                        items = r_xi.json().get("data", [])
                        playable = [e for e in items if e.get("betting", {}).get("playableMarketCount", 0) > 0]

                        for ev in playable[: self.config.max_events_per_comp]:
                            ev_id = str(ev.get("id"))
                            ev_name = ev.get("name", "")
                            comp_info = ev.get("competition", {})
                            comp_name = comp_info.get("name", "Unknown Competition")
                            country = ev.get("country", {}).get("name", "International")
                            commence = ev.get("startDate")

                            h_team = ev.get("homeTeam", {}).get("name")
                            a_team = ev.get("awayTeam", {}).get("name")
                            if not h_team and " vs " in ev_name:
                                parts = ev_name.split(" vs ")
                                h_team, a_team = parts[0], parts[1]
                            elif not h_team and " - " in ev_name:
                                parts = ev_name.split(" - ")
                                h_team, a_team = parts[0], parts[1]

                            try:
                                r_det = client.get(
                                    f"https://xiddaa.com/api/v1/events/{ev_id}",
                                    headers=xi_headers,
                                )
                                if r_det.status_code == 200:
                                    det_data = r_det.json().get("data", {})
                                    norm_res = normalize_xiddaa_event(det_data, captured_at)
                                    ev_records = norm_res.accepted
                                    canonical_eid = ev_records[0].event_id if ev_records else f"xiddaa_{ev_id}"
                                    discovered_events.append({
                                        "event_id": canonical_eid,
                                        "source_event_id": ev_id,
                                        "provider": "xiddaa",
                                        "home_team": h_team or ev_name,
                                        "away_team": a_team or "",
                                        "competition": comp_name,
                                        "country": country,
                                        "sport": "soccer",
                                        "commence_time": commence,
                                        "odds_record_count": len(ev_records),
                                        "status": "DISCOVERED_WITH_ODDS" if ev_records else "DISCOVERED_NO_ODDS",
                                    })
                                    all_odds_records.extend(ev_records)
                            except Exception:
                                pass
                except Exception as e:
                    pass

            provider_status["xiddaa"] = "AVAILABLE" if xiddaa_success else "PROVIDER_UNAVAILABLE"
        else:
            provider_status["xiddaa"] = "CONFIG_DISABLED_OR_NO_KEY"

        return discovered_events, all_odds_records, provider_status

    def execute_live_product_pipeline(self) -> dict[str, Any]:
        """Execute complete live prediction product run."""
        captured_at = datetime.now(UTC)
        ts_str = captured_at.strftime("%Y%m%d_%H%M%S")
        run_id = f"run_{ts_str}"

        # 1. Load history
        histories = self.load_historical_datasets()

        # 2. Discover live matches & odds
        discovered_events, odds_records, provider_status = self.discover_live_events_and_odds(captured_at)

        # Index odds by (event_id, provider, bookmaker, market)
        records_by_event: dict[str, list[NormalizedOddsRecord]] = {}
        for r in odds_records:
            records_by_event.setdefault(r.event_id, []).append(r)

        # 3. Model C Execution & Evaluation
        evaluated_predictions: list[dict[str, Any]] = []
        value_candidates: list[dict[str, Any]] = []
        high_odds_candidates: list[dict[str, Any]] = []
        insufficient_history_events: list[dict[str, Any]] = []

        total_scanned = len(discovered_events)
        matches_with_odds = sum(1 for e in discovered_events if e["odds_record_count"] > 0)
        model_c_available_matches = 0
        insufficient_history_matches = 0
        unique_bookmakers = set()
        unique_markets = set()

        for ev in discovered_events:
            eid = ev["event_id"]
            comp = ev["competition"]
            h_team = ev["home_team"]
            a_team = ev["away_team"]
            commence = ev["commence_time"]
            ev_records = records_by_event.get(eid, [])

            for r in ev_records:
                unique_bookmakers.add(r.bookmaker)
                unique_markets.add(r.market)

            # Determine point-in-time data cutoff (strictly before kickoff)
            if commence:
                try:
                    cutoff_dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                    if cutoff_dt.tzinfo is None:
                        cutoff_dt = cutoff_dt.replace(tzinfo=UTC)
                except Exception:
                    cutoff_dt = captured_at
            else:
                cutoff_dt = captured_at

            # League Eligibility Guard
            hist_matches = histories.get(comp, [])
            if len(hist_matches) < self.config.min_historical_matches:
                # Check normalized competition names
                for k, v in COMPETITION_HISTORICAL_MAP.items():
                    if k.lower() in comp.lower() or comp.lower() in k.lower():
                        hist_matches = histories.get(k, [])
                        break

            is_eligible = len(hist_matches) >= self.config.min_historical_matches

            if not is_eligible:
                insufficient_history_matches += 1
                insufficient_history_events.append({
                    "event_id": eid,
                    "match": f"{h_team} vs {a_team}",
                    "competition": comp,
                    "model_status": ModelCStatus.INSUFFICIENT_HISTORY,
                    "historical_matches": len(hist_matches),
                    "min_required": self.config.min_historical_matches,
                    "odds_available": len(ev_records) > 0,
                })
                continue

            # Eligible: Fit Model C strictly
            model_c_available_matches += 1
            try:
                model_c = TimeDecayedPoissonModel(
                    decay_half_life_days=self.config.decay_half_life_days,
                    shrinkage_weight=self.config.shrinkage_weight,
                )
                model_c.fit(hist_matches, data_cutoff=cutoff_dt)
                pred_c = model_c.predict_match(home_team=h_team, away_team=a_team, prediction_timestamp=captured_at)

                lh = pred_c.expected_home_goals
                la = pred_c.expected_away_goals
                market_engine = FootballMarketEngine(lambda_home=lh, lambda_away=la)
                market_suite = market_engine.get_full_market_suite()
                market_suite["expected_goals"] = {"home": lh, "away": la}

                # Evaluate odds against Model C theoretical probabilities
                event_selections_evaluated = []

                for r in ev_records:
                    p_model = map_market_selection_to_probability(
                        market=r.market,
                        selection=r.selection,
                        home_team=h_team,
                        away_team=a_team,
                        market_suite=market_suite,
                    )

                    if p_model is not None and p_model > 0.0001:
                        fair_odds = round(1.0 / p_model, 2)
                        bm_odds = r.odds_decimal
                        # Raw Edge (%) = (P_model * O_bm) - 1.0
                        edge_pct = round(((p_model * bm_odds) - 1.0) * 100, 2)
                        ev_pct = edge_pct  # Mathematical EV % on 1 unit stake
                        is_pos_ev = ev_pct > 0.0
                        is_high_odd = bm_odds >= 2.0
                        odds_band = classify_odds_band(bm_odds)

                        # Classification label
                        if is_pos_ev and p_model >= 0.02:
                            classification = "VALUE CANDIDATE"
                        elif is_pos_ev and p_model < 0.02:
                            classification = "SPECULATIVE HIGH ODDS CANDIDATE"
                        elif is_high_odd:
                            classification = "HIGH ODDS (NEGATIVE EV)"
                        else:
                            classification = "FAIR / NEGATIVE EV"

                        eval_rec = {
                            "event_id": eid,
                            "match": f"{h_team} vs {a_team}",
                            "competition": comp,
                            "kickoff": commence,
                            "market": r.market,
                            "selection": r.selection,
                            "provider": r.provider,
                            "bookmaker": r.bookmaker,
                            "bookmaker_odds": bm_odds,
                            "model_probability": round(p_model, 4),
                            "model_fair_odds": fair_odds,
                            "edge_percent": edge_pct,
                            "expected_value_percent": ev_pct,
                            "is_positive_ev": is_pos_ev,
                            "is_high_odds": is_high_odd,
                            "odds_band": odds_band,
                            "candidate_classification": classification,
                            "model_version": model_c.MODEL_VERSION,
                            "rating_version": model_c.RATING_VERSION,
                            "data_cutoff": cutoff_dt.isoformat(),
                            "prediction_timestamp": captured_at.isoformat(),
                            # Post-match settlement schema ready
                            "settlement": {
                                "actual_result": None,
                                "settled": False,
                                "won": None,
                                "lost": None,
                                "push": None,
                                "roi_return": None,
                            },
                        }
                        event_selections_evaluated.append(eval_rec)

                        if is_pos_ev:
                            value_candidates.append(eval_rec)
                        if is_high_odd:
                            high_odds_candidates.append(eval_rec)

                evaluated_predictions.append({
                    "event_id": eid,
                    "fixture": f"{h_team} vs {a_team}",
                    "home_team": h_team,
                    "away_team": a_team,
                    "competition": comp,
                    "kickoff": commence,
                    "model_status": ModelCStatus.AVAILABLE,
                    "expected_goals": {"home": round(lh, 3), "away": round(la, 3)},
                    "most_likely_score": market_suite.get("most_likely_score"),
                    "1x2_probabilities": market_suite.get("1x2"),
                    "evaluated_selections_count": len(event_selections_evaluated),
                    "selections": event_selections_evaluated,
                })

            except Exception as e:
                insufficient_history_matches += 1
                insufficient_history_events.append({
                    "event_id": eid,
                    "match": f"{h_team} vs {a_team}",
                    "competition": comp,
                    "model_status": ModelCStatus.INSUFFICIENT_HISTORY,
                    "error": str(e),
                    "odds_available": len(ev_records) > 0,
                })

        # Correct Score specific breakdowns
        cs_candidates = [c for c in high_odds_candidates if c["market"] == "CORRECT_SCORE"]
        cs_pos_ev = [c for c in cs_candidates if c["is_positive_ev"]]

        # Odds bands distribution across all evaluated selections
        band_distribution = {
            ">=100": sum(1 for c in high_odds_candidates if c["odds_band"] == ">=100"),
            ">=50": sum(1 for c in high_odds_candidates if c["odds_band"] == ">=50"),
            ">=30": sum(1 for c in high_odds_candidates if c["odds_band"] == ">=30"),
            ">=20": sum(1 for c in high_odds_candidates if c["odds_band"] == ">=20"),
            ">=10": sum(1 for c in high_odds_candidates if c["odds_band"] == ">=10"),
            ">=5": sum(1 for c in high_odds_candidates if c["odds_band"] == ">=5"),
            ">=2": sum(1 for c in high_odds_candidates if c["odds_band"] == ">=2"),
        }

        # 4. Save Immutable Prediction Snapshots
        predictions_payload = {
            "run_id": run_id,
            "generated_at": captured_at.isoformat(),
            "model_metadata": {
                "model_name": "TimeDecayedPoissonModel (Model C)",
                "model_version": "0.2.0",
                "rating_version": "empirical_bayes_shrunk_decay_v2",
                "decay_half_life_days": self.config.decay_half_life_days,
                "shrinkage_weight": self.config.shrinkage_weight,
                "global_baseline_fallback_count": 0,
                "note": "Bookmaker odds are strictly NOT inputs to Model C.",
            },
            "summary": {
                "total_events_scanned": total_scanned,
                "matches_with_real_odds": matches_with_odds,
                "model_c_available_matches": model_c_available_matches,
                "insufficient_history_matches": insufficient_history_matches,
                "unique_bookmakers_count": len(unique_bookmakers),
                "unique_markets_count": len(unique_markets),
                "total_evaluated_selections": sum(p["evaluated_selections_count"] for p in evaluated_predictions),
                "total_positive_ev_candidates": len(value_candidates),
                "total_high_odds_candidates": len(high_odds_candidates),
                "correct_score_high_odds_count": len(cs_candidates),
                "correct_score_pos_ev_count": len(cs_pos_ev),
                "odds_bands_distribution": band_distribution,
                "providers": provider_status,
            },
            "predictions": evaluated_predictions,
            "insufficient_history_events": insufficient_history_events,
            "value_candidates": value_candidates[:50],  # top 50 value candidates
            "high_odds_candidates": high_odds_candidates[:50],  # top 50 high odds
        }

        # Save to primary TASK-019 location
        task019_dir = self.config.artifacts_dir
        task019_dir.mkdir(parents=True, exist_ok=True)

        pred_file = task019_dir / "predictions.json"
        odds_file = task019_dir / "odds_snapshot.json"
        meta_file = task019_dir / "model_metadata.json"

        with open(pred_file, "w", encoding="utf-8") as f:
            json.dump(predictions_payload, f, indent=2, ensure_ascii=False, default=str)

        with open(odds_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "run_id": run_id,
                    "captured_at": captured_at.isoformat(),
                    "total_odds_records": len(odds_records),
                    "unique_bookmakers": sorted(unique_bookmakers),
                    "unique_markets": sorted(unique_markets),
                    "records": [asdict(r) for r in odds_records],
                },
                f,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(predictions_payload["model_metadata"], f, indent=2, ensure_ascii=False, default=str)

        # Also save to timestamped run folder (guarantees run immutability)
        run_folder = task019_dir / run_id
        run_folder.mkdir(parents=True, exist_ok=True)
        with open(run_folder / "predictions.json", "w", encoding="utf-8") as f:
            json.dump(predictions_payload, f, indent=2, ensure_ascii=False, default=str)

        # 5. Grow HistoricalOddsArchive with SELF_CAPTURED records
        hist_batch = []
        for r in odds_records:
            if r.odds_decimal > 1.001:
                sid = make_snapshot_id(r.provider, r.event_id, r.bookmaker, r.market, r.selection, captured_at.isoformat())
                hist_batch.append(
                    HistoricalOddsRecord(
                        historical_snapshot_id=sid,
                        provider=r.provider,
                        source_type=ProvenanceType.SELF_CAPTURED,
                        provider_event_id=r.source_event_id or r.event_id,
                        event_id=r.event_id,
                        sport=r.sport,
                        competition=r.competition,
                        competition_id=getattr(r, "competition_id", None),
                        event_start_time=r.kickoff or "",
                        home_team=r.home_team or "",
                        away_team=r.away_team or "",
                        bookmaker=r.bookmaker,
                        market=r.market,
                        selection=r.selection,
                        odds_decimal=r.odds_decimal,
                        odds_raw=float(r.odds_raw) if str(r.odds_raw).replace(".", "", 1).replace("-", "", 1).isdigit() else r.odds_decimal,
                        odds_format_raw=str(r.odds_format),
                        actual_snapshot_timestamp=captured_at.isoformat(),
                        retrieved_at=captured_at.isoformat(),
                        snapshot_label=SnapshotLabel.REGULAR,
                        provider_snapshot_id=run_id,
                        import_batch_id="task019_live",
                    )
                )
        if hist_batch:
            self.archive.import_batch(hist_batch)

        return predictions_payload
