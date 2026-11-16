"""Bzzoiro Global Sports API Odds Adapter.

Provides unblocked, redundant global football odds (1X2 & Over/Under 2.5)
for international, European, South American, and domestic club fixtures when
primary sharp feeds experience SSL/network timeouts.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("BzzoiroOddsAdapter")

ROOT_DIR = Path(__file__).resolve().parent.parent


def _resolve_bzzoiro_key() -> str:
    key = os.environ.get("BZZOIRO_KEY", "").strip()
    if key:
        return key
    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() == "BZZOIRO_KEY":
                    return v.strip().strip('"').strip("'")
    return ""


def _valid_odd(val: Any) -> float | None:
    try:
        num = float(val)
        return num if num > 1.01 else None
    except (TypeError, ValueError):
        return None


def fetch_bzzoiro_global_odds(
    date_from: str | None = None,
    date_to: str | None = None,
    max_pages: int = 15,
    timeout: float = 8.0,
) -> list[dict[str, Any]]:
    """Fetch upcoming global football events with 1X2 / O/U 2.5 odds from Bzzoiro."""
    api_key = _resolve_bzzoiro_key()
    if not api_key:
        logger.debug("BZZOIRO_KEY not configured; skipping Bzzoiro global feed.")
        return []

    now_utc = datetime.now(UTC)
    d_from = date_from or now_utc.strftime("%Y-%m-%d")
    d_to = date_to or (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")

    params = urllib.parse.urlencode({"date_from": d_from, "date_to": d_to, "status": "notstarted"})
    next_url: str | None = f"https://sports.bzzoiro.com/api/events/?{params}"
    headers = {"Authorization": f"Token {api_key}", "User-Agent": "Mozilla/5.0"}

    results: list[dict[str, Any]] = []
    pages = 0

    while next_url and pages < max_pages:
        pages += 1
        try:
            req = urllib.request.Request(next_url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.debug(f"Bzzoiro global odds fetch interrupted on page {pages}: {exc}")
            break

        for ev in data.get("results") or []:
            oh = _valid_odd(ev.get("odds_home"))
            od = _valid_odd(ev.get("odds_draw"))
            oa = _valid_odd(ev.get("odds_away"))
            if not (oh and od and oa):
                continue

            o25 = _valid_odd(ev.get("odds_over_25"))
            u25 = _valid_odd(ev.get("odds_under_25"))
            league_obj = ev.get("league") or {}

            results.append({
                "event_id": f"bzz_{ev.get('id', '')}",
                "home": str(ev.get("home_team") or "").strip(),
                "away": str(ev.get("away_team") or "").strip(),
                "kickoff": str(ev.get("event_date") or ""),
                "league": str(league_obj.get("name") or "Bzzoiro Global"),
                "country": str(league_obj.get("country") or "International"),
                "provider": "Bzzoiro_Consensus",
                "open_1x2": None,
                "current_1x2": (oh, od, oa),
                "open_ou25": None,
                "current_ou25": (o25, u25) if (o25 and u25) else None,
            })

        next_url = data.get("next")

    return results

