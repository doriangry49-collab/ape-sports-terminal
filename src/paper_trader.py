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
    "usa.1", "bra.1", "arg.1", "mex.1", "all",
]


def _norm_team(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    for token in (
        "fc", "sc", "cf", "ac", "as", "us", "ss", "cd", "ud", "rc",
        "kv", "krc", "sv", "vfl", "vfb", "fsv", "tsg", "bsc", "1.",
        "united", "utd", "city", "calcio", "1913", "1907", "1899", "04", "05",
        ".", "-", "'",
    ):
        s = s.replace(token, " ")
    return " ".join(s.split())


def evaluate_outcome_win(market: str, outcome: str, home_goals: int, away_goals: int) -> bool:
    """Return True if the specified market outcome won given final goals."""
    m = market.upper().strip()
    o = outcome.upper().strip()
    if m == "1X2":
        if o in ("HOME", "1"):
            return home_goals > away_goals
        if o in ("DRAW", "X"):
            return home_goals == away_goals
        if o in ("AWAY", "2"):
            return away_goals > home_goals
    elif m in ("OU_2.5", "TOTALS_2.5"):
        total = home_goals + away_goals
        if "OVER" in o or "UST" in o:
            return total > 2.5
        if "UNDER" in o or "ALT" in o:
            return total < 2.5
    raise ValueError(f"Unsupported market/outcome combination: {market!r} / {outcome!r}")


class PaperTradingEngine:
    """Manages persistent paper-trading ledger and ESPN score settlement."""

    def __init__(self, ledger_path: Path | None = None) -> None:
        self.ledger_path = ledger_path or DEFAULT_LEDGER_PATH
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

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

    def record_signals(
        self,
        signals: Sequence[dict[str, Any]],
        latest_fair_lookup: dict[tuple[str, str, str], float] | None = None,
    ) -> dict[str, int]:
        """Insert new positive-EV signals and update pre-match CLV on existing PENDING rows."""
        rows = self.load_rows()
        by_id: dict[str, dict[str, Any]] = {r["signal_id"]: r for r in rows if r.get("signal_id")}

        inserted = 0
        updated = 0

        for sig in signals:
            raw_mid = str(sig.get("match_id", ""))
            ev_id = str(sig.get("event_id") or raw_mid.split("_")[0])
            mkt = str(sig.get("market", ""))
            out = str(sig.get("outcome", ""))
            sig_id = f"{ev_id}|{mkt}|{out}"

            soft_odds = float(sig.get("soft_odds", 0.0))
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
                latest_fair = latest_fair_lookup.get(k)
                if latest_fair and latest_fair > 1.0:
                    orig_soft = float(r["soft_odds"])
                    r["latest_pinnacle_fair_odds"] = f"{latest_fair:.3f}"
                    r["clv_ratio"] = f"{orig_soft / latest_fair:.4f}"

        self.save_rows(rows)
        return {"inserted": inserted, "updated": updated, "total": len(rows)}

    def settle_with_scores(self, completed_matches: Sequence[dict[str, Any]]) -> dict[str, int]:
        """Settle PENDING rows against a list of completed matches:
        each item has {'home': str, 'away': str, 'hg': int, 'ag': int, 'done': bool}.
        """
        rows = self.load_rows()
        settled_now = 0

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
                won = evaluate_outcome_win(r["market"], r["outcome"], hg, ag)
                soft_odds = float(r["soft_odds"])
                fair_prob = float(r["shin_fair_prob"])
                soft_implied = 1.0 / soft_odds if soft_odds > 1.0 else 0.5
                y = 1.0 if won else 0.0

                pnl = (soft_odds - 1.0) if won else -1.0
                brier_sharp = (fair_prob - y) ** 2
                brier_soft = (soft_implied - y) ** 2

                r["result_score"] = f"{hg}-{ag}"
                r["status"] = "WON" if won else "LOST"
                r["pnl_units"] = f"{pnl:+.3f}"
                r["brier_sharp"] = f"{brier_sharp:.4f}"
                r["brier_soft"] = f"{brier_soft:.4f}"
                settled_now += 1

        if settled_now > 0:
            self.save_rows(rows)
        return {"settled_now": settled_now, "total_rows": len(rows)}

    def fetch_espn_completed_and_settle(self, dates: Sequence[str] | None = None) -> dict[str, int]:
        """Fetch completed matches from ESPN scoreboard API and settle pending rows."""
        if not dates:
            today = datetime.now(UTC)
            dates = [
                (today - timedelta(days=1)).strftime("%Y%m%d"),
                today.strftime("%Y%m%d"),
            ]
        finals: list[dict[str, Any]] = []
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
                    comp = ev.get("competitions", [{}])[0]
                    done = comp.get("status", {}).get("type", {}).get("completed", False)
                    teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
                    if "home" in teams and "away" in teams:
                        finals.append({
                            "home": teams["home"].get("team", {}).get("displayName", ""),
                            "away": teams["away"].get("team", {}).get("displayName", ""),
                            "hg": int(teams["home"].get("score", 0) or 0),
                            "ag": int(teams["away"].get("score", 0) or 0),
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

