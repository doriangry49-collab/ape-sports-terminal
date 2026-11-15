"""Autonomous Live Stale-Line & Steam Monitoring Daemon.

Executes periodic scans against PropLine and Nesine CDN, detects steam moves,
logs new positive-EV arbitrage opportunities into the paper-trading ledger,
dispatches native Windows toast notifications for new signals, writes heartbeat
status, and refreshes the interactive web dashboard automatically.
"""

from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT_DIR / "output" / "live_monitor.log"
ALERTS_JSON = ROOT_DIR / "output" / "active_alerts.json"
ALERTS_LOG = ROOT_DIR / "output" / "live_alerts.log"
HEARTBEAT_JSON = ROOT_DIR / "output" / "daemon_heartbeat.json"
LEDGER_CSV = ROOT_DIR / "output" / "paper_trading_ledger.csv"
PID_LOCK_FILE = ROOT_DIR / "output" / "live_monitor_daemon.pid"
NESINE_TIMESERIES_DB = ROOT_DIR / "output" / "nesine_odds_timeseries.db"
UI_DIR = ROOT_DIR / "ui"
if UI_DIR.exists() and str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

try:
    from export_snapshot import generate_ui_snapshot

    from advanced_corner_model import AdvancedCornerEngine
    from atomic_io import atomic_write_json
    from build_dashboard import build_html
    from goal_anomaly_engine import (
        AnomalySignalTier,
        GoalAnomalyEngine,
        format_anomaly_telegram_alert,
        format_in_play_goal_anomaly_alert,
    )
    from live_settlement_engine import run_settlement_cycle
    from live_stale_line_adapter import fetch_and_scan_live_propline, fetch_nesine_live_bulletin
    from odds_pattern_miner import OddsPatternMiner, format_pattern_telegram_alert
    from team_strength_engine import TeamStrengthEngine
    from telegram_notifier import (
        check_and_reply_telegram_commands,
        format_corner_alert,
        load_telegram_offset,
        send_telegram_message,
    )
    from time_utils import parse_match_kickoff
    from value_engine import ValueScannerEngine, ValueSignal
except ImportError:
    from src.advanced_corner_model import AdvancedCornerEngine
    from src.atomic_io import atomic_write_json
    from src.build_dashboard import build_html
    try:
        from export_snapshot import generate_ui_snapshot
    except ImportError:
        try:
            from ui.export_snapshot import generate_ui_snapshot
        except ImportError:
            generate_ui_snapshot = None
    from src.live_settlement_engine import run_settlement_cycle
    from src.live_stale_line_adapter import fetch_and_scan_live_propline, fetch_nesine_live_bulletin
    from src.team_strength_engine import TeamStrengthEngine
    from src.telegram_notifier import (
        check_and_reply_telegram_commands,
        format_corner_alert,
        load_telegram_offset,
        send_telegram_message,
    )
    from src.time_utils import parse_match_kickoff
    from src.value_engine import ValueScannerEngine, ValueSignal
    try:
        from src.odds_pattern_miner import OddsPatternMiner, format_pattern_telegram_alert
    except ImportError:
        OddsPatternMiner, format_pattern_telegram_alert = None, None
    try:
        from src.goal_anomaly_engine import (
            AnomalySignalTier,
            GoalAnomalyEngine,
            format_anomaly_telegram_alert,
            format_in_play_goal_anomaly_alert,
        )
    except ImportError:
        GoalAnomalyEngine, format_anomaly_telegram_alert, format_in_play_goal_anomaly_alert, AnomalySignalTier = None, None, None, None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("LiveMonitor")

TRT_TZ = timezone(timedelta(hours=3))

_CACHED_TEAM_ENGINE: Any | None = None
_CACHED_CORNER_ENGINE: Any | None = None
_CACHED_PATTERN_MINER: Any | None = None
_CACHED_FINGERPRINT_ENGINE: Any | None = None
_CACHED_GOAL_ANOMALY_ENGINE: Any | None = None


def _get_cached_team_engine() -> Any:
    global _CACHED_TEAM_ENGINE
    if _CACHED_TEAM_ENGINE is None or type(_CACHED_TEAM_ENGINE) is not TeamStrengthEngine:
        eng = TeamStrengthEngine()
        if hasattr(eng, "load_or_train"):
            eng.load_or_train()
        _CACHED_TEAM_ENGINE = eng
    return _CACHED_TEAM_ENGINE


def _get_cached_corner_engine() -> Any:
    global _CACHED_CORNER_ENGINE
    if AdvancedCornerEngine is None or not isinstance(AdvancedCornerEngine, type):
        return AdvancedCornerEngine() if callable(AdvancedCornerEngine) else None
    if _CACHED_CORNER_ENGINE is None or type(_CACHED_CORNER_ENGINE) is not AdvancedCornerEngine:
        _CACHED_CORNER_ENGINE = AdvancedCornerEngine()
    return _CACHED_CORNER_ENGINE


def _get_cached_pattern_miner() -> Any:
    global _CACHED_PATTERN_MINER
    if _CACHED_PATTERN_MINER is None and OddsPatternMiner is not None:
        _CACHED_PATTERN_MINER = OddsPatternMiner()
    return _CACHED_PATTERN_MINER


def _get_cached_fingerprint_engine() -> Any:
    global _CACHED_FINGERPRINT_ENGINE
    if _CACHED_FINGERPRINT_ENGINE is None:
        try:
            from odds_fingerprint_engine import OddsFingerprintEngine
            _CACHED_FINGERPRINT_ENGINE = OddsFingerprintEngine()
        except Exception:
            try:
                from src.odds_fingerprint_engine import OddsFingerprintEngine
                _CACHED_FINGERPRINT_ENGINE = OddsFingerprintEngine()
            except Exception:
                _CACHED_FINGERPRINT_ENGINE = None
    return _CACHED_FINGERPRINT_ENGINE


