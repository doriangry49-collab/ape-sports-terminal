"""Autonomous Live Stale-Line & Steam Monitoring Daemon.

Executes periodic scans against PropLine and Nesine CDN, detects steam moves,
logs new positive-EV arbitrage opportunities into the paper-trading ledger,
and refreshes the interactive web dashboard automatically.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from build_dashboard import build_html
from live_stale_line_adapter import fetch_and_scan_live_propline

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT_DIR / "output" / "live_monitor.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("LiveMonitor")


def run_single_scan_cycle(settle_espn: bool = True) -> dict[str, Any]:
    """Execute a single scan iteration, record signals, and update dashboard."""
    start_t = time.time()
    logger.info("Starting live scan cycle across target leagues and Nesine CDN...")

    result = fetch_and_scan_live_propline(settle_espn=settle_espn)
    elapsed = round(time.time() - start_t, 2)

    leagues = result.get("leagues_scanned", 0)
    fixtures = result.get("fixtures_with_pinnacle", 0)
    matched = result.get("nesine_matched_fixtures", 0)
    signals = result.get("positive_ev_signals_count", 0)
    steam_signals = result.get("steam_confirmed_signals_count", 0)

    logger.info(
        f"Scan completed in {elapsed}s | Leagues: {leagues} | Fixtures: {fixtures} | "
        f"Nesine Matched: {matched}/{fixtures} | +EV Signals: {signals} (Steam: {steam_signals})"
    )

    # Rebuild web dashboard
    build_html()
    logger.info("Interactive dashboard HTML refreshed successfully.")
    return result


def start_monitor_loop(interval_sec: int = 3600, max_cycles: int | None = None) -> None:
    """Run recurring scan loop with specified sleep interval."""
    logger.info(f"Starting Live Monitor Daemon (Interval: {interval_sec}s)...")
    cycle = 0
    while True:
        cycle += 1
        logger.info(f"--- Cycle #{cycle} at {datetime.now(UTC).isoformat()} ---")
        try:
            run_single_scan_cycle()
        except Exception as e:
            logger.error(f"Error during scan cycle #{cycle}: {e}", exc_info=True)

        if max_cycles and cycle >= max_cycles:
            logger.info(f"Reached max cycles ({max_cycles}). Exiting daemon.")
            break

        logger.info(f"Sleeping for {interval_sec} seconds until next cycle...")
        time.sleep(interval_sec)


def main():
    parser = argparse.ArgumentParser(description="Live Stale-Line & Steam Monitor Daemon")
    parser.add_argument("--once", action="store_true", help="Run a single scan cycle and exit")
    parser.add_argument("--interval", type=int, default=3600, help="Scan interval in seconds (default: 3600)")
    parser.add_argument("--max-cycles", type=int, default=None, help="Maximum number of cycles before exit")
    args = parser.parse_args()

    if args.once:
        run_single_scan_cycle()
    else:
        start_monitor_loop(interval_sec=args.interval, max_cycles=args.max_cycles)


if __name__ == "__main__":
    main()
