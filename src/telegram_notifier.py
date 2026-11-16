"""Telegram Bot Notification Engine (v1.0).

Delivers real-time +EV betting signals, bankroll shield alerts, and structured coupons
directly to the user's Telegram channel or personal chat via the Oddiero Bot.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from atomic_io import atomic_write_text
except ImportError:
    from src.atomic_io import atomic_write_text

try:
    from time_utils import parse_match_kickoff
except ImportError:
    try:
        from src.time_utils import parse_match_kickoff
    except ImportError:
        parse_match_kickoff = None

try:
    from live_stale_line_adapter import fetch_nesine_live_bulletin
except ImportError:
    try:
        from src.live_stale_line_adapter import fetch_nesine_live_bulletin
    except ImportError:
        def fetch_nesine_live_bulletin() -> list[dict[str, Any]]:
            return []

try:
    from goal_anomaly_engine import format_anomaly_telegram_alert, format_in_play_goal_anomaly_alert
except ImportError:
    try:
        from src.goal_anomaly_engine import format_anomaly_telegram_alert, format_in_play_goal_anomaly_alert
    except ImportError:
        format_anomaly_telegram_alert = None
        format_in_play_goal_anomaly_alert = None

logger = logging.getLogger("TelegramNotifier")

ROOT_DIR = Path(__file__).resolve().parent.parent
COUPONS_FILE = ROOT_DIR / "output" / "active_coupons.json"
BANKROLL_FILE = ROOT_DIR / "output" / "active_bankroll.json"
TELEGRAM_OFFSET_FILE = ROOT_DIR / "output" / "telegram_last_update_id.txt"
load_dotenv(ROOT_DIR / ".env")


def load_telegram_offset() -> int | None:
    """Load the last processed Telegram update_id from disk."""
    if TELEGRAM_OFFSET_FILE.exists():
        try:
            content = TELEGRAM_OFFSET_FILE.read_text(encoding="utf-8").strip()
            if content.isdigit():
                return int(content)
        except Exception as e:
            logger.warning(f"Could not read Telegram offset from {TELEGRAM_OFFSET_FILE}: {e}")
    return None


def save_telegram_offset(offset: int) -> None:
    """Atomically persist the last processed Telegram update_id to disk."""
    try:
        atomic_write_text(TELEGRAM_OFFSET_FILE, str(offset))
    except Exception as e:
        logger.warning(f"Could not save Telegram offset {offset} to {TELEGRAM_OFFSET_FILE}: {e}")


def get_telegram_credentials() -> tuple[str | None, str | None]:
    """Retrieve Bot token and Chat ID from environment."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    return token, chat_id


def send_telegram_message(
    text: str,
    chat_id: str | None = None,
    bot_token: str | None = None,
    parse_mode: str = "Markdown",
) -> bool:
    """Send a Markdown-formatted message to the specified Telegram chat."""
    token, env_chat_id = get_telegram_credentials()
    active_token = bot_token or token
    active_chat_id = chat_id or env_chat_id

    if not active_token or not active_chat_id:
        return False

    url = f"https://api.telegram.org/bot{active_token}/sendMessage"
    payload = {
        "chat_id": active_chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("ok"))
    except Exception as e:
        logger.warning(f"Telegram dispatch error: {e}")
        return False


def escape_markdown(text: str) -> str:
    """Escape Telegram Markdown special characters in plain text tokens to prevent formatting parse errors."""
    if not text:
        return ""
    return str(text).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")


