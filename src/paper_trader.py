"""Automated Paper-Trading Ledger, CLV Tracker & ESPN Score Settlement Engine.

Maintains `output/paper_trading_ledger.csv`:
1. Logs live Stale-Line signals without duplicates (`signal_id = event_id|market|outcome`).
2. Updates latest pre-match Pinnacle odds to compute real Closing Line Value
   (`clv_ratio = soft_odds / latest_pinnacle_fair_odds`).
3. Fetches completed match scores from ESPN public scoreboard API to settle `PENDING`
   signals and compute OOS ROI, Win Rate, CLV Beat %, and Brier Score advantage.
"""
from __future__ import annotations

import csv
import difflib
import json
import re
import sys
import unicodedata
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER_PATH = PROJECT_ROOT / "output" / "paper_trading_ledger.csv"

LEDGER_FIELDS = [
    "signal_id",
    "event_id",
    "captured_at_utc",
    "kickoff",
    "league",
    "tier",
    "home",
    "away",
    "market",
    "outcome",
    "soft_book",
    "soft_odds",
    "pinnacle_odds_at_bet",
    "shin_fair_prob",
    "shin_fair_odds",
    "edge_pct",
    "kelly_pct",
    "steam_drift_pp",
    "is_steam_confirmed",
    "latest_pinnacle_fair_odds",
    "clv_ratio",
    "result_score",
    "status",
    "pnl_units",
    "brier_sharp",
    "brier_soft",
]

ESPN_LEAGUE_SLUGS = [
    "ita.1", "ita.2", "ger.1", "ger.2", "esp.1", "esp.2",
    "eng.1", "eng.2", "fra.1", "fra.2", "ned.1", "por.1",
    "bel.1", "tur.1", "sco.1", "gre.1", "sui.1", "swe.1",
    "uefa.champions", "uefa.europa", "uefa.europa.conf",
    "uefa.nations", "concacaf.nations.league", "caf.nations", "fifa.friendly",
    "fifa.worldq.uefa", "fifa.worldq.conmebol", "fifa.worldq.concacaf", "fifa.worldq.afc", "fifa.worldq.caf",
    "usa.1", "bra.1", "bra.2", "aus.1", "arg.1", "mex.1", "all",
]


_NORM_STOPWORDS = {
    "fc", "sc", "cf", "ac", "as", "us", "ss", "cd", "ud", "rc",
    "kv", "krc", "sv", "vfl", "vfb", "fsv", "tsg", "bsc", "1",
    "united", "utd", "city", "calcio", "1913", "1907", "1899", "04", "05",
}

_TR_TO_EN_TEAM_MAP = {
    "sirbistan": "serbia",
    "almanya": "germany",
    "hollanda": "netherlands",
    "yunanistan": "greece",
    "turkiye": "turkey",
    "ingiltere": "england",
    "ispanya": "spain",
    "italya": "italy",
    "fransa": "france",
    "portekiz": "portugal",
    "avusturya": "austria",
    "belcika": "belgium",
    "karadag": "montenegro",
    "letonya": "latvia",
    "arnavutluk": "albania",
    "cekya": "czechia",
    "hirvatistan": "croatia",
    "iskocya": "scotland",
    "isvicre": "switzerland",
    "isvec": "sweden",
    "norvec": "norway",
    "danimarka": "denmark",
    "polonya": "poland",
    "meksika": "mexico",
    "brezilya": "brazil",
    "arjantin": "argentina",
    "kolombiya": "colombia",
    "fas": "morocco",
    "misir": "egypt",
    "guney afrika": "south africa",
    "fildisi sahili": "ivory coast",
    "kuba": "cuba",
}


def _norm_team(name: str) -> str:
    s = name.replace("ı", "i").replace("İ", "i")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()
    for ch in (".", "-", "'"):
        s = s.replace(ch, " ")
    cleaned = " ".join(s.split())
    if cleaned in _TR_TO_EN_TEAM_MAP:
        cleaned = _TR_TO_EN_TEAM_MAP[cleaned]
    words = cleaned.split()
    filtered = [w for w in words if w not in _NORM_STOPWORDS]
    return " ".join(filtered) if filtered else cleaned


