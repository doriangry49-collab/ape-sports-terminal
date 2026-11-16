"""NBA Live Prediction Operations CLI (TASK-006)."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure project root and src are on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

import httpx

from config.settings import get_settings
from sports_engine.domain.schemas import ModelPrediction
from sports_engine.features.nba_dataset import fetch_or_load_nba_historical_games
from sports_engine.models.nba_elo import NBAEloModel
from sports_engine.normalization.canonical import build_canonical_fixture_id, normalize_entity_name
from sports_engine.storage.parquet_io import write_parquet


def american_to_decimal(price: float | int) -> float:
    """Convert American moneyline odds to standard European decimal odds."""
    p = float(price)
    if p > 0:
        return round(1.0 + (p / 100.0), 3)
    elif p < 0:
        return round(1.0 + (100.0 / abs(p)), 3)
    return 1.0


def fetch_upcoming_nba_events_and_odds() -> tuple[list[dict[str, Any]], str]:
    """Fetch upcoming NBA events and 2-way moneyline odds from PropLine."""
    settings = get_settings()

    if settings.propline_key:
        url = "https://api.prop-line.com/v1/sports/basketball_nba/odds"
        try:
            resp = httpx.get(
                url,
                headers={"x-api-key": settings.propline_key},
                params={"markets": "h2h"},
                timeout=12.0,
            )
            if resp.status_code == 200:
                events = resp.json()
                if isinstance(events, list) and len(events) > 0:
                    return events, "live_propline_api"
        except Exception:
            pass

    # Fallback to events endpoint if odds fails
    url_events = "https://api.prop-line.com/v1/sports/basketball_nba/events"
    if settings.propline_key:
        try:
            resp = httpx.get(url_events, headers={"x-api-key": settings.propline_key}, timeout=10.0)
            if resp.status_code == 200:
                events = resp.json()
                if isinstance(events, list) and len(events) > 0:
                    return events, "live_propline_events_api"
        except Exception:
            pass

    raise RuntimeError("Unable to fetch upcoming NBA fixtures from PropLine.")


def parse_nba_odds(event: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Extract bookmaker decimal moneyline odds for an NBA match."""
    bookmakers: dict[str, dict[str, float]] = {}

    for bm in event.get("bookmakers", []):
        bm_key = bm.get("key", "unknown")
        for m in bm.get("markets", []):
            if m.get("key") == "h2h":
                odds_dict: dict[str, float] = {}
                for outcome in m.get("outcomes", []):
                    side = outcome.get("side")
                    price = outcome.get("price", 0)
                    dec = american_to_decimal(price)
                    if side == "home":
                        odds_dict["home"] = dec
                    elif side == "away":
                        odds_dict["away"] = dec

                # Fallback matching by position if side wasn't explicit
                if len(odds_dict) < 2 and len(m.get("outcomes", [])) >= 2:
                    outs = m["outcomes"]
                    odds_dict = {
                        "home": american_to_decimal(outs[0]["price"]),
                        "away": american_to_decimal(outs[1]["price"]),
                    }

                if len(odds_dict) >= 2:
                    bookmakers[bm_key] = odds_dict

    return bookmakers


