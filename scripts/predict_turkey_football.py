"""Turkey Football Full Market Intelligence Engine CLI (TASK-007)."""

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

from config.settings import get_settings
from sports_engine.collectors.turkey_football import (
    classify_fixture_competition,
    discover_turkey_football_universe,
)
from sports_engine.domain.schemas import ModelPrediction
from sports_engine.features.dataset import fetch_or_load_historical_matches
from sports_engine.models.football_markets import FootballMarketEngine
from sports_engine.models.poisson import PoissonGoalModel
from sports_engine.normalization.canonical import build_canonical_fixture_id, normalize_entity_name
from sports_engine.storage.parquet_io import write_parquet
from scripts.predict_batch import fetch_upcoming_events_and_odds, parse_event_odds


def run_turkey_football_full_market_operations(
    sample_size: int = 300,
    data_cutoff_iso: str | None = None,
) -> dict[str, Any]:
    """Execute full-market prediction operations for all Turkish football competitions."""
    settings = get_settings()

    generated_at = datetime.now(UTC)
    ts_snapshot_id = generated_at.strftime("%Y%m%d_%H%M%S")

    if data_cutoff_iso:
        data_cutoff = datetime.fromisoformat(data_cutoff_iso.replace("Z", "+00:00"))
        if data_cutoff.tzinfo is None:
            data_cutoff = data_cutoff.replace(tzinfo=UTC)
    else:
        # Strict temporal anti-leakage
        data_cutoff = generated_at

    # 1. Discover all Turkish football competitions
    competitions = discover_turkey_football_universe()

    # 2. Ingest historical finished matches strictly up to data_cutoff
    history_matches = fetch_or_load_historical_matches(
        league_id=11,
        limit=sample_size,
        data_cutoff=data_cutoff,
    )

    # 3. Fit unified baseline Poisson model
    poisson_model = PoissonGoalModel().fit(history_matches)

    # 4. Fetch upcoming Turkish football fixtures & multi-market odds from PropLine
    raw_events, source_desc = fetch_upcoming_events_and_odds()

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

        # Classify competition (Süper Lig vs 1. Lig / Other)
        comp_name = classify_fixture_competition(home_raw, away_raw)
        comp_id = "tr_1_lig" if "1. Lig" in comp_name else "tr_super_lig"

        canonical_fixture_id = build_canonical_fixture_id(
            canonical_league_id=comp_id,
            season="2026_2027",
            home_team_id=norm_home,
            away_team_id=norm_away,
            event_time=kickoff_dt,
        )

        # Basic Poisson goal expectancy
        base_pred = poisson_model.predict_match(home_team=norm_home, away_team=norm_away)
        lambda_h = base_pred.expected_home_goals
        lambda_a = base_pred.expected_away_goals

        # Instantiate Football Market Engine for full market derivation
        market_engine = FootballMarketEngine(lambda_home=lambda_h, lambda_away=lambda_a)
        full_markets = market_engine.get_full_market_suite()

        # Parse live bookmaker odds
        bookmakers = parse_event_odds(ev)
        primary_bm = "pinnacle" if "pinnacle" in bookmakers else (list(bookmakers.keys())[0] if bookmakers else "none")
        ref_odds = bookmakers.get(primary_bm, {"home": 0.0, "draw": 0.0, "away": 0.0})

        # Scan longshots
        longshots = market_engine.scan_longshots(min_odds=3.0)

        prediction_id = f"{canonical_fixture_id}_{ts_snapshot_id}"

        match_record = {
            "prediction_id": prediction_id,
            "snapshot_id": ts_snapshot_id,
            "sport": "football",
            "competition": {
                "competition_id": comp_id,
                "competition_name": comp_name,
                "is_super_lig": (comp_id == "tr_super_lig"),
                "is_non_super_lig": (comp_id != "tr_super_lig"),
            },
            "fixture": {
                "canonical_fixture_id": canonical_fixture_id,
                "home_team": home_raw,
                "away_team": away_raw,
                "canonical_home_team": norm_home,
                "canonical_away_team": norm_away,
                "propline_event_id": event_id,
                "kickoff": kickoff_dt.isoformat(),
            },
            "generated_at": generated_at.isoformat(),
            "data_cutoff": data_cutoff.isoformat(),
            "expected_goals": {"home": lambda_h, "away": lambda_a},
            "markets": {
                "1x2": {
                    "probabilities": full_markets["1x2"],
                    "fair_odds": {
                        "HOME": round(1.0 / full_markets["1x2"]["HOME"], 2),
                        "DRAW": round(1.0 / full_markets["1x2"]["DRAW"], 2),
                        "AWAY": round(1.0 / full_markets["1x2"]["AWAY"], 2),
                    },
                    "current_odds": ref_odds,
                    "primary_bookmaker": primary_bm,
                },
                "double_chance": full_markets["double_chance"],
                "draw_no_bet": full_markets["draw_no_bet"],
                "totals_2_5": full_markets["totals"]["OVER_UNDER_2.5"],
                "btts": full_markets["btts"],
                "first_half": full_markets["first_half"],
                "second_half": full_markets["second_half"],
                "top_correct_scores": full_markets["top_correct_scores"],
                "ht_ft": full_markets["ht_ft"],
            },
            "longshots": [
                {
                    "market": ls.market_type,
                    "selection": ls.selection,
                    "probability": ls.probability,
                    "fair_odds": ls.fair_odds,
                    "tier": ls.longshot_tier,
                    "status": "UNADJUSTED",
                }
                for ls in longshots[:8]
            ],
            "model_version": poisson_model.MODEL_VERSION,
            "feature_set_version": poisson_model.FEATURE_SET_VERSION,
        }
        predictions.append(match_record)

        # Store domain records into DuckDB Parquet for 1X2, Totals, BTTS
        domain_preds.append(
            ModelPrediction(
                prediction_id=f"{prediction_id}_1x2_home",
                fixture_id=canonical_fixture_id,
                generated_at=generated_at,
                data_cutoff=data_cutoff,
                model_name=poisson_model.MODEL_NAME,
                model_version=poisson_model.MODEL_VERSION,
                market_type="1X2",
                selection="HOME",
                predicted_probability=full_markets["1x2"]["HOME"],
                fair_odds=round(1.0 / full_markets["1x2"]["HOME"], 2),
                metadata={"competition": comp_name, "expected_goals": lambda_h},
            )
        )
        domain_preds.append(
            ModelPrediction(
                prediction_id=f"{prediction_id}_ou25_over",
                fixture_id=canonical_fixture_id,
                generated_at=generated_at,
                data_cutoff=data_cutoff,
                model_name=poisson_model.MODEL_NAME,
                model_version=poisson_model.MODEL_VERSION,
                market_type="OVER_UNDER_2.5",
                selection="OVER",
                predicted_probability=full_markets["totals"]["OVER_UNDER_2.5"]["OVER"],
                fair_odds=round(1.0 / full_markets["totals"]["OVER_UNDER_2.5"]["OVER"], 2),
                metadata={"competition": comp_name},
            )
        )
        domain_preds.append(
            ModelPrediction(
                prediction_id=f"{prediction_id}_btts_yes",
                fixture_id=canonical_fixture_id,
                generated_at=generated_at,
                data_cutoff=data_cutoff,
                model_name=poisson_model.MODEL_NAME,
                model_version=poisson_model.MODEL_VERSION,
                market_type="BTTS",
                selection="YES",
                predicted_probability=full_markets["btts"]["YES"],
                fair_odds=round(1.0 / full_markets["btts"]["YES"], 2),
                metadata={"competition": comp_name},
            )
        )

    # 5. Persist immutable snapshot files
    gold_dir = settings.gold_dir / "predictions"
    snapshots_dir = gold_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    snapshot_payload = {
        "snapshot_id": ts_snapshot_id,
        "engine": "turkey_football_full_market_engine",
        "generated_at": generated_at.isoformat(),
        "data_cutoff": data_cutoff.isoformat(),
        "total_competitions_discovered": len(competitions),
        "total_fixtures": len(predictions),
        "odds_source": source_desc,
        "predictions": predictions,
    }

    # Snapshot JSON & Parquet
    snap_json_file = snapshots_dir / f"turkey_football_snapshot_{ts_snapshot_id}.json"
    with open(snap_json_file, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, ensure_ascii=False, indent=2)

    snap_parquet_file = snapshots_dir / f"turkey_football_snapshot_{ts_snapshot_id}.parquet"
    write_parquet(domain_preds, snap_parquet_file)

    # Latest Pointers
    latest_json = gold_dir / "latest_turkey_football_predictions.json"
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, ensure_ascii=False, indent=2)

    latest_parquet = gold_dir / "latest_turkey_football_predictions.parquet"
    write_parquet(domain_preds, latest_parquet)

    return {
        "snapshot_id": ts_snapshot_id,
        "generated_at": generated_at.isoformat(),
        "data_cutoff": data_cutoff.isoformat(),
        "competitions": competitions,
        "total_competitions": len(competitions),
        "total_fixtures": len(predictions),
        "snapshot_json_path": str(snap_json_file),
        "snapshot_parquet_path": str(snap_parquet_file),
        "latest_json_path": str(latest_json),
        "latest_parquet_path": str(latest_parquet),
        "predictions": predictions,
    }