def _extract_match_date(kickoff_str: str, fallback_str: str = "") -> str:
    """Extract YYYY-MM-DD date string from kickoff or timestamp."""
    for s in (kickoff_str, fallback_str):
        s_clean = str(s or "").strip()
        if len(s_clean) >= 10:
            part = s_clean[:10]
            if part[4:5] == "-" and part[7:8] == "-":
                return part
            if part[2:3] == "." and part[5:6] == ".":
                return f"{part[6:10]}-{part[3:5]}-{part[0:2]}"
    return datetime.now(UTC).strftime("%Y-%m-%d")


def build_composite_signal_id(
    match_date: str,
    home: str,
    away: str,
    market: str,
    outcome: str,
) -> str:
    """Construct collision-free composite signal ID: {match_date}_{home_norm}_{away_norm}|{market}|{outcome}."""
    h_norm = _norm_team(home).replace(" ", "_") or "unknown_home"
    a_norm = _norm_team(away).replace(" ", "_") or "unknown_away"
    d_clean = _extract_match_date(match_date)
    return f"{d_clean}_{h_norm}_{a_norm}|{market}|{outcome}"


def validate_coupon_stake_and_exposure(
    coupon: dict[str, Any],
    existing_coupons: Sequence[dict[str, Any]] | None = None,
) -> None:
    """Enforce SPEC-0015 minimum stake (>= 50.0 TL) and max 1 active coupon per match per night."""
    stake = float(coupon.get("stake", 0.0) or 0.0)
    if stake < 50.0:
        raise ValueError(f"SPEC-0015 violation: Minimum stake is 50.0 TL (got {stake:.2f} TL).")

    if existing_coupons:
        active_fixtures: set[str] = set()
        for c in existing_coupons:
            if c.get("id") and c.get("id") == coupon.get("id"):
                continue
            if c.get("status", "PENDING") in ("PENDING", "IN_PLAY"):
                for p in c.get("picks", []):
                    h = _norm_team(str(p.get("home") or p.get("home_team") or ""))
                    a = _norm_team(str(p.get("away") or p.get("away_team") or ""))
                    m_raw = str(p.get("match") or "").strip().lower()
                    f_key = f"{h}__{a}" if (h and a) else m_raw
                    if f_key:
                        active_fixtures.add(f_key)

        seen_in_this_coupon: set[str] = set()
        for p in coupon.get("picks", []):
            h = _norm_team(str(p.get("home") or p.get("home_team") or ""))
            a = _norm_team(str(p.get("away") or p.get("away_team") or ""))
            m_raw = str(p.get("match") or "").strip().lower()
            f_key = f"{h}__{a}" if (h and a) else m_raw
            if f_key:
                if f_key in active_fixtures or f_key in seen_in_this_coupon:
                    raise ValueError(
                        f"Exposure cap violation: Match '{f_key}' exceeds maximum 1 coupon per night."
                    )
                seen_in_this_coupon.add(f_key)


