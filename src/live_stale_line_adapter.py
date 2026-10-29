"""Live 36-League Stale-Line, Live Nesine CDN & Steam Adapter (v2.1).

Scans active European, Cup (UCL, UEL, UECL, DFB), Secondary European (Alpha Zone),
and World leagues from PropLine AND automatically fetches the live Turkish Nesine
pre-match bulletin (`https://cdnbulten.nesine.com/api/bulten/getprebultenfull`),
matching Pinnacle sharp odds directly against live Nesine 1X2 & 2.5 O/U odds.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from paper_trader import PaperTradingEngine
from stale_line_scanner import (
    devig_power,
    devig_shin,
    scan_stale_lines,
)
from steam_tracker import PinnacleSteamTracker
from team_normalizer import TeamNormalizer

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

_NORMALIZER = TeamNormalizer()

NESINE_CDN_URL = "https://cdnbulten.nesine.com/api/bulten/getprebultenfull"

# Comprehensive 28-League Target Map (36 PropLine Soccer Catalog Filtered to Active Match Leagues)
TARGET_LEAGUES: dict[str, tuple[str, str]] = {
    # TIER 1: 11 Secondary European Leagues (+22.35% Draw Steam Alpha Zone)
    "soccer_turkey_super_league": ("Türkiye Süper Lig (T1)", "TIER_1_SEC"),
    "soccer_belgium_first_div": ("Belçika Pro League (B1)", "TIER_1_SEC"),
    "soccer_netherlands_eredivisie": ("Hollanda Eredivisie (N1)", "TIER_1_SEC"),
    "soccer_portugal_primeira_liga": ("Portekiz Primeira Liga (P1)", "TIER_1_SEC"),
    "soccer_greece_super_league": ("Yunanistan Süper Lig (G1)", "TIER_1_SEC"),
    "soccer_scotland_premiership": ("İskoçya Premiership (SC0)", "TIER_1_SEC"),
    "soccer_efl_champ": ("İngiltere Championship (E1)", "TIER_1_SEC"),
    "soccer_england_league1": ("İngiltere League 1 (E2)", "TIER_1_SEC"),
    "soccer_england_league2": ("İngiltere League 2 (E3)", "TIER_1_SEC"),
    "soccer_germany_bundesliga2": ("Almanya Bundesliga 2 (D2)", "TIER_1_SEC"),
    "soccer_italy_serie_b": ("İtalya Serie B (I2)", "TIER_1_SEC"),
    "soccer_spain_segunda_division": ("İspanya La Liga 2 (SP2)", "TIER_1_SEC"),
    "soccer_france_ligue_two": ("Fransa Ligue 2 (F2)", "TIER_1_SEC"),
    "soccer_austria_bundesliga": ("Avusturya Bundesliga (AUT)", "TIER_1_SEC"),
    "soccer_switzerland_superleague": ("İsviçre Super League (SWZ)", "TIER_1_SEC"),
    "soccer_denmark_superliga": ("Danimarka Superliga (DEN)", "TIER_1_SEC"),
    "soccer_poland_ekstraklasa": ("Polonya Ekstraklasa (POL)", "TIER_1_SEC"),
    # EUROPEAN CUPS
    "soccer_uefa_champs_league": ("UEFA Şampiyonlar Ligi (UCL)", "CUP"),
    "soccer_uefa_europa_league": ("UEFA Avrupa Ligi (UEL)", "CUP"),
    "soccer_uefa_europa_conference_league": ("UEFA Konferans Ligi (UECL)", "CUP"),
    "soccer_germany_dfb_pokal": ("Almanya DFB Pokal (KUPA)", "CUP"),
    # TIER 2: Big-5 European Leagues
    "soccer_epl": ("İngiltere Premier League (E0)", "TIER_2_MAJ"),
    "soccer_germany_bundesliga": ("Almanya Bundesliga (D1)", "TIER_2_MAJ"),
    "soccer_italy_serie_a": ("İtalya Serie A (I1)", "TIER_2_MAJ"),
    "soccer_spain_la_liga": ("İspanya La Liga (SP1)", "TIER_2_MAJ"),
    "soccer_france_ligue_one": ("Fransa Ligue 1 (F1)", "TIER_2_MAJ"),
    # WORLD LEAGUES (Monitored; Draw signals disabled per backtest proof)
    "soccer_brazil_campeonato": ("Brezilya Série A (BRA)", "NO_DRAW_EDGE"),
    "soccer_usa_mls": ("ABD MLS (USA)", "NO_DRAW_EDGE"),
}

SOFT_BOOKS_PRIORITY: tuple[str, ...] = (
    "nesine",
    "b365",
    "bet365",
    "unibet",
    "bovada",
    "betmgm",
    "williamhill",
    "tipico",
    "betway",
    "fanduel",
    "draftkings",
    "betrivers",
    "betonlineag",
    "winamax",
    "betclic",
    "paddypower",
    "ladbrokes",
    "coral",
    "skybet",
    "888sport",
    "betsson",
    "nordicbet",
    "bwin",
    "sportingbet",
    "interwetten",
    "snai",
    "eurobet",
    "sisal",
    "lottomatica",
    "codere",
    "kirolbet",
    "luckia",
    "retabet",
    "sts",
    "fortuna_pl",
    "superbet_ro",
)


def fetch_nesine_live_bulletin() -> list[dict[str, Any]]:
    """Fetch all live football pre-match events and odds from Nesine public CDN."""
    try:
        req = urllib.request.Request(
            NESINE_CDN_URL,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            if resp.status != 200:
                return []
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []

    ea_list = payload.get("sg", {}).get("EA", [])
    parsed_matches: list[dict[str, Any]] = []
    for item in ea_list:
        if item.get("TYPE") != 1 or not item.get("MA"):
            continue
        hn = item.get("HN", "")
        an = item.get("AN", "")
        if not hn or not an:
            continue

        odds_1x2: tuple[float, float, float] | None = None
        odds_ou25: tuple[float, float] | None = None
        mbs_val = item.get("EMBS") or 1

        for mkt in item.get("MA", []):
            mtid = mkt.get("MTID")
            sov = float(mkt.get("SOV") or 0.0)
            oca = {o.get("N"): float(o.get("O") or 0.0) for o in mkt.get("OCA", [])}
            if mtid == 1:
                o1, ox, o2 = oca.get(1, 0.0), oca.get(2, 0.0), oca.get(3, 0.0)
                if o1 > 1.01 and ox > 1.01 and o2 > 1.01:
                    odds_1x2 = (o1, ox, o2)
                    mbs_val = mkt.get("MBS") or mbs_val
            elif mtid == 12 and abs(sov - 2.5) <= 1e-4:
                # In Nesine MTID=12 (SOV=2.5): N=1 is 2.5 Alt (Under), N=2 is 2.5 Üst (Over)
                o_under, o_over = oca.get(1, 0.0), oca.get(2, 0.0)
                if o_over > 1.01 and o_under > 1.01:
                    odds_ou25 = (o_over, o_under)

        if odds_1x2 or odds_ou25:
            parsed_matches.append({
                "nesine_code": item.get("C"),
                "home": hn,
                "away": an,
                "date_str": item.get("D", ""),
                "time_str": item.get("T", ""),
                "mbs": mbs_val,
                "nesine_1x2": odds_1x2,
                "nesine_ou25": odds_ou25,
            })
    return parsed_matches


def match_nesine_fixture(
    home: str,
    away: str,
    nesine_bulletin: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find the matching Nesine bulletin entry for a Pinnacle (home, away) fixture."""
    return _NORMALIZER.match_fixture(
        home,
        away,
        nesine_bulletin,
        home_key="home",
        away_key="away",
        threshold=0.65,
    )


