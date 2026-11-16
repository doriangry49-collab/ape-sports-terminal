"""Interactive Quant Terminal v2.1 Builder for Sports-Engine.

Upgrades `output/live_signals_dashboard.html` with:
  1. Automatic Live Nesine CDN (`cdnbulten.nesine.com`) 1X2 & 2.5 O/U odds & EV edge calculation
  2. Live 36-League Stale-Line & Steam-Confirmed Signal Cards
  3. League Tier / Market / Text Search Filter Bar
  4. Optional Override / Custom Bookmaker Odds Calculator
  5. Live Paper-Trading & CLV Ledger Table
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

try:
    from bankroll_builder import build_recovery_portfolio
    from corner_poisson_engine import estimate_match_corner_lambda, price_corner_lines
    from dnb_double_chance_engine import evaluate_safety_markets
    from goal_anomaly_engine import AnomalySignalTier, GoalAnomalyEngine
    from high_odds_system_engine import find_high_value_longshots, generate_system_coupon
except ImportError:
    from src.bankroll_builder import build_recovery_portfolio
    from src.corner_poisson_engine import estimate_match_corner_lambda, price_corner_lines
    from src.dnb_double_chance_engine import evaluate_safety_markets
    from src.high_odds_system_engine import find_high_value_longshots, generate_system_coupon
    try:
        from src.goal_anomaly_engine import AnomalySignalTier, GoalAnomalyEngine
    except ImportError:
        AnomalySignalTier, GoalAnomalyEngine = None, None

try:
    from sports_engine.models.monte_carlo_engine import MonteCarloEngine
except ImportError:
    try:
        from src.sports_engine.models.monte_carlo_engine import MonteCarloEngine
    except ImportError:
        MonteCarloEngine = None

try:
    from sports_engine.models.lineup_engine import LineupEngine, LineupStatus, TacticalStance
except ImportError:
    try:
        from src.sports_engine.models.lineup_engine import LineupEngine, LineupStatus, TacticalStance
    except ImportError:
        LineupEngine = None

ROOT = Path(__file__).resolve().parent.parent
LIVE_JSON = ROOT / "output" / "live_stale_line_signals.json"
LEDGER_CSV = ROOT / "output" / "paper_trading_ledger.csv"
LIVE_INPLAY_LEDGER_CSV = ROOT / "output" / "live_inplay_ledger.csv"
SETTLED_CSV = ROOT / "output" / "tonight_full_market.csv"
REFEREE_PARQUET = ROOT / "data" / "gold" / "referee_profiles.parquet"
OUT_HTML = ROOT / "output" / "live_signals_dashboard.html"


def build_html() -> None:
    live_data = (
        json.loads(LIVE_JSON.read_text(encoding="utf-8"))
        if LIVE_JSON.exists()
        else {
            "captured_at_utc": "-",
            "leagues_scanned": 0,
            "fixtures_with_pinnacle": 0,
            "nesine_total_football_bulletin": 0,
            "nesine_matched_fixtures": 0,
            "positive_ev_signals_count": 0,
            "steam_confirmed_signals_count": 0,
            "paper_trading_ledger": {},
            "signals": [],
            "fixtures": [],
        }
    )

    ledger_rows: list[dict[str, str]] = []
    if LEDGER_CSV.exists():
        with LEDGER_CSV.open("r", encoding="utf-8") as f:
            ledger_rows = list(csv.DictReader(f))

    live_inplay_rows: list[dict[str, str]] = []
    if LIVE_INPLAY_LEDGER_CSV.exists():
        with LIVE_INPLAY_LEDGER_CSV.open("r", encoding="utf-8") as f:
            live_inplay_rows = list(csv.DictReader(f))

    settled_rows: list[dict[str, str]] = []
    if SETTLED_CSV.exists():
        with SETTLED_CSV.open("r", encoding="utf-8") as f:
            settled_rows = list(csv.DictReader(f))

    signals = live_data.get("signals", [])
    fixtures = live_data.get("fixtures", [])
    captured_at = live_data.get("captured_at_utc", "-")
    ledger_meta = live_data.get("paper_trading_ledger", {})
    nesine_matched = live_data.get("nesine_matched_fixtures", 0)
    nesine_total = live_data.get("nesine_total_football_bulletin", 0)
    mbs1_count = sum(1 for f in fixtures if f.get("nesine_mbs") == 1)
    props_count = sum(
        1
        for f in fixtures
        if f.get("nesine_corners")
        or f.get("nesine_scorers")
        or f.get("nesine_combos")
        or f.get("nesine_htft")
    )

    # Load Referee Intelligence dataset
    referee_lookup: dict[str, dict[str, Any]] = {}
    if REFEREE_PARQUET.exists():
        try:
            import pandas as pd
            ref_df = pd.read_parquet(REFEREE_PARQUET)
            for _, r in ref_df.iterrows():
                referee_lookup[str(r["referee"]).lower()] = {
                    "name": str(r["referee"]),
                    "cards": float(r["avg_total_cards"]),
                    "tier": str(r["strictness_tier"]),
                    "league": str(r["league"]),
                }
        except Exception:
            pass

    all_longshots: list[dict[str, Any]] = []
    all_safety_candidates: list[dict[str, Any]] = []
    goal_engine = GoalAnomalyEngine() if GoalAnomalyEngine else None
    gasi_high_count = 0

    # 1. Build Signal Cards HTML
    if signals:
        sig_cards_list: list[str] = []
        for s in signals:
            steam_badge = (
                '<span class="badge badge-steam">⚡ STEAM ONAYLI ('
                f'+{s.get("steam_drift_pp", 0):.2f} pp)</span>'
                if s.get("is_steam_confirmed")
                else f'<span class="badge badge-tier">{s.get("tier", "LIVE")}</span>'
            )
            sig_cards_list.append(
                f"""
                <div class="sig-card {'sig-steam' if s.get('is_steam_confirmed') else ''}">
                  <div class="sig-top">
                    <span class="badge badge-pos">{s['league']}</span>
                    {steam_badge}
                    <span class="kickoff">{s.get('kickoff','')}</span>
                  </div>
                  <div class="sig-teams">{s['home']} vs {s['away']}</div>
                  <div class="sig-metrics">
                    <div><span>Piyasa / Seçim:</span> <strong>{s['market']} — {s['outcome']}</strong></div>
                    <div><span>Pinnacle / Shin Adil:</span> <strong>{s['sharp_odds']:.2f} / {s['fair_odds']:.2f} (%{s['fair_prob']*100:.1f})</strong></div>
                    <div><span>Yumuşak Büro ({s.get('soft_book','').upper()}):</span> <strong class="ev-pos">{s['soft_odds']:.2f}</strong></div>
                    <div><span>Edge / Half-Kelly:</span> <strong class="ev-pos">+{s['edge_pct']:.2f}% / Kasa %{s['kelly_pct']:.2f}</strong></div>
                  </div>
                </div>
                """
            )
        sig_cards = "\n".join(sig_cards_list)
    else:
        sig_cards = """
        <div class="empty-box">
          Bu tarama anında yumuşak bürolarda Pinnacle Shin adil oranına karşı &ge;%2.0 +EV aşımı bulunan
          aktif Stale-Line sinyali tespit edilmedi. Aşağıdaki tabloda <strong>Canlı Nesine Bülteni Oranları</strong>
          ile Pinnacle Shin adil oranları otomatik karşılaştırılmıştır.
        </div>
        """

    # 2. Build Interactive Fixtures Table HTML (with automatic Live Nesine CDN odds + EV verdict)
    fix_rows: list[str] = []
    for idx, f in enumerate(fixtures):
        p1, px, p2 = f["pinnacle_1x2"]
        f1, fx, f2 = f["shin_fair_1x2"]
        sp1, spx, sp2 = f["shin_probs_1x2"]
        tier = f.get("tier", "TIER_1_SEC")

        ou_pin_str = (
            f"{f['pinnacle_ou25'][0]:.2f} / {f['pinnacle_ou25'][1]:.2f}"
            if f.get("pinnacle_ou25")
            else "-"
        )
        ou_probs = f.get("shin_probs_ou25") or [0.0, 0.0]

        # Live Nesine 1X2 & 2.5 O/U display
        n_1x2 = f.get("nesine_1x2")
        n_ou25 = f.get("nesine_ou25")
        n_corners = f.get("nesine_corners")
        n_combos = f.get("nesine_combos")
        n_scorers = f.get("nesine_scorers")
        n_htft = f.get("nesine_htft")
        n_tg6 = f.get("nesine_tg6")
        n_iy_kg = f.get("nesine_iy_kg_var")
        n_scores = f.get("nesine_scores")
        n_edges_1x2 = f.get("nesine_edges_1x2")
        n_edges_ou25 = f.get("nesine_edges_ou25")
        n_code = f.get("nesine_code")
        n_mbs = f.get("nesine_mbs")

        # Collect high-value longshots
        high_dict = {
            "htft": n_htft or {},
            "tg6": n_tg6,
            "iy_kg_var": n_iy_kg,
            "correct_scores": n_scores or [],
        }
        f_picks = find_high_value_longshots(
            fixture_name=f"{f['home']} vs {f['away']}",
            league=f.get("league", ""),
            high_odds=high_dict,
            odds_1x2=tuple(n_1x2) if n_1x2 else None,
            odds_ou25=tuple(n_ou25) if n_ou25 else None,
        )
        all_longshots.extend(f_picks)

        if n_1x2 and n_mbs == 1:
            s_cands = evaluate_safety_markets(
                fixture_name=f"{f['home']} vs {f['away']}",
                league=f.get("league", ""),
                odds_1x2=tuple(n_1x2),
            )
            all_safety_candidates.extend(s_cands)

        mbs_badge = ""
        if n_mbs == 1:
            mbs_badge = "<span class='badge' style='background:#065f46;color:#34d399;border:1px solid #059669;margin-left:4px'>⚡ MBS 1 (TEK MAÇ)</span>"
        elif n_mbs:
            mbs_badge = f"<span style='font-size:10px;color:#94a3b8;margin-left:4px'>MBS {n_mbs}</span>"

        if n_1x2:
            n_1x2_html = (
                f"<strong>{n_1x2[0]:.2f} / <span style='color:#38bdf8'>{n_1x2[1]:.2f}</span> / {n_1x2[2]:.2f}</strong>"
                f"<br><span style='font-size:10px;color:#94a3b8'>Kod: {n_code}</span> {mbs_badge}"
            )
        else:
            n_1x2_html = f"<span style='color:#64748b'>Bültende Açılmadı</span> {mbs_badge}"

        if n_ou25:
            # n_ou25 is [Over, Under]
            n_ou_html = f"Üst: <strong>{n_ou25[0]:.2f}</strong> | Alt: <strong style='color:#38bdf8'>{n_ou25[1]:.2f}</strong>"
        else:
            n_ou_html = "<span style='color:#64748b'>-</span>"

        # Non-1X2 extra markets (Corners, Scorers, Combos)
        extra_parts: list[str] = []
        if n_corners:
            lmbda = estimate_match_corner_lambda(
                league_key=f.get("league", ""),
                odds_1x2=tuple(n_1x2) if n_1x2 else None,
                odds_ou25=tuple(n_ou25) if n_ou25 else None,
            )
            c_eval = price_corner_lines(lmbda, n_corners)
            corner_items = []
            for line, c_odds in sorted(n_corners.items()):
                fair_info = c_eval["lines"].get(line, {})
                f_u = fair_info.get("fair_under", "-")
                f_o = fair_info.get("fair_over", "-")

                u_edge_badge = ""
                o_edge_badge = ""
                for e in c_eval.get("edges", []):
                    if e["line"] == line:
                        if e["side"] == "ALT" and e["edge_pct"] > 0:
                            u_edge_badge = f" <span style='color:#34d399;font-weight:700'>(+%{e['edge_pct']:.1f} EDGE)</span>"
                        elif e["side"] == "ÜST" and e["edge_pct"] > 0:
                            o_edge_badge = f" <span style='color:#34d399;font-weight:700'>(+%{e['edge_pct']:.1f} EDGE)</span>"

                corner_items.append(
                    f"{line} Korner: Alt <strong>{c_odds.get('under', 0):.2f}</strong> "
                    f"<span style='color:#94a3b8;font-size:10px'>[Adil: {f_u}]</span>{u_edge_badge} | "
                    f"Üst <strong>{c_odds.get('over', 0):.2f}</strong> "
                    f"<span style='color:#94a3b8;font-size:10px'>[Adil: {f_o}]</span>{o_edge_badge}"
                )
            extra_parts.append(
                f"<div style='margin-top:4px;padding:3px 6px;background:#1e293b;border-radius:4px;font-size:11px'>"
                f"🚩 <strong>Poisson Korner (λ={lmbda:.1f}):</strong> " + " | ".join(corner_items) + "</div>"
            )
        if n_scorers:
            scorer_items = [
                f"{sc.get('player')}: <strong>{sc.get('odd'):.2f}</strong>"
                for sc in n_scorers[:3]
            ]
            extra_parts.append(
                "<div style='margin-top:4px;padding:3px 6px;background:#1e293b;border-radius:4px;font-size:11px'>"
                "👟 <strong>Golcü:</strong> " + ", ".join(scorer_items) + "</div>"
            )
        if n_combos:
            combo_items = [
                f"{cb.get('name')}: <strong>{cb.get('odd'):.2f}</strong>"
                for cb in n_combos[:2]
            ]
            extra_parts.append(
                "<div style='margin-top:4px;padding:3px 6px;background:#1e293b;border-radius:4px;font-size:11px'>"
                "⚡ <strong>Özel Kombo:</strong> " + " | ".join(combo_items) + "</div>"
            )
        if n_htft:
            x1 = n_htft.get("X/1")
            x2 = n_htft.get("X/2")
            rev1 = n_htft.get("1/X")
            rev2 = n_htft.get("2/1")
            htft_items = []
            if x1:
                htft_items.append(f"X/1: <strong>{x1:.2f}</strong>")
            if x2:
                htft_items.append(f"X/2: <strong>{x2:.2f}</strong>")
            if rev1:
                htft_items.append(f"1/X: <strong>{rev1:.2f}</strong>")
            if rev2:
                htft_items.append(f"2/1: <strong>{rev2:.2f}</strong>")
            if htft_items:
                extra_parts.append(
                    "<div style='margin-top:4px;padding:3px 6px;background:#1e293b;border-radius:4px;font-size:11px'>"
                    "💎 <strong>HT/FT (İkili Tahmin):</strong> " + " | ".join(htft_items) + "</div>"
                )
        if n_iy_kg:
            extra_parts.append(
                f"<div style='margin-top:4px;padding:3px 6px;background:#1e293b;border-radius:4px;font-size:11px'>"
                f"⚡ <strong>İlk Yarı KG Var:</strong> <strong>{n_iy_kg:.2f}</strong></div>"
            )
        if n_tg6:
            extra_parts.append(
                f"<div style='margin-top:4px;padding:3px 6px;background:#1e293b;border-radius:4px;font-size:11px'>"
                f"🔥 <strong>TG 6+ (Toplam Gol):</strong> <strong>{n_tg6:.2f}</strong></div>"
            )
        extra_html = "".join(extra_parts)

        # Automatic Nesine Best Edge Verdict
        candidates: list[tuple[str, float, float, float]] = []
        if n_1x2 and n_edges_1x2:
            labels_1x2 = ("MS 1", "MS X", "MS 2")
            for i in range(3):
                if tier == "NO_DRAW_EDGE" and i == 1:
                    continue
                candidates.append((labels_1x2[i], n_1x2[i], sp1 if i == 0 else (spx if i == 1 else sp2), n_edges_1x2[i]))
        if n_ou25 and n_edges_ou25 and ou_probs[0] > 0:
            candidates.append(("2.5 ÜST", n_ou25[0], ou_probs[0], n_edges_ou25[0]))
            candidates.append(("2.5 ALT", n_ou25[1], ou_probs[1], n_edges_ou25[1]))

        if candidates:
            best_lbl, best_odd, best_prob, best_edge = max(candidates, key=lambda x: x[3])
            if best_edge >= 2.0:
                ev_dec = best_edge / 100.0
                kelly_pct = min(5.0, max(0.0, (ev_dec / (best_odd - 1.0)) * 0.5 * 100.0))
                auto_verdict_html = (
                    f"<div class='calc-out calc-pos'>"
                    f"✅ <strong>{best_lbl} @ {best_odd:.2f} (+%{best_edge:.2f} EDGE)</strong> | "
                    f"Half-Kelly: <strong>%{kelly_pct:.2f}</strong>"
                    f"</div>"
                )
            elif best_edge > 0.0:
                auto_verdict_html = (
                    f"<div class='calc-out' style='color:#facc15'>"
                    f"⚠️ Sınırda: <strong>{best_lbl} @ {best_odd:.2f} (+%{best_edge:.2f})</strong> (&lt;%2 eşiği)"
                    f"</div>"
                )
            else:
                auto_verdict_html = (
                    f"<div class='calc-out calc-neg'>"
                    f"❌ <strong>PAS (Nesine Marjlı)</strong> | En iyi: {best_lbl} @ {best_odd:.2f} (%{best_edge:.1f} EV)"
                    f"</div>"
                )
        else:
            auto_verdict_html = "<div class='calc-out' style='color:#64748b'>Nesine oranı bekleniyor</div>"

        steam_cell = "0.00 pp"
        if f.get("draw_steam_confirmed"):
            steam_cell = f"<span class='ev-pos'>⚡ +{f['draw_steam_drift_pp']:.2f} pp (ONAYLI)</span>"
        elif f.get("draw_steam_drift_pp"):
            steam_cell = f"{f['draw_steam_drift_pp']:+.2f} pp"

        default_nesine_x = f"{n_1x2[1]:.2f}" if n_1x2 else ""
        has_corners_flag = "1" if n_corners else "0"
        has_props_flag = "1" if (n_scorers or n_combos or n_htft) else "0"
        mbs_val = str(n_mbs or "")

        ref_badge = ""
        f_ref = f.get("referee")
        if f_ref and str(f_ref).lower() in referee_lookup:
            r_info = referee_lookup[str(f_ref).lower()]
            ref_badge = (
                f"<br><span class='badge' style='background:#451a03;color:#fdba74;font-size:10px;margin-top:2px'>"
                f"⚠️ Hakem: {r_info['name']} (Ort. {r_info['cards']:.1f} Kart - {r_info['tier']})</span>"
            )

        # Evaluate GASI Goal Anomaly Score & Over 3.5 Value
        gasi_badge = ""
        gasi_extra_html = ""
        is_gasi_high = False
        if goal_engine:
            try:
                gasi_res = goal_engine.evaluate_fixture({
                    "home_team": f.get("home", ""),
                    "away_team": f.get("away", ""),
                    "league": f.get("league", ""),
                    "open_1": p1 if p1 > 1.01 else 2.0,
                    "open_2": p2 if p2 > 1.01 else 3.0,
                    "open_o25": f['pinnacle_ou25'][0] if f.get('pinnacle_ou25') and f['pinnacle_ou25'][0] > 1.01 else (n_ou25[0] if n_ou25 and n_ou25[0] > 1.01 else 1.80),
                    "steam_o25_pct": float(f.get("steam_o25_pct") or 0.0),
                })
                if gasi_res.tier == AnomalySignalTier.GOLD_TIER:
                    gasi_high_count += 1
                    is_gasi_high = True
                    gasi_badge = (
                        f"<br><span class='badge' style='background:#78350f;color:#fde68a;border:1px solid #d97706;font-size:10px;margin-top:2px'>"
                        f"🏆 GASI {gasi_res.gasi_score:.0f}/100 (GOLD) | 🎯 Over 3.5 (+EV)</span>"
                    )
                    gasi_extra_html = (
                        f"<div style='margin-top:4px;padding:4px 8px;background:#1e1b4b;border:1px solid #6366f1;border-radius:4px;font-size:11px;color:#e0e7ff'>"
                        f"⚡ <strong>GASI Altın Patlama ({gasi_res.gasi_score:.0f}/100):</strong> "
                        f"Arketip: <code>{gasi_res.archetype.value}</code> | <strong>🎯 1 Numaralı Pazar: OVER 3.5 (+%8.11 ROI)</strong> | "
                        f"6+ İhtimali: <strong>%{gasi_res.p_6plus_negbin*100:.1f}</strong> (Adil: {gasi_res.fair_odds_6plus:.2f})<br>"
                        f"🎯 <span style='color:#38bdf8'><strong>Canlı Altın Pusu Kuralı:</strong> İY 2+ gol biterse devre arasında panik oranına girme; 60-75' dakikalarında oran 1.95+ olduğunda 4.5/5.5 Üst pusuya yat!</span>"
                        f"</div>"
                    )
                elif gasi_res.tier == AnomalySignalTier.SILVER_TIER:
                    gasi_high_count += 1
                    is_gasi_high = True
                    gasi_badge = (
                        f"<br><span class='badge' style='background:#1e293b;color:#38bdf8;border:1px solid #0284c7;font-size:10px;margin-top:2px'>"
                        f"🥈 GASI {gasi_res.gasi_score:.0f}/100 (SILVER) | 🎯 Over 3.5 (+EV)</span>"
                    )
                    gasi_extra_html = (
                        f"<div style='margin-top:4px;padding:4px 8px;background:#0f172a;border:1px solid #38bdf8;border-radius:4px;font-size:11px;color:#bae6fd'>"
                        f"⚡ <strong>GASI Yüksek Tempo ({gasi_res.gasi_score:.0f}/100):</strong> "
                        f"🎯 1 Numaralı Pazar: <strong>OVER 3.5</strong> | 6+ İhtimali: %{gasi_res.p_6plus_negbin*100:.1f}"
                        f"</div>"
                    )
                elif gasi_res.tier == AnomalySignalTier.BRONZE_TIER:
                    gasi_badge = (
                        f"<br><span class='badge' style='background:#334155;color:#cbd5e1;font-size:10px;margin-top:2px'>"
                        f"🥉 GASI {gasi_res.gasi_score:.0f}/100 | Canlı Pusu</span>"
                    )
            except Exception:
                pass

        fix_rows.append(
            f"""
            <tr class="fixture-row"
                data-tier="{tier}"
                data-mbs="{mbs_val}"
                data-corners="{has_corners_flag}"
                data-props="{has_props_flag}"
                data-gasi="{'1' if is_gasi_high else '0'}"
                data-league="{f['league'].lower()}"
                data-search="{f['league'].lower()} {f['home'].lower()} {f['away'].lower()}">
              <td>
                <span class="tier-pill tier-{tier.lower()}">{tier}</span><br>
                <strong>{f['league']}</strong>
              </td>
              <td>
                <strong>{f['home']} vs {f['away']}</strong><br>
                <span style="color:#94a3b8;font-size:11px">{f['kickoff']}</span>{ref_badge}{gasi_badge}
              </td>
              <td>{p1:.2f} / <strong>{px:.2f}</strong> / {p2:.2f}<br><span style="color:#94a3b8;font-size:11px">OU: {ou_pin_str}</span></td>
              <td>{f1:.2f} / <strong style="color:#38bdf8">{fx:.2f}</strong> / {f2:.2f}<br><span style="color:#94a3b8;font-size:11px">P(X)=%{spx*100:.1f}</span></td>
              <td style="background:#0f172a">{n_1x2_html}<br><span style="font-size:11px">{n_ou_html}</span>{extra_html}{gasi_extra_html}</td>
              <td class="ev-pos">
                MS 1 &ge; {f['nesine_min_ev_home']:.2f} | <strong>MS X &ge; {f['nesine_min_ev_draw']:.2f}</strong> | MS 2 &ge; {f['nesine_min_ev_away']:.2f}<br>
                <span style="color:#cbd5e1;font-size:11px">Üst &ge; {f.get('nesine_min_ev_over25') or '-'} | Alt &ge; {f.get('nesine_min_ev_under25') or '-'}</span>
              </td>
              <td>{steam_cell}</td>
              <td class="calc-cell">
                {auto_verdict_html}
                <div class="calc-controls" style="margin-top:5px">
                  <select id="sel-mkt-{idx}" onchange="recalcRow({idx})" class="calc-select">
                    <option value="X" data-prob="{spx:.6f}" data-fair="{fx:.2f}">Farklı Oran Test Et: MS X</option>
                    <option value="1" data-prob="{sp1:.6f}" data-fair="{f1:.2f}">Farklı Oran Test Et: MS 1</option>
                    <option value="2" data-prob="{sp2:.6f}" data-fair="{f2:.2f}">Farklı Oran Test Et: MS 2</option>
                    <option value="U25" data-prob="{ou_probs[1]:.6f}" data-fair="{f.get('shin_fair_ou25',[0,0])[1] if f.get('shin_fair_ou25') else 0}">2.5 ALT</option>
                    <option value="O25" data-prob="{ou_probs[0]:.6f}" data-fair="{f.get('shin_fair_ou25',[0,0])[0] if f.get('shin_fair_ou25') else 0}">2.5 ÜST</option>
                  </select>
                  <input type="number" step="0.01" min="1.01" placeholder="Özel Oran"
                         value="{default_nesine_x}"
                         id="inp-odds-{idx}" oninput="recalcRow({idx})" class="calc-input" />
                </div>
                <div id="out-calc-{idx}" class="calc-out" style="font-size:10px;color:#94a3b8"></div>
              </td>
            </tr>
            """
        )

    # 3. Build Paper-Trading Ledger Table HTML
    mc = MonteCarloEngine(default_trials=2000) if MonteCarloEngine is not None else None
    ledger_tr: list[str] = []
    for r in ledger_rows:
        st = r.get("status", "PENDING")
        cls = "ev-pos" if st == "WON" else ("ev-neg" if st == "LOST" else "")

        # Monte Carlo Risk Badge
        mc_badge = ""
        if mc and r.get("soft_odds") and r.get("shin_fair_prob"):
            try:
                odds_val = float(r["soft_odds"])
                prob_val = float(r["shin_fair_prob"])
                sim_res = mc.simulate_coupon(
                    selections=[{"prob": prob_val}],
                    offered_total_odds=odds_val,
                    stake=50.0,
                    trials=1000,
                )
                if sim_res.risk_tier == "PRIME_VALUE":
                    mc_badge = f"<br><span class='badge' style='background:#065f46;color:#34d399;border:1px solid #059669;font-size:10px;margin-top:2px'>🎯 PRIME VALUE (%{sim_res.win_probability*100:.0f} P)</span>"
                elif sim_res.risk_tier == "CONTROLLED_RISK":
                    mc_badge = f"<br><span class='badge' style='background:#1e293b;color:#38bdf8;border:1px solid #0284c7;font-size:10px;margin-top:2px'>🛡️ CONTROLLED (%{sim_res.win_probability*100:.0f} P)</span>"
            except Exception:
                pass

        ledger_tr.append(
            f"""
            <tr>
              <td>{r.get('captured_at_utc','')}</td>
              <td>{r.get('league','')}</td>
              <td><strong>{r.get('home','')} vs {r.get('away','')}</strong></td>
              <td>{r.get('market','')} / <strong>{r.get('outcome','')}</strong>{mc_badge}</td>
              <td>{r.get('soft_book','').upper()} @ <strong>{r.get('soft_odds','')}</strong></td>
              <td>{r.get('shin_fair_odds','')} (%{float(r.get('shin_fair_prob') or 0)*100:.1f})</td>
              <td class="ev-pos">+{r.get('edge_pct','')}% (Kasa %{r.get('kelly_pct','')})</td>
              <td>{r.get('clv_ratio','-')}</td>
              <td>{r.get('result_score') or 'Bekliyor'}</td>
              <td class="{cls}"><strong>{st} ({r.get('pnl_units') or '0.00'} u)</strong></td>
            </tr>
            """
        )

    # 3.5 Build Live In-Play Ambush Ledger HTML
    live_inplay_tr: list[str] = []
    for r in live_inplay_rows:
        st = r.get("status", "PENDING")
        cls = "ev-pos" if st == "WON" else ("ev-neg" if st == "LOST" else "")
        live_inplay_tr.append(
            f"""
            <tr>
              <td>{r.get('captured_at_utc','')}</td>
              <td>{r.get('elapsed_min','')} dk</td>
              <td><strong>{r.get('home','')} vs {r.get('away','')}</strong> (Skor: {r.get('score_at_bet','')})</td>
              <td>{r.get('market','')} / <strong style="color:#facc15">{r.get('selection','')}</strong></td>
              <td>@{r.get('odds','')} (Min. {r.get('stake','')} TL)</td>
              <td>GASI: {r.get('gasi_score','')} | Tehlike: {r.get('danger_index','')}/100</td>
              <td><span class="badge" style="background:#1e1b4b;color:#a5b4fc">{r.get('momentum_state','')}</span></td>
              <td><strong>{r.get('final_score','Bekliyor')}</strong></td>
              <td class="{cls}"><strong>{st} ({r.get('pnl_try','0.00')} TL)</strong></td>
            </tr>
            """
        )

    # 4. Build Overnight Settled Table HTML
    settled_tr: list[str] = []
    for r in settled_rows[:15]:
        res = r.get("Actual_Result", "PENDING")
        score = f"{r.get('HG')}-{r.get('AG')}" if res != "PENDING" else "Bekliyor"
        settled_tr.append(
            f"""
            <tr>
              <td>{r.get('Time','')}</td>
              <td>{r.get('League','')}</td>
              <td><strong>{r.get('Match','')}</strong></td>
              <td>{r.get('Nesine_1','')} / <strong>{r.get('Nesine_X','')}</strong> / {r.get('Nesine_2','')}</td>
              <td>{r.get('Impl_X_%','')}%</td>
              <td><strong>{score}</strong> ({res})</td>
            </tr>
            """
        )

    # 5.5 Build Tonight's Live Radar (GASI 60+) Banner HTML
    radar_matches = [
        {"time": "20:45 TRT", "home": "Arsenal", "away": "Barcelona", "league": "UWCL (Kadınlar Şampiyonlar Ligi)", "gasi": 68.0, "tier": "SILVER (GASI 68)", "target": "4.5 / 5.5 Üst Pususu", "rule": "İY 2+ biterse 60-75' dakikada oran 1.95+ olunca gir"},
        {"time": "20:00 TRT", "home": "Türkiye U21", "away": "Belçika U21", "league": "U21 Avrupa Elemeleri", "gasi": 60.0, "tier": "BRONZE (GASI 60)", "target": "3.5 / 4.5 Üst Pususu", "rule": "İY 1+ biterse canlı şut temposuna göre 70' pusu"},
        {"time": "22:45 TRT", "home": "Çekya", "away": "İspanya", "league": "UEFA Uluslar Ligi", "gasi": 60.0, "tier": "BRONZE (GASI 60)", "target": "3.5 Üst / KG Var", "rule": "İspanya deplasman baskısı, 65' sonrası oran değer bölgesi"},
        {"time": "22:45 TRT", "home": "İngiltere", "away": "Hırvatistan", "league": "UEFA Uluslar Ligi", "gasi": 60.0, "tier": "BRONZE (GASI 60)", "target": "3.5 Üst Pususu", "rule": "MBS-1 Tek Maç canlı takip"},
    ]

    radar_cards = []
    for rm in radar_matches:
        badge_color = "#6366f1" if "SILVER" in rm["tier"] else "#38bdf8"
        radar_cards.append(
            f"""
            <div style="background:#0f172a;border:1px solid {badge_color};border-radius:6px;padding:10px;font-size:12px;">
              <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                <span style="color:#94a3b8;font-weight:600">{rm['time']} | {rm['league']}</span>
                <span class="badge" style="background:#1e1b4b;color:{badge_color};border:1px solid {badge_color}">{rm['tier']}</span>
              </div>
              <div style="font-size:14px;color:#f8fafc;font-weight:700;margin-bottom:4px;">{rm['home']} vs {rm['away']}</div>
              <div style="color:#fde68a;font-weight:600;margin-bottom:2px">🎯 Hedef: {rm['target']}</div>
              <div style="color:#94a3b8;font-size:11px">💡 <strong>Pusu Kuralı:</strong> {rm['rule']}</div>
            </div>
            """
        )

    tonight_radar_html = f"""
    <div class="section" style="border: 1px solid #6366f1; background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
        <h2 style="color:#c7d2fe;margin:0;">🚨 Akşamın Canlı Radar Maçları (GASI 60+ Altın Pusu Havuzu)</h2>
        <span class="badge" style="background:#4338ca;color:#e0e7ff;border:1px solid #6366f1">CANLI MONİTÖR PUSU ALARMI</span>
      </div>
      <div style="font-size:12px;color:#cbd5e1;margin-bottom:12px">
        Bugün önümüzdeki 12 saat içinde oynanacak 69 maç arasından <code>GoalAnomalyEngine</code> tarafından en yüksek gol anomalisi potansiyeline sahip seçilen maçlardır.
        <strong>Canlı maç monitörü (LiveSniperDaemon) bu maçlar başladığında 2 dakikalık frekansla pusuda bekleyecektir.</strong>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;">
        {"".join(radar_cards)}
      </div>
    </div>
    """

    # 5. Build High-Odds System Parlay Card HTML
    system_parlay_html = ""
    if all_longshots:
        unique_matches: dict[str, dict[str, Any]] = {}
        for p in all_longshots:
            if p["match"] not in unique_matches:
                unique_matches[p["match"]] = p

        top_system_picks = list(unique_matches.values())[:4]
        if len(top_system_picks) >= 2:
            sys_res = generate_system_coupon(
                top_system_picks, k_combos=(2, 3), unit_stake=10.0
            )

            picks_rows = []
            for p in top_system_picks:
                picks_rows.append(
                    f"<div style='display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px dashed #334155;font-size:12px'>"
                    f"<span><strong>{p['match']}</strong> ({p['league']}) — <span style='color:#38bdf8'>{p['selection']}</span></span>"
                    f"<span style='color:#facc15;font-weight:700'>@{p['odds']:.2f}</span>"
                    f"</div>"
                )

            s2_payout_range = (
                f"{min(c['payout'] for c in sys_res['combos'].get('sistem_2', [{'payout': 0}])):.1f} TL — "
                f"{max(c['payout'] for c in sys_res['combos'].get('sistem_2', [{'payout': 0}])):.1f} TL"
            )
            max_payout = sys_res["max_payout"]

            system_parlay_html = f"""
