"""APE Sports-Engine — Single-Command Daily Prototype Pipeline (v1.0).

Unifies the core verified modules into one end-to-end operational flow:
1. Live Bulletin Ingestion: Fetches real Nesine pre-match bulletin (SPEC-0012 fail-closed).
2. Constitutional Window Guard: Enforces TRT kickoff > now + 3m (SPEC-0013) and <= 12h (SPEC-0014).
3. Quantitative Model Pricing: Loads Empirical Bayes & Dixon-Coles ratings (TeamStrengthEngine)
   and evaluates positive-EV edges without silent unknown-team fallbacks.
4. Discrete Kelly Sizing: Enforces >= 50.0 TL minimum stake (SPEC-0015) and ruin-bound protection.
5. Coupon Builder & Optional Ledger/Settlement: Constructs an uncorrelated value coupon and
   optionally records to PaperTradingEngine or settles pending bets via ESPN.

Usage:
    python scripts/run_daily_prototype.py
    python scripts/run_daily_prototype.py --bankroll 2000 --min-ev 5.0
    python scripts/run_daily_prototype.py --record-ledger --settle-espn
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure project root and src are importable regardless of working directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
for p in (str(PROJECT_ROOT), str(SRC_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Fix Windows console encoding for Turkish characters and box-drawing glyphs
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from atomic_io import atomic_write_json
from discrete_kelly_optimizer import DiscreteKellyOptimizer
from live_stale_line_adapter import (
    AdapterError,
    fetch_and_scan_live_propline,
    fetch_nesine_live_bulletin,
)
from paper_trader import PaperTradingEngine, is_corner_market
from team_strength_engine import MIN_SAMPLE_MATCHES, TeamStrengthEngine
from time_utils import TRT_TZ, parse_match_kickoff

MIN_CONSTITUTIONAL_STAKE_TL = 50.0
MAX_CONSTITUTIONAL_HOURS = 12
MIN_PLAYABLE_ODDS = 1.45
MAX_PLAYABLE_ODDS = 6.50
MAX_ANOMALY_EDGE_PCT = 35.0

_SHARP_OUTCOME_MAP: dict[str, tuple[str, str]] = {
    "HOME": ("1X2", "MS 1"),
    "DRAW": ("1X2", "MS X"),
    "AWAY": ("1X2", "MS 2"),
    "OVER_2.5": ("Alt/Üst 2.5", "2.5 Üst"),
    "UNDER_2.5": ("Alt/Üst 2.5", "2.5 Alt"),
}


def _parse_iso_window(
    kickoff_iso: str | None,
    now_trt: datetime,
    max_hours: int,
) -> tuple[str, str, str] | None:
    """Validate an ISO kickoff string against SPEC-0013 (> +3m) and SPEC-0014 (<= +max_hours)."""
    if not kickoff_iso:
        return None
    try:
        iso_clean = str(kickoff_iso).strip()
        if iso_clean.endswith("Z"):
            iso_clean = iso_clean[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TRT_TZ)
        ko_trt = dt.astimezone(TRT_TZ)
    except ValueError:
        return None

    if ko_trt <= now_trt + timedelta(minutes=3):
        return None
    if ko_trt > now_trt + timedelta(hours=max_hours):
        return None

    ko_utc_iso = (ko_trt - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ko_utc_iso, ko_trt.strftime("%Y-%m-%d %H:%M TRT"), ko_trt.strftime("%H:%M")


def _build_kelly_enriched_signal(
    base_sig: dict[str, Any],
    optimizer: DiscreteKellyOptimizer,
    bankroll: float,
    enforced_stake: float,
    min_ev_pct: float,
    meta: dict[str, Any],
    min_odds: float = MIN_PLAYABLE_ODDS,
    max_odds: float = MAX_PLAYABLE_ODDS,
) -> dict[str, Any] | None:
    """Compute Quarter-Kelly sizing under SPEC-0015 and enforce playable odds & EV guardrails."""
    book_odd = float(base_sig.get("book_odd") or 1.0)
    prob = float(base_sig.get("prob") or 0.0)
    edge_pct = float(base_sig.get("edge_pct") or 0.0)
    if not (min_odds <= book_odd <= max_odds) or not (0.0 < prob < 1.0):
        return None
    if edge_pct < min_ev_pct or edge_pct > MAX_ANOMALY_EDGE_PCT:
        return None

    kelly_res = optimizer.compute_fractional_kelly_stake(
        current_bankroll=bankroll,
        win_prob=prob,
        odds=book_odd,
        min_ticket_cost=enforced_stake,
        kelly_fraction=0.25,
        min_ev_pct=min_ev_pct,
    )
    if not kelly_res.get("is_viable"):
        return None

    enriched = dict(base_sig)
    enriched.update(meta)
    enriched.update({
        "soft_odds": book_odd,
        "fair_odds": float(base_sig.get("fair_odd") or round(1.0 / prob, 2)),
        "kelly_pct": round(float(kelly_res.get("capped_f") or 0.0) * 100.0, 2),
        "stake": float(kelly_res["stake"]),
        "potential_return": float(kelly_res["potential_return"]),
        "net_profit": float(kelly_res["net_profit"]),
        "ruin_prob": float(kelly_res["ruin_prob"]),
        "regime": kelly_res["regime"],
    })
    return enriched


def _merge_engine_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate identical match/selection signals across Engine 1 and Engine 2."""
    by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for sig in signals:
        key = (
            str(sig.get("home", "")).strip().lower(),
            str(sig.get("away", "")).strip().lower(),
            str(sig.get("market", "")).strip(),
            str(sig.get("selection", "")).strip(),
        )
        existing = by_key.get(key)
        if existing is None:
            cand = dict(sig)
            cand.setdefault("dual_confirmed", False)
            by_key[key] = cand
            continue

        if existing.get("source_engine") != sig.get("source_engine"):
            existing["dual_confirmed"] = True
        if float(sig.get("edge_pct") or 0.0) > float(existing.get("edge_pct") or 0.0):
            dual_flag = existing.get("dual_confirmed", False)
            updated = dict(sig)
            updated["dual_confirmed"] = dual_flag
            by_key[key] = updated

    # Deduplicate same-match corner markets to the single highest-EV barem to prevent correlated double-exposure
    non_corner: list[dict[str, Any]] = []
    best_corner_by_match: dict[tuple[str, str], dict[str, Any]] = {}
    for sig in by_key.values():
        if not is_corner_market(str(sig.get("market", "")), str(sig.get("selection", ""))):
            non_corner.append(sig)
            continue
        m_key = (
            str(sig.get("home", "")).strip().lower(),
            str(sig.get("away", "")).strip().lower(),
        )
        rank = (
            float(sig.get("edge_pct") or 0.0),
            float(sig.get("prob") or 0.0),
            float(sig.get("book_odd") or sig.get("soft_odds") or 0.0),
        )
        cur = best_corner_by_match.get(m_key)
        if cur is None:
            best_corner_by_match[m_key] = sig
        else:
            cur_rank = (
                float(cur.get("edge_pct") or 0.0),
                float(cur.get("prob") or 0.0),
                float(cur.get("book_odd") or cur.get("soft_odds") or 0.0),
            )
            if rank > cur_rank:
                best_corner_by_match[m_key] = sig

    merged = non_corner + list(best_corner_by_match.values())
    merged.sort(key=lambda s: (bool(s.get("dual_confirmed")), float(s.get("edge_pct") or 0.0)), reverse=True)
    return merged


