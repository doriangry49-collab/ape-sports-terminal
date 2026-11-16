"""TASK-018: Import TASK-017 SELF_CAPTURED snapshots into HistoricalOddsArchive."""
import sys
import json
import importlib.util
from pathlib import Path
from datetime import UTC, datetime

SPORTS_ROOT = Path("C:/Users/Thea-Aria/ .gemini/antigravity/scratch/ec2-file-explorer/sports-engine")

# Direct import — avoids triggering storage/__init__.py which needs config.settings
_spec = importlib.util.spec_from_file_location(
    "historical_odds_archive",
    str(SPORTS_ROOT / "src/sports_engine/storage/historical_odds_archive.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

HistoricalOddsArchive = _mod.HistoricalOddsArchive
HistoricalOddsRecord = _mod.HistoricalOddsRecord
ProvenanceType = _mod.ProvenanceType
SnapshotLabel = _mod.SnapshotLabel
make_snapshot_id = _mod.make_snapshot_id
calculate_movement = _mod.calculate_movement

TASK017_DIR = SPORTS_ROOT / "artifacts/odds/TASK-017-odds-history"
HIST_DIR = SPORTS_ROOT / "artifacts/odds/historical"
COVERAGE_PATH = SPORTS_ROOT / "artifacts/odds/TASK-018-coverage.json"

archive = HistoricalOddsArchive(HIST_DIR)
snap_files = sorted(TASK017_DIR.glob("odds_snapshot_*.json"))

print("=" * 60)
print(f"TASK-018: Importing {len(snap_files)} TASK-017 snapshots")
print("=" * 60)

retrieved_at = datetime.now(UTC).isoformat()
total_saved = 0
total_dup = 0
total_err = 0

for sf in snap_files:
    with open(sf, encoding="utf-8") as f:
        data = json.load(f)

    records = data.get("records", [])
    snap_id = data.get("snapshot_id", sf.stem)
    captured_at = data.get("captured_at", retrieved_at)
    batch = []

    for rec in records:
        try:
            eid = rec.get("event_id", "")
            prov = rec.get("provider", "propline")
            bm = rec.get("bookmaker", "")
            mkt = rec.get("market", "")
            sel = rec.get("selection", "")
            odds = float(rec.get("odds_decimal", 0))
            if not eid or not bm or not mkt or not sel or odds < 1.001:
                continue

            sid = make_snapshot_id(prov, eid, bm, mkt, sel, captured_at)

            batch.append(HistoricalOddsRecord(
                historical_snapshot_id=sid,
                provider=prov,
                source_type=ProvenanceType.SELF_CAPTURED,
                provider_event_id=rec.get("source_event_id", eid),
                event_id=eid,
                sport=rec.get("sport", "soccer"),
                competition=rec.get("competition", ""),
                competition_id=rec.get("competition_id"),
                event_start_time=rec.get("event_start_time", rec.get("commence_time", "")),
                home_team=rec.get("home_team", ""),
                away_team=rec.get("away_team", ""),
                bookmaker=bm,
                market=mkt,
                selection=sel,
                odds_decimal=odds,
                odds_raw=float(rec.get("odds_raw", odds)),
                odds_format_raw=rec.get("odds_format", "decimal"),
                actual_snapshot_timestamp=captured_at,
                retrieved_at=retrieved_at,
                source_timestamp=captured_at,
                snapshot_label=SnapshotLabel.REGULAR,
                provider_snapshot_id=snap_id,
                import_batch_id="task018_import",
            ))
        except Exception as e:
            total_err += 1

    counts = archive.import_batch(batch)
    total_saved += counts["saved"]
    total_dup += counts["duplicate"]
    total_err += counts["error"]
    print(f"  {sf.name}: saved={counts['saved']}, dup={counts['duplicate']}, err={counts['error']}")

print()
print(f"  TOTAL: saved={total_saved}, duplicate={total_dup}, error={total_err}")

# Coverage
cov = archive.coverage_report()
print()
print("=" * 60)
print("COVERAGE REPORT")
print("=" * 60)
for k, v in cov.items():
    print(f"  {k}: {v}")

# Proof-of-concept: query Arsenal vs Leeds 1X2 history
print()
print("=" * 60)
print("PROOF OF CONCEPT: Arsenal vs Leeds 1X2 Odds History")
print("=" * 60)

epl_event_id = "propline_soccer_epl_20261010_arsenal_vs_leeds"
h = archive.get_event_history(epl_event_id)
print(f"  Records for Arsenal vs Leeds: {len(h)}")

# Group by bookmaker for 1X2/Leeds
bm_groups = {}
for r in h:
    if r.market == "1X2" and r.selection == "Leeds":
        bm_groups.setdefault(r.bookmaker, []).append(r)

print(f"  Bookmakers with Leeds 1X2 history: {len(bm_groups)}")
for bm, recs in list(bm_groups.items())[:4]:
    snaps = [
        {
            "actual_snapshot_timestamp": r.actual_snapshot_timestamp,
            "odds_decimal": r.odds_decimal,
            "bookmaker": r.bookmaker,
            "market": r.market,
            "selection": r.selection,
            "event_id": r.event_id,
            "provider": r.provider,
            "source_type": r.source_type,
        }
        for r in recs
    ]
    hist = calculate_movement(snaps, "2026-10-10T11:30:00Z")
    if hist:
        print(f"  [{bm}] Leeds 1X2: n={hist.number_of_snapshots}, "
              f"first={hist.first_available_odds}, last_prematch={hist.last_prematch_odds}, "
              f"min={hist.minimum_odds}, max={hist.maximum_odds}, "
              f"abs_change={hist.absolute_change}, pct={hist.percentage_change}%")

# Save full coverage JSON
output = {
    "generated_at": retrieved_at,
    "import_summary": {
        "snapshot_files_processed": len(snap_files),
        "records_saved": total_saved,
        "duplicates_skipped": total_dup,
        "errors": total_err,
    },
    "provider_assessment": {
        "propline": {
            "key_present": True,
            "historical_odds_api": False,
            "historical_endpoint": "/v1/historical/ -> 404 Not Found",
            "scores_endpoint": True,
            "scores_delivers_historical_odds": False,
            "note": "PropLine only serves pre-match odds for upcoming events. No historical odds archive endpoint.",
        },
        "xiddaa": {
            "key_present": True,
            "historical_odds_api": False,
            "finished_events_total": 26497,
            "finished_odds_endpoint": False,
            "endpoint_tested": "/api/v1/events/{id}/odds -> 404 for finished events",
            "note": "Xiddaa archives 26,497 finished events but their odds endpoint returns 404 for finished events.",
        },
        "api_football": {
            "key_present": True,
            "plan": "Free",
            "daily_limit_requests": 100,
            "historical_odds_for_finished": False,
            "note": "Free plan. /odds returns 0 results for tested finished fixtures. Historical odds require paid plan.",
        },
        "the_odds_api": {
            "key_present": False,
            "historical_api_documented": True,
            "endpoints": [
                "/v4/historical/sports/{sport}/odds",
                "/v4/historical/sports/{sport}/events/{eventId}/odds",
            ],
            "coverage_from": "2020-01-01",
            "snapshot_interval_from_sept2022": "5 minutes",
            "free_tier_historical": False,
            "paid_required": True,
            "pricing": "From $30/month (20,000 credits). Historical: ~10 credits per region per market.",
            "action_required": "Subscribe and add THE_ODDS_API_KEY to .env",
        },
        "bzzoiro": {
            "key_present": True,
            "reachable": False,
            "note": "DNS resolution failed for api.bzzoiro.com",
        },
        "oddsportal": {
            "official_api": False,
            "web_scraping_only": True,
            "ssl_timeout": True,
            "note": "Web-only, no API. Scraping is TOS-restricted and SSL timed out in test.",
        },
    },
    "opening_closing_labels": {
        "confirmed_opening_odds_available": False,
        "confirmed_closing_odds_available": False,
        "labels_used": {
            "first_snapshot": "FIRST_AVAILABLE_SNAPSHOT",
            "last_before_kickoff": "LAST_PREMATCH_SNAPSHOT",
            "confirmed_closing": "CLOSING_ODDS (not yet applicable)",
        },
        "note": "No provider delivers labeled opening/closing odds. Synthetic opening/closing NEVER created.",
    },
    "coverage": cov,
    "ui_data_contract": {
        "query_interface": "OddsHistoryQueryRequest(event_id, market, selection, bookmaker, source_type)",
        "response_interface": "OddsHistoryResponse(event, market, selection, bookmakers, snapshots, by_bookmaker, movement_summary, provenance)",
        "module": "src/sports_engine/storage/historical_odds_archive.py",
        "ready_for_ui": True,
    },
    "historical_similarity_readiness": {
        "current_status": "INSUFFICIENT",
        "reason": "Only 4 SELF_CAPTURED snapshots from the same day. Need weeks of data or THE_ODDS_API backfill.",
        "minimum_for_similarity": ">=30 matches x >=3 distinct time-points",
    },
    "next_steps": [
        "1. Subscribe to The Odds API paid plan — add THE_ODDS_API_KEY to .env",
        "2. Run historical backfill for EPL/Supe-Lig from The Odds API (2022+ available)",
        "3. Run collect_snapshot.py daily for SELF_CAPTURED continuous archive",
        "4. After 2-4 weeks: activate Historical Similarity Engine",
    ],
}

with open(COVERAGE_PATH, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print()
print(f"Coverage report saved: {COVERAGE_PATH}")
