"""Autonomous Adaptive Dual-Engine +EV Watcher & Live In-Play Scheduler.

Runs on an adaptive cadence (2 minutes during live matches, 5 minutes idle),
evaluating Nesine MBS 1-2 matches inside the SPEC-0013 (> +3m) and SPEC-0014
(<= +12h) window through the Dual-Engine +EV Pipeline (TeamStrength ELO +
Sharp Consensus PropLine/ESPN/Bzzoiro), enforcing strict playable odds bounds
(1.45 <= odds <= 6.50, +4% <= EV <= +35%, stake >= 50 TL) to block zero-value
heavy favorites, refreshing the UI snapshot, and running LiveSniperDaemon.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
for _p in (str(ROOT_DIR), str(SRC_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from atomic_io import atomic_write_json
from high_odds_system_engine import compute_bivariate_score_matrix, estimate_lambdas_from_odds
from telegram_notifier import send_telegram_message

TRT_TZ = timezone(timedelta(hours=3))
NESINE_PRE_URL = "https://cdnbulten.nesine.com/api/bulten/getprebultenfull"
DEFAULT_SEEN_PATH = ROOT_DIR / "output" / "watcher_seen_signals.json"
DEFAULT_HEARTBEAT_PATH = ROOT_DIR / "output" / "nesine_watcher_heartbeat.json"
DEFAULT_LOG_PATH = ROOT_DIR / "output" / "nesine_watcher.log"

MIN_PLAYABLE_ODDS = 1.45
MAX_PLAYABLE_ODDS = 6.50
MIN_WATCHER_EV_PCT = 4.0
MAX_WATCHER_EV_PCT = 35.0
MIN_STAKE_TL = 50.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(DEFAULT_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("NesineWatcher")


def parse_kickoff_trt(
    date_str: Any,
    time_str: Any,
    now_trt: datetime | None = None,
) -> datetime | None:
    """Parse kickoff in TRT and enforce SPEC-0013 (> +3m) and SPEC-0014 (<= +12h)."""
    if not date_str or not time_str:
        return None
    ref_now = now_trt or datetime.now(TRT_TZ)
    dt_str = f"{str(date_str).strip()} {str(time_str).strip().lstrip('T')}"
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(dt_str, fmt).replace(tzinfo=TRT_TZ)
            if ref_now + timedelta(minutes=3) < dt <= ref_now + timedelta(hours=12):
                return dt
            return None
        except ValueError:
            continue
    return None


def fetch_nesine_pre_bulletin(
    url: str = NESINE_PRE_URL,
    timeout: int = 12,
) -> dict[str, Any]:
    """Fetch live Nesine pre-match bulletin JSON; fail-closed on network error (SPEC-0012)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Nesine CDN fetch failed: {exc}") from exc


def extract_mbs12_candidates(
    payload: dict[str, Any],
    now_trt: datetime | None = None,
) -> list[dict[str, Any]]:
    """Extract MBS 1-2 soccer fixtures in the SPEC-0013/0014 window with verified markets."""
    ref_now = now_trt or datetime.now(TRT_TZ)
    sg = payload.get("sg", {})
    ea_list = sg.get("EA", [])
    la_map = {
        item.get("LID"): item
        for item in sg.get("LA", [])
        if isinstance(item, dict) and item.get("LID")
    }

    candidates: list[dict[str, Any]] = []
    for item in ea_list:
        if not isinstance(item, dict) or item.get("TYPE") != 1 or not item.get("MA"):
            continue
        ko_dt = parse_kickoff_trt(item.get("D"), item.get("T"), now_trt=ref_now)
        if ko_dt is None:
            continue

        mbs_val = int(item.get("EMBS") or 1)
        mkts: dict[str, Any] = {}
        for mkt in item.get("MA", []):
            mtid = mkt.get("MTID")
            sov = round(float(mkt.get("SOV") or 0.0), 1)
            oca = {
                o.get("N"): float(o.get("O") or 0.0)
                for o in mkt.get("OCA", [])
                if isinstance(o, dict)
            }
            if mtid == 1 and oca.get(1, 0) > 1.01 and oca.get(2, 0) > 1.01 and oca.get(3, 0) > 1.01:
                mkts["1X2"] = (oca[1], oca[2], oca[3])
                mbs_val = int(mkt.get("MBS") or mbs_val)
            elif mtid == 12 and sov == 2.5 and oca.get(1, 0) > 1.01 and oca.get(2, 0) > 1.01:
                mkts["OU25"] = {"under": oca[1], "over": oca[2]}
            elif mtid == 38 and oca.get(1, 0) > 1.01 and oca.get(2, 0) > 1.01:
                mkts["BTTS"] = {"var": oca[1], "yok": oca[2]}

        if mbs_val not in (1, 2) or "1X2" not in mkts or "OU25" not in mkts:
            continue

        league_name = la_map.get(item.get("LC"), {}).get("N") or "Nesine"
        candidates.append(
            {
                "event_id": str(item.get("C") or item.get("EID") or f"{ko_dt.isoformat()}_{item.get('HN','')}_{item.get('AN','')}"),
                "ko_dt": ko_dt,
                "ko_str": ko_dt.strftime("%H:%M"),
                "league": league_name,
                "home": str(item.get("HN") or "").strip(),
                "away": str(item.get("AN") or "").strip(),
                "mbs": mbs_val,
                "mkts": mkts,
            }
        )

    candidates.sort(key=lambda c: c["ko_dt"])
    return candidates