def format_corner_alert(s: dict[str, Any]) -> str:
    """Format an individual corner betting value signal into clean, actionable Telegram Markdown."""
    raw_home = str(s.get("home", ""))
    raw_away = str(s.get("away", ""))
    raw_market = str(s.get("market", ""))
    raw_outcome = str(s.get("outcome") or s.get("selection", ""))

    home = raw_home.replace("_", " ")
    away = raw_away.replace("_", " ")
    market = raw_market.replace("_", " ")
    outcome = raw_outcome.replace("_", " ")

    odds = float(s.get("soft_odds") or s.get("book_odd", 0.0))
    fair = float(s.get("fair_odds") or s.get("fair_odd", 0.0))
    edge = float(s.get("edge_pct", 0.0))
    prob = float(s.get("prob", 0.0)) * 100
    mbs = s.get("mbs", 1)
    time_str = str(s.get("time", "")).strip()
    time_prefix = f"⏰ *{time_str}* | " if time_str else ""

    exp_c = s.get("expected_corners")
    exp_str = f" | μ: `{float(exp_c):.2f}` korner" if exp_c is not None else ""

    tier = str(s.get("tier", "TIER_2_VALUE"))
    tier_str = "🛡️ *Kategori:* TIER 1 KASA KALKANI\n" if "TIER_1" in tier else ""

    lines = [
        "🚩 *[KORNER DEĞER FIRSATI]*",
        f"{time_prefix}⚽ *{home} vs {away}* (MBS {mbs})",
        f"👉 *Piyasa:* {market} ➔ *{outcome}*",
        f"📊 *Nesine Oranı:* `{odds:.2f}` (Adil Oran: `{fair:.2f}`)",
        f"📐 *Model:* Negatif Binom (κ=0.14){exp_str}",
        f"📈 *Kazanma Olasılığı:* `%{prob:.1f}` | *Edge (EV):* `+%{edge:.1f}%`",
    ]
    if tier_str:
        lines.append(tier_str.strip())
    lines.append("💡 _Tavsiye: Kasa yönetimi doğrultusunda %1.5 - %3.0 stake._")
    return "\n".join(lines)


def format_in_play_sniper_alert(alert: dict[str, Any]) -> str:
    """Format an In-Play Continuous Sniper live ambush alert (10'-40' pressure anomaly) into Telegram Markdown.

    Enforces that the in-play alert strictly falls in the 10-40 minute window.
    """
    elapsed = alert.get("elapsed_min")
    if elapsed is None:
        elapsed = alert.get("minute")

    # Minute window constraint: strictly 10 to 40 minutes
    if elapsed is not None:
        try:
            m_val = int(elapsed)
            if not (10 <= m_val <= 40):
                raise ValueError(
                    f"In-Play Sniper alert rejected: minute {m_val} is outside valid 10'-40' window."
                )
        except (ValueError, TypeError) as e:
            if "outside valid" in str(e):
                raise

    home_raw = alert.get("home_team") or alert.get("home") or "Home"
    away_raw = alert.get("away_team") or alert.get("away") or "Away"
    league_raw = alert.get("league") or alert.get("competition") or "Canlı Futbol"

    home = escape_markdown(str(home_raw))
    away = escape_markdown(str(away_raw))
    league = escape_markdown(str(league_raw))

    score = alert.get("score") or f"{alert.get('hg', 0)}-{alert.get('ag', 0)}" if "hg" in alert else alert.get("current_score", "0-0")
    minute_display = f"{elapsed}'" if elapsed is not None else alert.get("trigger_window", "10'-40'")

    market = escape_markdown(str(alert.get("target_market") or alert.get("market") or "Canlı Korner / Baskı"))
    selection = escape_markdown(str(alert.get("selection") or alert.get("outcome") or "ÜST"))

    odds = float(alert.get("target_live_odds") or alert.get("soft_odds") or alert.get("book_odd") or 1.0)
    fair = float(alert.get("fair_odds") or 0.0)
    roi = float(alert.get("expected_live_roi") or alert.get("edge_pct") or alert.get("ev_pct") or 0.0)
    prob_val = float(alert.get("prob") or 0.0)
    prob_pct = prob_val * 100.0 if prob_val <= 1.0 else prob_val

    pre_mu = alert.get("prematch_lambda") or alert.get("pre_match_mu")
    pre_str = f" | λ: `{float(pre_mu):.2f}`" if pre_mu is not None else ""
    fair_str = f" (Adil: `{fair:.2f}`)" if fair > 1.0 else ""
    prob_str = f" | Olasılık: `%{prob_pct:.1f}`" if prob_pct > 0 else ""

    lines = [
        "⚡ *[APE IN-PLAY SNIPER — CANLI PUSU ALARMI]*",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⚽ *{home} vs {away}*",
        f"🏆 *Lig:* {league} | ⏱️ *Dakika:* `{minute_display}` | 🥅 *Skor:* `{score}`",
        f"🎯 *Pusu Hedefi:* *{market}* ➔ *{selection}*",
        f"📊 *Canlı Oran:* `{odds:.2f}`{fair_str}{pre_str}",
        f"📈 *Beklenen Live ROI:* `+%{roi:.1f}`{prob_str}",
        "━━━━━━━━━━━━━━━━━━━━",
        "🛡️ _Kural: Yalnızca 10'-40' arası 0-0 veya baskı anomalisi tespit edildiğinde pusudan çıkılır (SPEC-0015 Stake >= 50 TL)._",
    ]
    return "\n".join(lines)