def print_turkey_football_cli_table(result: dict[str, Any]) -> None:
    """Print readable terminal output conforming to TASK-007 specification."""
    comps = result["competitions"]
    preds = result["predictions"]

    print("\n" + "=" * 125)
    print(f" TÜRKİYE FOOTBALL PREDICTION UNIVERSE & FULL MARKET ENGINE (TASK-007)")
    print(f" SNAPSHOT ID:  {result['snapshot_id']}")
    print(f" GENERATED AT: {result['generated_at']}")
    print(f" DATA CUTOFF:  {result['data_cutoff']} (Strict Temporal Anti-Leakage)")
    print("=" * 125)

    print("\n[TFF COMPETITIONS CATALOG & PROVIDER AVAILABILITY]")
    comp_header = f"{'COMPETITION':<32} | {'TYPE':<16} | {'ACTIVE':<7} | {'UPCOMING':<9} | {'MODEL STATUS':<22}"
    print(comp_header)
    print("-" * 125)
    for c in comps:
        active_str = "YES" if c["active"] else "NO"
        ev_str = f"{c.get('upcoming_event_count', 0)} evs"
        print(f"{c['competition_name']:<32} | {c['competition_type']:<16} | {active_str:<7} | {ev_str:<9} | {c['model_available']:<22}")
    print("-" * 125)

    # Separate predictions into Süper Lig vs Non-Süper Lig (1. Lig / Cup)
    super_lig_preds = [p for p in preds if p["competition"]["is_super_lig"]]
    non_super_preds = [p for p in preds if p["competition"]["is_non_super_lig"]]

    print(f"\n[MULTI-MARKET PREDICTIONS — SÜPER LİG ({len(super_lig_preds)} FIXTURES)]")
    m_header = f"{'MATCH':<32} | {'1X2 (H/D/A)':<18} | {'1H RES':<14} | {'O/U 2.5':<14} | {'BTTS':<12} | {'TOP CS (Odds)':<16} | {'LONGSHOT (Tier)'}"
    print(m_header)
    print("-" * 125)
    for p in super_lig_preds:
        fix = p["fixture"]
        match_str = f"{fix['home_team']} vs {fix['away_team']}"
        m1x2 = p["markets"]["1x2"]["probabilities"]
        p_1x2_str = f"{m1x2['HOME']*100:.0f}%/{m1x2['DRAW']*100:.0f}%/{m1x2['AWAY']*100:.0f}%"

        m_1h = p["markets"]["first_half"]["1X2"]
        p_1h_str = f"{m_1h['HOME']*100:.0f}%/{m_1h['DRAW']*100:.0f}%/{m_1h['AWAY']*100:.0f}%"

        ou = p["markets"]["totals_2_5"]
        ou_str = f"O:{ou['OVER']*100:.0f}%/U:{ou['UNDER']*100:.0f}%"

        btts = p["markets"]["btts"]
        btts_str = f"Y:{btts['YES']*100:.0f}%/N:{btts['NO']*100:.0f}%"

        top_cs = p["markets"]["top_correct_scores"][0]
        cs_str = f"{top_cs['score']} ({top_cs['fair_odds']})"

        top_ls = p["longshots"][0] if p["longshots"] else None
        ls_str = f"{top_ls['selection']} ({top_ls['fair_odds']}) [{top_ls['tier'].split()[0]}]" if top_ls else "N/A"

        print(f"{match_str:<32} | {p_1x2_str:<18} | {p_1h_str:<14} | {ou_str:<14} | {btts_str:<12} | {cs_str:<16} | {ls_str}")

    print("-" * 125)

    if non_super_preds:
        print(f"\n[MULTI-MARKET PREDICTIONS — SÜPER LİG DIŞI / 1. LİG & KUPA ({len(non_super_preds)} FIXTURES)]")
        print(m_header)
        print("-" * 125)
        for p in non_super_preds:
            fix = p["fixture"]
            match_str = f"{fix['home_team']} vs {fix['away_team']}"
            m1x2 = p["markets"]["1x2"]["probabilities"]
            p_1x2_str = f"{m1x2['HOME']*100:.0f}%/{m1x2['DRAW']*100:.0f}%/{m1x2['AWAY']*100:.0f}%"

            m_1h = p["markets"]["first_half"]["1X2"]
            p_1h_str = f"{m_1h['HOME']*100:.0f}%/{m_1h['DRAW']*100:.0f}%/{m_1h['AWAY']*100:.0f}%"

            ou = p["markets"]["totals_2_5"]
            ou_str = f"O:{ou['OVER']*100:.0f}%/U:{ou['UNDER']*100:.0f}%"

            btts = p["markets"]["btts"]
            btts_str = f"Y:{btts['YES']*100:.0f}%/N:{btts['NO']*100:.0f}%"

            top_cs = p["markets"]["top_correct_scores"][0]
            cs_str = f"{top_cs['score']} ({top_cs['fair_odds']})"

            top_ls = p["longshots"][0] if p["longshots"] else None
            ls_str = f"{top_ls['selection']} ({top_ls['fair_odds']}) [{top_ls['tier'].split()[0]}]" if top_ls else "N/A"

            print(f"{match_str:<32} | {p_1x2_str:<18} | {p_1h_str:<14} | {ou_str:<14} | {btts_str:<12} | {cs_str:<16} | {ls_str}")
        print("-" * 125)

    print("\n[IMMUTABLE SNAPSHOT ARTIFACTS]")
    print(f"  JSON Snapshot:    {result['snapshot_json_path']}")
    print(f"  Parquet Snapshot: {result['snapshot_parquet_path']}")
    print(f"  TFF Catalog:      artifacts/turkey_football/competitions.json")
    print("=" * 125 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Turkey Football Full Market Prediction Engine")
    parser.add_argument("--limit", type=int, default=300, help="Historical training sample size")
    parser.add_argument("--data-cutoff", default=None, help="Strict historical data cutoff ISO datetime")
    args = parser.parse_args()

    res = run_turkey_football_full_market_operations(
        sample_size=args.limit,
        data_cutoff_iso=args.data_cutoff,
    )
    print_turkey_football_cli_table(res)


if __name__ == "__main__":
    main()
