"""Live 36-League Stale-Line, Live Nesine CDN & Steam Adapter (v2.1).

Scans active European, Cup (UCL, UEL, UECL, DFB), Secondary European (Alpha Zone),
and World leagues from PropLine AND automatically fetches the live Turkish Nesine
pre-match bulletin (`https://cdnbulten.nesine.com/api/bulten/getprebultenfull`),
matching Pinnacle sharp odds directly against live Nesine 1X2 & 2.5 O/U odds.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    from atomic_io import atomic_write_json
except ImportError:
    from src.atomic_io import atomic_write_json

from paper_trader import PaperTradingEngine
from stale_line_scanner import (
    devig_power,
    devig_shin,
    scan_stale_lines,
)
from steam_tracker import PinnacleSteamTracker
from team_normalizer import TeamNormalizer

logger = logging.getLogger("LiveStaleLineAdapter")

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

_NORMALIZER = TeamNormalizer()

NESINE_CDN_URL = "https://cdnbulten.nesine.com/api/bulten/getprebultenfull"


class AdapterError(Exception):
    """Base exception for external adapter and feed errors (SPEC-0012: Error != Unknown)."""
    pass


class AdapterTimeoutError(AdapterError):
    """Raised when external feed socket request times out."""
    pass


class AdapterHTTPError(AdapterError):
    """Raised when external HTTP feed returns non-200 status code."""
    def __init__(self, status_code: int, message: str, url: str = ""):
        super().__init__(f"HTTP {status_code}: {message} (url: {url})")
        self.status_code = status_code
        self.url = url


class AdapterPayloadError(AdapterError):
    """Raised when external payload format or JSON parsing fails."""
    pass


def is_kickoff_in_future(kickoff_iso: str | None, min_buffer_minutes: int = 5) -> bool:
    """Return False if kickoff is missing, invalid, or already started/passed."""
    if not kickoff_iso:
        return False
    try:
        dt = datetime.fromisoformat(str(kickoff_iso).replace("Z", "+00:00"))
        return dt > datetime.now(UTC) + timedelta(minutes=min_buffer_minutes)
    except Exception:
        return False

# Comprehensive 28-League Target Map (36 PropLine Soccer Catalog Filtered to Active Match Leagues)
_PROPLINE_CIRCUIT_BREAKER_UNTIL: float = 0.0

COUNTRY_CODE_MAP: dict[str, str] = {
    "TR": "Turkey",
    "ENG": "England",
    "GB": "England",
    "ES": "Spain",
    "DE": "Germany",
    "IT": "Italy",
    "FR": "France",
    "NL": "Netherlands",
    "BE": "Belgium",
    "PT": "Portugal",
    "GR": "Greece",
    "SCO": "Scotland",
    "BR": "Brazil",
    "AR": "Argentina",
    "KE": "Kenya",
    "GT": "Guatemala",
    "SK": "Slovakia",
    "PL": "Poland",
    "AUT": "Austria",
    "SWZ": "Switzerland",
    "DEN": "Denmark",
    "FUTBOL-GENEL": "International",
    "UEFA": "Europe",
}

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


def fetch_nesine_live_bulletin(
    timeout: float = 10.0,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    raise_on_error: bool = False,
) -> list[dict[str, Any]]:
    """Fetch all live football pre-match events and odds from Nesine public CDN.

    Hardened against network jitter: 10.0s socket timeout, exponential backoff retries,
    and SPEC-0012 diagnostic error reporting.
    """
    req = urllib.request.Request(
        NESINE_CDN_URL,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    last_error: Exception | None = None
    payload: dict[str, Any] | None = None

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise AdapterHTTPError(resp.status, f"Unexpected HTTP status {resp.status}", NESINE_CDN_URL)
                raw_bytes = resp.read()
                payload = json.loads(raw_bytes.decode("utf-8"))
                break
        except urllib.error.HTTPError as e:
            last_error = AdapterHTTPError(e.code, str(e.reason), NESINE_CDN_URL)
        except (TimeoutError, urllib.error.URLError) as e:
            is_timeout = isinstance(e, TimeoutError) or (
                hasattr(e, "reason") and ("timed out" in str(e.reason).lower() or isinstance(e.reason, TimeoutError))
            )
            if is_timeout:
                last_error = AdapterTimeoutError(f"Connection timed out after {timeout}s: {e}")
            else:
                last_error = AdapterError(f"Network URLError: {getattr(e, 'reason', e)}")
        except json.JSONDecodeError as e:
            last_error = AdapterPayloadError(f"Corrupted or invalid JSON payload: {e}")
        except Exception as e:
            last_error = AdapterError(f"Unexpected adapter error: {type(e).__name__}: {e}")

        if attempt < max_retries:
            delay = backoff_factor * (2 ** (attempt - 1))
            logger.warning(
                f"[SPEC-0012: AdapterRetry] Nesine CDN attempt {attempt}/{max_retries} failed: "
                f"{last_error}. Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)

    if payload is None:
        logger.error(
            f"[SPEC-0012: AdapterError] Nesine CDN bulletin fetch permanently failed after "
            f"{max_retries} attempts: {last_error}"
        )
        if raise_on_error and last_error:
            raise last_error
        return []

    ea_list = payload.get("sg", {}).get("EA", [])
    la_list = payload.get("sg", {}).get("LA", [])
    la_map = {item.get("LID"): item for item in la_list if isinstance(item, dict) and item.get("LID")}

    parsed_matches: list[dict[str, Any]] = []
    for item in ea_list:
        if item.get("TYPE") != 1 or not item.get("MA"):
            continue
        hn = item.get("HN", "")
        an = item.get("AN", "")
        if not hn or not an:
            continue

        lc_id = item.get("LC")
        league_meta = la_map.get(lc_id, {})
        league_name = league_meta.get("N") or "Nesine Canlı Bülten"
        raw_cc = league_meta.get("CC") or ""
        country_norm = COUNTRY_CODE_MAP.get(raw_cc, raw_cc.title() if raw_cc else "International")

        odds_1x2: tuple[float, float, float] | None = None
        odds_ou25: tuple[float, float] | None = None
        odds_dc: dict[str, float] = {}
        corners: dict[str, dict[str, float]] = {}
        combos: list[dict[str, Any]] = []
        scorers: list[dict[str, Any]] = []
        htft: dict[str, float] = {}
        tg6: float | None = None
        iy_kg_var: float | None = None
        scores: list[dict[str, Any]] = []
        mbs_val = item.get("EMBS") or 1

        htft_map = {
            1: "1/1", 2: "1/X", 3: "1/2",
            4: "X/1", 5: "X/X", 6: "X/2",
            7: "2/1", 8: "2/X", 9: "2/2",
        }

        ma_raw = item.get("MA")
        ma_list = ma_raw if isinstance(ma_raw, list) else []
        for mkt in ma_list:
            if not isinstance(mkt, dict):
                continue
            mtid = mkt.get("MTID")
            try:
                sov = float(mkt.get("SOV") or 0.0)
            except (ValueError, TypeError):
                sov = 0.0
            oca_raw = mkt.get("OCA")
            oca_list = oca_raw if isinstance(oca_raw, list) else []
            oca: dict[Any, float] = {}
            for o in oca_list:
                if isinstance(o, dict):
                    try:
                        n_val = o.get("N")
                        o_val = float(o.get("O") or 0.0)
                        if n_val is not None:
                            oca[n_val] = o_val
                    except (ValueError, TypeError):
                        pass
            if mtid == 1:
                o1, ox, o2 = oca.get(1, 0.0), oca.get(2, 0.0), oca.get(3, 0.0)
                if o1 > 1.01 and ox > 1.01 and o2 > 1.01:
                    odds_1x2 = (o1, ox, o2)
                    mbs_val = mkt.get("MBS") or mbs_val
            elif mtid == 3:
                # Nesine MTID=3 (Çifte Şans): N=1 -> 1X, N=2 -> 12, N=3 -> X2
                for n_idx, dc_key in ((1, "1X"), (2, "12"), (3, "X2")):
                    dc_val = float(oca.get(n_idx, 0.0) or 0.0)
                    if dc_val > 1.01:
                        odds_dc[dc_key] = dc_val
            elif mtid == 12 and abs(sov - 2.5) <= 1e-4:
                # In Nesine MTID=12 (SOV=2.5): N=1 is 2.5 Alt (Under), N=2 is 2.5 Üst (Over)
                o_under, o_over = oca.get(1, 0.0), oca.get(2, 0.0)
                if o_over > 1.01 and o_under > 1.01:
                    odds_ou25 = (o_over, o_under)
            elif mtid == 216:
                sov_norm = round(sov, 1)
                if sov_norm in (6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5):
                    u = float(oca.get(1, 0.0))
                    o = float(oca.get(2, 0.0))
                    if u > 1.01 and o > 1.01:
                        corners[f"{sov_norm}"] = {"under": u, "over": o}
            elif mtid in (885, 716):
                for oc in oca_list:
                    if isinstance(oc, dict):
                        nm = oc.get("ON")
                        try:
                            pr = float(oc.get("O") or 0.0)
                        except (ValueError, TypeError):
                            pr = 0.0
                        if nm and pr > 1.01:
                            combos.append({"name": nm, "odd": pr})
            elif mtid == 701:
                for oc in oca_list:
                    if isinstance(oc, dict):
                        pl = oc.get("ON")
                        try:
                            pr = float(oc.get("O") or 0.0)
                        except (ValueError, TypeError):
                            pr = 0.0
                        if pl and pr > 1.01:
                            scorers.append({"player": pl, "odd": pr})
            elif mtid == 5:
                for n_idx, lbl in htft_map.items():
                    val = oca.get(n_idx)
                    if val and val > 1.01:
                        htft[lbl] = val
            elif mtid == 43:
                val4 = oca.get(4)
                if val4 and val4 > 1.01:
                    tg6 = val4
            elif mtid == 225:
                val1 = oca.get(1)
                if val1 and val1 > 1.01:
                    iy_kg_var = val1
            elif mtid == 777:
                for oc in oca_list:
                    if isinstance(oc, dict):
                        nm = oc.get("ON")
                        try:
                            pr = float(oc.get("O") or 0.0)
                        except (ValueError, TypeError):
                            pr = 0.0
                        if nm and pr > 1.01:
                            scores.append({"score": nm, "odd": pr})

        if odds_1x2 or odds_ou25 or odds_dc or corners or combos or scorers or htft:
            scorers.sort(key=lambda x: x["odd"])
            combos.sort(key=lambda x: x["odd"])
            scores.sort(key=lambda x: x["odd"])
            parsed_matches.append({
                "nesine_code": item.get("C"),
                "home": hn,
                "away": an,
                "league": league_name,
                "country": country_norm,
                "date_str": item.get("D", ""),
                "time_str": item.get("T", ""),
                "mbs": mbs_val,
                "nesine_1x2": odds_1x2,
                "nesine_ou25": odds_ou25,
                "nesine_dc": odds_dc if odds_dc else None,
                "nesine_corners": corners if corners else None,
                "nesine_combos": combos[:4] if combos else None,
                "nesine_scorers": scorers[:4] if scorers else None,
                "nesine_htft": htft if htft else None,
                "nesine_tg6": tg6,
                "nesine_iy_kg_var": iy_kg_var,
                "nesine_scores": scores[:3] if scores else None,
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


def _get_json(
    url: str,
    headers: dict[str, str],
    params: dict[str, str],
    timeout: float = 10.0,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
) -> Any:
    """Fetch and parse JSON from external REST API with retry, backoff, and diagnostics."""
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}" if query else url
    req = urllib.request.Request(full_url, headers=headers)
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise AdapterHTTPError(resp.status, f"HTTP status {resp.status}", full_url)
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_error = AdapterHTTPError(e.code, str(e.reason), full_url)
            if e.code == 404:
                # 404 indicates league currently has no active fixtures; fail fast without retrying
                break
            if e.code == 429:
                # 429 Too Many Requests: use adaptive backoff to prevent throttling
                retry_after = e.headers.get("Retry-After") if hasattr(e, "headers") else None
                try:
                    retry_sec = float(retry_after) if retry_after else None
                except (ValueError, TypeError):
                    retry_sec = None
                if retry_sec is not None and retry_sec > 0:
                    delay = retry_sec
                else:
                    delay = max(backoff_factor * (2 ** (attempt - 1)), 2.5 * attempt)
                if attempt < max_retries:
                    logger.warning(
                        f"[SPEC-0012: AdapterRateLimit] 429 Too Many Requests on {full_url}. "
                        f"Backing off for {delay:.1f}s (attempt {attempt}/{max_retries})..."
                    )
                    time.sleep(delay)
                    continue
        except (TimeoutError, urllib.error.URLError) as e:
            is_timeout = isinstance(e, TimeoutError) or (
                hasattr(e, "reason") and ("timed out" in str(e.reason).lower() or isinstance(e.reason, TimeoutError))
            )
            if is_timeout:
                last_error = AdapterTimeoutError(f"Timeout after {timeout}s on {full_url}: {e}")
            else:
                last_error = AdapterError(f"URLError on {full_url}: {getattr(e, 'reason', e)}")
        except json.JSONDecodeError as e:
            last_error = AdapterPayloadError(f"Invalid JSON from {full_url}: {e}")
        except Exception as e:
            last_error = AdapterError(f"Unexpected error querying {full_url}: {type(e).__name__}: {e}")

        if attempt < max_retries:
            delay = backoff_factor * (2 ** (attempt - 1))
            logger.warning(
                f"[SPEC-0012: AdapterRetry] Request to {full_url} attempt {attempt}/{max_retries} failed: "
                f"{last_error}. Retrying in {delay:.1f}s..."
            )
            time.sleep(delay)

    logger.warning(
        f"[SPEC-0012: AdapterError] Request to {full_url} failed after {max_retries} attempts: {last_error}"
    )
    return None


def fetch_and_scan_live_propline(
    output_path: Path | None = None,
    settle_espn: bool = True,
    throttle_sec: float = 0.4,
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

    try:
        from sharp_feed_manager import DualFeedSharpManager
        feed_mgr = DualFeedSharpManager()
    except Exception:
        feed_mgr = None

    all_signals: list[dict[str, Any]] = []
    scanned_matches: list[dict[str, Any]] = []
    latest_fair_lookup: dict[tuple[str, str, str], float] = {}
    nesine_matched_count = 0

    global _PROPLINE_CIRCUIT_BREAKER_UNTIL
    if time.time() < _PROPLINE_CIRCUIT_BREAKER_UNTIL:
        cooldown_rem = int(_PROPLINE_CIRCUIT_BREAKER_UNTIL - time.time())
        logger.info(
            f"[SPEC-0012: CircuitBreaker Active] api.prop-line.com in cooldown ({cooldown_rem}s remaining). "
            f"Bypassing PropLine network calls; engaging DualFeed / cache fallback."
        )
        if feed_mgr:
            feed_mgr.engage_fallback()
    else:
        consecutive_propline_failures = 0
        for sport_key, (league_label, tier_tag) in TARGET_LEAGUES.items():
            if consecutive_propline_failures >= 2:
                _PROPLINE_CIRCUIT_BREAKER_UNTIL = time.time() + 900.0
                logger.warning(
                    f"[SPEC-0012: CircuitBreaker] api.prop-line.com failed on {consecutive_propline_failures} "
                    f"consecutive leagues; tripping circuit breaker for 15m. Engaging DualFeed / fallback."
                )
                if feed_mgr:
                    feed_mgr.engage_fallback()
                break
            if throttle_sec > 0:
                time.sleep(throttle_sec)
            url = f"https://api.prop-line.com/v1/sports/{sport_key}/odds"
            try:
                payload = _get_json(
                    url,
                    headers=headers,
                    params={"regions": "eu,us", "markets": "h2h,totals"},
                    timeout=3.0,
                    max_retries=1,
                )
            except Exception as e:
                logger.warning(f"Error scanning league {sport_key} ({league_label}): {e}")
                consecutive_propline_failures += 1
                if feed_mgr:
                    feed_mgr.report_propline_failure()
                continue

            if payload is None:
                consecutive_propline_failures += 1
                if feed_mgr:
                    feed_mgr.report_propline_failure()
                continue
            consecutive_propline_failures = 0
            if not payload:
                continue
            events = payload if isinstance(payload, list) else payload.get("events", [])
            for ev in events:
                home = ev.get("home_team", "")
                away = ev.get("away_team", "")
                kickoff = ev.get("commence_time", "")
                if not is_kickoff_in_future(kickoff):
                    continue
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
                    "nesine_corners": nesine_match.get("nesine_corners") if nesine_match else None,
                    "nesine_combos": nesine_match.get("nesine_combos") if nesine_match else None,
                    "nesine_scorers": nesine_match.get("nesine_scorers") if nesine_match else None,
                    "nesine_htft": nesine_match.get("nesine_htft") if nesine_match else None,
                    "nesine_tg6": nesine_match.get("nesine_tg6") if nesine_match else None,
                    "nesine_iy_kg_var": nesine_match.get("nesine_iy_kg_var") if nesine_match else None,
                    "nesine_scores": nesine_match.get("nesine_scores") if nesine_match else None,
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
                        if s.soft_odds > s.sharp_odds * 1.25 or not (1.45 <= s.soft_odds <= 6.50):
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

    def _append_nesine_fallback_signals(
        s_ev_id: str,
        s_league: str,
        s_home: str,
        s_away: str,
        s_kickoff: str,
        s_tier: str,
        s_sharp_1x2: Any,
        s_soft_1x2: Any,
        s_sharp_ou25: Any,
        s_soft_ou25: Any,
        s_open_1x2: Any = None,
        s_open_ou25: Any = None,
        s_nesine_meta: dict[str, Any] | None = None,
        s_provider: str | None = None,
    ) -> None:
        if not s_soft_1x2 and not s_soft_ou25:
            return
        sigs = scan_stale_lines(
            [
                {
                    "match_id": f"{s_ev_id}_nesine",
                    "league": s_league,
                    "home": s_home,
                    "away": s_away,
                    "sharp_timestamp": captured_ts,
                    "soft_timestamp": captured_ts,
                    "sharp_open_1x2": s_open_1x2,
                    "sharp_1x2": list(s_sharp_1x2) if s_sharp_1x2 else None,
                    "soft_1x2": s_soft_1x2,
                    "sharp_open_ou25": s_open_ou25,
                    "sharp_ou25": list(s_sharp_ou25) if s_sharp_ou25 else None,
                    "soft_ou25": s_soft_ou25,
                }
            ],
            devig_method="shin",
            min_edge=0.02,
        )
        for s in sigs:
            if s.soft_odds > s.sharp_odds * 1.25 or not (1.45 <= s.soft_odds <= 6.50):
                continue
            d = asdict(s)
            d["event_id"] = s_ev_id
            d["kickoff"] = s_kickoff
            d["soft_book"] = "nesine"
            d["tier"] = s_tier
            d["is_steam_confirmed"] = False
            if s_nesine_meta:
                d["nesine_code"] = s_nesine_meta.get("nesine_code")
                d["mbs"] = s_nesine_meta.get("mbs")
            if s_provider:
                d["sharp_provider"] = s_provider
            all_signals.append(d)

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
        if not is_kickoff_in_future(kickoff):
            continue
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
            "nesine_corners": nesine_match.get("nesine_corners") if nesine_match else None,
            "nesine_combos": nesine_match.get("nesine_combos") if nesine_match else None,
            "nesine_scorers": nesine_match.get("nesine_scorers") if nesine_match else None,
            "nesine_htft": nesine_match.get("nesine_htft") if nesine_match else None,
            "nesine_tg6": nesine_match.get("nesine_tg6") if nesine_match else None,
            "nesine_iy_kg_var": nesine_match.get("nesine_iy_kg_var") if nesine_match else None,
            "nesine_scores": nesine_match.get("nesine_scores") if nesine_match else None,
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

        _append_nesine_fallback_signals(
            ev_id,
            f"{league_label} [NESİNE]",
            home,
            away,
            kickoff,
            tier_tag,
            pin_1x2,
            nesine_1x2,
            pin_ou25,
            nesine_ou25,
            s_open_1x2=rec.get("open_1x2"),
            s_open_ou25=rec.get("open_ou25"),
            s_nesine_meta=nesine_match,
        )

    # Secondary Feed Fallback: ESPN / DraftKings sharp consensus (also covers international breaks)
    intl_fallback_leagues = {
        "soccer_uefa_nations_league": ("UEFA Uluslar Ligi (UNL)", "CUP"),
        "soccer_fifa_friendlies": ("FIFA Hazırlık Maçları (INT)", "CUP"),
        "soccer_fifa_world_cup_qualifiers_europe": ("UEFA Dünya Kupası Elemeleri", "CUP"),
        "soccer_conmebol_world_cup_qualifiers": ("CONMEBOL Dünya Kupası Elemeleri", "CUP"),
    }
    fallback_league_pool = (
        {**TARGET_LEAGUES, **intl_fallback_leagues}
        if (feed_mgr and not feed_mgr.propline_active)
        else (intl_fallback_leagues if (feed_mgr and nesine_matched_count == 0) else {})
    )
    if fallback_league_pool:
        logger.info("[DualFeed] Scanning secondary feeds (ESPN DraftKings + Bzzoiro Global)...")
        seen_nesine_codes = {
            m.get("nesine_code") for m in scanned_matches if m.get("nesine_code") is not None
        }

        def _ingest_fallback_events(
            events_list: list[dict[str, Any]],
            default_league: str,
            default_tier: str,
            sport_key_tag: str,
            source_tag: str,
            default_provider: str,
        ) -> None:
            nonlocal nesine_matched_count
            for eo in events_list:
                h = eo.get("home", "")
                a = eo.get("away", "")
                cur_1x2 = eo.get("current_1x2")
                cur_ou = eo.get("current_ou25")
                ko_iso = eo.get("kickoff", "")
                if not cur_1x2 or not is_kickoff_in_future(ko_iso):
                    continue
                ev_id = eo.get("event_id", f"{source_tag.lower()}_{h}_{a}")
                if ev_id in seen_ids:
                    continue

                nes_m = match_nesine_fixture(h, a, nesine_bulletin)
                n_code = nes_m.get("nesine_code") if nes_m else None
                if n_code is not None and n_code in seen_nesine_codes:
                    continue
                nes_1x2 = nes_m["nesine_1x2"] if nes_m else None
                nes_ou25 = nes_m["nesine_ou25"] if nes_m else None
                if nes_m:
                    nesine_matched_count += 1
                    if n_code is not None:
                        seen_nesine_codes.add(n_code)

                l_lbl = eo.get("league") or default_league
                shin_p = devig_shin(cur_1x2)
                pow_p = devig_power(cur_1x2)
                shin_ou_p = devig_shin(cur_ou) if cur_ou else None
                nesine_edges_1x2 = (
                    [round(((shin_p[i] * nes_1x2[i]) - 1.0) * 100.0, 2) for i in range(3)]
                    if nes_1x2
                    else None
                )
                nesine_edges_ou25 = (
                    [round(((shin_ou_p[i] * nes_ou25[i]) - 1.0) * 100.0, 2) for i in range(2)]
                    if (nes_ou25 and shin_ou_p)
                    else None
                )

                scanned_matches.append({
                    "event_id": ev_id,
                    "sport_key": sport_key_tag,
                    "league": f"{l_lbl} [{source_tag}]",
                    "tier": default_tier,
                    "home": h,
                    "away": a,
                    "kickoff": ko_iso,
                    "pinnacle_open_1x2": eo.get("open_1x2"),
                    "pinnacle_1x2": list(cur_1x2),
                    "pinnacle_ou25": list(cur_ou) if cur_ou else None,
                    "nesine_code": n_code,
                    "nesine_mbs": nes_m["mbs"] if nes_m else None,
                    "nesine_1x2": list(nes_1x2) if nes_1x2 else None,
                    "nesine_ou25": list(nes_ou25) if nes_ou25 else None,
                    "nesine_corners": nes_m.get("nesine_corners") if nes_m else None,
                    "shin_probs_1x2": [round(p, 4) for p in shin_p],
                    "shin_probs_ou25": [round(p, 4) for p in shin_ou_p] if shin_ou_p else None,
                    "shin_fair_1x2": [round(1.0 / p, 2) for p in shin_p],
                    "shin_fair_ou25": [round(1.0 / p, 2) for p in shin_ou_p] if shin_ou_p else None,
                    "power_fair_1x2": [round(1.0 / p, 2) for p in pow_p],
                    "nesine_edges_1x2": nesine_edges_1x2,
                    "nesine_edges_ou25": nesine_edges_ou25,
                    "snapshots_count": 1,
                    "draw_steam_drift_pp": 0.0,
                    "draw_steam_confirmed": False,
                    "under_steam_drift_pp": 0.0,
                    "under_steam_confirmed": False,
                })
                seen_ids.add(ev_id)

                _append_nesine_fallback_signals(
                    ev_id,
                    f"{l_lbl} [{source_tag}/NESİNE]",
                    h,
                    a,
                    ko_iso,
                    default_tier,
                    cur_1x2,
                    nes_1x2,
                    cur_ou,
                    nes_ou25,
                    s_open_1x2=eo.get("open_1x2"),
                    s_open_ou25=eo.get("open_ou25"),
                    s_nesine_meta=nes_m,
                    s_provider=eo.get("provider", default_provider),
                )

        for skey, (llabel, ttag) in fallback_league_pool.items():
            espn_odds = feed_mgr.get_fallback_odds_for_league(skey)
            _ingest_fallback_events(
                espn_odds,
                llabel,
                ttag,
                f"fallback_{skey}",
                "ESPN",
                "ESPN_DraftKings",
            )

        if feed_mgr and not feed_mgr.propline_active:
            bzz_odds = feed_mgr.get_bzzoiro_fallback_odds()
            _ingest_fallback_events(
                bzz_odds,
                "Bzzoiro Global",
                "CUP",
                "fallback_bzzoiro",
                "BZZOIRO",
                "Bzzoiro_Consensus",
            )

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
    atomic_write_json(output_path, result)
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
