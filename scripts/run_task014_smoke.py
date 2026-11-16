"""TASK-014 — Real Data Smoke Test Runner.

Calls live PropLine and Xiddaa APIs and normalizes actual responses.
Shows canonical output: provider, bookmaker, market, selection, odds_raw, odds_decimal, captured_at.

NOTE: Manual diagnostic script. Not collected by pytest.
Run manually via: python scripts/run_task014_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sports_engine.adapters.propline_adapter import normalize_propline_event
from sports_engine.adapters.schema import CanonicalMarket
from sports_engine.adapters.xiddaa_adapter import normalize_xiddaa_event


def main() -> None:
    captured_at = datetime.now(UTC)
    propline_key = os.getenv("PROPLINE_KEY")
    xiddaa_key = os.getenv("XIDDAA_KEY")

    smoke_results: dict[str, Any] = {"propline": [], "xiddaa": [], "summary": {}}

    print("=" * 70)
    print("TASK-014 REAL DATA SMOKE TEST")
    print(f"Captured at: {captured_at.isoformat()}")
    print("=" * 70)

    # ── PROPLINE SMOKE TEST ───────────────────────────────────────────────────
    print("\n=== PROPLINE: Arsenal vs Leeds (EPL) — h2h + totals + correct_score ===")
    pl_headers = {"x-api-key": propline_key} if propline_key else {}
    event_id = "214632"
    sport_key = "soccer_epl"

    with httpx.Client(timeout=15.0) as client:
        for market_key in ["h2h", "totals", "correct_score"]:
            url = f"https://api.prop-line.com/v1/sports/{sport_key}/events/{event_id}/odds"
            try:
                r = client.get(url, headers=pl_headers, params={"markets": market_key, "regions": "eu,us"})
                if r.status_code != 200:
                    print(f"  [{market_key}] HTTP {r.status_code}")
                    continue

                event_data = r.json()
                event_data["id"] = event_id
                event_data["home_team"] = "Arsenal"
                event_data["away_team"] = "Leeds"
                event_data["commence_time"] = "2026-10-10T11:30:00Z"

                result = normalize_propline_event(
                    event_data, sport_key, "Premier League", "England", captured_at
                )

                market_records = [rec for rec in result.accepted if rec.source_market_id == market_key]
                print(f"\n  Market: {market_key.upper()} -> {len(market_records)} normalized records")
                for rec in market_records[:4]:
                    print(
                        f"    {rec.provider:<10} | {rec.bookmaker:<12} | {rec.market:<18} | "
                        f"{rec.selection:<20} | raw={rec.odds_raw:<8} | dec={rec.odds_decimal:.4f}"
                    )

                smoke_results["propline"].extend([
                    {
                        "provider": rec.provider,
                        "bookmaker": rec.bookmaker,
                        "market": rec.market,
                        "selection": rec.selection,
                        "odds_raw": rec.odds_raw,
                        "odds_decimal": rec.odds_decimal,
                        "captured_at": rec.captured_at.isoformat(),
                    }
                    for rec in market_records[:3]
                ])
            except Exception as e:
                print(f"  [{market_key}] PropLine request failed: {e}")

    # ── XIDDAA SMOKE TEST ────────────────────────────────────────────────────
    print("\n\n=== XIDDAA: Today's prematch event — Correct Score + HT/FT + 1H markets ===")
    xi_headers = {"X-API-Key": xiddaa_key} if xiddaa_key else {}

    with httpx.Client(timeout=25.0) as client:
        try:
            r = client.get(
                "https://xiddaa.com/api/v1/events",
                headers=xi_headers,
                params={"classification": "prematch", "take": 10},
            )
            events = r.json().get("data", []) if r.status_code == 200 else []
            playable = [e for e in events if e.get("betting", {}).get("playableMarketCount", 0) > 0]
            print(f"  Found {len(playable)} playable prematch events today")

            tested_events = 0
            for ev in playable[:3]:
                ev_id = ev.get("id")
                ev_name = ev.get("name")
                try:
                    r_det = client.get(f"https://xiddaa.com/api/v1/events/{ev_id}", headers=xi_headers)
                    if r_det.status_code != 200:
                        continue
                    ev_data = r_det.json().get("data", {})
                except Exception as e:
                    print(f"  Warning: Detail request for {ev_id} failed: {e}")
                    continue

                result = normalize_xiddaa_event(ev_data, captured_at)
                if not result.accepted:
                    continue

                tested_events += 1
                print(f"\n  Event: {ev_name} [{ev_id}]")
                print(f"  Accepted: {len(result.accepted)} | Rejected: {len(result.rejected)}")

                target_markets = {
                    CanonicalMarket.CORRECT_SCORE,
                    CanonicalMarket.H1_CORRECT_SCORE,
                    CanonicalMarket.HT_FT,
                    CanonicalMarket.HT_FT_SCORE,
                    CanonicalMarket.H1_1X2,
                    CanonicalMarket.H1_TOTALS,
                    CanonicalMarket.H1_BTTS,
                    CanonicalMarket.BTTS,
                }

                markets_seen = set()
                for rec in result.accepted:
                    key = (rec.market, rec.source_market_id)
                    if key not in markets_seen and (rec.market in target_markets or not markets_seen):
                        markets_seen.add(key)
                        print(
                            f"    {rec.provider:<8} | {rec.bookmaker:<8} | "
                            f"{rec.market:<22} | {rec.selection:<20} | "
                            f"raw={rec.odds_raw:<8} | dec={rec.odds_decimal:.3f}"
                        )
                        smoke_results["xiddaa"].append({
                            "provider": rec.provider,
                            "bookmaker": rec.bookmaker,
                            "market": rec.market,
                            "selection": rec.selection,
                            "odds_raw": rec.odds_raw,
                            "odds_decimal": rec.odds_decimal,
                            "captured_at": rec.captured_at.isoformat(),
                        })

                if tested_events >= 2:
                    break
        except Exception as e:
            print(f"  Warning during Xiddaa live smoke fetch: {e}")

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    print("\n\n=== SMOKE TEST SUMMARY ===")
    print(f"  PropLine records normalized: {len(smoke_results['propline'])}")
    print(f"  Xiddaa records normalized:   {len(smoke_results['xiddaa'])}")
    total = len(smoke_results["propline"]) + len(smoke_results["xiddaa"])
    print(f"  Total VERIFIED_REAL_ODDS:    {total}")

    smoke_results["summary"] = {
        "propline_count": len(smoke_results["propline"]),
        "xiddaa_count": len(smoke_results["xiddaa"]),
        "total": total,
        "captured_at": captured_at.isoformat(),
    }

    out_file = PROJECT_ROOT / "output" / "014_smoke_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(smoke_results, f, ensure_ascii=False, indent=2)

    print(f"\n  Smoke results saved to {out_file}")
    print("\nSMOKE TEST COMPLETE — Manual verification finished.")


if __name__ == "__main__":
    main()