def _get_cached_goal_anomaly_engine() -> Any:
    global _CACHED_GOAL_ANOMALY_ENGINE
    if _CACHED_GOAL_ANOMALY_ENGINE is None and GoalAnomalyEngine is not None:
        _CACHED_GOAL_ANOMALY_ENGINE = GoalAnomalyEngine()
    return _CACHED_GOAL_ANOMALY_ENGINE



def update_and_compute_nesine_steam(
    bulletin: list[dict[str, Any]],
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Track initial opening Nesine odds in SQLite (`nesine_odds_timeseries.db`) and compute live steam %."""
    if not bulletin:
        return bulletin
    target_db = db_path or NESINE_TIMESERIES_DB
    if target_db == ROOT_DIR / "output" / "nesine_odds_timeseries.db":
        if ALERTS_JSON.parent != ROOT_DIR / "output":
            target_db = ALERTS_JSON.parent / "nesine_odds_timeseries.db"
        elif HEARTBEAT_JSON.parent != ROOT_DIR / "output":
            target_db = HEARTBEAT_JSON.parent / "nesine_odds_timeseries.db"
    target_db.parent.mkdir(parents=True, exist_ok=True)
    now_utc = datetime.now(UTC).isoformat()

    try:
        with sqlite3.connect(str(target_db), timeout=5.0) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nesine_opening_odds (
                    fixture_key TEXT PRIMARY KEY,
                    first_seen_utc TEXT,
                    open_1 REAL,
                    open_x REAL,
                    open_2 REAL,
                    open_o25 REAL,
                    open_u25 REAL
                )
                """
            )
            cur = conn.cursor()
            for f in bulletin:
                d_str = str(f.get("date_str") or "").strip()
                h_str = str(f.get("home") or "").strip().lower()
                a_str = str(f.get("away") or "").strip().lower()
                if not h_str or not a_str:
                    continue
                fkey = f"{d_str}_{h_str}_{a_str}"

                nes_1x2 = f.get("nesine_1x2")
                c1, cx, c2 = (
                    (float(nes_1x2[0]), float(nes_1x2[1]), float(nes_1x2[2]))
                    if isinstance(nes_1x2, (tuple, list)) and len(nes_1x2) == 3
                    else (None, None, None)
                )
                nes_ou = f.get("nesine_ou25")
                co25, cu25 = (
                    (float(nes_ou[0]), float(nes_ou[1]))
                    if isinstance(nes_ou, (tuple, list)) and len(nes_ou) == 2
                    else (None, None)
                )

                cur.execute(
                    "SELECT open_1, open_x, open_2, open_o25, open_u25 FROM nesine_opening_odds WHERE fixture_key = ?",
                    (fkey,),
                )
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        """
                        INSERT INTO nesine_opening_odds (fixture_key, first_seen_utc, open_1, open_x, open_2, open_o25, open_u25)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (fkey, now_utc, c1, cx, c2, co25, cu25),
                    )
                    f["steam_1_pct"] = 0.0
                    f["steam_o25_pct"] = 0.0
                else:
                    op1, opx, op2, op_o25, op_u25 = row
                    steam_1 = (
                        round(((c1 - float(op1)) / float(op1)) * 100.0, 2)
                        if (c1 and op1 and float(op1) > 1.01)
                        else 0.0
                    )
                    steam_o25 = (
                        round(((co25 - float(op_o25)) / float(op_o25)) * 100.0, 2)
                        if (co25 and op_o25 and float(op_o25) > 1.01)
                        else 0.0
                    )
                    f["steam_1_pct"] = steam_1
                    f["steam_o25_pct"] = steam_o25
            conn.commit()
    except Exception as e:
        logger.debug(f"Nesine steam tracker warning: {e}")

    return bulletin


def parse_match_kickoff(
    date_str: str | None,
    time_str: str | None,
    now_trt: datetime | None = None,
    min_lead_minutes: int = 3,
    max_lead_hours: int = 12,
) -> tuple[datetime | None, str | None]:
    """Parse kickoff date and time strings into TRT datetime and ISO-UTC string.

    Enforces SPEC-0013 and SPEC-0014 fail-closed kickoff validation:
    - Matches starting within min_lead_minutes (default 3m) or in the past return (None, None).
    - Matches starting more than max_lead_hours (default 12h) in the future return (None, None).
    Returns (match_dt_trt, kickoff_iso_utc) if valid upcoming fixture in window, else (None, None).
    """
    if not date_str or not time_str:
        return None, None

    if now_trt is None:
        now_trt = datetime.now(TRT_TZ)

    d_clean = str(date_str).strip()
    t_clean = str(time_str).strip().lstrip("T")
    dt_combined = f"{d_clean} {t_clean}"

    match_dt = None
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            match_dt = datetime.strptime(dt_combined, fmt).replace(tzinfo=TRT_TZ)
            break
        except ValueError:
            pass

    if match_dt is None:
        return None, None

    # SPEC-0013: Skip finished or ongoing matches
    if match_dt <= now_trt + timedelta(minutes=min_lead_minutes):
        return None, None

    # SPEC-0014: Maximum 12-hour window limit
    if match_dt > now_trt + timedelta(hours=max_lead_hours):
        return None, None

    kickoff_iso = match_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return match_dt, kickoff_iso


def _is_corner_signal(s: dict[str, Any]) -> bool:
    if s.get("is_corner"):
        return True
    m_str = str(s.get("market") or "").lower()
    o_str = str(s.get("outcome") or "").lower()
    sel_str = str(s.get("selection") or "").lower()
    return any(k in m_str or k in o_str or k in sel_str for k in ("korner", "corner"))


def filter_mbs_signals(
    signals: list[dict[str, Any]],
    corner_mbs3_min_edge: float = 4.0,
    non_corner_mbs3_min_edge: float = 15.0,
) -> list[dict[str, Any]]:
    """Filter signals by MBS constraint, relaxing threshold for corners (>=4.0% vs >=15.0%)."""
    passed = []
    for s in signals:
        is_corner = _is_corner_signal(s)
        mbs_val = int(s.get("mbs", 1))
        edge_val = float(s.get("edge_pct", 0.0))
        if mbs_val > 2:
            if is_corner and edge_val < corner_mbs3_min_edge:
                continue
            elif not is_corner and edge_val < non_corner_mbs3_min_edge:
                continue
        passed.append(s)
    return passed


def _dispatch_priority_group(s: dict[str, Any]) -> int:
    """Assign dispatch priority: 0 = verified 1X2 value (+39.3% ROI), 1 = corners (8.5-10.5), 2 = others."""
    mkt = str(s.get("market") or "").strip().upper()
    has_real_odds = float(s.get("soft_odds") or s.get("offered_odds") or s.get("book_odd") or 0.0) > 1.01
    if mkt == "1X2" and (has_real_odds or s.get("is_value_signal") or s.get("is_steam_confirmed")):
        return 0
    if _is_corner_signal(s):
        return 1
    return 2


def prioritize_dispatch_queue(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order dispatch queue prioritizing verified 1X2 value signals first, then corners, then other markets."""
    return sorted(alerts, key=_dispatch_priority_group)