def evaluate_high_prob_signals(
    candidates: list[dict[str, Any]],
    min_prob: float = 0.65,
    min_odds: float = MIN_PLAYABLE_ODDS,
    max_odds: float = MAX_PLAYABLE_ODDS,
) -> list[dict[str, Any]]:
    """Price candidates via Dixon-Coles and return selections within playable odds bounds."""
    signals: list[dict[str, Any]] = []
    for c in candidates:
        o1x2 = c["mkts"]["1X2"]
        ou25 = c["mkts"]["OU25"]
        lh, la = estimate_lambdas_from_odds(o1x2, (ou25["over"], ou25["under"]))
        matrix = compute_bivariate_score_matrix(lh, la)

        p_h = sum(p for (x, y), p in matrix.items() if x > y)
        p_d = sum(p for (x, y), p in matrix.items() if x == y)
        p_a = sum(p for (x, y), p in matrix.items() if x < y)
        p_o25 = sum(p for (x, y), p in matrix.items() if x + y > 2.5)
        p_u25 = 1.0 - p_o25
        p_btts_yes = sum(p for (x, y), p in matrix.items() if x > 0 and y > 0)
        p_btts_no = 1.0 - p_btts_yes

        checks: list[tuple[str, str, float, float]] = [
            ("1X2", "MS 1", o1x2[0], p_h),
            ("1X2", "MS X", o1x2[1], p_d),
            ("1X2", "MS 2", o1x2[2], p_a),
            ("OU25", "2.5 Üst", ou25["over"], p_o25),
            ("OU25", "2.5 Alt", ou25["under"], p_u25),
        ]
        if "BTTS" in c["mkts"]:
            checks.append(("BTTS", "KG Var", c["mkts"]["BTTS"]["var"], p_btts_yes))
            checks.append(("BTTS", "KG Yok", c["mkts"]["BTTS"]["yok"], p_btts_no))

        for market, selection, odd, prob in checks:
            if min_odds <= odd <= max_odds and prob >= min_prob:
                signals.append(
                    {
                        "event_id": c["event_id"],
                        "ko_str": c["ko_str"],
                        "ko_date": c["ko_dt"].strftime("%Y-%m-%d"),
                        "league": c["league"],
                        "home": c["home"],
                        "away": c["away"],
                        "mbs": c["mbs"],
                        "market": market,
                        "selection": selection,
                        "odds": round(odd, 2),
                        "model_prob": round(prob * 100.0, 1),
                    }
                )
    return signals


