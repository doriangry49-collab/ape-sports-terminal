"""Live In-Play Ambush Paper Trading Ledger & Settlement Engine.

Manages the lifecycle of live in-play ambush bets:
1. Records qualifying in-play signals (Goal Ambush Over 3.5/4.5/5.5, Corner Sniper) to CSV
2. Enforces SPEC-0015 minimum 50.0 TL stake
3. Periodically queries match completion status to settle paper bets (WON / LOST / PUSH)
4. Calculates unit PnL and cumulative live ROI
5. Prevents duplicate logging via event_id + market key
"""

from __future__ import annotations

import csv
import difflib
import json
import logging
import re
import unicodedata
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("LiveInPlayLedger")

ROOT_DIR = Path(__file__).resolve().parent.parent
LIVE_LEDGER_CSV = ROOT_DIR / "output" / "live_inplay_ledger.csv"

LEDGER_HEADERS = [
    "captured_at_utc",
    "event_id",
    "league",
    "home",
    "away",
    "elapsed_min",
    "score_at_bet",
    "market",
    "selection",
    "target_line",
    "odds",
    "stake",
    "gasi_score",
    "danger_index",
    "momentum_state",
    "final_score",
    "status",
    "pnl_units",
    "pnl_try",
]


class LiveInPlayLedger:
    """Handles logging, settling, and performance tracking of in-play ambush positions."""

    def __init__(self, ledger_file: Path | None = None) -> None:
        self.ledger_file = ledger_file or LIVE_LEDGER_CSV
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        if not self.ledger_file.exists():
            self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(LEDGER_HEADERS)

    def get_existing_event_keys(self) -> set[str]:
        """Return set of recorded position keys (event_id_selection)."""
        keys: set[str] = set()
        if not self.ledger_file.exists():
            return keys

        with self.ledger_file.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                k = f"{row.get('event_id')}_{row.get('selection')}"
                keys.add(k)
        return keys

    def record_in_play_bet(self, signal: dict[str, Any]) -> bool:
        """Record an approved in-play signal as a pending paper trade.

        Enforces SPEC-0015 (min 50 TL) and deduplication.
        """
        ev_id = str(signal.get("event_id", ""))
        sel = str(signal.get("selection", ""))
        key = f"{ev_id}_{sel}"

        if key in self.get_existing_event_keys():
            return False

        raw_odd = signal.get("book_odd") or signal.get("soft_odds")
        if raw_odd is None:
            logger.debug(f"[SPEC-0012 SKIP] Missing real live odds for in-play bet: {signal.get('home')} vs {signal.get('away')}")
            return False
        odds = float(raw_odd)
        if odds <= 1.01:
            logger.debug(f"[SPEC-0012 SKIP] Invalid odds ({odds}) for in-play bet: {signal.get('home')} vs {signal.get('away')}")
            return False

        stake = max(50.0, float(signal.get("stake", 50.0) or 50.0))  # SPEC-0015 compliant

        m_eval = signal.get("momentum_eval")
        danger = getattr(m_eval, "danger_index", 0.0) if m_eval else 0.0
        m_state = getattr(m_eval, "state", "") if m_eval else ""
        if hasattr(m_state, "value"):
            m_state = m_state.value

        row = {
            "captured_at_utc": datetime.now(UTC).isoformat(),
            "event_id": ev_id,
            "league": signal.get("league", ""),
            "home": signal.get("home", ""),
            "away": signal.get("away", ""),
            "elapsed_min": signal.get("elapsed_min", 0),
            "score_at_bet": signal.get("score", ""),
            "market": signal.get("market", "CANLI GOL PUSU"),
            "selection": sel,
            "target_line": signal.get("line") or signal.get("selection", ""),
            "odds": f"{odds:.2f}",
            "stake": f"{stake:.2f}",
            "gasi_score": f"{signal.get('gasi_score', 0):.1f}",
            "danger_index": f"{danger:.1f}",
            "momentum_state": str(m_state),
            "final_score": "Bekliyor",
            "status": "PENDING",
            "pnl_units": "0.00",
            "pnl_try": "0.00",
        }

        with self.ledger_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LEDGER_HEADERS)
            writer.writerow(row)

        logger.info(f"Recorded in-play paper bet: {signal.get('home')} vs {signal.get('away')} - {sel} @ {odds}")
        return True

    def settle_bet(
        self,
        event_id: str,
        selection: str,
        final_home_goals: int,
        final_away_goals: int,
        final_corners: int | None = None,
    ) -> bool:
        """Settle a recorded paper trade given completed match stats."""
        if not self.ledger_file.exists():
            return False

        rows: list[dict[str, str]] = []
        settled_count = 0

        with self.ledger_file.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        total_goals = final_home_goals + final_away_goals
        final_score_str = f"{final_home_goals}-{final_away_goals}"

        for r in rows:
            if r.get("event_id") == event_id and r.get("selection") == selection:
                if r.get("status") != "PENDING":
                    continue

                raw_row_odd = r.get("odds")
                try:
                    odds = float(raw_row_odd) if raw_row_odd not in (None, "") else 0.0
                except (TypeError, ValueError):
                    odds = 0.0
                if odds <= 1.01:
                    continue
                stake = float(r.get("stake") or 50.0)
                market = r.get("market", "")
                sel = r.get("selection", "")

                won = False
                push = False

                if "KORNER" in market or "CORNER" in market:
                    # SPEC-0012 Fail-Closed: never settle a Corner bet as LOST when final_corners is unknown
                    if final_corners is None:
                        continue
                    m_line = re.search(r"(\d+(?:\.\d+)?)", sel)
                    if not m_line:
                        continue
                    line_val = float(m_line.group(1))
                    if final_corners > line_val:
                        won = True
                    elif final_corners == line_val:
                        push = True
                else:
                    # Goal bet settlement e.g. "4.5 ÜST" or "ÜST 4.5"
                    m_line = re.search(r"(\d+(?:\.\d+)?)", sel)
                    if not m_line:
                        continue
                    line_val = float(m_line.group(1))
                    if total_goals > line_val:
                        won = True
                    elif total_goals == line_val:
                        push = True

                if won:
                    status = "WON"
                    pnl_u = odds - 1.0
                    pnl_try = (odds - 1.0) * stake
                elif push:
                    status = "PUSH"
                    pnl_u = 0.0
                    pnl_try = 0.0
                else:
                    status = "LOST"
                    pnl_u = -1.0
                    pnl_try = -stake

                r["final_score"] = final_score_str
                r["status"] = status
                r["pnl_units"] = f"{pnl_u:+.2f}"
                r["pnl_try"] = f"{pnl_try:+.2f}"
                settled_count += 1

        if settled_count > 0:
            with self.ledger_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=LEDGER_HEADERS)
                writer.writeheader()
                writer.writerows(rows)
            return True

        return False

    def get_summary(self) -> dict[str, Any]:
        """Compute performance metrics across all settled in-play paper trades."""
        if not self.ledger_file.exists():
            return {"total_bets": 0, "settled": 0, "won": 0, "lost": 0, "roi_pct": 0.0, "total_pnl_try": 0.0}

        total = 0
        settled = 0
        won = 0
        lost = 0
        total_stake = 0.0
        total_pnl = 0.0

        with self.ledger_file.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                total += 1
                st = r.get("status")
                stake = float(r.get("stake", 50.0) or 50.0)
                if st in ("WON", "LOST", "PUSH"):
                    settled += 1
                    total_stake += stake
                    total_pnl += float(r.get("pnl_try", 0.0) or 0.0)
                    if st == "WON":
                        won += 1
                    elif st == "LOST":
                        lost += 1

        win_rate = (won / settled * 100.0) if settled > 0 else 0.0
        roi = (total_pnl / total_stake * 100.0) if total_stake > 0 else 0.0

        return {
            "total_bets": total,
            "settled": settled,
            "won": won,
            "lost": lost,
            "win_rate_pct": round(win_rate, 1),
            "roi_pct": round(roi, 1),
            "total_stake_try": round(total_stake, 2),
            "total_pnl_try": round(total_pnl, 2),
        }

    @staticmethod
    def _norm_team(name: str) -> str:
        s = name.replace("ı", "i").replace("İ", "i").replace("Türkiye", "Turkey").replace("TÜRKIYE", "Turkey")
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
        return " ".join(s.replace(".", " ").replace("-", " ").split())

    def _fetch_espn_event_outcome(self, event_id: str, league: str) -> dict[str, Any] | None:
        """Fetch final completed match score and boxscore corners from ESPN event summary API."""
        slugs_to_try = [league] if league and league != "all" else []
        slugs_to_try.append("all")
        for slug in slugs_to_try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={event_id}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception:
                continue

            comp = (data.get("header") or {}).get("competitions", [{}])[0]
            st_type = (comp.get("status") or {}).get("type", {})
            completed = bool(st_type.get("completed") or st_type.get("state") == "post")
            comps = comp.get("competitors") or []
            if len(comps) < 2:
                continue
            teams_by_side = {c.get("homeAway"): c for c in comps}
            h_c = teams_by_side.get("home") or comps[0]
            a_c = teams_by_side.get("away") or comps[1]
            h_name = (h_c.get("team") or {}).get("displayName") or (h_c.get("team") or {}).get("name") or ""
            a_name = (a_c.get("team") or {}).get("displayName") or (a_c.get("team") or {}).get("name") or ""
            try:
                hg = int(h_c.get("score"))
                ag = int(a_c.get("score"))
            except (TypeError, ValueError):
                hg, ag = None, None

            corners_val: int | None = None
            box_teams = (data.get("boxscore") or {}).get("teams") or []
            tot_c = 0
            corner_sides_found = 0
            for bt in box_teams:
                for stat in bt.get("statistics") or []:
                    if stat.get("name") == "wonCorners" and stat.get("displayValue") is not None:
                        try:
                            tot_c += int(float(stat["displayValue"]))
                            corner_sides_found += 1
                        except (TypeError, ValueError):
                            pass
            if corner_sides_found >= 2:
                corners_val = tot_c

            return {
                "completed": completed,
                "status_desc": st_type.get("description", ""),
                "home": h_name,
                "away": a_name,
                "hg": hg,
                "ag": ag,
                "corners": corners_val,
            }
        return None

    def settle_pending_from_espn(self) -> dict[str, Any]:
        """Query ESPN Summary API for all PENDING rows and settle completed bets (fail-closed per SPEC-0012)."""
        if not self.ledger_file.exists():
            return {"settled_now": 0, "summary": self.get_summary(), "details": []}

        with self.ledger_file.open("r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        event_cache: dict[str, dict[str, Any] | None] = {}
        settled_now = 0
        corners_missing = 0
        not_completed = 0
        non_espn_ids = 0
        team_mismatch = 0

        for r in rows:
            if r.get("status") != "PENDING":
                continue
            ev_id = str(r.get("event_id") or "").strip()
            if not ev_id.isdigit():
                non_espn_ids += 1
                continue

            if ev_id not in event_cache:
                event_cache[ev_id] = self._fetch_espn_event_outcome(ev_id, str(r.get("league") or "all"))
            outcome = event_cache[ev_id]
            if not outcome or not outcome.get("completed"):
                not_completed += 1
                continue
            hg = outcome.get("hg")
            ag = outcome.get("ag")
            if hg is None or ag is None:
                not_completed += 1
                continue

            # Sanity-verify teams match to guard against synthetic/recycled numeric test IDs (e.g. 999001)
            sh = difflib.SequenceMatcher(None, self._norm_team(r.get("home", "")), self._norm_team(outcome["home"])).ratio()
            sa = difflib.SequenceMatcher(None, self._norm_team(r.get("away", "")), self._norm_team(outcome["away"])).ratio()
            if min(sh, sa) < 0.45:
                team_mismatch += 1
                continue

            market = r.get("market", "")
            corners = outcome.get("corners")
            if ("KORNER" in market.upper() or "CORNER" in market.upper()) and corners is None:
                # Record factual final score note without falsely settling corner outcome
                r["final_score"] = f"{hg}-{ag} (K:N/A)"
                corners_missing += 1
                continue

            try:
                odds = float(r.get("odds") or 0.0)
                stake = float(r.get("stake") or 50.0)
            except (TypeError, ValueError):
                continue
            if odds <= 1.01:
                continue

            sel = r.get("selection", "")
            m_line = re.search(r"(\d+(?:\.\d+)?)", sel)
            if not m_line:
                continue
            line_val = float(m_line.group(1))

            actual_val = corners if ("KORNER" in market.upper() or "CORNER" in market.upper()) else (hg + ag)
            is_under = any(k in sel.upper() for k in ("ALT", "UNDER", "<"))
            won = (actual_val < line_val) if is_under else (actual_val > line_val)
            push = (actual_val == line_val)

            if won:
                status = "WON"
                pnl_u = odds - 1.0
                pnl_try = (odds - 1.0) * stake
            elif push:
                status = "PUSH"
                pnl_u = 0.0
                pnl_try = 0.0
            else:
                status = "LOST"
                pnl_u = -1.0
                pnl_try = -stake

            r["final_score"] = f"{hg}-{ag}" + (f" (K:{corners})" if corners is not None else "")
            r["status"] = status
            r["pnl_units"] = f"{pnl_u:+.2f}"
            r["pnl_try"] = f"{pnl_try:+.2f}"
            settled_now += 1

        if settled_now > 0 or corners_missing > 0:
            with self.ledger_file.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=LEDGER_HEADERS)
                writer.writeheader()
                writer.writerows(rows)

        return {
            "settled_now": settled_now,
            "corners_unavailable_pending": corners_missing,
            "not_completed_or_unfound": not_completed,
            "non_espn_test_ids": non_espn_ids,
            "team_mismatch_skipped": team_mismatch,
            "summary": self.get_summary(),
        }

