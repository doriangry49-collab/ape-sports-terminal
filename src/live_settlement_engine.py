"""Live Match Score Settlement & Bankroll Accounting Engine (v1.0).

Continuously tracks active tickets in `output/active_coupons.json`, polls official
ESPN scoreboard feeds for match conclusions, evaluates 1X2, Over/Under, TG 6+ and HT/FT
outcomes, calculates system and accumulator payouts, updates `output/active_bankroll.json`,
and delivers instant settlement alerts to Telegram.
"""

from __future__ import annotations

import difflib
import itertools
import json
import logging
import math
import re
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from atomic_io import atomic_write_json
except ImportError:
    from src.atomic_io import atomic_write_json

ROOT_DIR = Path(__file__).resolve().parent.parent
COUPONS_FILE = ROOT_DIR / "output" / "active_coupons.json"
BANKROLL_FILE = ROOT_DIR / "output" / "active_bankroll.json"

logger = logging.getLogger("SettlementEngine")

ESPN_LEAGUE_MAP = {
    "ucl": "uefa.champions",
    "uel": "uefa.europa",
    "uecl": "uefa.europa.conf",
    "champions": "uefa.champions",
    "europa": "uefa.europa",
}


def normalize_espn_league(league_key: str) -> str:
    lk = league_key.lower().strip()
    return ESPN_LEAGUE_MAP.get(lk, lk)


try:
    from telegram_notifier import send_telegram_message
except ImportError:
    try:
        from src.telegram_notifier import send_telegram_message
    except ImportError:
        def send_telegram_message(*args, **kwargs):
            return False