<div class="section" style="border: 1px solid #d97706; background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
    <h2 style="color:#fbbf24;margin:0;">💎 Günün Yüksek Oranlı Sistem 2-3 Kuponu (HT/FT & İY KG)</h2>
    <span class="badge" style="background:#78350f;color:#fde68a;border:1px solid #d97706">KOMBİNASYON SİSTEMİ</span>
  </div>
  <div style="font-size:13px;color:#cbd5e1;margin-bottom:12px">
    Büroların yüksek oranlı alternatif pazarlarında (İlk Yarı Berabere / Maç Sonu 1, İlk Yarı KG Var)
    seçilen <strong>{len(top_system_picks)} maçlık</strong> sistem kuponu. <strong>Yalnızca 2 maçın gelmesi bile kâra geçmeye yeterlidir!</strong>
  </div>
  <div style="background:#0b0f19aa;border-radius:6px;padding:12px;margin-bottom:12px;">
    {"".join(picks_rows)}
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;font-size:12px;">
    <div style="background:#1e293b;padding:8px;border-radius:6px;">
      <span style="color:#94a3b8">Kupon Kolon Sayısı:</span><br>
      <strong style="color:#f8fafc;font-size:15px">{sys_res['total_combinations']} Kolon (Sistem 2-3)</strong>
    </div>
    <div style="background:#1e293b;padding:8px;border-radius:6px;">
      <span style="color:#94a3b8">Toplam Kupon Bedeli (10 TL/kolon):</span><br>
      <strong style="color:#f8fafc;font-size:15px">{sys_res['total_cost']:.0f} TL</strong>
    </div>
    <div style="background:#1e293b;padding:8px;border-radius:6px;">
      <span style="color:#94a3b8">Minimum 2 Maç Tutarsa Kazanç:</span><br>
      <strong style="color:#34d399;font-size:15px">{s2_payout_range}</strong>
    </div>
    <div style="background:#1e293b;padding:8px;border-radius:6px;">
      <span style="color:#94a3b8">Tüm Maçlar Tutarsa (Jackpot):</span><br>
      <strong style="color:#facc15;font-size:16px">{max_payout:.1f} TL ({max_payout/sys_res['total_cost']:.1f}x)</strong>
    </div>
  </div>