def _lookup_sharp_prob_for_signal(
    fx: dict[str, Any],
    market: str,
    selection: str,
) -> float | None:
    """Resolve the sharp de-vigged win probability matching a Motor 1 signal, or None."""
    sel_upper = selection.strip().upper()
    s1x2 = fx.get("shin_probs_1x2")
    if s1x2 and len(s1x2) == 3:
        p1, px, p2 = (float(s1x2[0] or 0.0), float(s1x2[1] or 0.0), float(s1x2[2] or 0.0))
        if market == "1X2":
            if sel_upper == "MS 1":
                return p1
            if sel_upper == "MS X":
                return px
            if sel_upper == "MS 2":
                return p2
        elif market == "Çifte Şans":
            if sel_upper.startswith("1X"):
                return p1 + px
            if sel_upper.startswith("X2"):
                return px + p2
            if sel_upper.startswith("12"):
                return p1 + p2

    sou = fx.get("shin_probs_ou25")
    if sou and len(sou) == 2 and market in ("2.5 Gol", "Alt/Üst 2.5"):
        po, pu = (float(sou[0] or 0.0), float(sou[1] or 0.0))
        if "ÜST" in sel_upper or "UST" in sel_upper:
            return po
        if "ALT" in sel_upper:
            return pu

    return None