def evaluate_outcome_win(
    market: str,
    outcome: str,
    home_goals: int,
    away_goals: int,
    ht_home_goals: int | None = None,
    ht_away_goals: int | None = None,
    total_corners: int | None = None,
) -> bool:
    """Return True if the specified market outcome won given final goals, HT goals, or corners."""
    # Turkish-safe uppercase: 'Çifte Şans'.upper() == 'ÇIFTE ŞANS' (dotted İ is never produced)
    m = market.upper().replace("İ", "I").strip()
    o = outcome.upper().replace("İ", "I").strip()
    if m == "TOPLAM GOL" or m.startswith("TG"):
        digits = "".join(ch for ch in o if ch.isdigit())
        if digits and o.rstrip().endswith("+"):
            return (home_goals + away_goals) >= int(digits)
    if m == "1X2":
        tokens = set(re.split(r"[\s/()]+", o))
        if "1" in tokens or "HOME" in tokens or "EV" in tokens:
            return home_goals > away_goals
        if "X" in tokens or "DRAW" in tokens or "BERABER" in tokens or "BERABERLIK" in tokens:
            return home_goals == away_goals
        if "2" in tokens or "AWAY" in tokens or "DEP" in tokens or "DEPLASMAN" in tokens:
            return away_goals > home_goals
    elif m in ("OU_2.5", "TOTALS_2.5", "2.5 GOL", "TOTALS"):
        total = home_goals + away_goals
        if "OVER" in o or "UST" in o or "ÜST" in o:
            return total > 2.5
        if "UNDER" in o or "ALT" in o:
            return total < 2.5
    elif "CIFTE" in m or "ÇIFTE" in m or "DOUBLE_CHANCE" in m or "DC" in m:
        if "1X" in o:
            return home_goals >= away_goals
        if "X2" in o:
            return away_goals >= home_goals
        if "12" in o:
            return home_goals != away_goals
    elif "KG" in m or "BTTS" in m:
        btts = home_goals > 0 and away_goals > 0
        if "VAR" in o or "YES" in o:
            return btts
        if "YOK" in o or "NO" in o:
            return not btts
    elif "IY/MS" in m or "HT/FT" in m or "HT_FT" in m:
        if ht_home_goals is None or ht_away_goals is None:
            raise ValueError(f"Missing half-time score for HT/FT settlement: {market!r} / {outcome!r}")
        ht_res = "1" if ht_home_goals > ht_away_goals else ("2" if ht_away_goals > ht_home_goals else "X")
        ft_res = "1" if home_goals > away_goals else ("2" if away_goals > home_goals else "X")
        actual_htft = f"{ht_res}/{ft_res}"
        match = re.search(r"([1X2]/[1X2])", o)
        if match:
            return actual_htft == match.group(1)
    elif "KORNER" in m or "CORNER" in m:
        if total_corners is None:
            raise ValueError(f"Missing corner statistics for Corner settlement: {market!r} / {outcome!r}")
        line_match = re.search(r"(\d+\.?\d*)", o) or re.search(r"(\d+\.?\d*)", m)
        if line_match:
            line_val = float(line_match.group(1))
            if "ALT" in o or "UNDER" in o:
                return total_corners < line_val
            if "UST" in o or "ÜST" in o or "OVER" in o:
                return total_corners > line_val
    raise ValueError(f"Unsupported market/outcome combination: {market!r} / {outcome!r}")


def is_corner_market(market: str, outcome: str = "") -> bool:
    """Return True when market or outcome denotes a total-corners betting market."""
    m = str(market or "").upper()
    o = str(outcome or "").upper()
    return "KORNER" in m or "CORNER" in m or "KORNER" in o or "CORNER" in o