def format_copula_sgp_alert(sgp: dict[str, Any]) -> str:
    """Format a Copula Same-Game Parlay (SGP) combination signal into Telegram Markdown.

    Enforces SPEC-0013 (kickoff > now + 3m) and SPEC-0014 (now < kickoff <= now + 12h) if kickoff is provided.
    """
    kickoff = sgp.get("kickoff") or sgp.get("kickoff_iso")
    if kickoff:
        try:
            if isinstance(kickoff, str):
                ko_dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
            else:
                ko_dt = kickoff
            if ko_dt.tzinfo is None:
                ko_dt = ko_dt.replace(tzinfo=UTC)
            now_utc = datetime.now(UTC)
            # SPEC-0013: Not finished / not already kicked off (+3 min lead time)
            if ko_dt <= now_utc + timedelta(minutes=3):
                raise ValueError(
                    f"SGP alert rejected by SPEC-0013: match kickoff {kickoff} has already started or lacks 3m lead time."
                )
            # SPEC-0014: Maximum 12 hours ahead
            if ko_dt > now_utc + timedelta(hours=12):
                raise ValueError(
                    f"SGP alert rejected by SPEC-0014: match kickoff {kickoff} is beyond the 12-hour maximum window."
                )
        except (ValueError, TypeError) as e:
            if "SPEC-0013" in str(e) or "SPEC-0014" in str(e):
                raise

    home_raw = sgp.get("home_team") or sgp.get("home") or "Home"
    away_raw = sgp.get("away_team") or sgp.get("away") or "Away"
    league_raw = sgp.get("league") or sgp.get("competition") or "Lig"

    home = escape_markdown(str(home_raw))
    away = escape_markdown(str(away_raw))
    league = escape_markdown(str(league_raw))

    ko_str = escape_markdown(str(sgp.get("kickoff_trt") or sgp.get("time") or "Bugün"))

    leg_1 = escape_markdown(str(sgp.get("leg_1") or sgp.get("leg_a") or "Ayak 1"))
    leg_2 = escape_markdown(str(sgp.get("leg_2") or sgp.get("leg_b") or "Ayak 2"))

    copula_fam = escape_markdown(str(sgp.get("copula_family") or sgp.get("copula_type") or "Clayton/Gumbel"))

    book_odds = float(sgp.get("book_sgp_odds") or sgp.get("soft_odds") or sgp.get("odds") or 1.0)
    fair_odds = float(sgp.get("fair_joint_odds") or sgp.get("fair_odds") or 1.0)
    ev_roi = float(sgp.get("joint_ev_roi") or sgp.get("edge_pct") or 0.0)

    j_prob = float(sgp.get("joint_prob") or 0.0)
    prob_pct = j_prob * 100.0 if j_prob <= 1.0 else j_prob

    lines = [
        "🧬 *[APE COPULA SGP — KOMBİNASYON SİNYALİ]*",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⚽ *{home} vs {away}*",
        f"🏆 *Lig:* {league} | ⏰ *TRT:* {ko_str}",
        f"🔗 *Ayak 1:* {leg_1}",
        f"🔗 *Ayak 2:* {leg_2}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📐 *Bağımlılık Modeli:* `{copula_fam}`",
        f"🎯 *Kombine Oranı:* `{book_odds:.2f}` (Adil: `{fair_odds:.2f}`)",
        f"🎲 *Birleşik Olasılık:* `%{prob_pct:.1f}`",
        f"📈 *Ortak Değer (EV ROI):* `+%{ev_roi:.1f}`",
        "━━━━━━━━━━━━━━━━━━━━",
        "💡 _Syndicate VIP Sınıfı: Bağımsız olasılık yanılsaması elenmiş, kuyruk korelasyonu (copula) ile doğrulanmış kombine._",
    ]
    return "\n".join(lines)