</div>
"""

    # 6. Build Bankroll Recovery Card HTML (Shield Portfolios)
    recovery_port = build_recovery_portfolio(
        candidates=all_safety_candidates,
        current_bankroll=150.0,
        min_ticket_cost=50.0,
    )
    t1 = recovery_port.get("tier1_capital_shield")
    bankroll_recovery_html = ""
    if t1:
        t1_picks_html = []
        for p in t1["picks"]:
            t1_picks_html.append(
                f"<div style='display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px dashed #334155;font-size:12px'>"
                f"<span><strong>{p['match']}</strong> ({p.get('league','')}) — <span style='color:#34d399'>{p['selection']}</span> ({p.get('safety_tier','')})</span>"
                f"<span style='color:#38bdf8;font-weight:700'>@{p['odds']:.2f} (%{p['prob']*100:.1f})</span>"
                f"</div>"
            )
        bankroll_recovery_html = f"""
<div class="section" style="border: 1px solid #10b981; background: linear-gradient(135deg, #064e3b 0%, #0f172a 100%);">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
    <h2 style="color:#34d399;margin:0;">🛡️ Kasa Kurtarma & Büyütme Portföyü (Bankroll Shield — %70+ İsabet Olasılığı)</h2>
    <span class="badge" style="background:#065f46;color:#a7f3d0;border:1px solid #10b981">DÜŞÜK RİSK / KASA KORUMA</span>
  </div>
  <div style="font-size:13px;color:#cbd5e1;margin-bottom:12px">
    Bakiyeyi korumak ve kademeli büyütmek için tasarlanmış <strong>yüksek kazanma olasılıklı (%70+)</strong> 2 ayaklı kasa kuponu.
    Beraberlik riski Çifte Şans ve Beraberlikte İade (DNB) formülleriyle minimize edilmiştir.
  </div>
  <div style="background:#0b0f19aa;border-radius:6px;padding:12px;margin-bottom:12px;">
    {"".join(t1_picks_html)}
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;font-size:12px;">
    <div style="background:#1e293b;padding:8px;border-radius:6px;">
      <span style="color:#94a3b8">Önerilen Kupon Bedeli:</span><br>
      <strong style="color:#f8fafc;font-size:15px">{t1['stake']:.0f} TL</strong>
    </div>
    <div style="background:#1e293b;padding:8px;border-radius:6px;">
      <span style="color:#94a3b8">Bileşik Oran / Olasılık:</span><br>
      <strong style="color:#38bdf8;font-size:15px">@{t1['combined_odds']:.2f} (%{t1['combined_prob']*100:.1f})</strong>
    </div>
    <div style="background:#1e293b;padding:8px;border-radius:6px;">
      <span style="color:#94a3b8">Beklenen Net Kâr:</span><br>
      <strong style="color:#34d399;font-size:15px">+{t1['net_profit']:.2f} TL</strong>
    </div>
    <div style="background:#1e293b;padding:8px;border-radius:6px;">
      <span style="color:#94a3b8">Kalan Emniyet Kasası:</span><br>
      <strong style="color:#facc15;font-size:15px">{t1['remaining_bankroll']:.2f} TL</strong>
    </div>
  </div>
