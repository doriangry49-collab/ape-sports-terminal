"""Automated Autonomous Live In-Play Match Monitor Daemon (v2.0 Adaptive).

Runs periodic scanning passes targeting in-play matches:
- Scans ESPN live scoreboard for soccer fixtures in 15-85 minute windows
- Evaluates live goal timing windows and player threat bursts
- Evaluates LiveMomentumEngine (velocity, symmetry, rolling 15m window)
- Routes qualifying signals through SyndicateCommittee (RiskActuaryAgent, etc.)
- Records paper bets to LiveInPlayLedger (SPEC-0015 compliant >= 50 TL)
- Dispatches Telegram alerts when real live book odds are present
- Adaptive Polling Frequency:
    * IDLE_SLEEP (default 600s / 10m): When 0 active in-play matches exist (prevents rate limits)
    * ACTIVE_SLEEP (default 180s / 3m): When 1+ matches are active in play
    * HIGH_INTENSITY_SLEEP (default 120s / 2m): When 1+ matches are in late crunch time (60-85 min)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any

from in_play_sniper_engine import InPlaySniperEngine
from syndicate.committee import SyndicateCommittee

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("LiveSniperDaemon")

# Adaptive Polling Constants
IDLE_SLEEP_SECONDS = 600           # 10 minutes when no matches are active
ACTIVE_SLEEP_SECONDS = 180         # 3 minutes when matches are in-play
CRUNCH_SLEEP_SECONDS = 120         # 2 minutes when matches are in 60-85m crunch window


def calculate_adaptive_sleep(live_matches: list[dict[str, Any]]) -> int:
    """Determine optimal next poll delay based on active match telemetry."""
    if not live_matches:
        return IDLE_SLEEP_SECONDS

    # Check if any active match is in the 60-85' ambush/crunch window
    in_crunch = any(60 <= m.get("elapsed_min", 0) <= 85 for m in live_matches)
    if in_crunch:
        return CRUNCH_SLEEP_SECONDS

    return ACTIVE_SLEEP_SECONDS


def run_single_pass(
    sniper: InPlaySniperEngine | None = None,
    committee: SyndicateCommittee | None = None,
    dispatch_telegram: bool = True,
) -> dict[str, Any]:
    """Execute a single autonomous live scan pass."""
    if sniper is None:
        sniper = InPlaySniperEngine()
    if committee is None:
        committee = SyndicateCommittee()

    now_utc = datetime.now(UTC).isoformat()
    logger.info(f"=== Starting Live In-Play Scan Pass at {now_utc} ===")

    bridge_stats = sniper.refresh_nesine_bridge()
    live_matches = sniper.fetch_live_in_play_matches(min_minute=10, max_minute=85)
    real_odds_count = sum(1 for m in live_matches if m.get("has_real_live_odds"))
    nesine_linked_count = sum(1 for m in live_matches if m.get("nesine_pre_match") or m.get("odds_source") == "nesine_live")
    logger.info(
        f"Active in-play soccer matches found: {len(live_matches)} "
        f"(RealLiveOdds={real_odds_count}, NesineLinked={nesine_linked_count}, "
        f"NesineBridgeCache={bridge_stats.get('pre_cached_count', 0)})"
    )

    # 1. Scan Goal Anomalies (GASI Altın Pusu)
    goal_opps = sniper.scan_in_play_goal_anomalies(
        committee=committee,
        dispatch_telegram=dispatch_telegram,
        min_minute=15,
        max_minute=85,
    )
    logger.info(f"Qualified Goal Anomaly Ambush opportunities: {len(goal_opps)}")

    # 2. Scan Corner Sniper Panic Mispricings
    corner_opps = sniper.scan_in_play_opportunities(
        committee=committee,
        dispatch_telegram=dispatch_telegram,
    )
    logger.info(f"Qualified Corner Sniper opportunities: {len(corner_opps)}")

    # 3. Auto-settle any completed PENDING rows from ESPN Summary API
    settlement_res = sniper.ledger.settle_pending_from_espn() if sniper.ledger else {}
    ledger_summary = sniper.ledger.get_summary() if sniper.ledger else {}
    next_sleep = calculate_adaptive_sleep(live_matches)

    return {
        "timestamp_utc": now_utc,
        "matches_count": len(live_matches),
        "real_odds_count": real_odds_count,
        "nesine_linked_count": nesine_linked_count,
        "nesine_bridge_cache_count": bridge_stats.get("pre_cached_count", 0),
        "live_matches_sample": [
            {
                "event_id": m.get("event_id"),
                "match": f"{m.get('home')} vs {m.get('away')}",
                "clock": m.get("clock_display"),
                "score": f"{m.get('hg')}-{m.get('ag')}",
                "league": m.get("league_code"),
                "live_total_line": m.get("live_total_line"),
                "live_total_over_odds": m.get("live_total_over_odds"),
                "live_1x2": m.get("live_1x2"),
                "odds_source": m.get("odds_source"),
                "nesine_code": m.get("nesine_code"),
            }
            for m in live_matches
        ],
        "goal_opportunities": len(goal_opps),
        "corner_opportunities": len(corner_opps),
        "settlement_cycle": settlement_res,
        "ledger_summary": ledger_summary,
        "next_sleep_seconds": next_sleep,
    }


def run_daemon_loop(max_cycles: int | None = None) -> None:
    """Run persistent background loop with adaptive polling intervals."""
    sniper = InPlaySniperEngine()
    committee = SyndicateCommittee()
    cycle = 0

    logger.info("Adaptive In-Play Sniper Daemon initialized.")

    while True:
        cycle += 1
        sleep_dur = IDLE_SLEEP_SECONDS
        try:
            res = run_single_pass(sniper=sniper, committee=committee, dispatch_telegram=True)
            sleep_dur = res.get("next_sleep_seconds", ACTIVE_SLEEP_SECONDS)
            logger.info(
                f"Cycle #{cycle} completed: {res['matches_count']} matches, "
                f"{res['goal_opportunities']} goal opps. Next poll in {sleep_dur}s"
            )
        except Exception as e:
            logger.error(f"Error in cycle #{cycle}: {e}", exc_info=True)

        if max_cycles is not None and cycle >= max_cycles:
            logger.info(f"Reached max cycles ({max_cycles}). Daemon stopping.")
            break

        time.sleep(sleep_dur)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live In-Play Sniper Daemon & Night Monitor")
    parser.add_argument("--once", action="store_true", help="Run a single scan pass and exit.")
    parser.add_argument("--no-telegram", action="store_true", help="Suppress Telegram dispatch during scan.")
    args = parser.parse_args(argv)

    if args.once:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        res = run_single_pass(dispatch_telegram=not args.no_telegram)
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0

    run_daemon_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
