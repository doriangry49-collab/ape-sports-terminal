"""Data quality audit script for TASK-008 Phase 1B.1."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

raw_root = Path("artifacts/provider_validation/raw")

def run_audit():
    print("=== DATA QUALITY AUDIT ===")
    
    # 1. PropLine Bulk Odds Inspection
    pl_bulk = raw_root / "propline" / "Bulk Odds (1X2 _ h2h _ totals)_20260929_154502.json"
    if pl_bulk.exists():
        data = json.loads(pl_bulk.read_text(encoding="utf-8"))
        print(f"PropLine Bulk Odds Events Count: {len(data)}")
        for idx, ev in enumerate(data[:3]):
            fixture = f"{ev.get('home_team')} vs {ev.get('away_team')}"
            bks = ev.get("bookmakers", [])
            print(f"\nFixture: {fixture} | Sport Key: {ev.get('sport_key')}")
            print(f"Bookmaker count: {len(bks)}")
            for b in bks:
                b_name = b.get("title") or b.get("key")
                b_update = b.get("last_update")
                markets = [m.get("key") for m in b.get("markets", [])]
                # Check outcome timestamps
                sample_ts = []
                for m in b.get("markets", []):
                    for o in m.get("outcomes", []):
                        if o.get("book_updated_at"):
                            sample_ts.append(o.get("book_updated_at"))
                print(f"  - Bookmaker: {b_name} | last_update: {b_update} | Markets: {set(markets)} | Timestamps count: {len(sample_ts)}")

    # 2. Cross-provider pair breakdown
    from sports_engine.collectors.global_discovery import GlobalDiscoveryEngine
    engine = GlobalDiscoveryEngine()
    comps, fixtures, metrics = engine.build_registry()
    
    api_comps = [c for c in comps if c.providers.api_football]
    bz_comps = [c for c in comps if c.providers.bzzoiro]
    pl_comps = [c for c in comps if c.providers.prop_line]
    xi_comps = [c for c in comps if c.providers.xiddaa]
    
    def pair_stat(p1_name, p1_list, p2_name, p2_list, attr1, attr2):
        # Candidates is the size of the smaller pool or cross
        p1_ids = {c.competition_id for c in p1_list}
        p2_ids = {c.competition_id for c in p2_list}
        matched = p1_ids.intersection(p2_ids)
        rate = len(matched) / min(len(p1_ids), len(p2_ids)) if min(len(p1_ids), len(p2_ids)) > 0 else 0
        print(f"  * {p1_name} ({len(p1_ids)}) <-> {p2_name} ({len(p2_ids)}): Matched = {len(matched)}, Match Rate = {rate:.1%}")

    print("\n--- CROSS-PROVIDER PAIR RECONCILIATION ---")
    pair_stat("API-Football", api_comps, "Bzzoiro", bz_comps, "api_football", "bzzoiro")
    pair_stat("API-Football", api_comps, "PropLine", pl_comps, "api_football", "prop_line")
    pair_stat("API-Football", api_comps, "xiddaa", xi_comps, "api_football", "xiddaa")
    pair_stat("Bzzoiro", bz_comps, "PropLine", pl_comps, "bzzoiro", "prop_line")
    pair_stat("Bzzoiro", bz_comps, "xiddaa", xi_comps, "bzzoiro", "xiddaa")
    pair_stat("PropLine", pl_comps, "xiddaa", xi_comps, "prop_line", "xiddaa")

    # 3. Canonical Odds Contract & Timestamp Layers
    from sports_engine.collectors.betting_universe import BettingUniverseEngine
    from sports_engine.domain.odds_contract import validate_phase_compatibility
    bu_engine = BettingUniverseEngine()
    records = bu_engine.extract_canonical_odds_records()
    print(f"\n--- CANONICAL ODDS CONTRACT (Extracted {len(records)} records) ---")
    for r in records[:3]:
        print(f"  * [{r.fixture_id}] {r.bookmaker} | Market: {r.market} ({r.selection}) @ {r.price}")
        print(f"    - event_last_update:    {r.event_last_update}")
        print(f"    - market_last_update:   {r.market_last_update}")
        print(f"    - outcome_last_update:  {r.outcome_last_update}")
        print(f"    - snapshot_collected_at:{r.snapshot_collected_at.isoformat()}")
        print(f"    - match_phase:          {r.match_phase} | Source: {r.source}")

    # 4. Cross-Provider Match Evidence
    evidences = bu_engine.get_cross_provider_match_evidence()
    print(f"\n--- CROSS-PROVIDER FIXTURE MATCH EVIDENCE ({len(evidences)} verified matches) ---")
    for ev in evidences:
        print(f"  * {ev.provider_A} <-> {ev.provider_B}: {ev.canonical_fixture_id} (Confidence: {ev.confidence:.2f})")
        print(f"    - Method:      {ev.match_method}")
        print(f"    - Team Match:  {ev.team_match}")
        print(f"    - Date Match:  {ev.date_match}")
        print(f"    - Comp Match:  {ev.competition_match}")

    # 5. PREMATCH / LIVE Guard Verification
    print("\n--- PREMATCH / LIVE GUARD VERIFICATION ---")
    print(f"  * PREMATCH <-> PREMATCH: {validate_phase_compatibility('PREMATCH', 'PREMATCH')}")
    print(f"  * LIVE <-> LIVE:         {validate_phase_compatibility('LIVE', 'LIVE')}")
    try:
        validate_phase_compatibility("PREMATCH", "LIVE")
    except ValueError as e:
        print(f"  * PREMATCH <-> LIVE:     BLOCKED (Expected: {e})")

if __name__ == "__main__":
    run_audit()