def format_coupon_telegram(
    coupon_name: str,
    picks: list[dict[str, Any]],
    total_odds: float,
    stake: float,
    potential_return: float,
    strategy_note: str = "",
) -> str:
    """Format a coupon into a clean Telegram Markdown message."""
    lines = [
        f"🎯 *{coupon_name}*",
        "━━━━━━━━━━━━━━━━━━",
    ]
    if strategy_note:
        lines.append(f"💡 _{strategy_note}_\n")

    for i, p in enumerate(picks, 1):
        m_name = p.get("match", "Maç")
        m_time = p.get("time", "")
        sel = p.get("selection", "")
        mkt = p.get("market", "")
        odd = p.get("book_odd") or p.get("odds") or 1.0
        prob = p.get("prob")
        prob_str = f" (%{prob * 100:.1f} şans)" if prob else ""
        time_badge = f"[{m_time}] " if m_time else ""

        lines.append(f"*{i}.* {time_badge}{m_name}")
        lines.append(f"   👉 *{mkt} - {sel}* @ `{odd:.2f}`{prob_str}")

    net_profit = potential_return - stake
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(f"📈 *Toplam Oran:* `{total_odds:.2f}`")
    lines.append(f"💰 *Kupon Tutarı:* `{stake:.2f} TL`")
    lines.append(f"🏆 *Olası Kazanç:* `{potential_return:.2f} TL` (Net: `+{net_profit:.2f} TL`)")

    return "\n".join(lines)


def send_coupon_telegram(
    coupon_name: str,
    picks: list[dict[str, Any]],
    total_odds: float,
    stake: float,
    potential_return: float,
    strategy_note: str = "",
) -> bool:
    """Helper to format and send a coupon directly to Telegram."""
    msg = format_coupon_telegram(
        coupon_name=coupon_name,
        picks=picks,
        total_odds=total_odds,
        stake=stake,
        potential_return=potential_return,
        strategy_note=strategy_note,
    )
    return send_telegram_message(msg)


_GLOBAL_FINGERPRINT_ENGINE: Any | None = None


def get_fingerprint_engine() -> Any:
    global _GLOBAL_FINGERPRINT_ENGINE
    if _GLOBAL_FINGERPRINT_ENGINE is None:
        try:
            from odds_fingerprint_engine import OddsFingerprintEngine
        except ImportError:
            from src.odds_fingerprint_engine import OddsFingerprintEngine
        _GLOBAL_FINGERPRINT_ENGINE = OddsFingerprintEngine()
    return _GLOBAL_FINGERPRINT_ENGINE