def send_windows_toast(title: str, message: str) -> bool:
    """Send a native Windows 10/11 Toast Notification via PowerShell."""
    ps_code = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$template = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>{title}</text>
            <text>{message}</text>
        </binding>
    </visual>
</toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("APE Sports-Engine").Show($toast)
"""
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
        return res.returncode == 0
    except Exception as e:
        logger.debug(f"Toast notification failed: {e}")
        return False


def load_seen_alerts() -> set[str]:
    """Load previously alerted signal IDs to avoid redundant alerts."""
    if ALERTS_JSON.exists():
        try:
            data = json.loads(ALERTS_JSON.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(data)
        except Exception as e:
            logger.debug(f"Failed to read {ALERTS_JSON}: {e}")
    return set()


def save_seen_alerts(alerts: set[str]) -> None:
    """Persist alerted signal IDs atomically."""
    try:
        atomic_write_json(ALERTS_JSON, sorted(alerts))
    except Exception as e:
        logger.warning(f"Could not save active alerts: {e}")


def send_telegram_startup_ping() -> bool:
    """Send a startup verification heartbeat to Telegram channel confirming bot health."""
    now_trt_str = datetime.now(TRT_TZ).strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        "🚀 *APE QUANT VIP SİNYAL MOTORU AKTİF (v2.0)*\n"
        "───────────────────────────────\n"
        "🛡️ *Model:* Shin Devigging + Dixon-Coles\n"
        "📊 *Filtre:* Min +%3.0 EV | Half-Kelly (0.5x)\n"
        "🎯 *Oran Bandı:* `1.35 - 3.50`\n"
        "⏰ *Pencere:* 12 Saatlik Kural (SPEC-0014) & TRT Kickoff (SPEC-0013)\n"
        f"📡 *Durum:* Canlı tarama devrede ({now_trt_str} TRT)\n"
        "───────────────────────────────\n"
        "🔒 _APE Quality OS: SPEC-0012 & Fail-Closed Hazır._"
    )
    success = send_telegram_message(msg)
    if success:
        logger.info("Telegram startup verification ping delivered successfully.")
    else:
        logger.warning("Telegram startup verification ping failed (check token or network).")
    return success


def format_signal_telegram(s: dict[str, Any] | ValueSignal) -> str:
    """Format an individual value signal into clean, actionable Telegram Markdown."""
    if isinstance(s, ValueSignal):
        return ValueScannerEngine.format_vip_telegram_message(s)

    if s.get("is_corner") or "korner" in str(s.get("market", "")).lower():
        return format_corner_alert(s)

    if s.get("is_value_signal") or ("ev_roi" in s and "fair_odds_shin" in s):
        return ValueScannerEngine.format_vip_telegram_message(s)

    home = s.get("home", "")
    away = s.get("away", "")
    market = s.get("market", "")
    outcome = s.get("outcome", "")
    odds = float(s.get("soft_odds", 0.0))
    fair = float(s.get("fair_odds", 0.0))
    edge = float(s.get("edge_pct", 0.0))
    prob = float(s.get("prob", 0.0)) * 100
    mbs = s.get("mbs", 1)
    time_str = s.get("time", "")
    is_steam = s.get("is_steam_confirmed", False)
    tier = str(s.get("tier", "TIER_2_VALUE"))

    badge = "⚡ *[STEAM ONAYLI]*" if is_steam else "🎯 *[YENİ +EV SİNYALİ]*"
    time_prefix = f"⏰ *{time_str}* | " if time_str else ""
    mbs_str = f" (MBS {mbs})" if mbs else ""

    lines = [
        f"{badge}",
        f"{time_prefix}⚽ *{home} vs {away}*{mbs_str}",
        f"👉 *Piyasa:* {market} ➔ *{outcome}*",
        f"📊 *Nesine:* `{odds:.2f}` (Adil: `{fair:.2f}`)",
        f"📈 *Kazanma Şansı:* `%{prob:.1f}` | *Edge:* `+%{edge:.1f}%`",
    ]
    if "TIER_1" in tier:
        lines.append("🛡️ *Kategori:* TIER 1 KASA KALKANI")

    # Display Syndicate Agent Committee Verdicts if available
    votes = s.get("committee_votes")
    if votes and isinstance(votes, list):
        summary_parts = []
        for v in votes:
            agent_n = v.get("agent", "")
            appr = v.get("approved", False)
            icon = "✅" if appr else "❌"
            if "Risk" in agent_n:
                summary_parts.append(f"🛡️ Risk: {icon}")
            elif "Market" in agent_n:
                summary_parts.append(f"📈 Market: {icon}")
            elif "Quant" in agent_n:
                summary_parts.append(f"🔬 Quant: {icon}")
            elif "Props" in agent_n:
                summary_parts.append(f"🎯 Props: {icon}")
            elif "Odds" in agent_n or "Analyst" in agent_n:
                summary_parts.append(f"🧬 k-NN: {icon}")
        if summary_parts:
            lines.append("👥 *Sindika Konseyi:* " + " | ".join(summary_parts))
    return "\n".join(lines)


def scan_quant_engine_signals(
    min_edge_pct: float = 3.0,
    bulletin: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Scan live Nesine bulletin fixtures against quantitative empirical Bayes engine and Shin devigging."""
    try:
        if bulletin is None:
            bulletin = fetch_nesine_live_bulletin()
        if not bulletin:
            return []
        update_and_compute_nesine_steam(bulletin)
        engine = _get_cached_team_engine()
        corner_engine = _get_cached_corner_engine()
        fp_engine = _get_cached_fingerprint_engine()
        val_engine = ValueScannerEngine(
            min_ev_roi=0.03,
            min_prob_edge=0.015,
            min_odds=1.35,
            max_odds=3.50,
            enforce_time_window=True,
        )

        now_trt = datetime.now(TRT_TZ)

        signals = []
        for fixture in bulletin:
            # Kickoff validation (SPEC-0013 & SPEC-0014): strictly skip finished/distant matches
            match_dt, kickoff_iso = parse_match_kickoff(
                fixture.get("date_str"), fixture.get("time_str"), now_trt=now_trt
            )
            if match_dt is None or kickoff_iso is None:
                continue

            # Evaluate 1X2 using ValueScannerEngine with Shin margin devigging & Kelly sizing
            # Only run team-strength 1X2 pricing when both teams exist in historical ratings (matches > 0)
            if hasattr(engine, "get_team_rating"):
                h_rating = engine.get_team_rating(fixture.get("home", ""))
                a_rating = engine.get_team_rating(fixture.get("away", ""))
                both_teams_known = int(h_rating.get("matches", 0)) > 0 and int(a_rating.get("matches", 0)) > 0
            else:
                both_teams_known = True

            odds_1x2 = fixture.get("nesine_1x2")
            steam_1_pct = float(fixture.get("steam_1_pct", 0.0))
            steam_o25_pct = float(fixture.get("steam_o25_pct", 0.0))

            # Optional 3D Fingerprint lookup for cross-validation (k-NN twins on de-vigged odds)
            fp_res = None
            if fp_engine is not None:
                try:
                    fp_res = fp_engine.scan_fixture(fixture, k=50)
                except Exception as fe:
                    logger.debug(f"Fingerprint lookup failed for {fixture.get('home')}: {fe}")
                    fp_res = None

            if both_teams_known and odds_1x2 and len(odds_1x2) == 3:
                try:
                    preds = engine.predict_match(fixture.get("home", ""), fixture.get("away", ""))
                    m_probs = [
                        preds["p_1x2"]["1"],
                        preds["p_1x2"]["X"],
                        preds["p_1x2"]["2"],
                    ]
                    val_sigs = val_engine.scan_1x2_fixture(
                        fixture_id=str(fixture.get("nesine_code") or f"{fixture.get('home')}_{fixture.get('away')}"),
                        league=str(fixture.get("league", "Nesine")),
                        home_team=fixture.get("home", ""),
                        away_team=fixture.get("away", ""),
                        kickoff_dt=match_dt,
                        market_odds=list(odds_1x2),
                        model_probs=m_probs,
                        bookmaker="NESINE",
                    )
                    for vs in val_sigs:
                        # Walk-Forward Gate: Allow 1X2 value up to 3.20 (or up to 3.50 when backed by Steam or high EV)
                        is_steam_1x2 = bool(vs.selection in ("MS 1", "1") and steam_1_pct <= -4.0)
                        if vs.offered_odds > 3.20 and not is_steam_1x2 and vs.ev_roi < 8.0:
                            continue
                        signals.append({
                            "home": vs.home_team,
                            "away": vs.away_team,
                            "market": vs.market,
                            "outcome": vs.selection,
                            "selection": vs.selection,
                            "soft_book": "nesine",
                            "soft_odds": vs.offered_odds,
                            "fair_odds": vs.fair_odds_shin,
                            "fair_odds_shin": vs.fair_odds_shin,
                            "edge_pct": vs.edge_pct,
                            "ev_roi": vs.ev_roi,
                            "prob": vs.model_prob,
                            "half_kelly": vs.half_kelly,
                            "shin_margin": vs.shin_margin,
                            "shin_z": vs.shin_z,
                            "mbs": fixture.get("mbs", 1),
                            "time": fixture.get("time_str", ""),
                            "kickoff": kickoff_iso,
                            "kickoff_trt": vs.kickoff_trt,
                            "tier": "TIER_1_SHIN_QUANT" if (is_steam_1x2 or vs.ev_roi >= 6.0) else "TIER_2_SHIN_VALUE",
                            "is_steam_confirmed": is_steam_1x2,
                            "is_corner": False,
                            "is_value_signal": True,
                        })
                except Exception as ve:
                    logger.debug(f"Value engine evaluation error for fixture {fixture.get('home')}: {ve}")

            f_sigs = engine.evaluate_live_fixture(fixture, min_edge_pct=min_edge_pct)
            # 10-Month & 4-Season (23,474 matches) Walk-Forward Gate:
            # 1. Always filter out raw un-devigged 1X2 when ValueScannerEngine already evaluated 1X2 with Shin devigging
            # 2. Drop negative-EV high-variance traps proven to bleed in 10-month backtests (İY/MS, Toplam Gol TG 6+)
            # 3. Restrict Çifte Şans strictly to 1.32-1.60 Shield range when both teams are known
            # 4. Enforce 3D Consensus (TeamStrength + Fingerprint k-NN + Steam) on 2.5 Gol
            fp_valid = fp_res is not None
            fp_o25 = float(fp_res.pct_ft_o25) if fp_valid else 50.0
            fp_u25 = 100.0 - fp_o25

            vetted_f_sigs = []
            for s in f_sigs:
                mkt_str = str(s.get("market", ""))
                sel_str = str(s.get("selection") or s.get("outcome") or "")
                b_odd = float(s.get("book_odd") or s.get("soft_odds") or 0.0)
                if mkt_str == "1X2":
                    # Only filter out raw 1X2 if ValueScannerEngine already handled this fixture
                    if both_teams_known and odds_1x2 and len(odds_1x2) == 3 and hasattr(engine, "predict_match"):
                        continue
                if mkt_str in ("İY/MS", "Toplam Gol") or "Çifte Şans" in mkt_str or "korner" in mkt_str.lower():
                    # Unverified side markets without reliable sharp benchmark are disabled
                    continue
                if "2.5 Gol" in mkt_str:
                    if not both_teams_known:
                        continue
                    is_over = "ÜST" in sel_str.upper() or "UST" in sel_str.upper()
                    if is_over:
                        if fp_valid and fp_o25 < 56.0 and steam_o25_pct > -2.5:
                            continue
                    else:
                        if (fp_valid and fp_u25 < 52.0) or steam_o25_pct <= -2.5:
                            continue
                vetted_f_sigs.append(s)
            f_sigs = vetted_f_sigs

            # Drop any residual corner signals from TeamStrengthEngine (corner side engine disabled)
            f_sigs = [
                s for s in f_sigs
                if not s.get("is_corner") and "korner" not in str(s.get("market", "")).lower()
            ]

            for s in f_sigs:
                is_corner = bool(s.get("is_corner") or "korner" in str(s.get("market", "")).lower())
                mkt_name = str(s.get("market", ""))
                sel_name = str(s.get("outcome") or s.get("selection", ""))
                is_steam_tot = bool("2.5" in mkt_name and "ÜST" in sel_name.upper() and steam_o25_pct <= -2.5)
                tier_val = "TIER_1_SHIELD" if is_steam_tot else s.get("tier", "TIER_2_VALUE")
                signals.append({
                    "home": fixture.get("home", ""),
                    "away": fixture.get("away", ""),
                    "market": mkt_name,
                    "outcome": sel_name,
                    "selection": s.get("selection", ""),
                    "soft_book": "nesine",
                    "soft_odds": s.get("soft_odds") or s.get("book_odd", 0.0),
                    "fair_odds": s.get("fair_odds") or s.get("fair_odd", 0.0),
                    "edge_pct": s.get("edge_pct", 0.0),
                    "prob": s.get("prob", 0.0),
                    "mbs": s.get("mbs", 1),
                    "time": s.get("time", ""),
                    "kickoff": kickoff_iso,
                    "tier": tier_val,
                    "is_steam_confirmed": is_steam_tot,
                    "is_corner": is_corner,
                    "expected_corners": s.get("expected_corners"),
                    "distribution": s.get("distribution"),
                    "line": s.get("line"),
                    "side": s.get("side"),
                    "diagnostics": s.get("diagnostics"),
                })
        return signals
    except Exception as e:
        logger.warning(f"Quant scan failed: {e}")
        return []