def run_nba_predictions(
    sample_size: int = 600,
    data_cutoff_iso: str | None = None,
    limit_events: int = 15,
) -> dict[str, Any]:
    """Execute live NBA prediction operations and persist immutable snapshot."""
    settings = get_settings()

    generated_at = datetime.now(UTC)
    ts_snapshot_id = generated_at.strftime("%Y%m%d_%H%M%S")

    if data_cutoff_iso:
        data_cutoff = datetime.fromisoformat(data_cutoff_iso.replace("Z", "+00:00"))
        if data_cutoff.tzinfo is None:
            data_cutoff = data_cutoff.replace(tzinfo=UTC)
    else:
        # Strict anti-leakage: cutoff is exactly prediction run time
        data_cutoff = generated_at

    # 1. Ingest upcoming NBA events & odds
    raw_events, source_desc = fetch_upcoming_nba_events_and_odds()

    # 2. Ingest historical NBA finished games strictly up to data_cutoff
    history_games = fetch_or_load_nba_historical_games(
        limit=sample_size,
        data_cutoff=data_cutoff,
    )

    # 3. Fit NBA Elo Model
    model = NBAEloModel().fit(history_games)

    predictions: list[dict[str, Any]] = []
    domain_preds: list[ModelPrediction] = []

    for ev in raw_events[:limit_events]:
        home_raw = ev.get("home_team", "")
        away_raw = ev.get("away_team", "")
        commence_raw = ev.get("commence_time", "")
        event_id = str(ev.get("id", ""))

        if not home_raw or not away_raw or not commence_raw:
            continue

        kickoff_dt = datetime.fromisoformat(commence_raw.replace("Z", "+00:00"))
        if kickoff_dt.tzinfo is None:
            kickoff_dt = kickoff_dt.replace(tzinfo=UTC)

        norm_home = normalize_entity_name(home_raw)
        norm_away = normalize_entity_name(away_raw)

        canonical_fixture_id = build_canonical_fixture_id(
            canonical_league_id="basketball_nba",
            season="2026_2027",
            home_team_id=norm_home,
            away_team_id=norm_away,
            event_time=kickoff_dt,
        )

        pred = model.predict_game(home_team=norm_home, away_team=norm_away)
        bookmakers = parse_nba_odds(ev)

        # Primary reference bookmaker
        primary_bm = list(bookmakers.keys())[0] if bookmakers else "consensus_estimate"
        ref_odds = bookmakers.get(primary_bm, {"home": 0.0, "away": 0.0})

        # Calculate preliminary edge
        edge_home = round(((pred.home_probability * ref_odds["home"]) - 1.0) * 100, 2) if ref_odds.get("home", 0.0) > 0 else 0.0
        edge_away = round(((pred.away_probability * ref_odds["away"]) - 1.0) * 100, 2) if ref_odds.get("away", 0.0) > 0 else 0.0

        prediction_id = f"{canonical_fixture_id}_{ts_snapshot_id}"

        match_record = {
            "prediction_id": prediction_id,
            "snapshot_id": ts_snapshot_id,
            "sport": "basketball_nba",
            "fixture": {
                "canonical_fixture_id": canonical_fixture_id,
                "league": "NBA",
                "home_team": home_raw,
                "away_team": away_raw,
                "canonical_home_team": norm_home,
                "canonical_away_team": norm_away,
                "propline_event_id": event_id,
            },
            "kickoff": kickoff_dt.isoformat(),
            "generated_at": generated_at.isoformat(),
            "data_cutoff": data_cutoff.isoformat(),
            "home_probability": pred.home_probability,
            "away_probability": pred.away_probability,
            "fair_home_odds": pred.fair_home_odds,
            "fair_away_odds": pred.fair_away_odds,
            "current_odds": {
                "primary_bookmaker": primary_bm,
                "home": ref_odds.get("home", 0.0),
                "away": ref_odds.get("away", 0.0),
                "all_bookmakers": bookmakers,
            },
            "model_preliminary_edge": {
                "edge_type": "model-based preliminary edge (unadjusted for bookmaker margin)",
                "home_edge_pct": edge_home,
                "away_edge_pct": edge_away,
            },
            "ratings": {
                "home_rating": pred.home_rating,
                "away_rating": pred.away_rating,
                "hca_bonus": pred.metadata.get("home_court_advantage"),
            },
            "model_version": pred.model_version,
            "feature_set_version": pred.feature_set_version,
        }
        predictions.append(match_record)

        # Domain records for DuckDB Parquet
        for sel, prob, odds in [("HOME", pred.home_probability, pred.fair_home_odds), ("AWAY", pred.away_probability, pred.fair_away_odds)]:
            domain_preds.append(
                ModelPrediction(
                    prediction_id=f"{prediction_id}_{sel.lower()}",
                    fixture_id=canonical_fixture_id,
                    generated_at=generated_at,
                    data_cutoff=data_cutoff,
                    model_name=pred.model_name,
                    model_version=pred.model_version,
                    market_type="MONEYLINE",
                    selection=sel,
                    predicted_probability=prob,
                    fair_odds=odds,
                    metadata={"primary_bookmaker": primary_bm, "market_odds": ref_odds.get(sel.lower(), 0.0)},
                )
            )

    # 4. Save artifacts
    gold_dir = settings.gold_dir / "predictions"
    snapshots_dir = gold_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    snapshot_payload = {
        "snapshot_id": ts_snapshot_id,
        "sport": "basketball_nba",
        "generated_at": generated_at.isoformat(),
        "data_cutoff": data_cutoff.isoformat(),
        "training_sample_games": len(history_games),
        "odds_source": source_desc,
        "model_name": model.MODEL_NAME,
        "model_version": model.MODEL_VERSION,
        "total_fixtures": len(predictions),
        "predictions": predictions,
    }

    # 4a. Immutable timestamped snapshot
    snap_json_file = snapshots_dir / f"nba_snapshot_{ts_snapshot_id}.json"
    with open(snap_json_file, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, ensure_ascii=False, indent=2)

    snap_parquet_file = snapshots_dir / f"nba_snapshot_{ts_snapshot_id}.parquet"
    write_parquet(domain_preds, snap_parquet_file)

    # 4b. Latest pointer
    latest_json_file = gold_dir / "latest_nba_predictions.json"
    with open(latest_json_file, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, ensure_ascii=False, indent=2)

    latest_parquet_file = gold_dir / "latest_nba_predictions.parquet"
    write_parquet(domain_preds, latest_parquet_file)

    return {
        "snapshot_id": ts_snapshot_id,
        "generated_at": generated_at.isoformat(),
        "data_cutoff": data_cutoff.isoformat(),
        "training_sample_size": len(history_games),
        "total_fixtures": len(predictions),
        "source": source_desc,
        "snapshot_json_path": str(snap_json_file),
        "snapshot_parquet_path": str(snap_parquet_file),
        "latest_json_path": str(latest_json_file),
        "latest_parquet_path": str(latest_parquet_file),
        "predictions": predictions,
    }


