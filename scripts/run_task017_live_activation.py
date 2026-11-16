"""TASK-017: Model C Live Activation, League Eligibility Guard & Historical Odds Archive.

Execution flow:
1. Ingest real pre-match odds from PropLine & Xiddaa using canonical adapters.
2. Determine League Eligibility:
   - Competitions with >= 30 historical matches -> MODEL_C_AVAILABLE (Fit Time-Decayed Model C).
   - Competitions with < 30 historical matches -> INSUFFICIENT_HISTORY (Explicitly flagged; NO silent fallback).
3. Compute Model C Expected Goals, Probabilities & Fair Odds.
4. Calculate Selection Edge & Expected Value against live bookmaker consensus.
5. Re-evaluate TASK-015's 505 Value + High Odds candidates (Global Baseline vs Model C).
6. Archive immutable snapshot into artifacts/odds/TASK-017-odds-history/.
7. Compute line movements against prior snapshot archive.
8. Output artifacts/backtests/TASK-017-model-comparison.json.
"""

import os
import sys
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import httpx
from dotenv import load_dotenv

# Fix Windows cp1254 console encoding (prevents UnicodeEncodeError on Greek chars)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Path setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

load_dotenv(PROJECT_ROOT / ".env")

from sports_engine.adapters.propline_adapter import normalize_propline_event
from sports_engine.adapters.xiddaa_adapter import normalize_xiddaa_event
from sports_engine.adapters.schema import CanonicalMarket, NormalizedOddsRecord
from sports_engine.models.time_decay_poisson import TimeDecayedPoissonModel, ModelCStatus
from sports_engine.models.football_markets import FootballMarketEngine
from sports_engine.pricing.no_vig import no_vig_multiplicative
from sports_engine.features.dataset import fetch_or_load_historical_matches
from sports_engine.storage.odds_archive import OddsArchiveManager, HistoricalOddsEntry

PROPLINE_KEY = os.getenv("PROPLINE_KEY")
XIDDAA_KEY = os.getenv("XIDDAA_KEY")

SNAPSHOT_DIR = PROJECT_ROOT / "artifacts" / "snapshots"
ODDS_HISTORY_DIR = PROJECT_ROOT / "artifacts" / "odds" / "TASK-017-odds-history"
BACKTEST_DIR = PROJECT_ROOT / "artifacts" / "backtests"
AUDIT_DIR = PROJECT_ROOT / "artifacts" / "audits"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
ODDS_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_DIR.mkdir(parents=True, exist_ok=True)


# Preload known historical match databases
LEAGUE_ID_MAP = {
    "Premier League": 1,
    "soccer_epl": 1,
    "Trendyol Süper Lig": 11,
    "soccer_turkey_super_league": 11,
    "UEFA Nations League": 64,
    "soccer_uefa_nations_league": 64,
}


def map_selection_to_model(
    market: str,
    selection: str,
    home_team: str,
    away_team: str,
    model_suite: dict[str, Any],
) -> float | None:
    """Map canonical market and selection string to model probability."""
    sel_u = selection.strip()
    home_u = home_team.strip().lower()
    away_u = away_team.strip().lower()

    if market == CanonicalMarket.H1X2.value or market == "1X2":
        m_1x2 = model_suite.get("1x2", {})
        if sel_u in ("1", "HOME") or sel_u.lower() == home_u:
            return m_1x2.get("HOME")
        if sel_u in ("X", "DRAW", "Draw") or sel_u.lower() == "draw":
            return m_1x2.get("DRAW")
        if sel_u in ("2", "AWAY") or sel_u.lower() == away_u:
            return m_1x2.get("AWAY")

    elif market == CanonicalMarket.TOTALS.value or market == "TOTALS":
        totals = model_suite.get("totals", {})
        for line in [0.5, 1.5, 2.5, 3.5, 4.5]:
            line_key = f"OVER_UNDER_{line}"
            if str(line) in sel_u:
                if any(x in sel_u.lower() for x in ["over", "üst"]):
                    return totals.get(line_key, {}).get("OVER")
                if any(x in sel_u.lower() for x in ["under", "alt"]):
                    return totals.get(line_key, {}).get("UNDER")
        if any(x in sel_u.lower() for x in ["over", "üst"]):
            return totals.get("OVER_UNDER_2.5", {}).get("OVER")
        if any(x in sel_u.lower() for x in ["under", "alt"]):
            return totals.get("OVER_UNDER_2.5", {}).get("UNDER")

    elif market == CanonicalMarket.BTTS.value or market == "BTTS":
        btts = model_suite.get("btts", {})
        if any(x in sel_u.lower() for x in ["var", "yes", "btts yes"]):
            return btts.get("YES")
        if any(x in sel_u.lower() for x in ["yok", "no", "btts no"]):
            return btts.get("NO")

    elif market == CanonicalMarket.CORRECT_SCORE.value or market == "CORRECT_SCORE":
        for item in model_suite.get("top_correct_scores", []):
            if item.get("score") == sel_u:
                return item.get("probability")
        try:
            parts = sel_u.split("-")
            if len(parts) == 2:
                x, y = int(parts[0]), int(parts[1])
                import math
                lh = model_suite.get("expected_goals", {}).get("home", 1.42)
                la = model_suite.get("expected_goals", {}).get("away", 1.12)
                p = (math.pow(lh, x) * math.exp(-lh) / math.factorial(x)) * (math.pow(la, y) * math.exp(-la) / math.factorial(y))
                return round(p, 4)
        except Exception:
            return None

    elif market == CanonicalMarket.HT_FT.value or market == "HT_FT":
        ht_ft = model_suite.get("ht_ft", {})
        if sel_u in ht_ft:
            return ht_ft[sel_u].get("probability")

    return None