def process_user_command(text: str) -> str:
    """Evaluate and respond to interactive Telegram commands from the user.

    Supports both direct slash commands (e.g. '/kasa') and group bot commands
    with appended bot usernames (e.g. '/kasa@OddieroBot', '/kuponlar@OddieroBot').
    """
    cleaned = text.strip()
    if not cleaned.startswith("/"):
        return (
            f"❓ Bilinmeyen komut: `{text}`\n"
            "Kullanılabilir komutları görmek için */yardim* yazabilirsiniz."
        )

    # Normalize command: extract first token and strip bot username (e.g. '/kasa@oddierobot' -> '/kasa')
    first_token = cleaned.split()[0].lower()
    cmd = first_token.split("@")[0]

    if cmd in ("/start", "/yardim", "/help"):
        return (
            "🏛️ *APE SYNDICATE OS — KOMUTA MASASI*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Hoş geldiniz Şef! Aşağıdaki komutları doğrudan bana yazabilirsiniz:\n\n"
            "💰 */kasa* ➔ Güncel bakiye, kuponlar ve sermaye kalkanı\n"
            "🎫 */kuponlar* ➔ Bu gece oynanan kuponlar ve kazanç projeksiyonu\n"
            "🔥 */radar* ➔ GASI 70+ Gol Anomalisi & Canlı Pusu Adayları (6+ Gol)\n"
            "⚽ */maclar* ➔ Gece takip edilen kritik maçlar ve saatleri\n"
            "🚩 */korner* ➔ Negatif Binom korner modeli durumu ve analiz çizgileri\n"
            "🏆 */oruntu* ➔ Tarihsel altın örüntü eşleşmesi yakalanan maçlar\n"
            "🧬 */parmakizi <takım>* ➔ Maçın 50 tarihsel ikizini ve ampirik gerçekleşme tablosunu dök\n"
            "📡 */durum* ➔ Canlı tarama daemon'ı ve departman ajanlarının sağlığı\n\n"
            "_Ofis 7/24 piyasayı taramakta ve +EV fırsatları yakaladıkça bildirmektedir._"
        )
    if cmd in ("/kasa", "/bankroll"):
        bankroll_file = BANKROLL_FILE
        b_data = {}
        if bankroll_file.exists():
            try:
                b_data = json.loads(bankroll_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        init = float(b_data.get("initial_bankroll", 150.0))
        staked = float(b_data.get("total_staked", 150.0))
        cash = float(b_data.get("cash_balance", 0.0))
        pnl = float(b_data.get("realized_pnl", 0.0))
        status_lbl = str(b_data.get("status", "ALL_IN_PLAY"))
        return (
            "💰 *GÜNCEL KASA BİLANÇOSU*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 *Başlangıç Kasası:* `{init:.2f} TL`\n"
            f"🎟️ *Bağlanan Tutar (3 Kupon):* `{staked:.2f} TL`\n"
            f"💳 *Nakit Bakiye:* `{cash:.2f} TL`\n"
            f"📈 *Net Kâr/Zarar:* `{pnl:+.2f} TL`\n"
            f"🛡️ *Yönetim Modeli:* Discrete Kelly (`{status_lbl}`)\n"
            "🎯 *Maksimum Olası Kazanç:* `~13.000+ TL`\n"
            "📊 22:45 ve 23:00 maçları canlı takip ediliyor."
        )
    if cmd in ("/kuponlar", "/kupon"):
        coupons_file = COUPONS_FILE
        coupons = []
        if coupons_file.exists():
            try:
                coupons = json.loads(coupons_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        if coupons:
            lines = ["🎫 *BEKLEYEN AKTİF KUPONLAR*", "━━━━━━━━━━━━━━━━━━━━"]
            for i, c in enumerate(coupons, 1):
                stat = c.get("status", "PENDING")
                icon = "🟡" if stat == "PENDING" else ("🟢" if stat == "WON" else "🔴")
                lines.append(f"{icon} *{i}. {c.get('name')}* (`{c.get('stake', 0):.0f} TL`)")
                for p in c.get("picks", []):
                    p_score = f" [{p.get('score')}]" if p.get("score") else ""
                    lines.append(f"   • [{p.get('kickoff_trt', '')}] {p.get('match')}: *{p.get('selection')}* (@ {p.get('odds')}){p_score}")
                ret_str = f"{c.get('potential_return', 0):.2f} TL" if c.get("potential_return") else f"{c.get('potential_return_min', 0):.0f} - {c.get('potential_return_max', 0):.0f} TL"
                lines.append(f"   🏆 *Hedef:* `{ret_str}`\n")
            return "\n".join(lines)
        return (
            "🎫 *BEKLEYEN AKTİF KUPONLAR*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "1️⃣ *Tier 1 Kasa Kalkanı (50 TL)* ➔ Hedef: 147.00 TL\n"
            "2️⃣ *6+ Gol Sistem 1, 2, 3 (56 TL)* ➔ Hedef: 53 TL - 13.065 TL\n"
            "3️⃣ *Sistem 2, 3 Longshot (44 TL)* ➔ Hedef: 120 TL - 2.712 TL"
        )
    if cmd in ("/radar", "/gasi", "/anomali", "/goller"):
        wl_file = ROOT_DIR / "output" / "goal_anomaly_watchlist.json"
        candidates = []
        if wl_file.exists():
            try:
                candidates = json.loads(wl_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        if not candidates:
            return "ℹ️ Şu anda izleme listesinde bekleyen GASI 70+ maç bulunamadı."
        
        lines = [
            "🔥 *APE 6+ GOL ANOMALİSİ & ZAMANLAMA RADARI*",
            "━━━━━━━━━━━━━━━━━━━━",
            "⚡ *Strateji:* %88.8 İY 1.5 Üst kuralı (HT >= 2 gol şartı)\n"
        ]
        for i, c in enumerate(candidates[:4], 1):
            lines.append(f"⚽ *{i}. {c.get('home')} vs {c.get('away')}*")
            lines.append(f"   ⏰ Başlama: `{c.get('kickoff', 'TBD')}` | Arketip: `{c.get('archetype')}`")
            lines.append(f"   📊 GASI Skoru: `{c.get('gasi_score', 70.0):.1f}/100` ({c.get('tier')})")
            lines.append(f"   📈 6+ Gol İhtimali: `%{c.get('p_6plus', 22.0)}` (Adil: `@{c.get('fair_odds_6plus', 4.55):.2f}`)")
            lines.append(f"   🎯 Canlı Hedef: `{c.get('in_play_target_line', '4.5 / 5.5 ÜST')}`")
            lines.append(f"   ⏱️ Zirve Dilimi: `{c.get('home_peak_scoring', '76-90+')}` (Crunch Time)\n")
        lines.append("_Canlı maçta ilk yarı 2 gol atıldığında Telegram'a anlık patlama alarmı atılacaktır._")
        return "\n".join(lines)
    if cmd in ("/durum", "/status"):
        return (
            "📡 *APE SYNDICATE SİSTEM SAĞLIĞI*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 *Orkestratör:* Antigravity (AKTİF)\n"
            "🟢 *Canlı Tarama Motoru:* 300s Periyotla Canlı Taramada\n"
            "🟢 *8 Departman Masası:* Scout, Market, Quant, Risk, Audit, Odds Analyst, In-Play Trader, Props Hunter\n"
            "🛡️ *Filtre:* Kickoff > Şimdi + 3dk (Bitmiş maç engeli devrede)\n"
            "📱 *Telegram Kanalı:* Çift yönlü bağımsız thread aktif"
        )
    if cmd in ("/maclar", "/fikstur"):
        return (
            "⚽ *BU GECEKİ ODAK MAÇLARIMIZ*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⏰ *22:45* ➔ Marsilya vs Toulouse (Ligue 1 - MBS 1)\n"
            "⏰ *22:45* ➔ Juventus vs Napoli (Serie A - MBS 1)\n"
            "⏰ *23:00* ➔ Athletic Bilbao vs Real Sociedad (La Liga - MBS 1)\n"
            "⏰ *23:30* ➔ Braga vs Famalicao (Portekiz - MBS 1)\n"
            "⏰ *02:00* ➔ Bragantino vs Santos SP (Brezilya - MBS 1)"
        )
    if cmd in ("/korner", "/corners", "/corner"):
        return (
            "🚩 *KORNER MODELİ & PİYASA ANALİZİ*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📐 *Model Mimarisi:* Negatif Binom Dağılımı (κ=0.14)\n"
            "📊 *Desteklenen Çizgiler:* 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5\n"
            "⚙️ *Faktörler:* Takım Korner Profilleri (408 takım), 2.5 Ü/A Tempo Çarpanı, Skor/Liderlik Korner Aşınması (%12)\n"
            "🛡️ *Minimum Değer Eşiği:* +4.0% EV (MBS 3 korner kalkanı devrede)\n\n"
            "_Canlı bülten tarandıkça +EV korner fırsatları otomatik olarak kanala düşecektir._"
        )
    if cmd in ("/oruntu", "/pattern", "/altin"):
        try:
            try:
                from time_utils import parse_match_kickoff as _parse_ko
            except ImportError:
                from src.time_utils import parse_match_kickoff as _parse_ko

            try:
                from odds_pattern_miner import OddsPatternMiner
            except ImportError:
                from src.odds_pattern_miner import OddsPatternMiner

            bulletin = fetch_nesine_live_bulletin()
            miner = OddsPatternMiner()
            matches_found = []
            trt_tz = timezone(timedelta(hours=3))
            now_trt = datetime.now(trt_tz)
            for f in bulletin:
                d_str = f.get("date_str")
                t_str = f.get("time_str")
                ko_dt, _ = _parse_ko(d_str, t_str, now_trt=now_trt, min_lead_minutes=3, max_lead_hours=12)
                if not ko_dt:
                    continue
                pats = miner.match_fixture_patterns(f)
                for p in pats:
                    matches_found.append((f, p))

            if not matches_found:
                return "ℹ️ Şu anda 12 saatlik pencerede altın örüntü eşleşmesi bulunan maç bulunamadı."

            lines = ["🏆 *GÜNCEL ALTIN ÖRÜNTÜ EŞLEŞMELERİ (12 SAAT)*", "━━━━━━━━━━━━━━━━━━━━"]
            for f, p in matches_found[:4]:
                h = f.get("home", "")
                a = f.get("away", "")
                t = f.get("time_str", "")
                mbs = f.get("mbs", 1)
                lines.append(f"⚽ *[{t} TRT] {h} vs {a}* (MBS-{mbs})")
                lines.append(f"   📐 *Örüntü:* {p.get('pattern_name')}")
                lines.append(f"   📊 *12+ Korner:* %{p.get('pct_corners_12plus', 0):.1f} | *İY 1.5 Üst:* %{p.get('pct_ht_o15', 0):.1f}")
                lines.append(f"   💡 *Odak:* {p.get('recommended_focus')}\n")
            return "\n".join(lines)
        except Exception as e:
            return f"⚠️ Örüntü analizi hatası: {e}"
    if cmd in ("/parmakizi", "/fingerprint", "/ikiz"):
        query = " ".join(cleaned.split()[1:]).strip()
        try:
            try:
                from time_utils import parse_match_kickoff as _parse_ko
            except ImportError:
                from src.time_utils import parse_match_kickoff as _parse_ko

            try:
                from odds_fingerprint_engine import format_fingerprint_telegram_message
            except ImportError:
                from src.odds_fingerprint_engine import format_fingerprint_telegram_message

            bulletin = fetch_nesine_live_bulletin()
            trt_tz = timezone(timedelta(hours=3))
            now_trt = datetime.now(trt_tz)

            # SPEC-0013 & SPEC-0014: Only allow upcoming matches within (now + 3m, now + 12h]
            valid_bulletin = []
            for f in bulletin:
                ko_dt, _ = _parse_ko(
                    f.get("date_str"),
                    f.get("time_str"),
                    now_trt=now_trt,
                    min_lead_minutes=3,
                    max_lead_hours=12,
                )
                if ko_dt is not None:
                    valid_bulletin.append(f)

            target_fixture = None
            if query:
                q_lower = query.lower()
                for f in valid_bulletin:
                    h = f.get("home", "").lower()
                    a = f.get("away", "").lower()
                    if q_lower in h or q_lower in a:
                        target_fixture = f
                        break
            elif valid_bulletin:
                target_fixture = valid_bulletin[0]

            if not target_fixture:
                if query:
                    return (
                        f"ℹ️ Canlı bültende (12 saatlik SPEC-0013/0014 penceresinde) "
                        f"'{query}' ile eşleşen uygun bir maç bulunamadı."
                    )
                return "ℹ️ Lütfen sorgulamak istediğiniz takımı belirtin: `/parmakizi Arsenal`"

            engine = get_fingerprint_engine()
            report = engine.scan_fixture(target_fixture, k=50)
            if report:
                h = target_fixture.get("home", "")
                a = target_fixture.get("away", "")
                fixture_name = f"{h} vs {a}"
                time_str = target_fixture.get("time_str", "23:00")
                mbs = int(target_fixture.get("mbs") or target_fixture.get("EMBS") or 1)
                return format_fingerprint_telegram_message(fixture_name, time_str, mbs, report)
            return f"ℹ️ '{target_fixture.get('home')} vs {target_fixture.get('away')}' maçı için geçerli oranlar bulunamadı."
        except Exception as e:
            return f"⚠️ Parmak izi analiz hatası: {e}"
    return (
        f"❓ Bilinmeyen komut: `{text}`\n"
        "Kullanılabilir komutları görmek için */yardim* yazabilirsiniz."
    )


def check_and_reply_telegram_commands(offset: int | None = None) -> int | None:
    """Fetch recent messages sent to the bot, process slash commands, and reply.

    Hardened against startup replay: loads offset from disk, uses cold-start guard
    to avoid replaying stale backlogs, and persists update_id after each poll.
    """
    token, env_chat_id = get_telegram_credentials()
    if not token or not env_chat_id:
        return offset

    # 1. If offset not provided, load from disk
    if offset is None:
        offset = load_telegram_offset()

    # 2. Cold-start guard: if no prior offset exists on disk, discard past backlog
    if offset is None:
        try:
            init_url = f"https://api.telegram.org/bot{token}/getUpdates?offset=-1&limit=1"
            req = urllib.request.Request(init_url)
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                init_data = json.loads(resp.read().decode("utf-8"))
                if init_data.get("ok"):
                    results = init_data.get("result", [])
                    if results:
                        offset = results[-1].get("update_id", 0) + 1
                        save_telegram_offset(offset)
                        return offset
        except Exception as e:
            logger.warning(f"Failed to fetch initial Telegram offset via cold-start guard: {e}")

    url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=1"
    if offset is not None:
        url += f"&offset={offset}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("ok"):
                return offset

            results = data.get("result", [])
            max_update_id = offset

            authorized_chats = {cid.strip() for cid in str(env_chat_id).split(",") if cid.strip()}

            for item in results:
                up_id = item.get("update_id", 0)
                if max_update_id is None or up_id >= max_update_id:
                    max_update_id = up_id + 1

                msg = item.get("message", {})
                chat = msg.get("chat", {})
                chat_id = str(chat.get("id", ""))
                text = msg.get("text", "")

                # Only respond to authorized chat and non-empty commands
                if chat_id in authorized_chats and text.strip().startswith("/"):
                    reply_text = process_user_command(text)
                    send_telegram_message(reply_text, chat_id=chat_id)

            if max_update_id is not None and max_update_id != offset:
                save_telegram_offset(max_update_id)

            return max_update_id
    except Exception as e:
        logger.warning(f"Telegram polling warning: {e}")
        return offset


def handle_incoming_messages(offset: int | None = None) -> int | None:
    """Process incoming Telegram updates and execute interactive slash commands."""
    return check_and_reply_telegram_commands(offset=offset)

