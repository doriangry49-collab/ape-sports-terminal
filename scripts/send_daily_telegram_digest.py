"""Send a concise daily Nesine vs Fair Odds & Margin digest to Telegram."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from telegram_notifier import escape_markdown, send_telegram_message  # noqa: E402

TRT_TZ = timezone(timedelta(hours=3))
DEFAULT_REPORT_PATH = PROJECT_ROOT / "output" / "daily_prototype_report.json"


def is_telegram_signals_enabled(env_value: str | None = None) -> bool:
    """Return True only when outbound Telegram digest signals are explicitly opted in."""
    raw = os.getenv("APE_ENABLE_TELEGRAM_SIGNALS", "") if env_value is None else env_value
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _parse_kickoff_trt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    cleaned = str(raw).replace(" TRT", "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=TRT_TZ)
        except ValueError:
            continue
    return None


def build_digest_message(
    report: dict[str, Any],
    *,
    max_rows: int = 8,
    now_trt: datetime | None = None,
) -> str:
    """Format an honest Turkish Markdown digest from daily_prototype_report.json."""
    current_trt = now_trt or datetime.now(TRT_TZ)
    cutoff_trt = current_trt + timedelta(minutes=3)

    summary = report.get("summary") or {}
    generated_at = str(report.get("generated_at_trt") or current_trt.strftime("%Y-%m-%d %H:%M TRT"))
    bulletin_total = int(summary.get("bulletin_total_matches") or 0)
    sharp_matched = int(summary.get("sharp_nesine_matched") or 0)
    signals = report.get("signals") or []
    signals_count = len(signals)

    lines: list[str] = [
        "📊 *APE Spor İstihbaratı — Adil Oran & Marj Özeti*",
        f"🕒 Güncelleme: `{escape_markdown(generated_at)}`",
        f"📋 Bülten: `{bulletin_total}` maç | Keskin Eşleşme: `{sharp_matched}` | Gerçek +EV Sinyal: `{signals_count}`",
        "",
    ]

    if signals_count > 0:
        lines.append("🎯 *Doğrulanmış +EV Fırsatları:*")
        for sig in signals[:5]:
            match_name = escape_markdown(f"{sig.get('home', '?')} - {sig.get('away', '?')}")
            sel = escape_markdown(str(sig.get("selection") or sig.get("market") or ""))
            ko = escape_markdown(str(sig.get("kickoff_trt") or ""))
            lines.append(
                f"• *{match_name}* ({ko}) — `{sel}` | "
                f"Nesine `{sig.get('book_odd')}` vs Adil `{sig.get('fair_odd')}` "
                f"(`+{sig.get('edge_pct')}%`)"
            )
        lines.append("")
    else:
        lines.append("🛡️ *Gerçek +EV Sinyali Yok (0):* Keskin piyasa kontrolü +EV fırsat bulmadı; sahte sinyal üretilmedi.")
        lines.append("")

    comparisons = report.get("fair_odds_comparison") or []
    upcoming: list[dict[str, Any]] = []
    for row in comparisons:
        ko_dt = _parse_kickoff_trt(row.get("kickoff_trt"))
        if ko_dt is not None and ko_dt <= cutoff_trt:
            continue
        upcoming.append(row)

    upcoming.sort(
        key=lambda r: (
            float(r.get("nesine_overround_pct") or 999.0),
            -float(r.get("edge_pct") or -999.0),
        )
    )

    if upcoming:
        lines.append("⚖️ *En Düşük Nesine Marjlı & Adil Orana En Yakın Maçlar:*")
        for row in upcoming[:max_rows]:
            match_name = escape_markdown(str(row.get("match") or "?"))
            ko = escape_markdown(str(row.get("kickoff_trt") or "TBD").replace(" TRT", ""))
            sel = escape_markdown(str(row.get("selection") or row.get("market") or ""))
            nes = row.get("nesine_odd")
            fair = row.get("fair_odd")
            ov = row.get("nesine_overround_pct")
            edge = row.get("edge_pct")
            lines.append(
                f"• `{ko}` *{match_name}* | `{sel}`: Nesine `{nes}` vs Adil `{fair}` | "
                f"Marj `%{ov}` | Fark `{edge}%`"
            )
    else:
        lines.append("ℹ️ Şu an gelecek saatler için eşleşmiş adil oran kıyaslaması bulunamadı.")

    lines.extend([
        "",
        "🌐 Canlı Web Terminali: https://doriangry49-collab.github.io/ape-sports-terminal/",
    ])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send daily Nesine vs Fair Odds digest to Telegram.")
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--max-rows", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true", help="Print message without sending to Telegram.")
    parser.add_argument(
        "--enable-send",
        action="store_true",
        help="Explicitly allow outbound Telegram dispatch (or set APE_ENABLE_TELEGRAM_SIGNALS=1).",
    )
    args = parser.parse_args()

    if not args.report_path.exists():
        print(f"Report file not found: {args.report_path}")
        return 1

    report = json.loads(args.report_path.read_text(encoding="utf-8"))
    message = build_digest_message(report, max_rows=args.max_rows)

    if args.dry_run:
        print(message)
        return 0

    if not args.enable_send and not is_telegram_signals_enabled():
        print(
            "[PASSIVE MODE] Telegram signal dispatch is disabled "
            "(pass --enable-send or set APE_ENABLE_TELEGRAM_SIGNALS=1 to opt in)."
        )
        return 0

    ok = send_telegram_message(message)
    print(f"Telegram digest sent: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