def _veto_engine1_by_sharp_consensus(
    signals: list[dict[str, Any]],
    sharp_fixtures: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Veto Motor 1 signals when live Motor 2 sharp fair odds price the bet at negative EV."""
    by_code: dict[str, dict[str, Any]] = {}
    by_match: dict[tuple[str, str], dict[str, Any]] = {}
    for fx in sharp_fixtures:
        if not fx.get("shin_probs_1x2") and not fx.get("shin_probs_ou25"):
            continue
        code = fx.get("nesine_code")
        if code is not None:
            by_code[str(code)] = fx
        h = str(fx.get("home") or "").strip().lower()
        a = str(fx.get("away") or "").strip().lower()
        if h and a:
            by_match[(h, a)] = fx

    kept: list[dict[str, Any]] = []
    vetoed_count = 0
    for sig in signals:
        if sig.get("source_engine") != "team_strength":
            kept.append(sig)
            continue

        code = sig.get("nesine_code")
        fx = by_code.get(str(code)) if code is not None else None
        if fx is None:
            fx = by_match.get((
                str(sig.get("home") or "").strip().lower(),
                str(sig.get("away") or "").strip().lower(),
            ))

        sharp_prob = (
            _lookup_sharp_prob_for_signal(fx, str(sig.get("market") or ""), str(sig.get("selection") or ""))
            if fx is not None
            else None
        )
        if sharp_prob is not None and 0.0 < sharp_prob < 1.0:
            book_odd = float(sig.get("book_odd") or sig.get("soft_odds") or 1.0)
            sharp_ev_pct = ((sharp_prob * book_odd) - 1.0) * 100.0
            if sharp_ev_pct < 0.0:
                vetoed_count += 1
                continue
            enriched = dict(sig)
            enriched["sharp_fair_odd"] = round(1.0 / sharp_prob, 2)
            enriched["sharp_edge_pct"] = round(sharp_ev_pct, 2)
            kept.append(enriched)
        else:
            kept.append(sig)

    return kept, vetoed_count


def _build_fair_odds_comparison(
    sharp_fixtures: list[dict[str, Any]],
    window_by_code: dict[Any, dict[str, Any]],
    now_trt: datetime,
    max_hours: int,
    min_ev_pct: float = 4.0,
) -> list[dict[str, Any]]:
    """Build transparent World Fair Odds vs Nesine comparison across all matched window fixtures."""
    rows: list[dict[str, Any]] = []
    for fx in sharp_fixtures:
        n_code = fx.get("nesine_code")
        if n_code is None:
            continue
        parsed_win = _parse_iso_window(fx.get("kickoff"), now_trt, max_hours)
        if not parsed_win:
            continue
        _, ko_trt, _ = parsed_win
        matched_bul = window_by_code.get(n_code) or {}
        home = str(matched_bul.get("home") or fx.get("home") or "")
        away = str(matched_bul.get("away") or fx.get("away") or "")
        league = str(matched_bul.get("league") or fx.get("league") or "")
        mbs = int(matched_bul.get("mbs") or fx.get("nesine_mbs") or 1)

        n1x2 = fx.get("nesine_1x2") or matched_bul.get("nesine_1x2")
        s1x2_p = fx.get("shin_probs_1x2")
        s1x2_f = fx.get("shin_fair_1x2")
        if n1x2 and s1x2_p and len(n1x2) == 3 and len(s1x2_p) == 3:
            overround_1x2 = round(sum(1.0 / float(o) for o in n1x2 if float(o) > 1.0) * 100.0, 1)
            for idx, sel_lbl in enumerate(("MS 1", "MS X", "MS 2")):
                prob = float(s1x2_p[idx] or 0.0)
                n_odd = float(n1x2[idx] or 0.0)
                if prob <= 0.0 or n_odd <= 1.01:
                    continue
                fair_odd = float(s1x2_f[idx]) if s1x2_f and len(s1x2_f) == 3 else round(1.0 / prob, 2)
                edge = round(((prob * n_odd) - 1.0) * 100.0, 2)
                rows.append(_format_fair_row(
                    ko_trt, home, away, league, mbs, "1X2", sel_lbl, n_odd, fair_odd, prob, overround_1x2, edge, min_ev_pct
                ))

        nou = fx.get("nesine_ou25") or matched_bul.get("nesine_ou25")
        sou_p = fx.get("shin_probs_ou25")
        sou_f = fx.get("shin_fair_ou25")
        if nou and sou_p and len(nou) == 2 and len(sou_p) == 2:
            overround_ou = round(sum(1.0 / float(o) for o in nou if float(o) > 1.0) * 100.0, 1)
            for idx, sel_lbl in enumerate(("2.5 Üst", "2.5 Alt")):
                prob = float(sou_p[idx] or 0.0)
                n_odd = float(nou[idx] or 0.0)
                if prob <= 0.0 or n_odd <= 1.01:
                    continue
                fair_odd = float(sou_f[idx]) if sou_f and len(sou_f) == 2 else round(1.0 / prob, 2)
                edge = round(((prob * n_odd) - 1.0) * 100.0, 2)
                rows.append(_format_fair_row(
                    ko_trt, home, away, league, mbs, "2.5 Gol", sel_lbl, n_odd, fair_odd, prob, overround_ou, edge, min_ev_pct
                ))

    rows.sort(key=lambda r: (r["edge_pct"], r["fair_prob_pct"]), reverse=True)
    return rows


def _format_fair_row(
    ko_trt: str,
    home: str,
    away: str,
    league: str,
    mbs: int,
    market: str,
    selection: str,
    nesine_odd: float,
    fair_odd: float,
    prob: float,
    overround_pct: float,
    edge_pct: float,
    min_ev_pct: float,
) -> dict[str, Any]:
    if edge_pct >= min_ev_pct and MIN_PLAYABLE_ODDS <= nesine_odd <= MAX_PLAYABLE_ODDS:
        tag = "+EV FIRSAT"
    elif edge_pct >= -4.0:
        tag = "YAKIN DEĞER (DÜŞÜK MARJ)"
    else:
        tag = "NEGATİF EV (YÜKSEK NESİNE MARJI)"
    return {
        "kickoff_trt": ko_trt,
        "match": f"{home} vs {away}",
        "league": league,
        "mbs": mbs,
        "market": market,
        "selection": selection,
        "nesine_odd": round(nesine_odd, 2),
        "fair_odd": round(fair_odd, 2),
        "fair_prob_pct": round(prob * 100.0, 1),
        "nesine_overround_pct": overround_pct,
        "edge_pct": edge_pct,
        "honest_tag": tag,
    }


def build_uncorrelated_coupon(
    signals: list[dict[str, Any]],
    optimizer: DiscreteKellyOptimizer,
    bankroll: float,
    min_stake: float,
    max_legs: int = 3,
) -> dict[str, Any] | None:
    """Build a best-value uncorrelated combo coupon from directly playable markets."""
    playable = [
        s for s in signals
        if s.get("market") != "Çifte Şans" and float(s.get("book_odd", 0.0)) >= MIN_PLAYABLE_ODDS
    ]
    if not playable:
        return None

    # Sort by tier priority (SHIELD first) then EV%
    ranked = sorted(
        playable,
        key=lambda s: (1 if s.get("tier") == "TIER_1_SHIELD" else 0, float(s.get("edge_pct", 0.0))),
        reverse=True,
    )

    legs: list[dict[str, Any]] = []
    seen_matches: set[str] = set()
    for sig in ranked:
        match_key = str(sig.get("match", ""))
        if match_key in seen_matches:
            continue
        seen_matches.add(match_key)
        legs.append(sig)
        if len(legs) >= max_legs:
            break

    if not legs:
        return None

    # Respect MBS constraint: if any leg has MBS > len(legs), single/small combo isn't valid
    max_mbs = max(int(leg.get("mbs") or 1) for leg in legs)
    if len(legs) < max_mbs:
        # Try adding extra distinct matches to satisfy MBS
        for sig in ranked:
            match_key = str(sig.get("match", ""))
            if match_key in seen_matches:
                continue
            seen_matches.add(match_key)
            legs.append(sig)
            max_mbs = max(max_mbs, int(sig.get("mbs") or 1))
            if len(legs) >= max_mbs:
                break

    combined_prob = 1.0
    combined_odds = 1.0
    for leg in legs:
        combined_prob *= float(leg["prob"])
        combined_odds *= float(leg["book_odd"])

    combined_ev_pct = ((combined_prob * combined_odds) - 1.0) * 100.0
    if combined_ev_pct <= 0.0:
        return None

    sizing = optimizer.compute_fractional_kelly_stake(
        current_bankroll=bankroll,
        win_prob=combined_prob,
        odds=combined_odds,
        min_ticket_cost=min_stake,
        kelly_fraction=0.25,
        min_ev_pct=0.0,
    )
    if not sizing.get("is_viable"):
        return None

    stake = float(sizing.get("stake") or 0.0)
    if stake < min_stake:
        return None

    return {
        "legs": legs,
        "leg_count": len(legs),
        "mbs_satisfied": len(legs) >= max_mbs,
        "combined_prob": round(combined_prob, 4),
        "combined_odds": round(combined_odds, 2),
        "combined_ev_pct": round(combined_ev_pct, 2),
        "recommended_stake_tl": round(stake, 2),
        "potential_return_tl": round(stake * combined_odds, 2),
    }


def run_daily_pipeline(
    bankroll: float = 1000.0,
    min_ev_pct: float = 4.0,
    min_stake_tl: float = MIN_CONSTITUTIONAL_STAKE_TL,
    max_hours: int = MAX_CONSTITUTIONAL_HOURS,
    record_ledger: bool = False,
    settle_espn: bool = False,
    output_json: Path | None = None,
    sync_ui_snapshot: bool | None = None,
    ui_snapshot_path: Path | None = None,
) -> dict[str, Any]:
    """Execute the complete end-to-end daily sports prototype pipeline."""
    # Enforce constitutional guardrails regardless of caller overrides
    enforced_stake = max(MIN_CONSTITUTIONAL_STAKE_TL, float(min_stake_tl))
    enforced_hours = min(MAX_CONSTITUTIONAL_HOURS, max(1, int(max_hours)))

    now_trt = datetime.now(TRT_TZ)
    horizon_trt = now_trt + timedelta(hours=enforced_hours)

    print("=" * 92)
    print(f" 🚀 APE SPORTS-ENGINE — CANLI GÜNLÜK PROTOTİP ({now_trt.strftime('%d.%m.%Y %H:%M:%S')} TRT)")
    print(f" 🔒 Zaman Penceresi (SPEC-0013/0014): {now_trt.strftime('%H:%M')} -> {horizon_trt.strftime('%H:%M')} TRT (Max {enforced_hours}h)")
    print(f" 💰 Kasa: {bankroll:.2f} TL | Min Bahis (SPEC-0015): {enforced_stake:.2f} TL | Min EV: +{min_ev_pct:.1f}%")
    print("=" * 92)

    # 1. Fetch live Nesine bulletin (SPEC-0012 fail-closed: raise_on_error=True)
    print("\n[1/5] Nesine canlı bülteni çekiliyor...")
    try:
        raw_bulletin = fetch_nesine_live_bulletin(timeout=12.0, max_retries=3, raise_on_error=True)
    except AdapterError as exc:
        print(f" ❌ [SPEC-0012 FAIL-CLOSED] Dış kaynak hatası: {exc}")
        raise

    # 2. Temporal window filtering (SPEC-0013 & SPEC-0014)
    window_matches: list[dict[str, Any]] = []
    for match in raw_bulletin:
        ko_dt, ko_iso = parse_match_kickoff(
            match.get("date_str"),
            match.get("time_str"),
            now_trt=now_trt,
            min_lead_minutes=3,
            max_lead_hours=enforced_hours,
        )
        if ko_dt is None or ko_iso is None:
            continue
        enriched = dict(match)
        enriched["ko_dt"] = ko_dt
        enriched["ko_iso"] = ko_iso
        enriched["kickoff_trt"] = ko_dt.strftime("%d.%m %H:%M")
        window_matches.append(enriched)

    window_matches.sort(key=lambda m: m["ko_dt"])
    print(f" ✅ Bülten toplam: {len(raw_bulletin)} maç | 12 saat penceresinde geçerli: {len(window_matches)} maç")

    # 3. Load Empirical Bayes & Dixon-Coles ratings and evaluate matches
    print("\n[2/5] Takım gücü modeli (Empirical Bayes + Dixon-Coles) yükleniyor...")
    strength_engine = TeamStrengthEngine()
    strength_engine.load_or_train()
    print(
        f" ✅ Model hazır: {len(strength_engine.team_ratings)} takım derecelendirildi "
        f"({strength_engine.total_matches_trained} tarihi maç)"
    )

    print("\n[3/5] Penceredeki maçlar fiyatlanıyor ve +EV fırsatlar taranıyor...")
    optimizer = DiscreteKellyOptimizer()
    all_signals: list[dict[str, Any]] = []
    evaluated_fixtures = 0
    skipped_unknown = 0
    window_by_code: dict[Any, dict[str, Any]] = {
        m.get("nesine_code"): m for m in window_matches if m.get("nesine_code") is not None
    }

    for match in window_matches:
        signals = strength_engine.evaluate_live_fixture(match, min_edge_pct=min_ev_pct)
        if not signals:
            h_r = strength_engine.get_team_rating(match.get("home", ""))
            a_r = strength_engine.get_team_rating(match.get("away", ""))
            if int(h_r.get("matches", 0)) < MIN_SAMPLE_MATCHES or int(a_r.get("matches", 0)) < MIN_SAMPLE_MATCHES:
                skipped_unknown += 1
            else:
                evaluated_fixtures += 1
            continue

        evaluated_fixtures += 1
        for sig in signals:
            # Restrict Engine 1 to sharp-verifiable core markets (exclude unverified Corners / HT-FT / TG 6+)
            sig_mkt = str(sig.get("market") or "").strip()
            if sig_mkt not in ("1X2", "2.5 Gol", "Alt/Üst 2.5", "Çifte Şans"):
                continue
            enriched_sig = _build_kelly_enriched_signal(
                base_sig=sig,
                optimizer=optimizer,
                bankroll=bankroll,
                enforced_stake=enforced_stake,
                min_ev_pct=min_ev_pct,
                meta={
                    "source_engine": "team_strength",
                    "home": match.get("home", ""),
                    "away": match.get("away", ""),
                    "league": match.get("league", ""),
                    "country": match.get("country", ""),
                    "nesine_code": match.get("nesine_code"),
                    "mbs": match.get("mbs", 1),
                    "kickoff": match["ko_iso"],
                    "kickoff_trt": match["kickoff_trt"],
                    "soft_book": "nesine",
                },
            )
            if enriched_sig:
                all_signals.append(enriched_sig)

    engine1_signals_count = len(all_signals)
    print(f"      -> Motor 1 (Takım Gücü ELO): {engine1_signals_count} sinyal")

    print("\n[3b/5] Motor 2 (Keskin Piyasa Tarayıcısı — PropLine / ESPN Shin) çalıştırılıyor...")
    propline_res: dict[str, Any] = {}
    sharp_scanner_status = "ok"
    engine2_accepted_count = 0
    try:
        propline_res = fetch_and_scan_live_propline(
            output_path=None,
            settle_espn=False,
            throttle_sec=0.1,
        )
    except Exception as exc:
        sharp_scanner_status = f"degraded: {type(exc).__name__}: {exc}"
        print(f"      -> [SPEC-0012] Keskin Piyasa Tarayıcısı geçici hata verdi: {sharp_scanner_status}")

    for raw_sig in propline_res.get("signals") or []:
        edge_pct = float(raw_sig.get("edge_pct") or 0.0)
        if edge_pct < min_ev_pct:
            continue

        parsed_win = _parse_iso_window(raw_sig.get("kickoff"), now_trt, enforced_hours)
        if not parsed_win:
            continue
        ko_utc_iso, kickoff_trt, time_hhmm = parsed_win

        home_name = str(raw_sig.get("home", ""))
        away_name = str(raw_sig.get("away", ""))
        raw_market = str(raw_sig.get("market", ""))
        raw_outcome = str(raw_sig.get("outcome", ""))
        mapped_mkt, mapped_sel = _SHARP_OUTCOME_MAP.get(raw_outcome, (raw_market, raw_outcome))
        matched_bul = window_by_code.get(raw_sig.get("nesine_code"))

        base_sig = {
            "match": f"{home_name} vs {away_name}",
            "time": time_hhmm,
            "mbs": raw_sig.get("mbs") or (matched_bul.get("mbs") if matched_bul else 1),
            "market": mapped_mkt,
            "selection": mapped_sel,
            "outcome": raw_outcome,
            "book_odd": float(raw_sig.get("soft_odds") or 1.0),
            "fair_odd": float(raw_sig.get("fair_odds") or 1.0),
            "prob": float(raw_sig.get("fair_prob") or 0.0),
            "edge_pct": round(edge_pct, 2),
            "tier": "TIER_1_SHARP" if raw_sig.get("is_steam_confirmed") else "TIER_2_MARKET_EV",
        }
        enriched_sig = _build_kelly_enriched_signal(
            base_sig=base_sig,
            optimizer=optimizer,
            bankroll=bankroll,
            enforced_stake=enforced_stake,
            min_ev_pct=min_ev_pct,
            meta={
                "source_engine": "sharp_market",
                "sharp_provider": raw_sig.get("sharp_provider", "PropLine/Shin"),
                "sharp_odds": float(raw_sig.get("sharp_odds") or 0.0),
                "is_steam_confirmed": bool(raw_sig.get("is_steam_confirmed", False)),
                "home": home_name,
                "away": away_name,
                "league": raw_sig.get("league", ""),
                "country": matched_bul.get("country", "International") if matched_bul else "International",
                "nesine_code": raw_sig.get("nesine_code"),
                "kickoff": ko_utc_iso,
                "kickoff_trt": kickoff_trt,
                "soft_book": raw_sig.get("soft_book", "nesine"),
            },
        )
        if enriched_sig:
            all_signals.append(enriched_sig)
            engine2_accepted_count += 1

    print(
        f"      -> Motor 2: taranan={len(propline_res.get('fixtures') or [])}, "
        f"Nesine eşleşen={int(propline_res.get('nesine_matched_fixtures') or 0)}, "
        f"kabul edilen={engine2_accepted_count}"
    )
    all_signals, engine1_vetoed_count = _veto_engine1_by_sharp_consensus(
        all_signals,
        propline_res.get("fixtures") or [],
    )
    engine1_surviving_count = sum(1 for s in all_signals if s.get("source_engine") == "team_strength")
    if engine1_vetoed_count:
        print(
            f"      -> 🛡️ Keskin Piyasa Vetosu: Motor 1'den {engine1_vetoed_count} sinyal "
            f"(canlı adil orana göre negatif EV) veto edildi; kalan Motor 1={engine1_surviving_count}"
        )
    all_signals = _merge_engine_signals(all_signals)
    fair_comparison = _build_fair_odds_comparison(
        propline_res.get("fixtures") or [],
        window_by_code,
        now_trt,
        enforced_hours,
        min_ev_pct=min_ev_pct,
    )
    print(
        f" ✅ Değerlendirilen maç: {evaluated_fixtures} | Bilinmeyen takım (Fail-Closed atlandı): {skipped_unknown} "
        f"| +EV Sinyal: {len(all_signals)} | Dünya Kıyaslama Satırı: {len(fair_comparison)}"
    )

    # 4. Terminal Table Output
    print("\n" + "-" * 92)
    print(" 💎 EN YÜKSEK +EV DEĞER SİNYALLERİ (12 Saat Penceresi & >= 50 TL)")
    print("-" * 92)
    if all_signals:
        header = (
            f"{'SAAT':<11} | {'MAÇ':<28} | {'MBS':<3} | {'MARKET':<11} | "
            f"{'SEÇİM':<16} | {'ORAN':<5} | {'ADİL':<5} | {'EV%':<6} | {'BAHİS':<7}"
        )
        print(header)
        print("-" * 92)
        for s in all_signals[:15]:
            print(
                f"{s['kickoff_trt']:<11} | "
                f"{str(s['match'])[:26]:<28} | "
                f"{str(s.get('mbs', 1)):<3} | "
                f"{str(s['market'])[:10]:<11} | "
                f"{str(s['selection'])[:15]:<16} | "
                f"{s['book_odd']:<5.2f} | "
                f"{s['fair_odd']:<5.2f} | "
                f"+{s['edge_pct']:<5.1f} | "
                f"{s['stake']:<5.0f}TL"
            )
    else:
        print(" ℹ️ Bu zaman penceresinde ve minimum EV eşiğinde kriterlere uyan değer sinyali bulunamadı.")

    print("\n" + "-" * 92)
    print(" 🌍 DÜRÜST ETİKETLİ DÜNYA ADİL ORAN TABLOSU (Keskin Piyasa vs Nesine — En İyi 12)")
    print("-" * 92)
    if fair_comparison:
        f_header = (
            f"{'SAAT':<11} | {'MAÇ':<26} | {'SEÇİM':<10} | {'NESİNE':<6} | "
            f"{'ADİL':<5} | {'P%':<5} | {'MARJ':<6} | {'EV%':<7} | {'DURUM'}"
        )
        print(f_header)
        print("-" * 92)
        for r in fair_comparison[:12]:
            ko_short = str(r["kickoff_trt"])[5:16] if len(str(r["kickoff_trt"])) >= 16 else str(r["kickoff_trt"])
            print(
                f"{ko_short:<11} | "
                f"{r['match'][:24]:<26} | "
                f"{r['selection'][:9]:<10} | "
                f"{r['nesine_odd']:<6.2f} | "
                f"{r['fair_odd']:<5.2f} | "
                f"{r['fair_prob_pct']:<5.1f} | "
                f"%{r['nesine_overround_pct']:<5.1f} | "
                f"{r['edge_pct']:+6.1f}% | "
                f"{r['honest_tag']}"
            )
    else:
        print(" ℹ️ Dünya piyasasıyla eşleşen aktif pencere maçı bulunamadı.")

    # 5. Uncorrelated Value Coupon Recommendation
    coupon = build_uncorrelated_coupon(all_signals, optimizer, bankroll, enforced_stake, max_legs=3)
    print("\n" + "-" * 92)
    print(" 🎟️  ÖNERİLEN GÜNÜN KUPONU (Korelasyonsuz +EV Kombine)")
    print("-" * 92)
    if coupon:
        for idx, leg in enumerate(coupon["legs"], start=1):
            print(
                f"  {idx}. [{leg['kickoff_trt']}] {leg['match']} "
                f"-> {leg['market']} / {leg['selection']} @ {leg['book_odd']:.2f} "
                f"(Adil: {leg['fair_odd']:.2f}, EV: +{leg['edge_pct']:.1f}%)"
            )
        mbs_ok = "EVET ✅" if coupon["mbs_satisfied"] else "HAYIR ⚠️ (MBS uyarısı)"
        print(
            f"\n  Toplam Oran: {coupon['combined_odds']:.2f} | Model Olasılığı: {coupon['combined_prob']*100:.1f}% | "
            f"Kupon EV: +{coupon['combined_ev_pct']:.1f}% | MBS Uygun: {mbs_ok}"
        )
        print(
            f"  Önerilen Tutar: {coupon['recommended_stake_tl']:.0f} TL -> "
            f"Olası Kazanç: {coupon['potential_return_tl']:.2f} TL"
        )
    else:
        print(" ℹ️ Kombine kupon oluşturmak için yeterli doğrudan oynanabilir +EV bacak bulunamadı.")

    # 6. Paper Trading Ledger & Optional ESPN Settlement
    print("\n[4/5] Paper-Trading Defteri & ESPN Sonuçlandırma...")
    paper_trader = PaperTradingEngine()
    ledger_ops: dict[str, Any] = {}
    if record_ledger and all_signals:
        playable_to_record = [s for s in all_signals if s.get("market") != "Çifte Şans"]
        if playable_to_record:
            ledger_ops["record"] = paper_trader.record_value_signals(playable_to_record)
            print(f" 📝 Deftere işlendi: {ledger_ops['record']}")
    if settle_espn:
        ledger_ops["settlement"] = paper_trader.fetch_espn_completed_and_settle()
        print(f" 🏁 ESPN sonuçlandırma: {ledger_ops['settlement']}")

    ledger_summary = paper_trader.compute_summary()
    print(
        f" 📊 Defter Özeti -> Toplam Sinyal: {ledger_summary['total_signals']} | "
        f"Bekleyen: {ledger_summary['pending_count']} | Sonuçlanan: {ledger_summary['settled_count']} | "
        f"ROI: {ledger_summary['roi_pct']:.2f}%"
    )

    # 7. Export Atomic JSON Artifact
    print("\n[5/5] Çıktı raporu kaydediliyor...")
    report_path = output_json or (PROJECT_ROOT / "output" / "daily_prototype_report.json")
    payload = {
        "generated_at_trt": now_trt.isoformat(),
        "window_end_trt": horizon_trt.isoformat(),
        "config": {
            "bankroll_tl": bankroll,
            "min_ev_pct": min_ev_pct,
            "min_stake_tl": enforced_stake,
            "max_hours": enforced_hours,
        },
        "summary": {
            "bulletin_total_matches": len(raw_bulletin),
            "window_valid_matches": len(window_matches),
            "evaluated_known_matches": evaluated_fixtures,
            "skipped_unknown_matches": skipped_unknown,
            "signals_count": len(all_signals),
            "engine1_signals_count": engine1_surviving_count,
            "engine1_raw_signals_count": engine1_signals_count,
            "engine1_vetoed_by_sharp_count": engine1_vetoed_count,
            "engine2_signals_count": engine2_accepted_count,
            "sharp_fixtures_scanned": len(propline_res.get("fixtures") or []),
            "sharp_nesine_matched": int(propline_res.get("nesine_matched_fixtures") or 0),
            "sharp_scanner_status": sharp_scanner_status,
            "fair_comparison_count": len(fair_comparison),
        },
        "signals": all_signals,
        "fair_odds_comparison": fair_comparison[:50],
        "recommended_coupon": coupon,
        "paper_trading_summary": ledger_summary,
        "ledger_operations": ledger_ops,
    }
    atomic_write_json(report_path, payload)
    print(f" ✅ Rapor kaydedildi: {report_path}")

    should_sync_ui = (output_json is None) if sync_ui_snapshot is None else bool(sync_ui_snapshot)
    if should_sync_ui:
        ui_dir = PROJECT_ROOT / "ui"
        if str(ui_dir) not in sys.path:
            sys.path.insert(0, str(ui_dir))
        try:
            from export_snapshot import generate_ui_snapshot

            snap_out = generate_ui_snapshot(output_file=ui_snapshot_path)
            payload["summary"]["ui_snapshot_path"] = str(snap_out)
            print(f" 🖥️ UI Snapshot güncellendi: {snap_out}")
        except Exception as exc:
            payload["summary"]["ui_snapshot_error"] = f"{type(exc).__name__}: {exc}"
            print(f" ⚠️ [SPEC-0012] UI Snapshot güncelleme uyarısı: {exc}")

    print("=" * 92)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="APE Sports-Engine Single-Command Daily Prototype Pipeline"
    )
    parser.add_argument("--bankroll", type=float, default=1000.0, help="Mevcut kasa (TL)")
    parser.add_argument("--min-ev", type=float, default=4.0, help="Minimum beklenen değer eşiği (%%)")
    parser.add_argument("--min-stake", type=float, default=50.0, help="Minimum bahis tutarı (TL, >= 50)")
    parser.add_argument("--max-hours", type=int, default=12, help="Maksimum saat penceresi (<= 12)")
    parser.add_argument("--record-ledger", action="store_true", help="Bulunan sinyalleri deftere kaydet")
    parser.add_argument("--settle-espn", action="store_true", help="Bekleyen sinyalleri ESPN'den sonuçlandır")
    parser.add_argument("--save-json", type=str, default=None, help="JSON rapor çıktı yolu")
    parser.add_argument("--no-ui-sync", action="store_true", help="ui/data/sports_intelligence_snapshot.json aktarımını atla")
    args = parser.parse_args()

    out_path = Path(args.save_json) if args.save_json else None
    run_daily_pipeline(
        bankroll=args.bankroll,
        min_ev_pct=args.min_ev,
        min_stake_tl=args.min_stake,
        max_hours=args.max_hours,
        record_ledger=args.record_ledger,
        settle_espn=args.settle_espn,
        output_json=out_path,
        sync_ui_snapshot=False if args.no_ui_sync else None,
    )


if __name__ == "__main__":
    main()