class PaperTradingEngine:
    """Manages persistent paper-trading ledger and ESPN score settlement."""

    def __init__(
        self,
        ledger_path: Path | None = None,
        closing_line_store: Any | None = None,
    ) -> None:
        self.ledger_path = ledger_path or DEFAULT_LEDGER_PATH
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.closing_line_store = closing_line_store

    def load_rows(self) -> list[dict[str, str]]:
        if not self.ledger_path.exists():
            return []
        with open(self.ledger_path, encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def save_rows(self, rows: Sequence[dict[str, Any]]) -> None:
        with open(self.ledger_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS)
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in LEDGER_FIELDS})

    def record_value_signals(
        self,
        signals: Sequence[Any],
    ) -> dict[str, int]:
        """Record ValueSignal instances or value dicts directly into the paper trading ledger."""
        converted = []
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        for s in signals:
            if hasattr(s, "to_dict"):
                d = s.to_dict()
            else:
                d = dict(s)
            if "stake" in d and d["stake"] is not None:
                if float(d["stake"]) < 50.0:
                    raise ValueError(f"SPEC-0015 violation: Minimum stake is 50.0 TL (got {d['stake']}).")
            home_str = str(d.get("home_team", d.get("home", "")))
            away_str = str(d.get("away_team", d.get("away", "")))
            ko_str = str(d.get("kickoff_utc", d.get("kickoff", "")))
            match_date = _extract_match_date(ko_str, now_iso)
            home_norm = _norm_team(home_str).replace(" ", "_") or "unknown_home"
            away_norm = _norm_team(away_str).replace(" ", "_") or "unknown_away"
            mkt_str = str(d.get("market", "1X2"))
            out_str = str(d.get("selection", d.get("outcome", "")))
            comp_ev_id = str(d.get("fixture_id") or d.get("event_id") or f"{match_date}_{home_norm}_{away_norm}")
            sig_id = f"{match_date}_{home_norm}_{away_norm}|{mkt_str}|{out_str}"
            converted.append({
                "signal_id": sig_id,
                "match_id": comp_ev_id,
                "event_id": comp_ev_id,
                "timestamp_mode": now_iso,
                "kickoff": ko_str,
                "league": str(d.get("league", "")),
                "tier": str(d.get("tier", "TIER_1_SHIN_QUANT")),
                "home": home_str,
                "away": away_str,
                "market": mkt_str,
                "outcome": out_str,
                "soft_book": str(d.get("bookmaker", d.get("soft_book", "NESINE"))),
                "soft_odds": float(d.get("offered_odds", d.get("soft_odds", 0.0))),
                "fair_odds": float(d.get("fair_odds_shin", d.get("fair_odds", 0.0))),
                "fair_prob": float(d.get("fair_prob_shin", d.get("prob", 0.0))),
                "sharp_odds": float(d.get("fair_odds_shin", d.get("fair_odds", 0.0))),
                "edge_pct": float(d.get("edge_pct", 0.0)),
                "kelly_pct": float(d.get("half_kelly", d.get("kelly_pct", 0.0))),
                "is_steam_confirmed": bool(d.get("is_steam_confirmed", False)),
            })
        return self.record_signals(converted)

    def record_signals(
        self,
        signals: Sequence[dict[str, Any]],
        latest_fair_lookup: dict[tuple[str, str, str], float] | None = None,
    ) -> dict[str, int]:
        """Insert new positive-EV signals and update pre-match CLV on existing PENDING rows."""
        rows = self.load_rows()
        by_id: dict[str, dict[str, Any]] = {r["signal_id"]: r for r in rows if r.get("signal_id")}

        # Track matches that already hold any corner position in the ledger (by normalized comp_key & event_id)
        existing_corner_ids_by_match: dict[str, set[str]] = {}
        existing_corner_ids_by_event: dict[str, set[str]] = {}
        for r in rows:
            if not is_corner_market(r.get("market", ""), r.get("outcome", "")):
                continue
            r_id = str(r.get("signal_id") or "")
            r_date = _extract_match_date(str(r.get("kickoff", "")), str(r.get("captured_at_utc", "")))
            r_home = _norm_team(str(r.get("home", ""))).replace(" ", "_") or "unknown_home"
            r_away = _norm_team(str(r.get("away", ""))).replace(" ", "_") or "unknown_away"
            r_comp = f"{r_date}_{r_home}_{r_away}"
            existing_corner_ids_by_match.setdefault(r_comp, set()).add(r_id)
            r_ev = str(r.get("event_id") or "")
            if r_ev:
                existing_corner_ids_by_event.setdefault(r_ev, set()).add(r_id)

        # Pass 1: Validate constitutional stake floor & collapse corners to a single highest-EV line per match
        normalized_batch: list[tuple[dict[str, Any], str, str, str, float]] = []
        best_corner_idx: dict[str, tuple[tuple[float, float, float], int]] = {}
        for sig in signals:
            if "stake" in sig and sig["stake"] is not None:
                if float(sig["stake"]) < 50.0:
                    raise ValueError(f"SPEC-0015 violation: Minimum stake is 50.0 TL (got {sig['stake']}).")
            raw_mid = str(sig.get("match_id", ""))
            raw_ev = str(sig.get("event_id") or (raw_mid.split("_")[0] if raw_mid else ""))
            mkt = str(sig.get("market", ""))
            out = str(sig.get("outcome", ""))
            home_str = str(sig.get("home", ""))
            away_str = str(sig.get("away", ""))
            ko_str = str(sig.get("kickoff", ""))
            ts_str = str(sig.get("timestamp_mode", ""))
            match_date = _extract_match_date(ko_str, ts_str)
            home_norm = _norm_team(home_str).replace(" ", "_") or "unknown_home"
            away_norm = _norm_team(away_str).replace(" ", "_") or "unknown_away"
            comp_key = f"{match_date}_{home_norm}_{away_norm}"
            ev_id = raw_ev if raw_ev else comp_key
            sig_id = str(sig.get("signal_id") or f"{comp_key}|{mkt}|{out}")

            soft_odds = float(sig.get("soft_odds", 0.0))
            if soft_odds <= 1.01 or mkt.upper() == "GOLDEN_PATTERN":
                continue  # SPEC-0012 Fail-Closed: Never record unpriced or non-settleable pattern labels into ledger

            idx = len(normalized_batch)
            normalized_batch.append((sig, comp_key, ev_id, sig_id, soft_odds))
            if is_corner_market(mkt, out):
                match_group = comp_key if (home_norm != "unknown_home" or away_norm != "unknown_away") else ev_id
                rank = (
                    float(sig.get("edge_pct", 0.0) or 0.0),
                    float(sig.get("fair_prob", 0.0) or 0.0),
                    soft_odds,
                )
                prev = best_corner_idx.get(match_group)
                if prev is None or rank > prev[0]:
                    best_corner_idx[match_group] = (rank, idx)

        allowed_corner_indices = {v[1] for v in best_corner_idx.values()}
        inserted = 0
        updated = 0

        for idx, (sig, comp_key, ev_id, sig_id, soft_odds) in enumerate(normalized_batch):
            mkt = str(sig.get("market", ""))
            out = str(sig.get("outcome", ""))
            if is_corner_market(mkt, out):
                prior_ids = existing_corner_ids_by_match.get(comp_key) or existing_corner_ids_by_event.get(ev_id)
                if prior_ids:
                    # Match already owns a corner position: only update CLV for that exact signal_id, never open a 2nd line
                    if sig_id not in prior_ids:
                        continue
                elif idx not in allowed_corner_indices:
                    continue

            fair_odds = float(sig.get("fair_odds", 0.0))
            fair_prob = float(sig.get("fair_prob", 0.0))
            sharp_odds = float(sig.get("sharp_odds", 0.0))
            drift = sig.get("steam_drift_pp")
            steam_conf = bool(sig.get("is_steam_confirmed", False)) or (
                drift is not None and float(drift) >= 0.25
            )

            if sig_id not in by_id:
                clv = round(soft_odds / fair_odds, 4) if fair_odds > 1.0 else 1.0
                new_row = {
                    "signal_id": sig_id,
                    "event_id": ev_id,
                    "captured_at_utc": str(sig.get("timestamp_mode", "")),
                    "kickoff": str(sig.get("kickoff", "")),
                    "league": str(sig.get("league", "")),
                    "tier": str(sig.get("tier", "")),
                    "home": str(sig.get("home", "")),
                    "away": str(sig.get("away", "")),
                    "market": mkt,
                    "outcome": out,
                    "soft_book": str(sig.get("soft_book", "")),
                    "soft_odds": f"{soft_odds:.3f}",
                    "pinnacle_odds_at_bet": f"{sharp_odds:.3f}",
                    "shin_fair_prob": f"{fair_prob:.4f}",
                    "shin_fair_odds": f"{fair_odds:.3f}",
                    "edge_pct": f"{float(sig.get('edge_pct', 0.0)):.2f}",
                    "kelly_pct": f"{float(sig.get('kelly_pct', 0.0)):.2f}",
                    "steam_drift_pp": f"{float(drift):.2f}" if drift is not None else "0.00",
                    "is_steam_confirmed": "TRUE" if steam_conf else "FALSE",
                    "latest_pinnacle_fair_odds": f"{fair_odds:.3f}",
                    "clv_ratio": f"{clv:.4f}",
                    "result_score": "",
                    "status": "PENDING",
                    "pnl_units": "",
                    "brier_sharp": "",
                    "brier_soft": "",
                }
                rows.append(new_row)
                by_id[sig_id] = new_row
                inserted += 1
            else:
                existing = by_id[sig_id]
                if existing.get("status") == "PENDING" and fair_odds > 1.0:
                    orig_soft = float(existing["soft_odds"])
                    is_frozen = False
                    if self.closing_line_store:
                        try:
                            rec = self.closing_line_store.get_record(ev_id, mkt)
                            if rec and out in rec.fair_closing_odds:
                                is_frozen = True
                                f_odds = rec.fair_closing_odds[out]
                                existing["latest_pinnacle_fair_odds"] = f"{f_odds:.3f}"
                                existing["clv_ratio"] = f"{orig_soft / f_odds:.4f}"
                        except Exception:
                            pass

                    if not is_frozen:
                        existing["latest_pinnacle_fair_odds"] = f"{fair_odds:.3f}"
                        existing["clv_ratio"] = f"{orig_soft / fair_odds:.4f}"

                    if drift is not None:
                        existing["steam_drift_pp"] = f"{float(drift):.2f}"
                    if steam_conf:
                        existing["is_steam_confirmed"] = "TRUE"
                    updated += 1

        # Also update CLV for any existing PENDING row whose fixture is in latest_fair_lookup
        if latest_fair_lookup:
            for r in rows:
                if r.get("status") != "PENDING":
                    continue
                k = (r.get("event_id", ""), r.get("market", ""), r.get("outcome", ""))
                if self.closing_line_store:
                    try:
                        rec = self.closing_line_store.get_record(k[0], k[1])
                        if rec and k[2] in rec.fair_closing_odds:
                            orig_soft = float(r["soft_odds"])
                            f_odds = rec.fair_closing_odds[k[2]]
                            r["latest_pinnacle_fair_odds"] = f"{f_odds:.3f}"
                            r["clv_ratio"] = f"{orig_soft / f_odds:.4f}"
                            continue
                    except Exception:
                        pass

                latest_fair = latest_fair_lookup.get(k)
                if latest_fair and latest_fair > 1.0:
                    orig_soft = float(r["soft_odds"])
                    r["latest_pinnacle_fair_odds"] = f"{latest_fair:.3f}"
                    r["clv_ratio"] = f"{orig_soft / latest_fair:.4f}"

        self.save_rows(rows)
        return {"inserted": inserted, "updated": updated, "total": len(rows)}

    def sync_closing_lines(self, store: Any | None = None) -> int:
        """Lock pending ledger rows using frozen closing lines from ClosingLineStore."""
        cl_store = store or self.closing_line_store
        if not cl_store:
            return 0
        rows = self.load_rows()
        updated_count = 0
        for r in rows:
            if r.get("status") != "PENDING":
                continue
            ev_id = r.get("event_id", "")
            mkt = r.get("market", "")
            out = r.get("outcome", "")
            frozen = cl_store.get_record(ev_id, mkt)
            if frozen and out in frozen.fair_closing_odds:
                fair = frozen.fair_closing_odds[out]
                orig_soft = float(r.get("soft_odds", 1.0))
                r["latest_pinnacle_fair_odds"] = f"{fair:.3f}"
                r["clv_ratio"] = f"{orig_soft / fair:.4f}"
                updated_count += 1
        if updated_count > 0:
            self.save_rows(rows)
        return updated_count

    def settle_with_scores(self, completed_matches: Sequence[dict[str, Any]]) -> dict[str, int]:
        """Settle PENDING rows against a list of completed matches:
        each item has {'home': str, 'away': str, 'hg': int, 'ag': int, 'done': bool}
        and optional 'ht_hg', 'ht_ag', 'corners', 'espn_event_id', 'espn_league'.
        """
        rows = self.load_rows()
        settled_now = 0
        unsettleable = 0
        stats_cache: dict[str, dict[str, int | None]] = {}

        for r in rows:
            if r.get("status") != "PENDING":
                continue
            home = r.get("home", "")
            away = r.get("away", "")
            best_m = None
            best_sc = 0.0
            for f in completed_matches:
                if not f.get("done"):
                    continue
                sh = difflib.SequenceMatcher(None, _norm_team(home), _norm_team(f["home"])).ratio()
                sa = difflib.SequenceMatcher(None, _norm_team(away), _norm_team(f["away"])).ratio()
                if min(sh, sa) < 0.45:
                    continue
                sc = 0.5 * (sh + sa)
                if sc > best_sc:
                    best_m, best_sc = f, sc

            if best_m and best_sc >= 0.60:
                hg = int(best_m["hg"])
                ag = int(best_m["ag"])
                ht_hg = best_m.get("ht_hg")
                ht_ag = best_m.get("ht_ag")
                corners_val = best_m.get("corners")

                mkt_upper = str(r.get("market", "")).upper().replace("İ", "I")
                if ("KORNER" in mkt_upper or "CORNER" in mkt_upper) and corners_val is None:
                    ev_id = str(best_m.get("espn_event_id") or "")
                    espn_lg = str(best_m.get("espn_league") or "all")
                    if ev_id:
                        if ev_id not in stats_cache:
                            try:
                                from live_settlement_engine import fetch_espn_event_stats
                            except ImportError:
                                from src.live_settlement_engine import fetch_espn_event_stats
                            stats_cache[ev_id] = fetch_espn_event_stats(ev_id, espn_lg)
                        corners_val = stats_cache[ev_id].get("corners")

                try:
                    won = evaluate_outcome_win(
                        r["market"],
                        r["outcome"],
                        hg,
                        ag,
                        ht_home_goals=int(ht_hg) if ht_hg is not None else None,
                        ht_away_goals=int(ht_ag) if ht_ag is not None else None,
                        total_corners=int(corners_val) if corners_val is not None else None,
                    )
                except ValueError:
                    # SPEC-0012 fail-closed: market needs data we do not have (HT score, corners...).
                    # Leave PENDING instead of guessing or crashing the whole scan cycle.
                    unsettleable += 1
                    continue
                soft_odds = float(r["soft_odds"])
                fair_prob = float(r["shin_fair_prob"])
                soft_implied = 1.0 / soft_odds if soft_odds > 1.0 else 0.5
                y = 1.0 if won else 0.0

                pnl = (soft_odds - 1.0) if won else -1.0
                brier_sharp = (fair_prob - y) ** 2
                brier_soft = (soft_implied - y) ** 2

                score_str = f"{hg}-{ag}"
                if corners_val is not None and ("KORNER" in mkt_upper or "CORNER" in mkt_upper):
                    score_str = f"{hg}-{ag} (K:{corners_val})"
                elif ht_hg is not None and ht_ag is not None and ("IY/MS" in mkt_upper or "HT" in mkt_upper):
                    score_str = f"{hg}-{ag} (İY:{ht_hg}-{ht_ag})"

                r["result_score"] = score_str
                r["status"] = "WON" if won else "LOST"
                r["pnl_units"] = f"{pnl:+.3f}"
                r["brier_sharp"] = f"{brier_sharp:.4f}"
                r["brier_soft"] = f"{brier_soft:.4f}"
                settled_now += 1

        if settled_now > 0:
            self.save_rows(rows)
        return {"settled_now": settled_now, "total_rows": len(rows), "unsettleable": unsettleable}

    def fetch_espn_completed_and_settle(self, dates: Sequence[str] | None = None) -> dict[str, int]:
        """Fetch completed matches from ESPN scoreboard API and settle pending rows."""
        pending_rows = [r for r in self.load_rows() if r.get("status") == "PENDING"]
        if not pending_rows:
            return {"settled_now": 0, "total_rows": len(self.load_rows()), "unsettleable": 0}

        if not dates:
            today = datetime.now(UTC)
            date_set = {
                (today - timedelta(days=1)).strftime("%Y%m%d"),
                today.strftime("%Y%m%d"),
            }
            for r in pending_rows:
                m_dt = _extract_match_date(r.get("kickoff", ""), r.get("captured_at_utc", ""))
                date_set.add(m_dt.replace("-", ""))
            dates = sorted(date_set)
        finals: list[dict[str, Any]] = []
        seen_event_ids: set[str] = set()

        # First fetch direct espn_<id> event summaries if present on PENDING rows
        for r in pending_rows:
            ev_raw = str(r.get("event_id") or "")
            if ev_raw.startswith("espn_") and ev_raw[5:].isdigit():
                espn_id = ev_raw[5:]
                if espn_id in seen_event_ids:
                    continue
                url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary?event={espn_id}"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        sdata = json.loads(resp.read().decode("utf-8"))
                    comp = (sdata.get("header") or {}).get("competitions", [{}])[0]
                    done = comp.get("status", {}).get("type", {}).get("completed", False)
                    teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
                    if "home" in teams and "away" in teams:
                        seen_event_ids.add(espn_id)
                        finals.append({
                            "espn_event_id": espn_id,
                            "espn_league": "all",
                            "home": teams["home"].get("team", {}).get("displayName", ""),
                            "away": teams["away"].get("team", {}).get("displayName", ""),
                            "hg": int(teams["home"].get("score", 0) or 0),
                            "ag": int(teams["away"].get("score", 0) or 0),
                            "ht_hg": None,
                            "ht_ag": None,
                            "done": bool(done),
                        })
                except Exception:
                    pass

        for slug in ESPN_LEAGUE_SLUGS:
            for d in dates:
                url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={d}&limit=500"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                except Exception:
                    continue
                for ev in data.get("events", []):
                    ev_id = str(ev.get("id", ""))
                    if ev_id and ev_id in seen_event_ids:
                        continue
                    if ev_id:
                        seen_event_ids.add(ev_id)
                    comp = ev.get("competitions", [{}])[0]
                    done = comp.get("status", {}).get("type", {}).get("completed", False)
                    teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
                    if "home" in teams and "away" in teams:
                        ht_hg = None
                        ht_ag = None
                        if done:
                            h_ls = teams["home"].get("linescores")
                            a_ls = teams["away"].get("linescores")
                            if isinstance(h_ls, list) and h_ls and isinstance(h_ls[0], dict):
                                v = h_ls[0].get("value", h_ls[0].get("displayValue"))
                                if v is not None:
                                    try:
                                        ht_hg = int(round(float(v)))
                                    except (ValueError, TypeError):
                                        pass
                            if isinstance(a_ls, list) and a_ls and isinstance(a_ls[0], dict):
                                v = a_ls[0].get("value", a_ls[0].get("displayValue"))
                                if v is not None:
                                    try:
                                        ht_ag = int(round(float(v)))
                                    except (ValueError, TypeError):
                                        pass
                        finals.append({
                            "espn_event_id": ev_id,
                            "espn_league": slug,
                            "home": teams["home"].get("team", {}).get("displayName", ""),
                            "away": teams["away"].get("team", {}).get("displayName", ""),
                            "hg": int(teams["home"].get("score", 0) or 0),
                            "ag": int(teams["away"].get("score", 0) or 0),
                            "ht_hg": ht_hg,
                            "ht_ag": ht_ag,
                            "done": bool(done),
                        })
        return self.settle_with_scores(finals)

    def compute_summary(self) -> dict[str, Any]:
        rows = self.load_rows()
        pending = [r for r in rows if r.get("status") == "PENDING"]
        settled = [r for r in rows if r.get("status") in ("WON", "LOST")]
        won = [r for r in settled if r.get("status") == "WON"]

        clv_vals = [float(r["clv_ratio"]) for r in rows if r.get("clv_ratio")]
        beat_clv = [x for x in clv_vals if x > 1.0]

        net_u = sum(float(r["pnl_units"]) for r in settled if r.get("pnl_units"))
        roi = (net_u / len(settled) * 100.0) if settled else 0.0

        b_sharp = [float(r["brier_sharp"]) for r in settled if r.get("brier_sharp")]
        b_soft = [float(r["brier_soft"]) for r in settled if r.get("brier_soft")]

        avg_bs = (sum(b_sharp) / len(b_sharp)) if b_sharp else None
        avg_bsoft = (sum(b_soft) / len(b_soft)) if b_soft else None

        return {
            "total_signals": len(rows),
            "pending_count": len(pending),
            "settled_count": len(settled),
            "won_count": len(won),
            "lost_count": len(settled) - len(won),
            "win_rate_pct": round(len(won) / len(settled) * 100.0, 2) if settled else 0.0,
            "net_units": round(net_u, 2),
            "roi_pct": round(roi, 2),
            "avg_clv_ratio": round(sum(clv_vals) / len(clv_vals), 4) if clv_vals else 1.0,
            "beat_clv_pct": round(len(beat_clv) / len(clv_vals) * 100.0, 2) if clv_vals else 0.0,
            "avg_brier_sharp": round(avg_bs, 4) if avg_bs is not None else None,
            "avg_brier_soft": round(avg_bsoft, 4) if avg_bsoft is not None else None,
            "brier_advantage": round(avg_bsoft - avg_bs, 4) if (avg_bs is not None and avg_bsoft is not None) else None,
        }


if __name__ == "__main__":
    engine = PaperTradingEngine()
    print(json.dumps(engine.compute_summary(), indent=2))

