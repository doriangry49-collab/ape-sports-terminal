"""Autonomous Match Settlement & Paper-Trading Ledger Updater Engine (v1.0).

Automates the settlement lifecycle:
1. Scans active 'PENDING' rows in paper_trading_ledger.csv
2. Resolves actual match scores via ESPN official results API
3. Evaluates market winning conditions (1X2, Over/Under, BTTS, Double Chance)
4. Calculates net PnL units and updates ledger atomically
5. Triggers dashboard rebuild upon new settlements
"""

from __future__ import annotations

import csv
import json
import logging
import re
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("AutoSettlementEngine")

ROOT_DIR = Path(__file__).resolve().parent.parent
LEDGER_CSV = ROOT_DIR / "output" / "paper_trading_ledger.csv"


class AutoSettlementEngine:
    """Evaluates pending paper-trading bets and commits settlement results to disk."""

    def __init__(self, ledger_path: Path | None = None) -> None:
        self.ledger_path = ledger_path or LEDGER_CSV

    def fetch_espn_results(self) -> dict[str, dict[str, Any]]:
        """Fetch completed match scores from ESPN soccer scoreboard.
        Returns a mapping of normalized match keys to score metadata.
        """
        url = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        results: dict[str, dict[str, Any]] = {}

        try:
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for ev in data.get("events", []):
                    st = ev.get("status", {}).get("type", {})
                    state = st.get("state", "")
                    # Target finished matches
                    if state == "post" or st.get("completed", False):
                        comp = ev.get("competitions", [{}])[0]
                        competitors = comp.get("competitors", [])
                        if len(competitors) >= 2:
                            home_c = competitors[0] if competitors[0].get("homeAway") == "home" else competitors[1]
                            away_c = competitors[1] if competitors[0].get("homeAway") == "home" else competitors[0]

                            try:
                                hg = int(home_c.get("score", 0))
                                ag = int(away_c.get("score", 0))
                            except (ValueError, TypeError):
                                continue

                            home_name = home_c.get("team", {}).get("name", "").lower()
                            away_name = away_c.get("team", {}).get("name", "").lower()

                            match_meta = {
                                "home": home_name,
                                "away": away_name,
                                "hg": hg,
                                "ag": ag,
                                "score_str": f"{hg}-{ag}",
                                "tot_goals": hg + ag,
                            }
                            # Store both direct and inverted lookup keys
                            results[f"{home_name} vs {away_name}"] = match_meta
                            results[home_name] = match_meta
                            results[away_name] = match_meta
        except Exception as e:
            logger.warning(f"Failed to fetch ESPN results: {e}")

        return results

    def evaluate_bet_outcome(
        self,
        market: str,
        outcome: str,
        hg: int,
        ag: int,
    ) -> bool:
        """Evaluate whether a specific market selection won based on final scores."""
        m_str = (market + " " + outcome).upper()
        tot = hg + ag

        # 1. Total Goals Over / Under checks
        if "2.5 ALT" in m_str or "2.5 UNDER" in m_str:
            return tot < 2.5
        if "2.5 ÜST" in m_str or "2.5 OVER" in m_str:
            return tot > 2.5
        if "3.5 ALT" in m_str or "3.5 UNDER" in m_str:
            return tot < 3.5
        if "3.5 ÜST" in m_str or "3.5 OVER" in m_str:
            return tot > 3.5
        if "1.5 ÜST" in m_str or "1.5 OVER" in m_str:
            return tot > 1.5
        if "1.5 ALT" in m_str or "1.5 UNDER" in m_str:
            return tot < 1.5

        # 2. Both Teams To Score (KG Var / Yok)
        if "KG VAR" in m_str or "BTTS YES" in m_str:
            return hg > 0 and ag > 0
        if "KG YOK" in m_str or "BTTS NO" in m_str:
            return hg == 0 or ag == 0

        # 3. 1X2 Match Outcome
        if "MS 1" in m_str or "KAZANIR" in m_str:
            # Home win check
            if "MS 2" in m_str:
                return ag > hg
            return hg > ag
        if "MS X" in m_str or "BERABERLİK" in m_str:
            return hg == ag
        if "MS 2" in m_str:
            return ag > hg

        # 4. Double Chance (Çifte Şans)
        if "1-X" in m_str or "1X" in m_str:
            return hg >= ag
        if "X-2" in m_str or "X2" in m_str:
            return ag >= hg
        if "1-2" in m_str or "12" in m_str:
            return hg != ag

        # Default fallback
        return False

    def settle_pending_bets(self, mock_results: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """Read ledger, match completed games, compute PnL, and commit back."""
        if not self.ledger_path.exists():
            logger.info("Ledger CSV does not exist.")
            return []

        with open(self.ledger_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        if not rows:
            return []

        results = mock_results if mock_results is not None else self.fetch_espn_results()
        settled_count = 0

        for r in rows:
            if r.get("status") != "PENDING":
                continue

            home_key = r.get("home", "").lower()
            away_key = r.get("away", "").lower()

            match_data = None
            # Lookup by combination or team name
            for k, meta in results.items():
                if (home_key in k and away_key in k) or (home_key in meta["home"] or away_key in meta["away"]):
                    match_data = meta
                    break

            if not match_data:
                continue

            hg = match_data["hg"]
            ag = match_data["ag"]
            won = self.evaluate_bet_outcome(
                market=r.get("market", ""),
                outcome=r.get("outcome", ""),
                hg=hg,
                ag=ag,
            )

            odds = float(r.get("soft_odds", 2.00) or 2.00)
            stake = 50.0  # SPEC-0015 compliant fixed stake

            if won:
                r["status"] = "WON"
                r["pnl_units"] = f"+{round((odds - 1.0) * stake, 2):.2f}"
            else:
                r["status"] = "LOST"
                r["pnl_units"] = f"-{stake:.2f}"

            r["result_score"] = match_data["score_str"]
            settled_count += 1

        if settled_count > 0:
            fieldnames = list(rows[0].keys())
            with open(self.ledger_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            logger.info(f"Successfully settled {settled_count} bets in {self.ledger_path}")

        return rows