def run_task017_pipeline() -> dict[str, Any]:
    captured_at = datetime.now(UTC)
    ts_str = captured_at.strftime("%Y%m%d_%H%M%S")
    snapshot_id = f"odds_snapshot_{ts_str}"
    print(f"\n{'='*70}\nTASK-017: MODEL C LIVE ACTIVATION & HISTORICAL ODDS ARCHIVE\nSnapshot ID: {snapshot_id} | Time: {captured_at.isoformat()}\n{'='*70}")

    archive_manager = OddsArchiveManager(ODDS_HISTORY_DIR)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. LOAD HISTORICAL MATCH ARCHIVES FOR ELIGIBLE LEAGUES
    # ──────────────────────────────────────────────────────────────────────────
    print("\n--- 1. Checking League Eligibility & Loading History ---")
    league_histories: dict[str, list[dict[str, Any]]] = {}
    league_eligibility_report: dict[str, dict[str, Any]] = {}

    # Check known leagues
    for l_name, b_id in [("Premier League", 1), ("Trendyol Süper Lig", 11), ("UEFA Nations League", 64)]:
        try:
            matches = fetch_or_load_historical_matches(league_id=b_id, limit=300)
            league_histories[l_name] = matches
            status = ModelCStatus.AVAILABLE if len(matches) >= 30 else ModelCStatus.INSUFFICIENT_HISTORY
            league_eligibility_report[l_name] = {
                "bzzoiro_id": b_id,
                "historical_matches": len(matches),
                "min_required": 30,
                "status": status,
                "model_ready": status == ModelCStatus.AVAILABLE,
            }
            print(f"  [{status}] {l_name}: {len(matches)} historical matches loaded.")
        except Exception as e:
            league_eligibility_report[l_name] = {
                "bzzoiro_id": b_id,
                "historical_matches": 0,
                "min_required": 30,
                "status": ModelCStatus.INSUFFICIENT_HISTORY,
                "error": str(e),
            }

    # ──────────────────────────────────────────────────────────────────────────
    # 2. INGEST LIVE ODDS (PROPLINE & XIDDAA)
    # ──────────────────────────────────────────────────────────────────────────
    print("\n--- 2. Ingesting Real Bookmaker Odds ---")
    all_normalized_records: list[NormalizedOddsRecord] = []
    events_summary: list[dict[str, Any]] = []

    # A. PropLine (EPL + UNL)
    pl_headers = {"x-api-key": PROPLINE_KEY}
    with httpx.Client(timeout=20.0) as client:
        for sport_key, comp_name, country in [
            ("soccer_epl", "Premier League", "England"),
            ("soccer_uefa_nations_league", "UEFA Nations League", "Europe"),
        ]:
            try:
                r = client.get(f"https://api.prop-line.com/v1/sports/{sport_key}/events", headers=pl_headers)
                if r.status_code == 200:
                    for ev in r.json()[:5]:
                        ev_id = ev.get("id")
                        h_team = ev.get("home_team")
                        a_team = ev.get("away_team")
                        commence = ev.get("commence_time")
                        ev_recs = []
                        for m_key in ["h2h", "totals", "correct_score"]:
                            url = f"https://api.prop-line.com/v1/sports/{sport_key}/events/{ev_id}/odds"
                            r_odds = client.get(url, headers=pl_headers, params={"markets": m_key, "regions": "eu,us"})
                            if r_odds.status_code == 200:
                                d_odds = r_odds.json()
                                d_odds["id"] = ev_id
                                d_odds["home_team"] = h_team
                                d_odds["away_team"] = a_team
                                d_odds["commence_time"] = commence
                                res = normalize_propline_event(d_odds, sport_key, comp_name, country, captured_at)
                                ev_recs.extend(res.accepted)
                        if ev_recs:
                            all_normalized_records.extend(ev_recs)
                            events_summary.append({
                                "event_id": ev_recs[0].event_id,
                                "source_event_id": str(ev_id),
                                "provider": "propline",
                                "home_team": h_team,
                                "away_team": a_team,
                                "competition": comp_name,
                                "country": country,
                                "commence_time": commence,
                                "record_count": len(ev_recs),
                            })
                            print(f"  + PropLine: {h_team} vs {a_team} ({comp_name}) -> {len(ev_recs)} odds records")
            except Exception as e:
                print(f"  PropLine {sport_key} error: {e}")

    # B. Xiddaa (Playable pre-match events)
    xi_headers = {"X-API-Key": XIDDAA_KEY}
    with httpx.Client(timeout=20.0) as client:
        try:
            r = client.get("https://xiddaa.com/api/v1/events", headers=xi_headers, params={"classification": "prematch", "take": 20})
            if r.status_code == 200:
                playable = [e for e in r.json().get("data", []) if e.get("betting", {}).get("playableMarketCount", 0) > 0]
                for ev in playable[:8]:
                    ev_id = ev.get("id")
                    ev_name = ev.get("name")
                    comp_name = ev.get("competition", {}).get("name", "Unknown")
                    country = ev.get("country", {}).get("name", "International")
                    r_det = client.get(f"https://xiddaa.com/api/v1/events/{ev_id}", headers=xi_headers)
                    if r_det.status_code == 200:
                        res = normalize_xiddaa_event(r_det.json().get("data", {}), captured_at)
                        if res.accepted:
                            all_normalized_records.extend(res.accepted)
                            events_summary.append({
                                "event_id": res.accepted[0].event_id,
                                "source_event_id": str(ev_id),
                                "provider": "xiddaa",
                                "home_team": ev.get("homeTeam", {}).get("name", ev_name),
                                "away_team": ev.get("awayTeam", {}).get("name", ""),
                                "competition": comp_name,
                                "country": country,
                                "commence_time": ev.get("startDate"),
                                "record_count": len(res.accepted),
                            })
                            print(f"  + Xiddaa: {ev_name} ({comp_name}) -> {len(res.accepted)} odds records")
        except Exception as e:
            print(f"  Xiddaa error: {e}")

    print(f"\nTotal live odds records collected: {len(all_normalized_records)} across {len(events_summary)} matches.")

    # ──────────────────────────────────────────────────────────────────────────
    # 3. FIT MODEL C & RUN EVALUATION WITH LEAGUE STATUS GUARD
    # ──────────────────────────────────────────────────────────────────────────
    print("\n--- 3. Running Model C (Time-Decayed) vs Global Baseline ---")
    event_model_c_suites: dict[str, dict[str, Any]] = {}
    event_global_suites: dict[str, dict[str, Any]] = {}
    unsupported_leagues: set[str] = set()

    for ev_meta in events_summary:
        eid = ev_meta["event_id"]
        comp = ev_meta["competition"]
        h_team = ev_meta["home_team"]
        a_team = ev_meta["away_team"]
        commence = ev_meta["commence_time"]

        # Parse data cutoff strictly before kickoff (anti-leakage)
        if commence:
            try:
                data_cutoff = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                if data_cutoff.tzinfo is None:
                    data_cutoff = data_cutoff.replace(tzinfo=UTC)
            except Exception:
                data_cutoff = captured_at
        else:
            data_cutoff = captured_at

        # Check if competition has historical matches
        hist_matches = league_histories.get(comp)

        # 1. Global Baseline Suite (for comparison)
        global_engine = FootballMarketEngine(lambda_home=1.42, lambda_away=1.12)
        event_global_suites[eid] = {
            "model_status": "GLOBAL_BASELINE_FALLBACK",
            "suite": global_engine.get_full_market_suite(),
            "meta": ev_meta,
        }

        # 2. Model C Suite
        if hist_matches and len(hist_matches) >= 30:
            try:
                model_c = TimeDecayedPoissonModel(decay_half_life_days=180.0, shrinkage_weight=3.0)
                model_c.fit(hist_matches, data_cutoff=data_cutoff)
                pred_c = model_c.predict_match(home_team=h_team, away_team=a_team, prediction_timestamp=captured_at)

                lh_c = pred_c.expected_home_goals
                la_c = pred_c.expected_away_goals
                engine_c = FootballMarketEngine(lambda_home=lh_c, lambda_away=la_c)

                event_model_c_suites[eid] = {
                    "model_status": ModelCStatus.AVAILABLE,
                    "model_version": model_c.MODEL_VERSION,
                    "rating_version": model_c.RATING_VERSION,
                    "expected_goals": {"home": lh_c, "away": la_c},
                    "team_ratings": {
                        "home": pred_c.metadata.get("home_team_ratings"),
                        "away": pred_c.metadata.get("away_team_ratings"),
                    },
                    "suite": engine_c.get_full_market_suite(),
                    "meta": ev_meta,
                }
                print(f"  [MODEL_C_AVAILABLE] {h_team} vs {a_team} ({comp}) -> lH={lh_c:.3f}, lA={la_c:.3f}")
            except Exception as e:
                print(f"  [MODEL_C_ERROR] {h_team} vs {a_team} ({comp}): {e}")
                event_model_c_suites[eid] = {
                    "model_status": ModelCStatus.INSUFFICIENT_HISTORY,
                    "reason": f"Fitting error: {e}",
                    "meta": ev_meta,
                }
        else:
            unsupported_leagues.add(comp)
            event_model_c_suites[eid] = {
                "model_status": ModelCStatus.INSUFFICIENT_HISTORY,
                "reason": f"No historical dataset with >= 30 matches for league '{comp}'.",
                "meta": ev_meta,
            }
            print(f"  [INSUFFICIENT_HISTORY] {h_team} vs {a_team} ({comp}) -> Model C skipped.")

    # ──────────────────────────────────────────────────────────────────────────
    # 4. RE-EVALUATE 505 HIGH-ODDS CANDIDATES: GLOBAL vs MODEL C
    # ──────────────────────────────────────────────────────────────────────────
    print("\n--- 4. Computing Edges & Re-evaluating 505 Candidates ---")
    comparison_edges: list[dict[str, Any]] = []

    # Group records by (event_id, provider, bookmaker, market)
    grouped: dict[tuple[str, str, str, str], dict[str, NormalizedOddsRecord]] = {}
    for r in all_normalized_records:
        k = (r.event_id, r.provider, r.bookmaker, r.market)
        if k not in grouped:
            grouped[k] = {}
        grouped[k][r.selection] = r

    global_val_high_count = 0
    model_c_val_high_count = 0
    collapsed_fake_edges = 0

    for (ev_id, provider, bm, market), selections in grouped.items():
        g_obj = event_global_suites.get(ev_id)
        c_obj = event_model_c_suites.get(ev_id)
        if not g_obj or not c_obj:
            continue

        home_t = g_obj["meta"]["home_team"]
        away_t = g_obj["meta"]["away_team"]
        comp = g_obj["meta"]["competition"]

        # No-vig
        market_odds_dict = {sel: rec.odds_decimal for sel, rec in selections.items() if rec.odds_decimal > 1.0}
        no_vig_probs = {}
        try:
            if len(market_odds_dict) >= 2:
                no_vig_probs, _, _ = no_vig_multiplicative(market_odds_dict)
        except Exception:
            no_vig_probs = {}

        for sel, rec in selections.items():
            entry_odd = rec.odds_decimal
            implied_prob = round(1.0 / entry_odd, 4) if entry_odd > 0 else 0.0
            nv_prob = no_vig_probs.get(sel, implied_prob)

            # Global baseline probability
            p_global = map_selection_to_model(market, sel, home_t, away_t, g_obj["suite"])
            ev_global = round((p_global * entry_odd) - 1.0, 4) if p_global else None
            is_global_val_high = (entry_odd >= 5.0 and ev_global is not None and ev_global > 0)
            if is_global_val_high:
                global_val_high_count += 1

            # Model C probability
            c_status = c_obj["model_status"]
            if c_status == ModelCStatus.AVAILABLE:
                p_model_c = map_selection_to_model(market, sel, home_t, away_t, c_obj["suite"])
                ev_model_c = round((p_model_c * entry_odd) - 1.0, 4) if p_model_c else None
                is_c_val_high = (entry_odd >= 5.0 and ev_model_c is not None and ev_model_c > 0)
                if is_c_val_high:
                    model_c_val_high_count += 1

                # Detect collapsed fake edge
                if is_global_val_high and not is_c_val_high:
                    collapsed_fake_edges += 1

                edge_status = "CALCULATED"
            else:
                p_model_c = None
                ev_model_c = None
                is_c_val_high = False
                edge_status = "UNAVAILABLE_INSUFFICIENT_HISTORY"

            if entry_odd >= 5.0:
                comparison_edges.append({
                    "event_id": ev_id,
                    "fixture": f"{home_t} vs {away_t}",
                    "competition": comp,
                    "market": market,
                    "selection": sel,
                    "bookmaker": bm,
                    "bookmaker_odds": entry_odd,
                    "no_vig_prob": nv_prob,
                    "global_prob": p_global,
                    "global_ev": ev_global,
                    "global_val_high": is_global_val_high,
                    "model_c_status": c_status,
                    "model_c_prob": p_model_c,
                    "model_c_ev": ev_model_c,
                    "model_c_val_high": is_c_val_high,
                    "edge_status": edge_status,
                })

    print(f"\n  Global Baseline Value + High Odds Candidates: {global_val_high_count}")
    print(f"  Model C Value + High Odds Candidates:        {model_c_val_high_count}")
    print(f"  Collapsed Fake Edges (Global EV > 0 -> Model C EV <= 0): {collapsed_fake_edges}")

    # ──────────────────────────────────────────────────────────────────────────
    # 5. IMMUTABLE ODDS SNAPSHOT ARCHIVE
    # ──────────────────────────────────────────────────────────────────────────
    print("\n--- 5. Archiving Immutable Historical Odds Snapshot ---")
    hist_entries = archive_manager.create_snapshot_records(
        records=all_normalized_records,
        snapshot_id=snapshot_id,
        captured_at=captured_at,
    )

    archive_metadata = {
        "snapshot_id": snapshot_id,
        "captured_at": captured_at.isoformat(),
        "total_records": len(hist_entries),
        "total_events": len(events_summary),
        "model_c_active_leagues": [k for k, v in league_eligibility_report.items() if v.get("status") == ModelCStatus.AVAILABLE],
        "insufficient_leagues": list(unsupported_leagues),
    }

    archive_path = archive_manager.save_immutable_snapshot(
        snapshot_id=snapshot_id,
        entries=hist_entries,
        metadata=archive_metadata,
    )
    print(f"  Successfully archived immutable snapshot: {archive_path}")

    # Check for line movement against earlier snapshots
    archived_list = archive_manager.list_archived_snapshots()
    print(f"  Current archive contains {len(archived_list)} immutable snapshot files: {archived_list}")

    line_movements = []
    if len(archived_list) >= 2:
        older_id = archived_list[-2]
        older_data = archive_manager.load_snapshot(older_id)
        current_data = archive_manager.load_snapshot(snapshot_id)
        line_movements = archive_manager.calculate_line_movement(
            older_entries=older_data.get("records", []),
            newer_entries=current_data.get("records", []),
        )
        print(f"  Calculated {len(line_movements)} price movements between {older_id} and {snapshot_id}.")

    # ──────────────────────────────────────────────────────────────────────────
    # 6. ASSEMBLE COMPARISON REPORT JSON
    # ──────────────────────────────────────────────────────────────────────────
    comparison_summary = {
        "generated_at": captured_at.isoformat(),
        "snapshot_id": snapshot_id,
        "league_eligibility": league_eligibility_report,
        "re_evaluation_summary": {
            "total_high_odds_records": len([c for c in comparison_edges]),
            "global_value_high_odds_count": global_val_high_count,
            "model_c_value_high_odds_count": model_c_val_high_count,
            "collapsed_fake_edges_count": collapsed_fake_edges,
            "reduction_percentage": round((collapsed_fake_edges / max(1, global_val_high_count)) * 100, 2),
        },
        "archive_status": {
            "archive_dir": str(ODDS_HISTORY_DIR),
            "snapshots_archived_count": len(archived_list),
            "current_snapshot_records": len(hist_entries),
            "line_movements_detected": len(line_movements),
        },
        "sample_collapsed_edges": [c for c in comparison_edges if c["global_val_high"] and not c["model_c_val_high"]][:15],
        "sample_genuine_model_c_edges": [c for c in comparison_edges if c["model_c_val_high"]][:15],
    }

    out_comparison = BACKTEST_DIR / "TASK-017-model-comparison.json"
    with open(out_comparison, "w", encoding="utf-8") as f:
        json.dump(comparison_summary, f, indent=2)

    print(f"\nSaved TASK-017 Model Comparison to {out_comparison}")
    return comparison_summary


if __name__ == "__main__":
    run_task017_pipeline()
