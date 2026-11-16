"""CLI runner for TASK-008 Phase 1B: Betting Universe & Market Coverage Analysis."""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sports_engine.collectors.betting_universe import BettingUniverseEngine


def main() -> None:
    print("=" * 75, flush=True)
    print("TASK-008 — PHASE 1B: BETTING UNIVERSE & MARKET COVERAGE ANALYSIS", flush=True)
    print("=" * 75, flush=True)

    engine = BettingUniverseEngine()
    active_fixtures, funnel = engine.build_active_fixture_registry()

    print("\n--- BETTING UNIVERSE FUNNEL (561 -> AKTİF KÜME) ---", flush=True)
    print(f"1. Global Catalog Competitions:            {funnel['catalog_competitions']}", flush=True)
    print(f"2. Competitions with Active Fixtures:      {funnel['competitions_with_active_fixtures']}", flush=True)
    print(f"3. Total Active Fixtures in Bulletin:       {funnel['total_active_fixtures']}", flush=True)
    print(f"4. Fixtures with Active Quoted Odds:       {funnel['fixtures_with_active_odds']}", flush=True)
    print(f"5. Fixtures with Turkey Legal Evidence:    {funnel['fixtures_with_turkey_legal_evidence']}", flush=True)
    print(f"6. Fixtures with Legal Status UNKNOWN:     {funnel['fixtures_unknown_legal_status']}", flush=True)

    print("\n--- GLOBAL MARKET TAXONOMY & COVERAGE (18 STANDARD MARKETS) ---", flush=True)
    print(f"Total Market Instance Evaluations:         {funnel['total_market_evaluations']}", flush=True)
    sb = funnel["status_breakdown"]
    print(f"  * OFFERED_AND_MODELLED:                  {sb['OFFERED_AND_MODELLED']}", flush=True)
    print(f"  * MODEL_ONLY (Derived by our Engine):    {sb['MODEL_ONLY']}", flush=True)
    print(f"  * OFFERED_BUT_UNMODELLED (Spreads/Cards):{sb['OFFERED_BUT_UNMODELLED']}", flush=True)
    print(f"  * UNKNOWN (Props/Corners):               {sb['UNKNOWN']}", flush=True)

    print("\n" + "=" * 75, flush=True)
    print("ACTIVE FIXTURE MARKET EVIDENCE DETAIL", flush=True)
    print("=" * 75, flush=True)

    for i, fix in enumerate(active_fixtures[:10], 1):
        print(f"\n[{i}] {fix.canonical_home_team} vs {fix.canonical_away_team}", flush=True)
        print(f"    Competition:   {fix.competition_name} ({fix.country}) [{fix.canonical_competition_id}]", flush=True)
        print(f"    Kickoff:       {fix.kickoff.isoformat()} | Providers: {', '.join(fix.provider_presence)}", flush=True)
        print(f"    Legal Status:  {fix.turkey_legal_status} (Fixture Evidence: {fix.fixture_evidence_present})", flush=True)
        print(f"    Bookmakers:    {fix.betting_presence.get('bookmaker_count', 0)} | Coverage Score: {fix.market_coverage_score:.1%}", flush=True)
        
        # Show sample markets
        offered_and_mod = [k for k, v in fix.market_presence.items() if v.status == "OFFERED_AND_MODELLED"]
        model_only = [k for k, v in fix.market_presence.items() if v.status == "MODEL_ONLY"]
        offered_unmod = [k for k, v in fix.market_presence.items() if v.status == "OFFERED_BUT_UNMODELLED"]
        
        print(f"    OFFERED & MODELLED:     {', '.join(offered_and_mod) if offered_and_mod else 'None'}", flush=True)
        print(f"    OFFERED BUT UNMODELLED: {', '.join(offered_unmod) if offered_unmod else 'None'}", flush=True)
        print(f"    MODEL ONLY:             {', '.join(model_only[:5])}...", flush=True)

    print("\n" + "=" * 75, flush=True)
    print("ARTIFACTS PERSISTED:", flush=True)
    print("  - Active Fixtures JSON: artifacts/registry/global_active_fixtures.json", flush=True)
    print("  - Active Gold Parquet:  data/gold/registry/global_active_fixtures.parquet", flush=True)
    print("=" * 75, flush=True)


if __name__ == "__main__":
    main()