def print_nba_cli_table(result: dict[str, Any]) -> None:
    """Print readable terminal output conforming to TASK-006 specification."""
    preds = result["predictions"]

    print("\n" + "=" * 110)
    print(f" NBA LIVE PREDICTION OPERATIONS (TASK-006)")
    print(f" SPORT:          BASKETBALL (NBA)")
    print(f" MODEL:          nba_elo_baseline (v0.1.0) with Home Court Advantage (+65 Elo)")
    print(f" TRAINING DATA:  {result['training_sample_size']} finished games (ESPN Public API 2023-2025)")
    print(f" GENERATED AT:   {result['generated_at']}")
    print(f" DATA CUTOFF:    {result['data_cutoff']} (Strict Temporal Anti-Leakage)")
    print(f" FIXTURES COUNT: {len(preds)} upcoming NBA matchups")
    print("=" * 110)

    header = f"{'MATCH':<38} | {'WIN PROBABILITIES':<20} | {'FAIR ODDS':<16} | {'CURRENT ODDS':<20} | {'PRELIM EDGE'}"
    print(header)
    print("-" * 110)

    for p in preds:
        fix = p["fixture"]
        match_str = f"{fix['home_team']} vs {fix['away_team']}"
        prob_str = f"H:{p['home_probability']*100:>4.1f}%  A:{p['away_probability']*100:>4.1f}%"
        fair_str = f"H:{p['fair_home_odds']:>4.2f}  A:{p['fair_away_odds']:>4.2f}"
        cur = p["current_odds"]
        bm = cur["primary_bookmaker"]
        if cur["home"] > 0:
            cur_str = f"[{bm[:6]}] H:{cur['home']:>4.2f} A:{cur['away']:>4.2f}"
            edges = p["model_preliminary_edge"]
            edge_summary = f"H:{edges['home_edge_pct']:+4.1f}% A:{edges['away_edge_pct']:+4.1f}%"
        else:
            cur_str = "Pre-market pending"
            edge_summary = "N/A"

        print(f"{match_str:<38} | {prob_str:<20} | {fair_str:<16} | {cur_str:<20} | {edge_summary}")

    print("-" * 110)
    print(" NOTICE: 2-way moneyline win probabilities derived from dynamic Elo ratings.")
    print("         Snapshots are immutable and retained for post-match scoring.")
    print(f" [IMMUTABLE SNAPSHOT PATHS]")
    print(f"  JSON Snapshot:    {result['snapshot_json_path']}")
    print(f"  Parquet Snapshot: {result['snapshot_parquet_path']}")
    print(f"  Latest Pointers:  {result['latest_json_path']}")
    print("=" * 110 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="NBA Live Prediction Operations")
    parser.add_argument("--limit", type=int, default=600, help="Historical training sample size")
    parser.add_argument("--events-limit", type=int, default=15, help="Number of upcoming events to predict")
    parser.add_argument("--data-cutoff", default=None, help="Strict historical data cutoff ISO datetime")
    args = parser.parse_args()

    res = run_nba_predictions(
        sample_size=args.limit,
        data_cutoff_iso=args.data_cutoff,
        limit_events=args.events_limit,
    )
    print_nba_cli_table(res)


if __name__ == "__main__":
    main()
