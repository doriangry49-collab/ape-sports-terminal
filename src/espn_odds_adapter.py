"""ESPN Public Scoreboard Odds Parser & Sharp/DraftKings Fallback Adapter.

Extracts moneyline, totals, and opening/closing odds from ESPN's public feed
to serve as an unblocked, zero-cost redundant odds provider when third-party APIs timeout.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger("EspnOddsAdapter")


def american_to_decimal(american_str: str | int | float | None) -> float | None:
    """Convert American odds format (+150, -185) to European decimal (2.50, 1.54)."""
    if american_str is None:
        return None
    try:
        val_str = str(american_str).replace("+", "").strip()
        val = float(val_str)
        if val == 0:
            return None
        if val > 0:
            return round((val / 100.0) + 1.0, 3)
        else:
            return round((100.0 / abs(val)) + 1.0, 3)
    except Exception:
        return None


def _is_total_line_25(node: dict[str, Any], side_prefix: str, fallback_total: Any) -> bool:
    """Return True only when an ESPN total quote explicitly prices the 2.5 goal line."""
    line = node.get("line")
    if isinstance(line, str) and line.strip():
        return line.strip().lower() in {f"{side_prefix}2.5", "2.5"}
    if isinstance(line, (int, float)):
        return abs(float(line) - 2.5) < 1e-6
    if fallback_total is not None:
        try:
            return abs(float(fallback_total) - 2.5) < 1e-6
        except (TypeError, ValueError):
            return False
    return False


def _extract_total_side(
    totals: dict[str, Any],
    side: str,
    period: str,
    fallback_total: Any,
) -> float | None:
    """Extract decimal odds for Over/Under 2.5, rejecting alternate lines like 1.5 or 3.5."""
    side_prefix = "o" if side == "over" else "u"
    side_obj = totals.get(side, {}) or {}
    if period == "open":
        node = side_obj.get("open", {}) or {}
    else:
        close_node = side_obj.get("close", {}) or {}
        cur_node = side_obj.get("current", {}) or {}
        node = close_node if american_to_decimal(close_node.get("odds")) is not None else cur_node

    odd = american_to_decimal(node.get("odds"))
    if odd is None or not _is_total_line_25(node, side_prefix, fallback_total):
        return None
    return odd


def fetch_espn_sharp_odds_for_league(league_slug: str = "eng.1") -> list[dict[str, Any]]:
    """Fetch live & pre-match odds from ESPN scoreboard for a given soccer league."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_slug}/scoreboard"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    results: list[dict[str, Any]] = []

    try:
        with urllib.request.urlopen(req, timeout=6.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.debug(f"Could not fetch ESPN odds for {league_slug}: {e}")
        return []

    events = data.get("events", [])
    for ev in events:
        comps = ev.get("competitions", [{}])[0]
        teams = {c.get("homeAway"): c for c in comps.get("competitors", [])}
        if "home" not in teams or "away" not in teams:
            continue

        home_name = teams["home"].get("team", {}).get("displayName", "")
        away_name = teams["away"].get("team", {}).get("displayName", "")
        kickoff = ev.get("date", "")
        ev_id = str(ev.get("id", ""))

        odds_list = comps.get("odds", [])
        if not odds_list or not isinstance(odds_list, list) or odds_list[0] is None:
            continue

        odds_obj = odds_list[0]
        provider_name = odds_obj.get("provider", {}).get("displayName", "ESPN_DraftKings")

        ml = odds_obj.get("moneyline", {})
        h_open = american_to_decimal(ml.get("home", {}).get("open", {}).get("odds"))
        h_cur = american_to_decimal(ml.get("home", {}).get("close", {}).get("odds") or ml.get("home", {}).get("current", {}).get("odds"))
        d_open = american_to_decimal(ml.get("draw", {}).get("open", {}).get("odds"))
        d_cur = american_to_decimal(ml.get("draw", {}).get("close", {}).get("odds") or ml.get("draw", {}).get("current", {}).get("odds"))
        a_open = american_to_decimal(ml.get("away", {}).get("open", {}).get("odds"))
        a_cur = american_to_decimal(ml.get("away", {}).get("close", {}).get("odds") or ml.get("away", {}).get("current", {}).get("odds"))

        # Totals — strictly require the 2.5 line (never alias 1.5 or 3.5 lines into ou25)
        totals = odds_obj.get("total", {}) or {}
        over_under_line = odds_obj.get("overUnder")
        o_open = _extract_total_side(totals, "over", "open", over_under_line)
        o_cur = _extract_total_side(totals, "over", "current", over_under_line)
        u_open = _extract_total_side(totals, "under", "open", over_under_line)
        u_cur = _extract_total_side(totals, "under", "current", over_under_line)

        results.append({
            "event_id": f"espn_{ev_id}",
            "home": home_name,
            "away": away_name,
            "kickoff": kickoff,
            "provider": provider_name,
            "open_1x2": (h_open, d_open, a_open) if (h_open and d_open and a_open) else None,
            "current_1x2": (h_cur, d_cur, a_cur) if (h_cur and d_cur and a_cur) else None,
            "open_ou25": (o_open, u_open) if (o_open and u_open) else None,
            "current_ou25": (o_cur, u_cur) if (o_cur and u_cur) else None,
        })

    return results