def load_active_coupons() -> list[dict[str, Any]]:
    """Load active tickets from disk."""
    if COUPONS_FILE.exists():
        try:
            return json.loads(COUPONS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load {COUPONS_FILE}: {e}")
    return []


def validate_coupon_constraints(
    coupon: dict[str, Any],
    existing_coupons: list[dict[str, Any]] | None = None,
) -> None:
    """Enforce SPEC-0015 minimum stake (>= 50.0 TL) and single-match exposure cap (max 1 active coupon per match)."""
    stake = float(coupon.get("stake", 0.0) or 0.0)
    if stake < 50.0:
        raise ValueError(f"SPEC-0015 violation: Minimum coupon stake is 50.0 TL (got {stake:.2f} TL).")

    if existing_coupons:
        active_matches: set[str] = set()
        for c in existing_coupons:
            if c.get("id") == coupon.get("id"):
                continue
            if c.get("status") in ("PENDING", "IN_PLAY"):
                for p in c.get("picks", []):
                    h = str(p.get("home") or "").lower().strip()
                    a = str(p.get("away") or "").lower().strip()
                    m_str = str(p.get("match") or f"{h} vs {a}").lower().strip()
                    key = f"{h}_{a}" if (h and a) else m_str
                    if key:
                        active_matches.add(key)

        for p in coupon.get("picks", []):
            h = str(p.get("home") or "").lower().strip()
            a = str(p.get("away") or "").lower().strip()
            m_str = str(p.get("match") or f"{h} vs {a}").lower().strip()
            key = f"{h}_{a}" if (h and a) else m_str
            if key and key in active_matches:
                raise ValueError(
                    f"Exposure cap violation: Match '{key}' already has an active coupon tonight (max 1 coupon per match)."
                )


def save_active_coupons(coupons: list[dict[str, Any]], enforce_constraints: bool = False) -> None:
    """Save active tickets to disk atomically."""
    if enforce_constraints:
        seen: list[dict[str, Any]] = []
        for c in coupons:
            if c.get("status") in ("PENDING", "IN_PLAY"):
                validate_coupon_constraints(c, seen)
                seen.append(c)
    atomic_write_json(COUPONS_FILE, coupons)


def load_bankroll() -> dict[str, Any]:
    """Load bankroll ledger."""
    if BANKROLL_FILE.exists():
        try:
            return json.loads(BANKROLL_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to load {BANKROLL_FILE}: {e}")
    return {
        "currency": "TL",
        "initial_bankroll": 150.0,
        "total_staked": 150.0,
        "cash_balance": 0.0,
        "realized_pnl": 0.0,
        "total_portfolio_value": 150.0,
        "active_tickets_count": 3,
        "settled_tickets_count": 0,
        "status": "ALL_IN_PLAY",
    }


def save_bankroll(bankroll: dict[str, Any]) -> None:
    """Save bankroll ledger atomically."""
    atomic_write_json(BANKROLL_FILE, bankroll)


def _extract_score_val(val: Any) -> int | None:
    """Safely convert score representation to int."""
    if val is None:
        return None
    try:
        return int(round(float(val)))
    except (ValueError, TypeError):
        return None


def _extract_ht_score(comp: dict[str, Any], is_ht_or_later: bool) -> int | None:
    """Extract half-time (period 1) score from competitor linescores if reached."""
    if not is_ht_or_later:
        return None
    linescores = comp.get("linescores")
    if isinstance(linescores, list):
        for ls in linescores:
            if isinstance(ls, dict) and ls.get("period") == 1:
                val = _extract_score_val(ls.get("value"))
                if val is not None:
                    return val
                val = _extract_score_val(ls.get("displayValue"))
                if val is not None:
                    return val
        if linescores and isinstance(linescores[0], dict):
            val = _extract_score_val(linescores[0].get("value"))
            if val is not None:
                return val
            val = _extract_score_val(linescores[0].get("displayValue"))
            if val is not None:
                return val
    return None


def fetch_espn_event_stats(event_id: str, espn_league: str) -> dict[str, int | None]:
    """Fetch corners and cards for an event from ESPN summary boxscore (Fail-Closed per SPEC-0012)."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{espn_league}/summary?event={event_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    res: dict[str, int | None] = {"corners": None, "cards": None}
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            boxscore = data.get("boxscore", {})
            teams = boxscore.get("teams", [])
            if not teams:
                return res
            tot_corners = 0
            tot_cards = 0
            found_corners = False
            found_cards = False
            for t in teams:
                for s in t.get("statistics", []):
                    name = s.get("name")
                    val = s.get("displayValue")
                    if val is None:
                        continue
                    if name == "wonCorners":
                        try:
                            tot_corners += int(float(val))
                            found_corners = True
                        except (ValueError, TypeError):
                            pass
                    elif name in ("yellowCards", "redCards"):
                        try:
                            tot_cards += int(float(val))
                            found_cards = True
                        except (ValueError, TypeError):
                            pass
            if found_corners:
                res["corners"] = tot_corners
            if found_cards:
                res["cards"] = tot_cards
    except Exception as e:
        logger.debug(f"Failed to fetch event stats for {event_id}: {e}")
    return res


def fetch_espn_scores(league_key: str, date_str: str | None = None) -> list[dict[str, Any]]:
    """Fetch live and completed match scores from ESPN API."""
    espn_league = normalize_espn_league(league_key)

    if date_str:
        dates_to_query = [date_str]
    else:
        today_str = datetime.now(UTC).strftime("%Y%m%d")
        yesterday_str = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y%m%d")
        dates_to_query = [today_str, yesterday_str]

    matches = []
    seen_keys = set()

    for d in dates_to_query:
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{espn_league}/scoreboard?dates={d}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for ev in data.get("events", []):
                    ev_id = str(ev.get("id", ""))
                    name = ev.get("name", "")
                    comps = ev.get("competitions", [{}])[0].get("competitors", [])
                    if len(comps) != 2:
                        continue

                    # Defensively map competitors by homeAway role (do NOT assume comps[0] is home)
                    teams = {c.get("homeAway"): c for c in comps}
                    if "home" not in teams or "away" not in teams:
                        home_comp = comps[0]
                        away_comp = comps[1]
                    else:
                        home_comp = teams["home"]
                        away_comp = teams["away"]

                    home_team = (
                        home_comp.get("team", {}).get("name", "")
                        or home_comp.get("team", {}).get("displayName", "")
                    )
                    away_team = (
                        away_comp.get("team", {}).get("name", "")
                        or away_comp.get("team", {}).get("displayName", "")
                    )

                    dedup_key = ev_id if ev_id else f"{home_team}_{away_team}"
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)

                    status_obj = ev.get("status", {})
                    status_desc = status_obj.get("type", {}).get("description", "")
                    period = status_obj.get("period", 0)

                    is_completed = status_desc in ("Full Time", "Final", "FT", "AET", "Penalties")
                    is_in_progress = "Half" in status_desc or "Progress" in status_desc
                    is_ht_or_later = is_completed or period >= 2 or "Half" in status_desc or status_desc in ("HT", "Halftime")

                    hg = _extract_score_val(home_comp.get("score")) or 0
                    ag = _extract_score_val(away_comp.get("score")) or 0

                    ht_hg = _extract_ht_score(home_comp, is_ht_or_later)
                    ht_ag = _extract_ht_score(away_comp, is_ht_or_later)

                    matches.append({
                        "event_id": ev_id,
                        "name": name,
                        "league": espn_league,
                        "home": home_team,
                        "away": away_team,
                        "hg": hg,
                        "ag": ag,
                        "ht_hg": ht_hg,
                        "ht_ag": ht_ag,
                        "status": status_desc,
                        "is_completed": is_completed,
                        "is_in_progress": is_in_progress,
                    })
        except Exception as e:
            logger.debug(f"ESPN fetch error for {espn_league} on {d}: {e}")

    return matches


def evaluate_pick_result(
    market: str,
    selection: str,
    hg: int,
    ag: int,
    ht_hg: int | None = None,
    ht_ag: int | None = None,
    corners: int | None = None,
    cards: int | None = None,
) -> bool:
    """Evaluate whether a pick won given the final (and half-time) score, corners, and cards."""
    m_upper = market.upper().strip()
    sel_upper = selection.upper().strip()

    # 1. Full Time 1X2
    if "1X2" in m_upper and "HT" not in m_upper and "IY" not in m_upper:
        if sel_upper in ("MS 1", "MS1", "1", "HOME"):
            return hg > ag
        if sel_upper in ("MS X", "MSX", "X", "DRAW"):
            return hg == ag
        if sel_upper in ("MS 2", "MS2", "2", "AWAY"):
            return ag > hg

    # 2. Total Goals 6+
    if "TG_6+" in m_upper or "6+" in sel_upper or "TG 6+" in sel_upper:
        return (hg + ag) >= 6

    # 3. 2.5 Over / Under
    if "2.5" in m_upper or "2.5" in sel_upper:
        if any(w in sel_upper for w in ("ÜST", "UST", "OVER", ">")):
            return (hg + ag) > 2.5
        if any(w in sel_upper for w in ("ALT", "UNDER", "<")):
            return (hg + ag) < 2.5

    # 4. Half Time / Full Time (HT/FT)
    if "HT_FT" in m_upper or "/" in selection or "İY/MS" in m_upper:
        if ht_hg is None or ht_ag is None:
            return False
        ht_res = "1" if ht_hg > ht_ag else ("2" if ht_ag > ht_hg else "X")
        ft_res = "1" if hg > ag else ("2" if ag > hg else "X")
        actual_htft = f"{ht_res}/{ft_res}"

        # Extract e.g. "X/1" or "2/2" from strings like "X/2 (İY 0 / MS 2)"
        match = re.search(r"([1X2]/[1X2])", sel_upper)
        if match:
            return actual_htft == match.group(1)
        return actual_htft == sel_upper

    # 5. Half Time 1X2 (Pure HT)
    if any(k in m_upper for k in ("HT_1X2", "IY_1X2", "H1_1X2")) or ("1X2" in m_upper and "HT" in m_upper):
        if ht_hg is None or ht_ag is None:
            return False
        if sel_upper in ("1", "MS 1", "IY 1", "HT 1", "HOME"):
            return ht_hg > ht_ag
        if sel_upper in ("X", "MS X", "IY X", "HT X", "DRAW"):
            return ht_hg == ht_ag
        if sel_upper in ("2", "MS 2", "IY 2", "HT 2", "AWAY"):
            return ht_ag > ht_hg

    # 6. Both Teams to Score (BTTS / KG)
    if "BTTS" in m_upper or "KG" in m_upper:
        if "FIRST_HALF" in m_upper or "İY" in m_upper:
            if ht_hg is None or ht_ag is None:
                return False
            actual_btts = (ht_hg >= 1) and (ht_ag >= 1)
        else:
            actual_btts = (hg >= 1) and (ag >= 1)
        if any(w in sel_upper for w in ("VAR", "YES", "EVET")):
            return actual_btts
        if any(w in sel_upper for w in ("YOK", "NO", "HAYIR")):
            return not actual_btts

    # 7. Total Corners
    if any(k in m_upper for k in ("CORNER", "KORNER")) or "KORNER" in sel_upper:
        if corners is None:
            return False
        line_match = re.search(r"(\d+\.?\d*)", sel_upper)
        line = float(line_match.group(1)) if line_match else 9.5
        if any(w in sel_upper for w in ("ALT", "UNDER", "<")):
            return corners < line
        if any(w in sel_upper for w in ("ÜST", "UST", "OVER", ">")):
            return corners > line
        return False

    # 8. Total Cards
    if any(k in m_upper for k in ("CARD", "KART")) or "KART" in sel_upper:
        if cards is None:
            return False
        line_match = re.search(r"(\d+\.?\d*)", sel_upper)
        line = float(line_match.group(1)) if line_match else 4.5
        if any(w in sel_upper for w in ("ALT", "UNDER", "<")):
            return cards < line
        if any(w in sel_upper for w in ("ÜST", "UST", "OVER", ">")):
            return cards > line
        return False

    return False


def calculate_system_payout(won_picks: list[dict[str, Any]], k_combos: tuple[int, ...], misli: float) -> float:
    """Calculate system parlay payout using combinatorial summation."""
    payout = 0.0
    for k in k_combos:
        if len(won_picks) >= k:
            for combo in itertools.combinations(won_picks, k):
                payout += math.prod(float(p["odds"]) for p in combo) * misli
    return round(payout, 2)


def run_settlement_cycle() -> dict[str, Any]:
    """Execute a single settlement inspection cycle across active tickets."""
    coupons = load_active_coupons()
    if not coupons:
        return {"settled": 0, "message": "No active coupons"}

    # Target leagues for tonight's games
    needed_leagues = {p.get("league_key", "fra.1") for c in coupons for p in c.get("picks", [])}
    live_scores: dict[str, dict[str, Any]] = {}

    for l_key in needed_leagues:
        matches = fetch_espn_scores(l_key)
        for m in matches:
            live_scores[f"{m['home']}_{m['away']}"] = m

    settled_coupons_count = 0
    total_new_winnings = 0.0

    for c in coupons:
        if c.get("status") not in ("PENDING", "IN_PLAY"):
            continue

        all_picks_completed = True
        picks = c.get("picks", [])

        for p in picks:
            # Match pick to ESPN match
            best_m = None
            best_sim = 0.0
            p_home = p.get("home", "").lower()
            p_away = p.get("away", "").lower()

            for _key, m in live_scores.items():
                m_h = m["home"].lower()
                m_a = m["away"].lower()
                sim_h = difflib.SequenceMatcher(None, p_home, m_h).ratio()
                sim_a = difflib.SequenceMatcher(None, p_away, m_a).ratio()
                if min(sim_h, sim_a) < 0.65:
                    continue
                avg_sim = (sim_h + sim_a) / 2.0
                if avg_sim > best_sim and avg_sim >= 0.65:
                    best_sim = avg_sim
                    best_m = m

            if best_m:
                if best_m["is_completed"]:
                    hg = best_m["hg"]
                    ag = best_m["ag"]
                    ht_hg = best_m.get("ht_hg")
                    ht_ag = best_m.get("ht_ag")
                    corners = best_m.get("corners")
                    cards = best_m.get("cards")

                    # If pick needs corners or cards and not yet in best_m, fetch from ESPN summary
                    p_mkt = p.get("market", "").upper()
                    p_sel = p.get("selection", "").upper()
                    needs_corners = any(k in p_mkt or k in p_sel for k in ("CORNER", "KORNER"))
                    needs_cards = any(k in p_mkt or k in p_sel for k in ("CARD", "KART"))
                    needs_ht = (
                        any(k in p_mkt or k in p_sel for k in ("HT_FT", "İY/MS", "HT_1X2", "IY_1X2", "H1_1X2", "FIRST_HALF"))
                        or "/" in p.get("selection", "")
                    )

                    if (needs_corners and corners is None) or (needs_cards and cards is None):
                        ev_id = best_m.get("event_id")
                        if ev_id:
                            stats = fetch_espn_event_stats(ev_id, best_m.get("league", "uefa.champions"))
                            corners = stats.get("corners")
                            cards = stats.get("cards")
                            best_m["corners"] = corners
                            best_m["cards"] = cards

                    # SPEC-0012 Fail-Closed: if required stats (corners, cards, or HT scores) are missing, keep PENDING
                    if (
                        (needs_corners and corners is None)
                        or (needs_cards and cards is None)
                        or (needs_ht and (ht_hg is None or ht_ag is None))
                    ):
                        all_picks_completed = False
                        p["status"] = "PENDING"
                        p["score"] = f"{hg}-{ag}"
                    else:
                        won = evaluate_pick_result(p["market"], p["selection"], hg, ag, ht_hg, ht_ag, corners=corners, cards=cards)
                        p["status"] = "WON" if won else "LOST"
                        score_str = f"{hg}-{ag}"
                        if ht_hg is not None and ht_ag is not None:
                            score_str += f" (HT {ht_hg}-{ht_ag})"
                        if corners is not None and needs_corners:
                            score_str += f" [Korner: {corners}]"
                        if cards is not None and needs_cards:
                            score_str += f" [Kart: {cards}]"
                        p["score"] = score_str
                else:
                    all_picks_completed = False
                    p["status"] = "IN_PLAY" if best_m["is_in_progress"] else "PENDING"
                    p["score"] = f"{best_m['hg']}-{best_m['ag']}"
            else:
                all_picks_completed = False

        # Evaluate coupon status if all picks concluded
        if all_picks_completed and all(p.get("status") in ("WON", "LOST") for p in picks):
            c_type = c.get("type", "ACCUMULATOR")
            payout = 0.0

            if c_type == "SINGLE":
                if all(p["status"] == "WON" for p in picks):
                    c["status"] = "WON"
                    calc_ret = float(picks[0].get("odds", 1.0)) * float(c.get("stake", 0.0))
                    payout = round(float(c.get("potential_return", calc_ret)), 2)
                else:
                    c["status"] = "LOST"
                    payout = 0.0

            elif c_type == "ACCUMULATOR":
                if all(p["status"] == "WON" for p in picks):
                    c["status"] = "WON"
                    calc_ret = math.prod(float(p["odds"]) for p in picks) * float(c.get("stake", 0.0))
                    payout = round(float(c.get("potential_return", calc_ret)), 2)
                else:
                    c["status"] = "LOST"
                    payout = 0.0

            elif c_type == "SYSTEM_1_2_3":
                misli = float(c.get("misli", 8))
                won_picks = [p for p in picks if p["status"] == "WON"]
                payout = calculate_system_payout(won_picks, (1, 2, 3), misli)
                c["status"] = "WON" if payout > 0 else "LOST"

            elif c_type == "SYSTEM_2_3":
                misli = float(c.get("misli", 11))
                won_picks = [p for p in picks if p["status"] == "WON"]
                payout = calculate_system_payout(won_picks, (2, 3), misli)
                c["status"] = "WON" if payout > 0 else "LOST"

            elif c_type.startswith("SYSTEM_"):
                # General fallback for any SYSTEM_X_Y
                parts = c_type.split("_")[1:]
                k_combos = tuple(int(x) for x in parts if x.isdigit())
                misli = float(c.get("misli", 1.0))
                won_picks = [p for p in picks if p["status"] == "WON"]
                payout = calculate_system_payout(won_picks, k_combos, misli)
                c["status"] = "WON" if payout > 0 else "LOST"

            c["payout"] = payout
            settled_coupons_count += 1
            total_new_winnings += payout

            # Dispatch Telegram Notification for settled coupon
            badge = "🏆 *[KUPON KAZANDI!]*" if payout > 0 else "❌ *[KUPON KAYBETTİ]*"
            msg = (
                f"{badge}\n"
                f"🎫 *{c['name']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )
            for p in picks:
                icon = "✅" if p['status'] == "WON" else "❌"
                msg += f"{icon} *{p['match']}*: {p['selection']} (Skor: {p.get('score', '-')})\n"

            net_pnl = payout - float(c.get("stake", 0.0))
            msg += "━━━━━━━━━━━━━━━━━━━━\n"
            msg += f"💵 *Kupon Tutarı:* `{c.get('stake', 0.0):.2f} TL`\n"
            msg += f"💰 *Kazanılan Tutar:* `{payout:.2f} TL` (Net: `+{net_pnl:.2f} TL`)\n"
            send_telegram_message(msg)

    if settled_coupons_count > 0:
        save_active_coupons(coupons)

        # Update bankroll ledger
        bankroll = load_bankroll()
        active_coupons = [c for c in coupons if c.get("status") in ("PENDING", "IN_PLAY")]
        settled_coupons = [c for c in coupons if c.get("status") in ("WON", "LOST")]

        # 1. Update cash balance with new winnings
        bankroll["cash_balance"] = round(float(bankroll.get("cash_balance", 0.0)) + total_new_winnings, 2)

        # 2. Synchronize active and settled coupon counts
        bankroll["active_tickets_count"] = len(active_coupons)
        bankroll["settled_tickets_count"] = len(settled_coupons)

        # 3. Total portfolio value = cash + active stakes currently in play
        active_stakes_in_play = sum(float(c.get("stake", 0.0)) for c in active_coupons)
        bankroll["total_portfolio_value"] = round(bankroll["cash_balance"] + active_stakes_in_play, 2)

        # 4. Realized PnL = total payouts won from settled coupons - total stakes of settled coupons
        total_settled_stakes = sum(float(c.get("stake", 0.0)) for c in settled_coupons)
        total_payouts_won = sum(float(c.get("payout", 0.0)) for c in settled_coupons)
        bankroll["realized_pnl"] = round(total_payouts_won - total_settled_stakes, 2)

        # 5. Ledger status and TRT timestamp
        if not active_coupons:
            bankroll["status"] = "ALL_SETTLED"
        elif settled_coupons:
            bankroll["status"] = "PARTIALLY_SETTLED"
        else:
            bankroll["status"] = "ALL_IN_PLAY"

        bankroll["currency"] = bankroll.get("currency", "TL")
        bankroll["last_updated_trt"] = datetime.now(UTC).strftime("%d.%m.%Y %H:%M")
        save_bankroll(bankroll)

    # Settle paper trading ledger rows against completed ESPN scores
    settled_paper_count = 0
    try:
        try:
            from paper_trader import PaperTradingEngine
        except ImportError:
            from src.paper_trader import PaperTradingEngine
        pt = PaperTradingEngine()
        pt_res = pt.fetch_espn_completed_and_settle()
        settled_paper_count = pt_res.get("settled_now", 0)
        if settled_paper_count > 0:
            logger.info(f"Settled {settled_paper_count} paper trading bets from ESPN scoreboard!")
    except Exception as e:
        logger.debug(f"Paper trading settlement error: {e}")

    return {
        "settled_coupons": settled_coupons_count,
        "new_winnings": total_new_winnings,
        "settled_paper_bets": settled_paper_count,
    }


settle_active_coupons = run_settlement_cycle