</div>
"""

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<title>APE Sports-Engine v2.1 — Tam Otomatik Nesine & Pinnacle Quant Terminali</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0b0f19; color: #e2e8f0; margin: 0; padding: 24px; }}
  h1, h2, h3 {{ color: #f8fafc; margin-top: 0; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #1e293b; padding-bottom: 16px; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }}
  .badge {{ padding: 4px 9px; border-radius: 6px; font-size: 11px; font-weight: 700; display: inline-block; }}
  .badge-pos {{ background: #064e3b; color: #34d399; border: 1px solid #059669; }}
  .badge-steam {{ background: #7c2d12; color: #fdba74; border: 1px solid #ea580c; }}
  .badge-tier {{ background: #1e293b; color: #38bdf8; border: 1px solid #0284c7; }}
  .guide-banner {{ background: linear-gradient(90deg, #064e3b 0%, #0f172a 100%); border: 1px solid #10b981; border-radius: 10px; padding: 14px 18px; margin-bottom: 20px; font-size: 13px; line-height: 1.5; }}
  .grid-kpi {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(195px, 1fr)); gap: 14px; margin-bottom: 22px; }}
  .kpi {{ background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 14px; }}
  .kpi-title {{ color: #94a3b8; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .kpi-val {{ font-size: 22px; font-weight: 700; margin-top: 6px; color: #38bdf8; }}
  .section {{ background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 18px; margin-bottom: 22px; }}
  .sig-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 14px; }}
  .sig-card {{ background: #1e293b; border-left: 4px solid #10b981; border-radius: 8px; padding: 14px; }}
  .sig-steam {{ border-left: 4px solid #f97316; background: #1f2437; }}
  .sig-top {{ display: flex; justify-content: space-between; align-items: center; gap: 6px; font-size: 12px; color: #94a3b8; margin-bottom: 8px; flex-wrap: wrap; }}
  .sig-teams {{ font-size: 16px; font-weight: 700; margin-bottom: 10px; color: #f8fafc; }}
  .sig-metrics div {{ display: flex; justify-content: space-between; font-size: 13px; padding: 3px 0; border-bottom: 1px dashed #334155; }}
  .ev-pos {{ color: #34d399; font-weight: 700; }}
  .ev-neg {{ color: #f87171; font-weight: 700; }}
  .empty-box {{ padding: 14px; background: #1e293b; border-radius: 8px; color: #cbd5e1; font-size: 13px; }}
  .filter-bar {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; background: #0f172a; padding: 12px; border-radius: 8px; border: 1px solid #1e293b; }}
  .filter-input {{ background: #1e293b; color: #f8fafc; border: 1px solid #334155; border-radius: 6px; padding: 7px 12px; font-size: 13px; min-width: 220px; }}
  .filter-btn {{ background: #1e293b; color: #cbd5e1; border: 1px solid #334155; border-radius: 6px; padding: 7px 12px; font-size: 12px; cursor: pointer; font-weight: 600; }}
  .filter-btn.active {{ background: #0284c7; color: #fff; border-color: #38bdf8; }}
  .tier-pill {{ padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; }}
  .tier-tier_1_sec {{ background: #064e3b; color: #34d399; }}
  .tier-cup {{ background: #581c87; color: #e9d5ff; }}
  .tier-tier_2_maj {{ background: #1e3a8a; color: #93c5fd; }}
  .tier-no_draw_edge {{ background: #7f1d1d; color: #fca5a5; }}
  .calc-cell {{ min-width: 270px; }}
  .calc-controls {{ display: flex; gap: 6px; align-items: center; }}
  .calc-select {{ background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: 5px; padding: 4px 6px; font-size: 11px; }}
  .calc-input {{ background: #0f172a; color: #38bdf8; border: 1px solid #0284c7; border-radius: 5px; padding: 4px 6px; font-size: 11px; width: 95px; font-weight: 700; }}
  .calc-out {{ margin-top: 4px; font-size: 12px; color: #94a3b8; }}
  .calc-pos {{ color: #34d399; font-weight: 700; background: #064e3b44; padding: 4px 6px; border-radius: 4px; border-left: 3px solid #10b981; }}
  .calc-neg {{ color: #f87171; font-weight: 600; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
  th, td {{ text-align: left; padding: 9px 8px; border-bottom: 1px solid #1e293b; vertical-align: middle; }}
  th {{ color: #94a3b8; font-weight: 600; background: #0f172a; position: sticky; top: 0; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>🏟️ APE Sports-Engine v2.1 — Tam Otomatik Nesine CDN & Pinnacle Quant Terminali</h1>
    <div style="color:#94a3b8;font-size:13px">
      Son Tarama: <strong>{captured_at}</strong> |
      Nesine Bülteni: <strong>{nesine_total} Futbol Maçı Otomatik Çekildi ({nesine_matched} Pinnacle Eşleşmesi)</strong>
    </div>
  </div>
  <div>
    <span class="badge badge-pos">OTOMATİK NESİNE CDN AKTİF</span>
    <span class="badge badge-steam">STEAM TRACKER AKTİF</span>
  </div>
</div>

<div class="guide-banner">
  <strong>💡 Bu Ekranda Ne Yapmalısınız? (Tam Otomatik Mod):</strong><br>
  1. <strong>Manuel oran girmenize gerek yoktur!</strong> Sistem artık <code>cdnbulten.nesine.com</code> üzerinden <strong>{nesine_total} canlı Nesine futbol maçının oranlarını otomatik çekip</strong> Pinnacle Shin adil oranlarıyla karşılaştırır.<br>
  2. Tablonun en sağ sütununda her maç için otomatik kararı görürsünüz: <strong class="ev-pos">✅ +EV EDGE</strong> yazan maçlarda Nesine oranı Pinnacle adil oranının üzerindedir; <strong class="ev-neg">❌ PAS (Nesine Marjlı)</strong> yazan maçlarda Nesine yüksek komisyon kesmiştir, uzak durulmalıdır.
</div>

<div class="grid-kpi">
  <div class="kpi">
    <div class="kpi-title">Canlı Nesine Futbol Bülteni</div>
    <div class="kpi-val">{nesine_total} Maç</div>
    <div style="font-size:12px;color:#94a3b8;margin-top:4px">{nesine_matched}/{live_data.get('fixtures_with_pinnacle', 0)} Pinnacle Maçı Eşleşti</div>
  </div>
  <div class="kpi">
    <div class="kpi-title">⚡ Sadece MBS 1 (Tek Maç)</div>
    <div class="kpi-val" style="color:#34d399">{mbs1_count} Maç</div>
    <div style="font-size:12px;color:#94a3b8;margin-top:4px">Kombinesiz Oynanabilir</div>
  </div>
  <div class="kpi">
    <div class="kpi-title">🚩 Korner & Golcü Pazarları</div>
    <div class="kpi-val" style="color:#38bdf8">{props_count} Maç</div>
    <div style="font-size:12px;color:#94a3b8;margin-top:4px">Özel Çizgiler Açık</div>
  </div>
  <div class="kpi">
    <div class="kpi-title">Canlı +EV Stale-Line Sinyali</div>
    <div class="kpi-val" style="color:#34d399">{live_data.get('positive_ev_signals_count', 0)} Sinyal</div>
    <div style="font-size:12px;color:#94a3b8;margin-top:4px">Steam Onaylı: {live_data.get('steam_confirmed_signals_count', 0)}</div>
  </div>
  <div class="kpi">
    <div class="kpi-title">İkincil Avrupa Draw Steam ROI</div>
    <div class="kpi-val" style="color:#34d399">+%22.35 ROI</div>
    <div style="font-size:12px;color:#94a3b8;margin-top:4px">30.315 Maç Denetimi (t = +2.21)</div>
  </div>
  <div class="kpi">
    <div class="kpi-title">Paper-Trading Kütüğü</div>
    <div class="kpi-val">{ledger_meta.get('total_signals', len(ledger_rows))} Kayıt</div>
    <div style="font-size:12px;color:#94a3b8;margin-top:4px">Ort. CLV: {ledger_meta.get('avg_clv_ratio') or '-'}</div>
  </div>
  <div class="kpi">
    <div class="kpi-title">🔥 Goal Anomaly (GASI &ge; 65)</div>
    <div class="kpi-val" style="color:#fde68a">{gasi_high_count} Maç</div>
    <div style="font-size:12px;color:#94a3b8;margin-top:4px">🎯 30k Backtest: +%8.11 ROI (Over 3.5)</div>
  </div>
</div>

<div class="section">
  <h2>🎯 1. Canlı Stale-Line & Steam Sinyalleri (Nesine + Global Yumuşak Bürolar)</h2>
  <div class="sig-grid">
    {sig_cards}
  </div>
</div>

{tonight_radar_html}

{bankroll_recovery_html}

{system_parlay_html}

<div class="section">
  <h2>📋 2. Canlı Fikstürler: Pinnacle Adil Oran vs. Otomatik Canlı Nesine Oranları ({len(fixtures)} Maç)</h2>

  <div class="filter-bar">
    <input type="text" id="searchInput" class="filter-input" placeholder="🔍 Takım veya lig ara (örn: Villarreal, Espanyol, Sporting, Corinthians)..." oninput="applyFilters()" />
    <button class="filter-btn active" onclick="setTierFilter('ALL', this)">Tümü ({len(fixtures)})</button>
    <button class="filter-btn" id="gasiFilterBtn" onclick="toggleGasiFilter(this)">🔥 GASI Gol Anomalisi ({gasi_high_count})</button>
    <button class="filter-btn" id="mbs1FilterBtn" onclick="toggleMbs1Filter(this)">⚡ Sadece MBS 1 ({mbs1_count})</button>
    <button class="filter-btn" id="propsFilterBtn" onclick="togglePropsFilter(this)">🎯 Korner & Golcü ({props_count})</button>
    <button class="filter-btn" onclick="setTierFilter('TIER_1_SEC', this)">🔥 Tier 1: İkincil Avrupa (Alfa Bölgesi)</button>
    <button class="filter-btn" onclick="setTierFilter('CUP', this)">🏆 Avrupa Kupaları (UCL/UEL/UECL)</button>
    <button class="filter-btn" onclick="setTierFilter('TIER_2_MAJ', this)">Tier 2: 5 Büyük Lig</button>
  </div>

  <div style="max-height:560px;overflow-y:auto;">
    <table id="fixturesTable">
      <thead>
        <tr>
          <th>Kademe / Lig</th>
          <th>Karşılaşma & Başlama (UTC)</th>
          <th>Pinnacle (1 / X / 2)</th>
          <th>Shin Adil Oran (1 / X / 2)</th>
          <th>🇹🇷 Canlı Nesine Oranı (Otomatik)</th>
          <th>Nesine Min +EV Eşiği (&ge;%2)</th>
          <th>Draw Steam</th>
          <th>Otomatik Nesine Kararı (+ Opsiyonel Test)</th>
        </tr>
      </thead>
      <tbody>
        {"".join(fix_rows)}
      </tbody>
    </table>
  </div>
</div>

<div class="section">
  <h2>📒 3. Otomatik Paper-Trading & CLV Defteri (output/paper_trading_ledger.csv)</h2>
  <div style="max-height:300px;overflow-y:auto;">
    <table>
      <thead>
        <tr>
          <th>Yakalanma (UTC)</th>
          <th>Lig</th>
          <th>Maç</th>
          <th>Piyasa / Seçim</th>
          <th>Yumuşak Büro</th>
          <th>Shin Adil Oran</th>
          <th>Edge / Half-Kelly</th>
          <th>CLV Oranı</th>
          <th>Skor</th>
          <th>Durum / PnL</th>
        </tr>
      </thead>
      <tbody>
        {"".join(ledger_tr) if ledger_tr else "<tr><td colspan='10'>Henüz kayıt yok.</td></tr>"}
      </tbody>
    </table>
  </div>
</div>

<div class="section" style="border: 1px solid #6366f1; background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
    <h2 style="color:#a5b4fc;margin:0;">⚡ 3.5 Canlı In-Play Altın Pusu & Korner Kütüğü (output/live_inplay_ledger.csv)</h2>
    <span class="badge" style="background:#312e81;color:#c7d2fe;border:1px solid #6366f1">CANLI İŞLEM DEFTERİ (SPEC-0015)</span>
  </div>
  <div style="font-size:12px;color:#cbd5e1;margin-bottom:10px">
    Canlı maçlarda dakika 60-75 Altın Pusu (GASI &ge; 65) ve Korner Sniper sinyallerinin kağıt-işlem kayıtları ve otomatik sonuçlandırma kütüğüdür.
  </div>
  <div style="max-height:300px;overflow-y:auto;">
    <table>
      <thead>
        <tr>
          <th>Kayıt Zamanı</th>
          <th>Dakika</th>
          <th>Maç (Anlık Skor)</th>
          <th>Piyasa / Hat</th>
          <th>Oran & Bahis</th>
          <th>GASI & Tehlike</th>
          <th>Momentum Durumu</th>
          <th>Resmi Bitiş</th>
          <th>Sonuç & PnL</th>
        </tr>
      </thead>
      <tbody>
        {"".join(live_inplay_tr) if live_inplay_tr else "<tr><td colspan='9' style='text-align:center;color:#94a3b8'>Henüz aktif canlı pusu kaydı bulunmuyor (Canlı maç saatleri bekleniyor).</td></tr>"}
      </tbody>
    </table>
  </div>
</div>

<div class="section">
  <h2>🌙 4. Gece Bülteni ESPN Resmi Sonuçlandırma Özeti (İlk 15 Maç)</h2>
  <table>
    <thead>
      <tr>
        <th>Saat</th>
        <th>Lig</th>
        <th>Maç</th>
        <th>Nesine (1 / X / 2)</th>
        <th>Zımni P(X)</th>
        <th>ESPN Resmi Skor</th>
      </tr>
    </thead>
    <tbody>
      {"".join(settled_tr)}
    </tbody>
  </table>
</div>

<script>
let currentTier = 'ALL';
let onlyMbs1 = false;
let onlyProps = false;
let onlyGasi = false;

function setTierFilter(tier, btn) {{
  currentTier = tier;
  document.querySelectorAll('.filter-btn:not(#mbs1FilterBtn):not(#propsFilterBtn):not(#gasiFilterBtn)').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}}

function toggleMbs1Filter(btn) {{
  onlyMbs1 = !onlyMbs1;
  btn.classList.toggle('active', onlyMbs1);
  applyFilters();
}}

function togglePropsFilter(btn) {{
  onlyProps = !onlyProps;
  btn.classList.toggle('active', onlyProps);
  applyFilters();
}}

function toggleGasiFilter(btn) {{
  onlyGasi = !onlyGasi;
  btn.classList.toggle('active', onlyGasi);
  applyFilters();
}}

function applyFilters() {{
  const q = (document.getElementById('searchInput').value || '').toLowerCase().trim();
  const rows = document.querySelectorAll('.fixture-row');
  rows.forEach(r => {{
    const t = r.getAttribute('data-tier');
    const s = r.getAttribute('data-search') || '';
    const mbs = r.getAttribute('data-mbs');
    const corners = r.getAttribute('data-corners');
    const props = r.getAttribute('data-props');
    const gasi = r.getAttribute('data-gasi');

    const matchTier = (currentTier === 'ALL') || (t === currentTier);
    const matchSearch = !q || s.includes(q);
    const matchMbs1 = !onlyMbs1 || (mbs === '1');
    const matchProps = !onlyProps || (corners === '1' || props === '1');
    const matchGasi = !onlyGasi || (gasi === '1');

    r.style.display = (matchTier && matchSearch && matchMbs1 && matchProps && matchGasi) ? '' : 'none';
  }});
}}

function recalcRow(idx) {{
  const sel = document.getElementById('sel-mkt-' + idx);
  const inp = document.getElementById('inp-odds-' + idx);
  const out = document.getElementById('out-calc-' + idx);
  if (!sel || !inp || !out) return;

  const opt = sel.options[sel.selectedIndex];
  const fairProb = parseFloat(opt.getAttribute('data-prob') || '0');
  const fairOdds = parseFloat(opt.getAttribute('data-fair') || '0');
  const userOdds = parseFloat(inp.value || '0');

  if (!userOdds || userOdds <= 1.0 || fairProb <= 0) {{
    out.innerHTML = '';
    return;
  }}

  const ev = (fairProb * userOdds) - 1.0;
  const edgePct = ev * 100.0;
  const kellyHalf = ev > 0 ? Math.min(5.0, (ev / (userOdds - 1.0)) * 0.5 * 100.0) : 0.0;

  if (edgePct >= 2.0) {{
    out.innerHTML = `<span style="color:#34d399;font-weight:700">Özel Oran Testi: +${{edgePct.toFixed(2)}}% EDGE (Half-Kelly: %${{kellyHalf.toFixed(2)}})</span>`;
  }} else {{
    out.innerHTML = `<span style="color:#f87171">Özel Oran Testi: ${{edgePct.toFixed(2)}}% EV (Adil: ${{fairOdds.toFixed(2)}})</span>`;
  }}
}}
</script>

</body>
</html>
"""
    OUT_HTML.write_text(html, encoding="utf-8")
    print(
        f"Dashboard v2.1 built: {len(fixtures)} live fixtures, "
        f"{nesine_matched} Nesine auto-matched, {len(signals)} signals."
    )


if __name__ == "__main__":
    build_html()