def scan_verified_ev_signals(
    min_odds: float = MIN_PLAYABLE_ODDS,
    max_odds: float = MAX_PLAYABLE_ODDS,
    min_ev_pct: float = MIN_WATCHER_EV_PCT,
    max_ev_pct: float = MAX_WATCHER_EV_PCT,
    min_stake_tl: float = MIN_STAKE_TL,
    include_synthetic_dc: bool = False,
    sync_ui_snapshot: bool = True,
) -> tuple[int, list[dict[str, Any]]]:
    """Run the Dual-Engine +EV Pipeline and return playable MBS 1-2 signals only."""
    from scripts.run_daily_prototype import run_daily_pipeline

    report = run_daily_pipeline(
        min_ev_pct=min_ev_pct,
        min_stake_tl=min_stake_tl,
        record_ledger=False,
        settle_espn=False,
        output_json=ROOT_DIR / "output" / "daily_prototype_report.json",
        sync_ui_snapshot=sync_ui_snapshot,
    )
    window_matches = int((report.get("summary") or {}).get("window_valid_matches") or 0)

    qualified: list[dict[str, Any]] = []
    for sig in report.get("signals") or []:
        odd = float(sig.get("book_odd") or sig.get("soft_odds") or 0.0)
        edge = float(sig.get("edge_pct") or 0.0)
        stake = float(sig.get("stake") or 0.0)
        mbs = int(sig.get("mbs") or 1)
        mkt = str(sig.get("market") or "")
        if not include_synthetic_dc and mkt == "Çifte Şans":
            continue
        if mbs not in (1, 2):
            continue
        if not (min_odds <= odd <= max_odds):
            continue
        if not (min_ev_pct <= edge <= max_ev_pct):
            continue
        if stake < min_stake_tl:
            continue

        ko_trt_full = str(sig.get("kickoff_trt") or "")
        ko_date = ko_trt_full[:10] if len(ko_trt_full) >= 10 else datetime.now(TRT_TZ).strftime("%Y-%m-%d")
        qualified.append(
            {
                "event_id": str(sig.get("nesine_code") or sig.get("match") or ""),
                "ko_str": str(sig.get("time") or ko_trt_full[11:16] or "TBD"),
                "ko_date": ko_date,
                "league": str(sig.get("league") or sig.get("country") or "Nesine"),
                "home": str(sig.get("home") or ""),
                "away": str(sig.get("away") or ""),
                "mbs": mbs,
                "market": mkt,
                "selection": str(sig.get("selection") or ""),
                "odds": round(odd, 2),
                "fair_odd": round(float(sig.get("fair_odd") or sig.get("fair_odds") or 1.0), 2),
                "edge_pct": round(edge, 1),
                "stake_tl": round(stake, 0),
                "model_prob": round(float(sig.get("prob") or 0.0) * 100.0, 1),
                "source_engine": str(sig.get("source_engine") or "dual_engine"),
                "dual_confirmed": bool(sig.get("dual_confirmed", False)),
            }
        )
    return window_matches, qualified


def make_signal_key(sig: dict[str, Any]) -> str:
    """Build stable deduplication key per match, market, and selection."""
    return f"{sig['ko_date']}|{sig['home']} vs {sig['away']}|{sig['market']}|{sig['selection']}"


def load_seen_keys(path: Path = DEFAULT_SEEN_PATH) -> set[str]:
    """Load persisted deduplication keys from disk."""
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {str(x) for x in data}
        except Exception as exc:
            logger.warning(f"Could not read seen keys at {path}: {exc}")
    return set()


def save_seen_keys(keys: set[str], path: Path = DEFAULT_SEEN_PATH) -> None:
    """Persist deduplication keys atomically."""
    atomic_write_json(path, sorted(keys))