def scan_odds_patterns(
    min_lead_minutes: int = 3,
    max_lead_hours: int = 12,
    bulletin: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Disabled side engine: Golden Pattern scanner retired due to unverified edge."""
    return []


def scan_goal_anomalies(
    min_lead_minutes: int = 3,
    max_lead_hours: int = 12,
    bulletin: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Disabled side engine: Goal Anomaly (GASI) scanner retired (21.4% live hit rate / synthetic edge)."""
    return []



def run_single_scan_cycle(
    settle_espn: bool = True,
    enable_telegram: bool = False,
    scan_quant: bool = False,
    min_edge: float = 4.0,
) -> dict[str, Any]:
    """Execute a single scan iteration, record signals, and update dashboard."""
    start_t = time.time()
    logger.info("Starting live scan cycle across target leagues and Nesine CDN...")

    result = fetch_and_scan_live_propline(settle_espn=settle_espn)
    elapsed = round(time.time() - start_t, 2)

    leagues = result.get("leagues_scanned", 0)
    fixtures = result.get("fixtures_with_pinnacle", 0)
    matched = result.get("nesine_matched_fixtures", 0)
    steam_signals = result.get("steam_confirmed_signals_count", 0)
    signals_list = result.get("signals", [])

    all_incoming = list(signals_list)
    if scan_quant:
        shared_bulletin = None
        try:
            shared_bulletin = fetch_nesine_live_bulletin()
            if shared_bulletin:
                update_and_compute_nesine_steam(shared_bulletin)
        except Exception as be:
            logger.debug(f"Bulletin pre-fetch warning: {be}")

        quant_signals = scan_quant_engine_signals(min_edge_pct=min_edge, bulletin=shared_bulletin)
        all_incoming.extend(quant_signals)

    # Sort incoming signals by edge descending
    all_incoming.sort(key=lambda x: float(x.get("edge_pct", 0.0)), reverse=True)

    logger.info(
        f"Scan completed in {elapsed}s | Leagues: {leagues} | Fixtures: {fixtures} | "
        f"Nesine Matched: {matched}/{fixtures} | Total +EV Signals: {len(all_incoming)} (Steam: {steam_signals})"
    )

    # Signal deduplication and alert dispatching
    seen_alerts = load_seen_alerts()
    new_alerts: list[dict[str, Any]] = []
    now_utc = datetime.now(UTC)

    pending_toasts: list[tuple[str, str]] = []

    # Filter all incoming signals through Syndicate Committee (P0 -> P3 Prioritized Review)
    committee = None
    try:
        from syndicate.committee import SyndicateCommittee
        committee = SyndicateCommittee()
    except Exception as ce:
        logger.debug(f"Could not load SyndicateCommittee: {ce}")

    for s in all_incoming:
        # Strictly reject any match that has already started or finished, or is outside the 12-hour window (SPEC-0013 & SPEC-0014)
        ko = s.get("kickoff")
        if not ko:
            continue  # Fail-closed: missing or undefined kickoff must be rejected per SPEC-0013
        try:
            ko_dt = datetime.fromisoformat(str(ko).replace("Z", "+00:00"))
            if ko_dt <= now_utc + timedelta(minutes=3) or ko_dt > now_utc + timedelta(hours=12):
                continue
        except Exception:
            continue

        # SPEC-0012 Fail-Closed: Reject dummy/unverified odds (<= 1.01) or unpriced pattern labels
        soft_odds_val = float(s.get("soft_odds") or s.get("offered_odds") or s.get("book_odd") or 0.0)
        mkt_upper = str(s.get("market") or "").upper()
        out_upper = str(s.get("outcome") or s.get("selection") or "").upper()
        if soft_odds_val <= 1.01 or mkt_upper == "GOLDEN_PATTERN":
            continue

        # Block unprofitable high corner Over lines (11.5 ÜST and 12.5 ÜST)
        if _is_corner_signal(s) and ("ÜST" in out_upper or "UST" in out_upper or "OVER" in out_upper):
            if any(hl in mkt_upper or hl in out_upper for hl in ("11.5", "12.5")) or float(s.get("line") or 0.0) >= 11.5:
                continue

        # Prefer playable matches (MBS 1 or 2), or high-edge MBS 3 (relax threshold to 4.0% for corners)
        if not filter_mbs_signals([s]):
            continue

        # Syndicate Committee Veto & Consensus Audit (never bypassed)
        if committee is not None:
            review = committee.review_signal(s)
            if not review.get("approved"):
                logger.info(
                    f"[SYNDICATE VETO] {s.get('home')} vs {s.get('away')} | "
                    f"{s.get('market')} {s.get('selection')} rejected: {review.get('veto_reason')}"
                )
                continue
            s["tier"] = review.get("final_tier", s.get("tier"))
            s["consensus_score"] = review.get("consensus_score")
            s["committee_votes"] = review.get("agent_verdicts")

        sig_id = (
            f"{s.get('home')}_{s.get('away')}_{s.get('market')}_"
            f"{s.get('outcome')}_{s.get('soft_book')}"
        )
        if sig_id not in seen_alerts:
            seen_alerts.add(sig_id)
            new_alerts.append(s)

            is_steam = s.get("is_steam_confirmed", False)
            is_pattern = s.get("is_golden_pattern", False)
            if is_pattern:
                prefix = "🏆 [ALTIN ÖRÜNTÜ]"
                toast_title = f"{prefix} {s.get('home')} vs {s.get('away')}"
                toast_body = f"{s.get('outcome')} | {s.get('selection')}"
            else:
                prefix = "⚡ [STEAM ONAYLI]" if is_steam else "🎯 [+EV FIRSATI]"
                toast_title = f"{prefix} {s.get('home')} vs {s.get('away')}"
                toast_body = (
                    f"{s.get('market')} / {s.get('outcome')} @ {s.get('soft_odds', 0):.2f} "
                    f"({s.get('soft_book', '').upper()}) | Edge: +%{s.get('edge_pct', 0):.2f}"
                )

            logger.info(f"NEW SIGNAL: {toast_title} -> {toast_body}")

            # Append to log file
            try:
                target_alerts_log = ALERTS_LOG
                if target_alerts_log == ROOT_DIR / "output" / "live_alerts.log":
                    if ALERTS_JSON.parent != ROOT_DIR / "output":
                        target_alerts_log = ALERTS_JSON.parent / "live_alerts.log"
                    elif HEARTBEAT_JSON.parent != ROOT_DIR / "output":
                        target_alerts_log = HEARTBEAT_JSON.parent / "live_alerts.log"
                target_alerts_log.parent.mkdir(parents=True, exist_ok=True)
                with target_alerts_log.open("a", encoding="utf-8") as f_log:
                    f_log.write(
                        f"[{datetime.now(UTC).isoformat()}] {toast_title} | {toast_body}\n"
                    )
            except Exception as e:
                logger.warning(f"Could not append to alerts log: {e}")

            pending_toasts.append((toast_title, toast_body))

    # Dispatch desktop toast notifications in a single summary when multiple signals arrive
    if len(pending_toasts) == 1:
        send_windows_toast(pending_toasts[0][0], pending_toasts[0][1])
    elif len(pending_toasts) > 1:
        top_title, top_body = pending_toasts[0]
        send_windows_toast(
            f"🎯 [{len(pending_toasts)} YENİ +EV SİNYALİ] {top_title}",
            top_body,
        )

    # Dispatch to Telegram (Rate-limited: Top 3 individual + digest if more)
    if enable_telegram and new_alerts:
        logger.info(f"Dispatching {len(new_alerts)} new alerts to Telegram...")
        # Prioritize corner alerts so they are not crowded out by nominal longshot crowding
        dispatch_alerts = prioritize_dispatch_queue(new_alerts)

        for s in dispatch_alerts[:3]:
            if s.get("is_golden_pattern") and s.get("pattern_data") and format_pattern_telegram_alert:
                tg_text = format_pattern_telegram_alert(s.get("fixture_data") or s, s["pattern_data"])
            elif s.get("is_goal_anomaly") and s.get("anomaly_result") and format_anomaly_telegram_alert:
                tg_text = format_anomaly_telegram_alert(
                    s["anomaly_result"], kickoff_str=s.get("time", ""), mbs=s.get("mbs", 1)
                )
            elif (s.get("is_corner") or "korner" in str(s.get("market", "")).lower()):
                tg_text = format_corner_alert(s)
            else:
                tg_text = format_signal_telegram(s)
            send_telegram_message(tg_text)
            time.sleep(0.5)

        if len(dispatch_alerts) > 3:
            remaining = len(dispatch_alerts) - 3
            digest = (
                f"🔔 *Bültende {remaining} ek +EV sinyal daha tespit edildi.*\n"
                f"Tüm sinyalleri ve canlı oran hareketlerini görmek için dashboard'u kontrol edebilirsiniz."
            )
            send_telegram_message(digest)

    if new_alerts:
        save_seen_alerts(seen_alerts)
        logger.info(f"Dispatched {len(new_alerts)} new +EV alerts (Desktop + Telegram).")
        try:
            try:
                from paper_trader import PaperTradingEngine
            except ImportError:
                from src.paper_trader import PaperTradingEngine
            target_ledger = LEDGER_CSV
            if target_ledger == ROOT_DIR / "output" / "paper_trading_ledger.csv" and ALERTS_JSON.parent != ROOT_DIR / "output":
                target_ledger = ALERTS_JSON.parent / "paper_trading_ledger.csv"
            playable_alerts = [
                a for a in new_alerts
                if float(a.get("soft_odds") or a.get("offered_odds") or 0.0) > 1.01
                and str(a.get("market") or "").upper() != "GOLDEN_PATTERN"
            ]
            if playable_alerts:
                PaperTradingEngine(ledger_path=target_ledger).record_value_signals(playable_alerts)
        except Exception as pe:
            logger.debug(f"Paper trading recording error: {pe}")

    # Rebuild web dashboard and update UI snapshot
    build_html()
    try:
        is_isolated_test = HEARTBEAT_JSON.parent != ROOT_DIR / "output"
        if not is_isolated_test:
            if "generate_ui_snapshot" in globals() and generate_ui_snapshot is not None:
                generate_ui_snapshot()
            else:
                if str(UI_DIR) not in sys.path:
                    sys.path.insert(0, str(UI_DIR))
                from export_snapshot import generate_ui_snapshot as _gen_ui
                _gen_ui()
    except Exception as e:
        logger.warning(f"UI snapshot export notice: {e}")
    logger.info("Interactive dashboard HTML and UI snapshot refreshed successfully.")

    # Settle active tickets from live ESPN match scores
    if settle_espn:
        try:
            settle_res = run_settlement_cycle()
            if settle_res.get("settled_coupons", 0) > 0:
                logger.info(
                    f"Settled {settle_res['settled_coupons']} coupons! New Winnings: {settle_res['new_winnings']:.2f} TL"
                )
        except Exception as e:
            logger.debug(f"Settlement cycle error: {e}")

    # Side engines (In-Play Sniper, In-Play Goal Anomaly, Copula SGP) disabled:
    # No free live corner/SGP odds feeds exist and empirical live hit rates were unprofitable.
    in_play_opps: list[dict[str, Any]] = []
    in_play_goal_opps: list[dict[str, Any]] = []
    sgp_opps: list[dict[str, Any]] = []

    # CLV Alpha Attribution Report Refresh (Proposal 5)
    try:
        from clv_alpha_attribution import CLVAlphaAttributionEngine
        if HEARTBEAT_JSON.parent == ROOT_DIR / "output":
            CLVAlphaAttributionEngine().generate_and_export_report()
        else:
            CLVAlphaAttributionEngine().generate_and_export_report(
                ledger_path=HEARTBEAT_JSON.parent / "paper_trading_ledger.csv",
                output_path=HEARTBEAT_JSON.parent / "clv_alpha_report.json",
            )
    except Exception as ae:
        logger.debug(f"CLV Alpha attribution refresh error: {ae}")

    # Write heartbeat atomically
    try:
        heartbeat_data = {
            "status": "HEALTHY",
            "last_cycle_utc": datetime.now(UTC).isoformat(),
            "elapsed_seconds": elapsed,
            "leagues_scanned": leagues,
            "fixtures_scanned": fixtures,
            "nesine_matched": matched,
            "positive_ev_signals": len(all_incoming),
            "steam_confirmed_signals": steam_signals,
            "new_alerts_in_cycle": len(new_alerts),
            "total_seen_alerts": len(seen_alerts),
            "in_play_opportunities": len(in_play_opps),
            "in_play_goal_opportunities": len(in_play_goal_opps),
            "sgp_opportunities": len(sgp_opps),
        }
        atomic_write_json(HEARTBEAT_JSON, heartbeat_data)
    except Exception as e:
        logger.warning(f"Could not write heartbeat: {e}")

    result["in_play_opportunities"] = in_play_opps
    result["in_play_goal_opportunities"] = in_play_goal_opps
    result["sgp_opportunities"] = sgp_opps
    return result


_LISTENER_THREAD: threading.Thread | None = None


def _is_pid_alive(pid: int) -> bool:
    """Return True if an OS Python process with the given PID is currently running."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                if not (ok and exit_code.value == 259):
                    return False
                buf_len = ctypes.c_ulong(1024)
                buf = ctypes.create_unicode_buffer(1024)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(buf_len)):
                    exe_name = Path(buf.value).name.lower()
                    if exe_name and "python" not in exe_name:
                        return False
                return True
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def release_daemon_pid_lock(lock_file: Path | None = None) -> None:
    """Release the single-instance PID lockfile if owned by the current process."""
    target = lock_file or PID_LOCK_FILE
    try:
        if target.exists():
            raw = target.read_text(encoding="utf-8").strip()
            if raw.isdigit() and int(raw) == os.getpid():
                target.unlink(missing_ok=True)
    except Exception:
        pass


def acquire_daemon_pid_lock(lock_file: Path | None = None) -> bool:
    """Acquire single-instance PID lock to prevent concurrent Telegram getUpdates HTTP 409 Conflicts."""
    target = lock_file or PID_LOCK_FILE
    my_pid = os.getpid()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raw = target.read_text(encoding="utf-8").strip()
            if raw.isdigit():
                existing_pid = int(raw)
                if existing_pid == my_pid:
                    return True
                if _is_pid_alive(existing_pid):
                    logger.warning(
                        f"Another LiveMonitor daemon instance (PID {existing_pid}) is already active; "
                        f"skipping duplicate instance to prevent Telegram HTTP 409 Conflict."
                    )
                    return False
        target.write_text(str(my_pid), encoding="utf-8")
        atexit.register(release_daemon_pid_lock, target)
        return True
    except Exception as e:
        logger.debug(f"PID lock check notice: {e}")
        return True


def start_telegram_listener_thread() -> threading.Thread | None:
    """Start an independent background daemon thread to instantly process Telegram commands."""
    global _LISTENER_THREAD
    if _LISTENER_THREAD is not None and _LISTENER_THREAD.is_alive():
        return _LISTENER_THREAD
    if not acquire_daemon_pid_lock():
        return None

    def _worker():
        logger.info("Telegram interactive listener thread started (1.5s poll).")
        offset = load_telegram_offset()
        if offset is not None:
            logger.info(f"Loaded persisted Telegram offset: {offset}")
        else:
            logger.info("No prior Telegram offset found; initializing clean listener.")
        while True:
            try:
                offset = check_and_reply_telegram_commands(offset)
            except Exception as e:
                logger.warning(f"Telegram polling warning: {e}")
            time.sleep(1.5)

    thread = threading.Thread(target=_worker, daemon=True, name="TelegramListener")
    thread.start()
    _LISTENER_THREAD = thread
    return thread


def start_monitor_loop(
    interval_sec: int = 120,
    max_cycles: int | None = None,
    enable_telegram: bool = True,
    scan_quant: bool = True,
    min_edge: float = 3.0,
) -> None:
    """Run recurring scan loop with specified sleep interval and interactive Telegram polling."""
    logger.info(f"Starting Live Monitor Daemon (Interval: {interval_sec}s, Telegram: {enable_telegram})...")
    if enable_telegram:
        send_telegram_startup_ping()
        start_telegram_listener_thread()

    cycle = 0
    while True:
        cycle += 1
        logger.info(f"--- Cycle #{cycle} at {datetime.now(UTC).isoformat()} ---")
        try:
            run_single_scan_cycle(
                enable_telegram=enable_telegram,
                scan_quant=scan_quant,
                min_edge=min_edge,
            )
        except Exception as e:
            logger.error(f"Error during scan cycle #{cycle}: {e}", exc_info=True)

        if max_cycles and cycle >= max_cycles:
            logger.info(f"Reached max cycles ({max_cycles}). Exiting daemon.")
            break

        logger.info(f"Sleeping for {interval_sec} seconds until next cycle...")
        time.sleep(interval_sec)


def main():
    parser = argparse.ArgumentParser(description="Live Stale-Line & Steam Monitor Daemon")
    parser.add_argument("--once", action="store_true", help="Run a single scan cycle and exit")
    parser.add_argument("--interval", type=int, default=120, help="Scan interval in seconds (default: 120 / 2m)")
    parser.add_argument("--max-cycles", type=int, default=None, help="Maximum number of cycles before exit")
    parser.add_argument("--no-telegram", action="store_true", help="Disable Telegram alerts")
    parser.add_argument("--no-quant", action="store_true", help="Disable Poisson quant engine scan")
    parser.add_argument("--min-edge", type=float, default=3.0, help="Minimum edge % threshold (default: 3.0)")
    parser.add_argument("--ping-only", action="store_true", help="Send Telegram startup verification ping and exit")
    parser.add_argument("--ping", action="store_true", help="Send Telegram verification ping before running cycle")
    args = parser.parse_args()

    if args.ping_only:
        send_telegram_startup_ping()
        sys.exit(0)

    enable_tg = not args.no_telegram
    scan_q = not args.no_quant

    if enable_tg and args.ping:
        send_telegram_startup_ping()

    if args.once:
        run_single_scan_cycle(enable_telegram=enable_tg, scan_quant=scan_q, min_edge=args.min_edge)
    else:
        if not acquire_daemon_pid_lock():
            sys.exit(0)
        start_monitor_loop(
            interval_sec=args.interval,
            max_cycles=args.max_cycles,
            enable_telegram=enable_tg,
            scan_quant=scan_q,
            min_edge=args.min_edge,
        )


if __name__ == "__main__":
    main()