def _extract_book_1x2(
    book_data: dict[str, Any], home: str, away: str
) -> tuple[float, float, float] | None:
    markets = book_data.get("markets", {})
    h2h = markets.get("h2h", {}).get("outcomes", [])
    if not h2h:
        return None
    odds_map: dict[str, float] = {}
    for o in h2h:
        name = o.get("name", "")
        price = float(o.get("price", 0.0))
        if price <= 1.0:
            continue
        if name == home:
            odds_map["H"] = price
        elif name == away:
            odds_map["A"] = price
        elif name.lower() in ("draw", "tie", "x"):
            odds_map["D"] = price
    if "H" in odds_map and "D" in odds_map and "A" in odds_map:
        return (odds_map["H"], odds_map["D"], odds_map["A"])
    return None


def _extract_book_ou25(book_data: dict[str, Any]) -> tuple[float, float] | None:
    markets = book_data.get("markets", {})
    totals = markets.get("totals", {}).get("outcomes", [])
    if not totals:
        return None
    odds_map: dict[str, float] = {}
    for o in totals:
        pt = o.get("point")
        if pt is None or abs(float(pt) - 2.5) > 1e-4:
            continue
        name = o.get("name", "").lower()
        price = float(o.get("price", 0.0))
        if price <= 1.0:
            continue
        if "over" in name:
            odds_map["O"] = price
        elif "under" in name:
            odds_map["U"] = price
    if "O" in odds_map and "U" in odds_map:
        return (odds_map["O"], odds_map["U"])
    return None


