"""Batch Prediction Operations for Upcoming Süper Lig Fixtures (TASK-004)."""

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
from sports_engine.features.dataset import fetch_or_load_historical_matches
from sports_engine.models.poisson import PoissonGoalModel
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


def fetch_upcoming_events_and_odds() -> tuple[list[dict[str, Any]], str]:
    """Fetch all upcoming events and 1X2 odds from PropLine with local fallback."""
    settings = get_settings()

    if settings.propline_key:
        url = "https://api.prop-line.com/v1/sports/soccer_turkey_super_lig/odds"
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

    # Fallback to local raw artifact
    fallback_file = Path("artifacts/provider_validation/raw/propline/Bulk Odds (1X2 _ h2h _ totals)_20260929_154502.json")
    if fallback_file.exists():
        with open(fallback_file, "r", encoding="utf-8") as f:
            return json.load(f), "cached_validation_artifact"

    raise RuntimeError("Unable to fetch upcoming fixtures from PropLine or cached fallback.")


def parse_event_odds(event: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Extract bookmaker decimal 1X2 odds from a PropLine event object."""
    bookmakers: dict[str, dict[str, float]] = {}

    for bm in event.get("bookmakers", []):
        bm_key = bm.get("key", "unknown")
        for m in bm.get("markets", []):
            if m.get("key") == "h2h":
                odds_dict: dict[str, float] = {}
                for outcome in m.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    side = outcome.get("side")
                    price = outcome.get("price", 0)
                    dec = american_to_decimal(price)

                    if side == "home" or any(t in name for t in ["rize", "galata", "besik", "konya", "gazi", "eyup", "samsun", "alanya", "gencler"]):
                        odds_dict["home"] = dec
                    elif side == "away" or any(t in name for t in ["fener", "kasim", "kocael", "basak", "corum", "goztepe", "trabzon", "erzurum", "amed"]):
                        odds_dict["away"] = dec
                    elif side == "draw" or "draw" in name or "berabere" in name:
                        odds_dict["draw"] = dec

                # Positional fallback if side wasn't explicit
                if len(odds_dict) < 3 and len(m.get("outcomes", [])) == 3:
                    outs = m["outcomes"]
                    odds_dict = {
                        "home": american_to_decimal(outs[0]["price"]),
                        "draw": american_to_decimal(outs[2]["price"] if "draw" in outs[2].get("name", "").lower() else outs[1]["price"]),
                        "away": american_to_decimal(outs[1]["price"] if "draw" in outs[2].get("name", "").lower() else outs[2]["price"]),
                    }

                if len(odds_dict) >= 3:
                    bookmakers[bm_key] = odds_dict

    return bookmakers


def run_live_prediction_operations(
    sample_size: int = 300,
    data_cutoff_iso: str | None = None,
) -> dict[str, Any]:
    """Execute live pre-match prediction operations and persist immutable snapshot."""
    settings = get_settings()

    generated_at = datetime.now(UTC)
    ts_snapshot_id = generated_at.strftime("%Y%m%d_%H%M%S")

    if data_cutoff_iso:
        data_cutoff = datetime.fromisoformat(data_cutoff_iso.replace("Z", "+00:00"))
        if data_cutoff.tzinfo is None:
            data_cutoff = data_cutoff.replace(tzinfo=UTC)
    else:
        # Strict anti-leakage: cutoff is exactly run time
        data_cutoff = generated_at

    # 1. Ingest upcoming fixtures
    raw_events, source_desc = fetch_upcoming_events_and_odds()

    # 2. Ingest historical training matches strictly up to data_cutoff
    history_matches = fetch_or_load_historical_matches(
        league_id=11,
        limit=sample_size,
        data_cutoff=data_cutoff,
    )

    # 3. Fit baseline Poisson model
    model = PoissonGoalModel().fit(history_matches)

    predictions: list[dict[str, Any]] = []
    domain_preds: list[ModelPrediction] = []

    for ev in raw_events:
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
            canonical_league_id="tr_super_lig",
            season="2026_2027",
            home_team_id=norm_home,
            away_team_id=norm_away,
            event_time=kickoff_dt,
        )

        pred = model.predict_match(home_team=norm_home, away_team=norm_away)
        bookmakers = parse_event_odds(ev)

        # Primary reference bookmaker
        primary_bm = "pinnacle" if "pinnacle" in bookmakers else (list(bookmakers.keys())[0] if bookmakers else "none")
        ref_odds = bookmakers.get(primary_bm, {"home": 0.0, "draw": 0.0, "away": 0.0})

        # Calculate preliminary edge (model probability * odds - 1)
        edge_home = round(((pred.home_probability * ref_odds["home"]) - 1.0) * 100, 2) if ref_odds["home"] > 0 else 0.0
        edge_draw = round(((pred.draw_probability * ref_odds["draw"]) - 1.0) * 100, 2) if ref_odds["draw"] > 0 else 0.0
        edge_away = round(((pred.away_probability * ref_odds["away"]) - 1.0) * 100, 2) if ref_odds["away"] > 0 else 0.0

        prediction_id = f"{canonical_fixture_id}_{ts_snapshot_id}"

        # Standard prediction record matching all required fields
        match_record = {
            "prediction_id": prediction_id,
            "snapshot_id": ts_snapshot_id,
            "fixture": {
                "canonical_fixture_id": canonical_fixture_id,
                "league": "Süper Lig",
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
            "draw_probability": pred.draw_probability,
            "away_probability": pred.away_probability,
            "fair_home_odds": pred.fair_home_odds,
            "fair_draw_odds": pred.fair_draw_odds,
            "fair_away_odds": pred.fair_away_odds,
            "current_odds": {
                "primary_bookmaker": primary_bm,
                "home": ref_odds.get("home", 0.0),
                "draw": ref_odds.get("draw", 0.0),
                "away": ref_odds.get("away", 0.0),
                "all_bookmakers": bookmakers,
            },
            "model_preliminary_edge": {
                "edge_type": "model-based preliminary edge (unadjusted for bookmaker margin)",
                "home_edge_pct": edge_home,
                "draw_edge_pct": edge_draw,
                "away_edge_pct": edge_away,
            },
            "model_version": pred.model_version,
            "feature_set_version": pred.feature_set_version,
            "training_context": {
                "sample_size": len(history_matches),
                "model_name": model.MODEL_NAME,
                "league_avg_home_goals": pred.metadata.get("league_avg_home_goals"),
                "league_avg_away_goals": pred.metadata.get("league_avg_away_goals"),
            },
        }
        predictions.append(match_record)

        # Domain records for DuckDB Parquet
        for sel, prob, odds in [("HOME", pred.home_probability, pred.fair_home_odds), ("DRAW", pred.draw_probability, pred.fair_draw_odds), ("AWAY", pred.away_probability, pred.fair_away_odds)]:
            domain_preds.append(
                ModelPrediction(
                    prediction_id=f"{prediction_id}_{sel.lower()}",
                    fixture_id=canonical_fixture_id,
                    generated_at=generated_at,
                    data_cutoff=data_cutoff,
                    model_name=pred.model_name,
                    model_version=pred.model_version,
                    market_type="1X2",
                    selection=sel,
                    predicted_probability=prob,
                    fair_odds=odds,
                    metadata={
                        "snapshot_id": ts_snapshot_id,
                        "primary_bookmaker": primary_bm,
                        "market_odds": ref_odds.get(sel.lower(), 0.0),
                    },
                )
            )

    # 4. Storage & Immutable Snapshot Management
    gold_dir = settings.gold_dir / "predictions"
    snapshots_dir = gold_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    snapshot_payload = {
        "snapshot_id": ts_snapshot_id,
        "generated_at": generated_at.isoformat(),
        "data_cutoff": data_cutoff.isoformat(),
        "training_sample_matches": len(history_matches),
        "odds_source": source_desc,
        "model_name": model.MODEL_NAME,
        "model_version": model.MODEL_VERSION,
        "total_fixtures": len(predictions),
        "predictions": predictions,
    }

    # 4a. Write timestamped immutable snapshot files (Never Overwritten)
    snap_json_file = snapshots_dir / f"prediction_snapshot_{ts_snapshot_id}.json"
    with open(snap_json_file, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, ensure_ascii=False, indent=2)

    snap_parquet_file = snapshots_dir / f"prediction_snapshot_{ts_snapshot_id}.parquet"
    write_parquet(domain_preds, snap_parquet_file)

    # 4b. Write / update 'latest' pointers for immediate operational querying
    latest_json_file = gold_dir / "latest_predictions.json"
    with open(latest_json_file, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, ensure_ascii=False, indent=2)

    latest_parquet_file = gold_dir / "latest_predictions.parquet"
    write_parquet(domain_preds, latest_parquet_file)

    return {
        "snapshot_id": ts_snapshot_id,
        "generated_at": generated_at.isoformat(),
        "data_cutoff": data_cutoff.isoformat(),
        "training_sample_size": len(history_matches),
        "total_fixtures": len(predictions),
        "source": source_desc,
        "snapshot_json_path": str(snap_json_file),
        "snapshot_parquet_path": str(snap_parquet_file),
        "latest_json_path": str(latest_json_file),
        "latest_parquet_path": str(latest_parquet_file),
        "predictions": predictions,
    }


def print_cli_operations_table(result: dict[str, Any]) -> None:
    """Print readable terminal output conforming to TASK-004 specification."""
    preds = result["predictions"]

    print("\n" + "=" * 115)
    print(f" LIVE PREDICTION OPERATIONS — TURKISH SÜPER LİG ({len(preds)} FIXTURES)")
    print(f" SNAPSHOT ID:  {result['snapshot_id']}")
    print(f" GENERATED AT: {result['generated_at']}")
    print(f" DATA CUTOFF:  {result['data_cutoff']} (Strict Temporal Anti-Leakage)")
    print(f" TRAINING DATA: {result['training_sample_size']} finished matches (Bzzoiro League 11)")
    print(f" ODDS SOURCE:  {result['source']} (PropLine)")
    print("=" * 115)

    header = f"{'MATCH':<32} | {'MODEL PROBABILITY':<23} | {'FAIR ODDS':<18} | {'CURRENT ODDS (Pinnacle)':<24} | {'PRELIM EDGE'}"
    print(header)
    print("-" * 115)

    for p in preds:
        fix = p["fixture"]
        match_str = f"{fix['home_team']} vs {fix['away_team']}"
        prob_str = f"H:{p['home_probability']*100:>4.1f}% D:{p['draw_probability']*100:>4.1f}% A:{p['away_probability']*100:>4.1f}%"
        fair_str = f"H:{p['fair_home_odds']:>4.2f} D:{p['fair_draw_odds']:>4.2f} A:{p['fair_away_odds']:>4.2f}"
        cur = p["current_odds"]
        cur_str = f"H:{cur['home']:>4.2f} D:{cur['draw']:>4.2f} A:{cur['away']:>4.2f}"

        # Preliminary edge
        edges = p["model_preliminary_edge"]
        h_e = f"{edges['home_edge_pct']:+4.1f}%" if cur["home"] > 0 else "N/A"
        a_e = f"{edges['away_edge_pct']:+4.1f}%" if cur["away"] > 0 else "N/A"
        edge_summary = f"H:{h_e} A:{a_e}"

        print(f"{match_str:<32} | {prob_str:<23} | {fair_str:<18} | {cur_str:<24} | {edge_summary}")

    print("-" * 115)
    print(" NOTICE: Edge is 'model-based preliminary edge (unadjusted for bookmaker margin)'.")
    print("         Snapshots are immutable and retained for post-match scoring.")
    print(f" [IMMUTABLE SNAPSHOT PATHS]")
    print(f"  JSON Snapshot:    {result['snapshot_json_path']}")
    print(f"  Parquet Snapshot: {result['snapshot_parquet_path']}")
    print(f"  Latest Pointers:  {result['latest_json_path']}")
    print("=" * 115 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Prediction Operations for Turkish Süper Lig")
    parser.add_argument("--limit", type=int, default=300, help="Historical training sample size")
    parser.add_argument("--data-cutoff", default=None, help="Strict historical data cutoff ISO datetime")
    args = parser.parse_args()

    res = run_live_prediction_operations(sample_size=args.limit, data_cutoff_iso=args.data_cutoff)
    print_cli_operations_table(res)


if __name__ == "__main__":
    main()
