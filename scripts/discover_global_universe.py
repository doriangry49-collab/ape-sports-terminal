"""CLI script to run Global Football Universe Discovery (TASK-008 Phase 1A)."""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sports_engine.collectors.global_discovery import GlobalDiscoveryEngine


def main() -> None:
    print("=" * 70)
    print("TASK-008 — PHASE 1A: GLOBAL FOOTBALL DISCOVERY & REGISTRY")
    print("=" * 70)

    engine = GlobalDiscoveryEngine()
    competitions, fixtures, metrics = engine.build_registry()

    print("\n--- GLOBAL COVERAGE METRICS ---")
    print(f"Global competitions discovered: {metrics['global_competitions_discovered']}")
    print(f"Countries: {metrics['countries_count']}")
    print(f"Competition types: {metrics['competition_types_count']}")
    print()
    print(f"API-Football competitions: {metrics['api_football_competitions']}")
    print(f"Bzzoiro competitions: {metrics['bzzoiro_competitions']}")
    print(f"PropLine competitions: {metrics['propline_competitions']}")
    print(f"xiddaa competitions: {metrics['xiddaa_competitions']}")
    print()
    print(f"Cross-provider matches: {metrics['cross_provider_matches']}")
    print(f"Canonical competitions: {metrics['canonical_competitions']}")
    print(f"Canonical fixtures: {metrics['canonical_fixtures']}")
    print()
    print(f"DATA_AVAILABLE: {metrics['data_available']}")
    print(f"BETTING_MARKET_AVAILABLE: {metrics['betting_market_available']}")
    print(f"TURKEY_LEGAL_MARKET_VERIFIED: {metrics['turkey_legal_market_verified']}")
    print(f"UNKNOWN: {metrics['unknown']}")

    print("\n" + "=" * 70)
    print("COUNTRY & REGIONAL BREAKDOWN (REAL EXAMPLES)")
    print("=" * 70)

    def print_sample(label: str, filter_fn) -> None:
        matches = [c for c in competitions if filter_fn(c)]
        print(f"\n{label} ({len(matches)} discovered):")
        for m in matches[:5]:
            providers = []
            if m.providers.api_football:
                providers.append("API-Football")
            if m.providers.bzzoiro:
                providers.append("Bzzoiro")
            if m.providers.prop_line:
                providers.append("PropLine")
            if m.providers.xiddaa:
                providers.append("xiddaa")
            p_str = ", ".join(providers)
            legal_str = f"Legal: {m.betting.turkey_legal_status}"
            ready_str = f"Model: {m.model.model_readiness}"
            print(f"  * [{m.competition_id}] {m.canonical_name} ({m.competition_type}) | Providers: [{p_str}] | {legal_str} | {ready_str}")

    print_sample("England", lambda c: c.country == "England")
    print_sample("Spain", lambda c: c.country == "Spain")
    print_sample("Italy", lambda c: c.country == "Italy")
    print_sample("Germany", lambda c: c.country == "Germany")
    print_sample("France", lambda c: c.country == "France")
    print_sample("Netherlands", lambda c: c.country == "Netherlands")
    print_sample("Portugal", lambda c: c.country == "Portugal")
    print_sample("South America", lambda c: c.region == "South America" or c.country in ["Brazil", "Argentina"])
    print_sample("International", lambda c: c.region == "International" or c.country == "International")
    print_sample("Turkey", lambda c: c.country == "Turkey")

    print("\n" + "=" * 70)
    print("ARTIFACTS SAVED:")
    print("  - Registry JSON: artifacts/registry/competition_registry.json")
    print("  - Fixtures JSON: artifacts/registry/fixture_registry.json")
    print("  - Gold Parquet:  data/gold/registry/competition_registry.parquet")
    print("=" * 70)


if __name__ == "__main__":
    main()