def format_watcher_telegram_batch(
    signals: list[dict[str, Any]],
    now_trt: datetime | None = None,
) -> str:
    """Format verified +EV MBS 1-2 signals (>=1.45 odds, >=50 TL) for Telegram."""
    ref_now = now_trt or datetime.now(TRT_TZ)
    lines = [
        "🎯 *[APE CANLI +EV İZLEYİCİ — DEĞER SİNYALLERİ]*",
        f"⏰ *Tarama:* `{ref_now.strftime('%H:%M')} TRT` | *Filtre:* `Oran ≥ 1.45 | EV ≥ %4 | MBS 1-2`",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for s in signals[:8]:
        ev_part = f" | Adil: `{s['fair_odd']:.2f}` | EV: `+%{s['edge_pct']:.1f}`" if "edge_pct" in s else ""
        stake_part = f" | Bahis: `{int(s['stake_tl'])} TL`" if "stake_tl" in s else ""
        src_lbl = "Çift Motor ✅" if s.get("dual_confirmed") else (
            "Keskin Piyasa" if s.get("source_engine") == "sharp_market" else "ELO + Poisson"
        )
        lines.append(
            f"• [{s['ko_str']}] *{s['home']} vs {s['away']}* (MBS {s['mbs']})\n"
            f"  🏆 _{s['league']}_ | `{src_lbl}`\n"
            f"  👉 *{s['selection']}* @ `{s['odds']:.2f}`{ev_part}{stake_part}"
        )
    if len(signals) > 8:
        lines.append(f"\n_...ve {len(signals) - 8} ek +EV sinyal daha._")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🔒 _SPEC-0013/0014/0015 aktif · Düşük çerez oranlar engellendi._")
    return "\n".join(lines)


def run_inplay_tracking_pass(dispatch_telegram: bool = True) -> dict[str, Any]:
    """Run one live in-play score & odds pass via LiveSniperDaemon."""
    try:
        from live_sniper_daemon import run_single_pass

        return run_single_pass(dispatch_telegram=dispatch_telegram)
    except Exception as exc:
        logger.warning(f"In-play tracking pass skipped/failed: {exc}")
        return {"error": str(exc), "matches_count": 0, "goal_opportunities": 0, "corner_opportunities": 0}


def run_watcher_cycle(
    min_prob: float = 0.65,
    min_odds: float = MIN_PLAYABLE_ODDS,
    max_odds: float = MAX_PLAYABLE_ODDS,
    min_ev_pct: float = MIN_WATCHER_EV_PCT,
    use_ev_pipeline: bool = True,
    seen_path: Path = DEFAULT_SEEN_PATH,
    heartbeat_path: Path = DEFAULT_HEARTBEAT_PATH,
    enable_telegram: bool = True,
    enable_inplay: bool = True,
    now_trt: datetime | None = None,
) -> dict[str, Any]:
    """Execute one pre-match Dual-Engine +EV scan + deduplicated alert + optional in-play pass."""
    ref_now = now_trt or datetime.now(TRT_TZ)
    if use_ev_pipeline:
        candidate_count, qualified = scan_verified_ev_signals(
            min_odds=min_odds,
            max_odds=max_odds,
            min_ev_pct=min_ev_pct,
            sync_ui_snapshot=(seen_path == DEFAULT_SEEN_PATH),
        )
    else:
        payload = fetch_nesine_pre_bulletin()
        candidates = extract_mbs12_candidates(payload, now_trt=ref_now)
        candidate_count = len(candidates)
        qualified = evaluate_high_prob_signals(
            candidates,
            min_prob=min_prob,
            min_odds=min_odds,
            max_odds=max_odds,
        )

    seen = load_seen_keys(seen_path)
    new_signals = [s for s in qualified if make_signal_key(s) not in seen]

    dispatched = False
    if new_signals and enable_telegram:
        msg = format_watcher_telegram_batch(new_signals, now_trt=ref_now)
        dispatched = send_telegram_message(msg)
        if dispatched:
            for s in new_signals:
                seen.add(make_signal_key(s))
            save_seen_keys(seen, seen_path)
    elif new_signals and not enable_telegram:
        for s in new_signals:
            seen.add(make_signal_key(s))
        save_seen_keys(seen, seen_path)

    inplay_res: dict[str, Any] = {}
    if enable_inplay:
        inplay_res = run_inplay_tracking_pass(dispatch_telegram=enable_telegram)

    summary = {
        "timestamp_trt": ref_now.isoformat(),
        "mode": "dual_engine_ev" if use_ev_pipeline else "high_prob_guarded",
        "min_odds": min_odds,
        "max_odds": max_odds,
        "min_ev_pct": min_ev_pct,
        "mbs12_candidates": candidate_count,
        "qualified_signals": len(qualified),
        "new_signals": len(new_signals),
        "telegram_dispatched": dispatched,
        "total_seen": len(seen),
        "inplay_matches": inplay_res.get("matches_count", 0),
        "inplay_goal_opps": inplay_res.get("goal_opportunities", 0),
        "inplay_corner_opps": inplay_res.get("corner_opportunities", 0),
    }
    atomic_write_json(heartbeat_path, summary)
    logger.info(
        f"Watcher cycle ({summary['mode']}): candidates={summary['mbs12_candidates']}, "
        f"qualified={summary['qualified_signals']}, new={summary['new_signals']}, "
        f"tg={dispatched}, inplay={summary['inplay_matches']}"
    )
    return summary


def compute_adaptive_interval_sec(
    summary: dict[str, Any] | None,
    live_interval_sec: int = 120,
    idle_interval_sec: int = 300,
) -> int:
    """Use faster 2-minute polling when live matches are active, else 5-minute idle polling."""
    live_count = int((summary or {}).get("inplay_matches") or 0)
    chosen = live_interval_sec if live_count > 0 else idle_interval_sec
    return max(30, int(chosen))


def run_watcher_loop(
    interval_sec: int = 300,
    live_interval_sec: int = 120,
    max_cycles: int | None = None,
    min_prob: float = 0.65,
    min_odds: float = MIN_PLAYABLE_ODDS,
    max_odds: float = MAX_PLAYABLE_ODDS,
    min_ev_pct: float = MIN_WATCHER_EV_PCT,
    enable_telegram: bool = True,
    enable_inplay: bool = True,
) -> None:
    """Run persistent adaptive watcher & live tracker loop (2m live, 5m idle)."""
    logger.info(
        f"Starting Autonomous Nesine Watcher (idle={interval_sec}s, live={live_interval_sec}s, "
        f"odds=[{min_odds:.2f}, {max_odds:.2f}], min_ev=+{min_ev_pct:.1f}%, "
        f"telegram={enable_telegram}, inplay={enable_inplay})"
    )
    cycle = 0
    while True:
        cycle += 1
        summary: dict[str, Any] | None = None
        try:
            summary = run_watcher_cycle(
                min_prob=min_prob,
                min_odds=min_odds,
                max_odds=max_odds,
                min_ev_pct=min_ev_pct,
                use_ev_pipeline=True,
                enable_telegram=enable_telegram,
                enable_inplay=enable_inplay,
            )
        except Exception as exc:
            logger.error(f"Cycle #{cycle} failed: {exc}", exc_info=True)

        if max_cycles is not None and cycle >= max_cycles:
            logger.info(f"Reached max_cycles={max_cycles}. Stopping watcher.")
            break
        sleep_sec = compute_adaptive_interval_sec(
            summary,
            live_interval_sec=live_interval_sec,
            idle_interval_sec=interval_sec,
        )
        logger.info(
            f"[AdaptivePoll] live_matches={(summary or {}).get('inplay_matches', 0)} -> sleeping {sleep_sec}s"
        )
        time.sleep(sleep_sec)


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous Adaptive Dual-Engine +EV Watcher")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--interval", type=int, default=300, help="Idle poll interval in seconds (default: 300)")
    parser.add_argument("--live-interval", type=int, default=120, help="Live poll interval in seconds (default: 120)")
    parser.add_argument("--min-odds", type=float, default=MIN_PLAYABLE_ODDS, help="Minimum decimal odds (default: 1.45)")
    parser.add_argument("--max-odds", type=float, default=MAX_PLAYABLE_ODDS, help="Maximum decimal odds (default: 6.50)")
    parser.add_argument("--min-ev", type=float, default=MIN_WATCHER_EV_PCT, help="Minimum EV%% (default: 4.0)")
    parser.add_argument("--min-prob", type=float, default=0.65, help="Legacy prob floor for fallback checks")
    parser.add_argument("--max-cycles", type=int, default=None, help="Max cycles before exit")
    parser.add_argument("--no-telegram", action="store_true", help="Dry-run without sending Telegram")
    parser.add_argument("--no-inplay", action="store_true", help="Disable live in-play pass")
    args = parser.parse_args()

    if args.once:
        run_watcher_cycle(
            min_prob=args.min_prob,
            min_odds=args.min_odds,
            max_odds=args.max_odds,
            min_ev_pct=args.min_ev,
            use_ev_pipeline=True,
            enable_telegram=not args.no_telegram,
            enable_inplay=not args.no_inplay,
        )
    else:
        run_watcher_loop(
            interval_sec=args.interval,
            live_interval_sec=args.live_interval,
            max_cycles=args.max_cycles,
            min_prob=args.min_prob,
            min_odds=args.min_odds,
            max_odds=args.max_odds,
            min_ev_pct=args.min_ev,
            enable_telegram=not args.no_telegram,
            enable_inplay=not args.no_inplay,
        )


if __name__ == "__main__":
    main()