def _get_json(url: str, headers: dict[str, str], params: dict[str, str]) -> Any:
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}" if query else url
    req = urllib.request.Request(full_url, headers=headers)
    with urllib.request.urlopen(req, timeout=20.0) as resp:
        if resp.status != 200:
            return None
        return json.loads(resp.read().decode("utf-8"))


def fetch_and_scan_live_propline(
    output_path: Path | None = None,
    settle_espn: bool = True,
) -> dict[str, Any]:
    api_key = os.getenv("PROPLINE_KEY")
    if not api_key:
        raise RuntimeError("PROPLINE_KEY missing in .env")

    headers = {"x-api-key": api_key, "Accept": "application/json"}
    captured_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Fetch live Nesine bulletin from official CDN
    nesine_bulletin = fetch_nesine_live_bulletin()

    steam_tracker = PinnacleSteamTracker(ROOT_DIR / "output" / "snapshots")
    paper_trader = PaperTradingEngine(ROOT_DIR / "output" / "paper_trading_ledger.csv")

    all_signals: list[dict[str, Any]] = []
    scanned_matches: list[dict[str, Any]] = []
    latest_fair_lookup: dict[tuple[str, str, str], float] = {}
    nesine_matched_count = 0

    for sport_key, (league_label, tier_tag) in TARGET_LEAGUES.items():
        url = f"https://api.prop-line.com/v1/sports/{sport_key}/odds"
        try:
            payload = _get_json(
                url,
                headers=headers,
                params={"regions": "eu,us", "markets": "h2h,totals"},
            )
        except Exception:
            continue

        if not payload:
            continue
        events = payload if isinstance(payload, list) else payload.get("events", [])
        for ev in events:
            home = ev.get("home_team", "")
            away = ev.get("away_team", "")
            kickoff = ev.get("commence_time", "")
            ev_id = str(ev.get("id", f"{sport_key}_{home}_{away}"))
            bks = ev.get("bookmakers", {})
            if not isinstance(bks, dict):
                continue

            pin = bks.get("pinnacle")
            if not pin:
                continue

            pin_1x2 = _extract_book_1x2(pin, home, away)
            pin_ou25 = _extract_book_ou25(pin)
            if not pin_1x2:
                continue

            # Match against live Nesine CDN bulletin
            nesine_match = match_nesine_fixture(home, away, nesine_bulletin)
            nesine_1x2 = nesine_match["nesine_1x2"] if nesine_match else None
            nesine_ou25 = nesine_match["nesine_ou25"] if nesine_match else None
            if nesine_match:
                nesine_matched_count += 1
                # Inject live Nesine odds into bookmakers dict so it's scanned automatically!
                bks["nesine"] = {"_direct_1x2": nesine_1x2, "_direct_ou25": nesine_ou25}

            # Track snapshot & compute real-time steam vs baseline
            steam_info = steam_tracker.record_and_evaluate_fixture(
                event_id=ev_id,
                league=league_label,
                home=home,
                away=away,
                kickoff=kickoff,
                pinnacle_1x2=pin_1x2,
                pinnacle_ou25=pin_ou25,
                captured_at_utc=captured_ts,
                devig_method="shin",
            )
            open_1x2 = steam_info.get("open_1x2")
            open_ou25 = steam_info.get("open_ou25")

            shin_probs = devig_shin(pin_1x2)
            power_probs = devig_power(pin_1x2)
            shin_ou_probs = devig_shin(pin_ou25) if pin_ou25 else None

            # Populate latest fair odds lookup for CLV tracking
            for idx, out_lbl in enumerate(("HOME", "DRAW", "AWAY")):
                latest_fair_lookup[(ev_id, "1X2", out_lbl)] = round(1.0 / shin_probs[idx], 4)
            if shin_ou_probs:
                latest_fair_lookup[(ev_id, "OU_2.5", "OVER_2.5")] = round(1.0 / shin_ou_probs[0], 4)
                latest_fair_lookup[(ev_id, "OU_2.5", "UNDER_2.5")] = round(1.0 / shin_ou_probs[1], 4)

            draw_steam = steam_info.get("steam_1x2", {}).get("DRAW", {})
            under_steam = steam_info.get("steam_ou25", {}).get("UNDER_2.5", {})

            # Compute direct Nesine EV edges for every market on this match
            nesine_edges_1x2 = None
            if nesine_1x2:
                nesine_edges_1x2 = [
                    round(((shin_probs[i] * nesine_1x2[i]) - 1.0) * 100.0, 2)
                    for i in range(3)
                ]
            nesine_edges_ou25 = None
            if nesine_ou25 and shin_ou_probs:
                nesine_edges_ou25 = [
                    round(((shin_ou_probs[i] * nesine_ou25[i]) - 1.0) * 100.0, 2)
                    for i in range(2)
                ]

            scanned_matches.append({
                "event_id": ev_id,
                "sport_key": sport_key,
                "league": league_label,
                "tier": tier_tag,
                "home": home,
                "away": away,
                "kickoff": kickoff,
                "pinnacle_open_1x2": open_1x2,
                "pinnacle_1x2": list(pin_1x2),
                "pinnacle_ou25": list(pin_ou25) if pin_ou25 else None,
                "nesine_code": nesine_match["nesine_code"] if nesine_match else None,
                "nesine_mbs": nesine_match["mbs"] if nesine_match else None,
                "nesine_1x2": list(nesine_1x2) if nesine_1x2 else None,
                "nesine_ou25": list(nesine_ou25) if nesine_ou25 else None,
                "nesine_edges_1x2": nesine_edges_1x2,
                "nesine_edges_ou25": nesine_edges_ou25,
                "shin_probs_1x2": [round(p, 4) for p in shin_probs],
                "shin_probs_ou25": [round(p, 4) for p in shin_ou_probs] if shin_ou_probs else None,
                "shin_fair_1x2": [round(1.0 / p, 2) for p in shin_probs],
                "power_fair_1x2": [round(1.0 / p, 2) for p in power_probs],
                "shin_fair_ou25": [round(1.0 / p, 2) for p in shin_ou_probs] if shin_ou_probs else None,
                "nesine_min_ev_home": round((1.0 / shin_probs[0]) * 1.02, 2),
                "nesine_min_ev_draw": round((1.0 / shin_probs[1]) * 1.02, 2),
                "nesine_min_ev_away": round((1.0 / shin_probs[2]) * 1.02, 2),
                "nesine_min_ev_over25": round((1.0 / shin_ou_probs[0]) * 1.02, 2) if shin_ou_probs else None,
                "nesine_min_ev_under25": round((1.0 / shin_ou_probs[1]) * 1.02, 2) if shin_ou_probs else None,
                "snapshots_count": steam_info.get("snapshots_count", 1),
                "draw_steam_drift_pp": draw_steam.get("steam_drift_pp", 0.0),
                "draw_steam_confirmed": draw_steam.get("is_steam_confirmed", False),
                "under_steam_drift_pp": under_steam.get("steam_drift_pp", 0.0),
                "under_steam_confirmed": under_steam.get("is_steam_confirmed", False),
            })

            # Scan synchronous soft books (including Nesine!) against Pinnacle
            for sb_key in SOFT_BOOKS_PRIORITY:
                sb_data = bks.get(sb_key)
                if not sb_data:
                    continue
                if sb_key == "nesine":
                    sb_1x2 = sb_data.get("_direct_1x2")
                    sb_ou25 = sb_data.get("_direct_ou25")
                else:
                    sb_1x2 = _extract_book_1x2(sb_data, home, away)
                    sb_ou25 = _extract_book_ou25(sb_data)
                if not sb_1x2 and not sb_ou25:
                    continue

                sigs = scan_stale_lines(
                    [
                        {
                            "match_id": f"{ev_id}_{sb_key}",
                            "league": f"{league_label} [{sb_key.upper()}]",
                            "home": home,
                            "away": away,
                            "sharp_timestamp": captured_ts,
                            "soft_timestamp": captured_ts,
                            "sharp_open_1x2": open_1x2,
                            "sharp_1x2": pin_1x2,
                            "soft_1x2": sb_1x2,
                            "sharp_open_ou25": open_ou25,
                            "sharp_ou25": pin_ou25,
                            "soft_ou25": sb_ou25,
                        }
                    ],
                    devig_method="shin",
                    min_edge=0.02,
                )
                for s in sigs:
                    if s.soft_odds > s.sharp_odds * 1.25:
                        continue
                    d = asdict(s)
                    d["event_id"] = ev_id
                    d["kickoff"] = kickoff
                    d["soft_book"] = sb_key
                    d["tier"] = tier_tag
                    d["is_steam_confirmed"] = bool(
                        s.steam_drift_pp is not None and s.steam_drift_pp >= 0.25
                    )
                    all_signals.append(d)

    # Enrich from baseline snapshot cache for any fixture missed due to transient API rate-limit
    seen_ids = {m["event_id"] for m in scanned_matches}
    league_to_tier = dict(TARGET_LEAGUES.values())
    for ev_id, rec in steam_tracker.index.items():
        if ev_id in seen_ids:
            continue
        pin_1x2_list = rec.get("last_1x2") or rec.get("open_1x2")
        if not pin_1x2_list or len(pin_1x2_list) != 3:
            continue
        pin_1x2 = (float(pin_1x2_list[0]), float(pin_1x2_list[1]), float(pin_1x2_list[2]))
        pin_ou_list = rec.get("last_ou25") or rec.get("open_ou25")
        pin_ou25 = (
            (float(pin_ou_list[0]), float(pin_ou_list[1]))
            if pin_ou_list and len(pin_ou_list) == 2
            else None
        )
        home = rec.get("home", "")
        away = rec.get("away", "")
        kickoff = rec.get("kickoff", "")
        league_label = rec.get("league", "")
        tier_tag = league_to_tier.get(league_label, "TIER_1_SEC")

        nesine_match = match_nesine_fixture(home, away, nesine_bulletin)
        nesine_1x2 = nesine_match["nesine_1x2"] if nesine_match else None
        nesine_ou25 = nesine_match["nesine_ou25"] if nesine_match else None
        if nesine_match:
            nesine_matched_count += 1

        shin_probs = devig_shin(pin_1x2)
        power_probs = devig_power(pin_1x2)
        shin_ou_probs = devig_shin(pin_ou25) if pin_ou25 else None

        nesine_edges_1x2 = (
            [round(((shin_probs[i] * nesine_1x2[i]) - 1.0) * 100.0, 2) for i in range(3)]
            if nesine_1x2
            else None
        )
        nesine_edges_ou25 = (
            [round(((shin_ou_probs[i] * nesine_ou25[i]) - 1.0) * 100.0, 2) for i in range(2)]
            if (nesine_ou25 and shin_ou_probs)
            else None
        )

        scanned_matches.append({
            "event_id": ev_id,
            "sport_key": "cached_pinnacle",
            "league": league_label,
            "tier": tier_tag,
            "home": home,
            "away": away,
            "kickoff": kickoff,
            "pinnacle_open_1x2": rec.get("open_1x2"),
            "pinnacle_1x2": list(pin_1x2),
            "pinnacle_ou25": list(pin_ou25) if pin_ou25 else None,
            "nesine_code": nesine_match["nesine_code"] if nesine_match else None,
            "nesine_mbs": nesine_match["mbs"] if nesine_match else None,
            "nesine_1x2": list(nesine_1x2) if nesine_1x2 else None,
            "nesine_ou25": list(nesine_ou25) if nesine_ou25 else None,
            "nesine_edges_1x2": nesine_edges_1x2,
            "nesine_edges_ou25": nesine_edges_ou25,
            "shin_probs_1x2": [round(p, 4) for p in shin_probs],
            "shin_probs_ou25": [round(p, 4) for p in shin_ou_probs] if shin_ou_probs else None,
            "shin_fair_1x2": [round(1.0 / p, 2) for p in shin_probs],
            "power_fair_1x2": [round(1.0 / p, 2) for p in power_probs],
            "shin_fair_ou25": [round(1.0 / p, 2) for p in shin_ou_probs] if shin_ou_probs else None,
            "nesine_min_ev_home": round((1.0 / shin_probs[0]) * 1.02, 2),
            "nesine_min_ev_draw": round((1.0 / shin_probs[1]) * 1.02, 2),
            "nesine_min_ev_away": round((1.0 / shin_probs[2]) * 1.02, 2),
            "nesine_min_ev_over25": round((1.0 / shin_ou_probs[0]) * 1.02, 2) if shin_ou_probs else None,
            "nesine_min_ev_under25": round((1.0 / shin_ou_probs[1]) * 1.02, 2) if shin_ou_probs else None,
            "snapshots_count": rec.get("snapshots_count", 1),
            "draw_steam_drift_pp": 0.0,
            "draw_steam_confirmed": False,
            "under_steam_drift_pp": 0.0,
            "under_steam_confirmed": False,
        })

        if nesine_1x2 or nesine_ou25:
            sigs = scan_stale_lines(
                [
                    {
                        "match_id": f"{ev_id}_nesine",
                        "league": f"{league_label} [NESİNE]",
                        "home": home,
                        "away": away,
                        "sharp_timestamp": captured_ts,
                        "soft_timestamp": captured_ts,
                        "sharp_open_1x2": rec.get("open_1x2"),
                        "sharp_1x2": pin_1x2,
                        "soft_1x2": nesine_1x2,
                        "sharp_open_ou25": rec.get("open_ou25"),
                        "sharp_ou25": pin_ou25,
                        "soft_ou25": nesine_ou25,
                    }
                ],
                devig_method="shin",
                min_edge=0.02,
            )
            for s in sigs:
                if s.soft_odds > s.sharp_odds * 1.25:
                    continue
                d = asdict(s)
                d["event_id"] = ev_id
                d["kickoff"] = kickoff
                d["soft_book"] = "nesine"
                d["tier"] = tier_tag
                d["is_steam_confirmed"] = False
                all_signals.append(d)

    # Persist snapshot archive
    steam_tracker.write_snapshot_archive(captured_ts, len(scanned_matches))

    # Deduplicate signals by (event_id, market, outcome), keeping highest soft_odds
    best_by_selection: dict[tuple[str, str, str], dict[str, Any]] = {}
    for sig in all_signals:
        key = (sig["event_id"], sig["market"], sig["outcome"])
        if key not in best_by_selection or sig["edge_pct"] > best_by_selection[key]["edge_pct"]:
            best_by_selection[key] = sig

    dedup_signals = sorted(
        best_by_selection.values(),
        key=lambda x: (x.get("is_steam_confirmed", False), x["edge_pct"]),
        reverse=True,
    )

    # Record signals into Paper-Trading Ledger & update CLV
    ledger_counts = paper_trader.record_signals(
        dedup_signals,
        latest_fair_lookup=latest_fair_lookup,
    )
    settle_stats = paper_trader.fetch_espn_completed_and_settle() if settle_espn else {"settled_now": 0}
    ledger_summary = paper_trader.compute_summary()

    result = {
        "captured_at_utc": captured_ts,
        "leagues_scanned": len(TARGET_LEAGUES),
        "fixtures_with_pinnacle": len(scanned_matches),
        "nesine_total_football_bulletin": len(nesine_bulletin),
        "nesine_matched_fixtures": nesine_matched_count,
        "positive_ev_signals_count": len(dedup_signals),
        "steam_confirmed_signals_count": sum(
            1 for s in dedup_signals if s.get("is_steam_confirmed")
        ),
        "paper_trading_ledger": {
            **ledger_counts,
            **settle_stats,
            **ledger_summary,
        },
        "signals": dedup_signals,
        "fixtures": sorted(scanned_matches, key=lambda x: x["kickoff"]),
    }

    if output_path is None:
        output_path = ROOT_DIR / "output" / "live_stale_line_signals.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    res = fetch_and_scan_live_propline(settle_espn=False)
    print(
        f"[LIVE SCAN v2.1 OK] Captured at {res['captured_at_utc']} | "
        f"Leagues: {res['leagues_scanned']} | "
        f"Fixtures w/ Pinnacle: {res['fixtures_with_pinnacle']} | "
        f"Nesine Matched: {res['nesine_matched_fixtures']}/{res['fixtures_with_pinnacle']} "
        f"(Bulletin: {res['nesine_total_football_bulletin']}) | "
        f"+EV Signals: {res['positive_ev_signals_count']}"
    )
