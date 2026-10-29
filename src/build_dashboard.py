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

ROOT = Path(__file__).resolve().parent.parent
LIVE_JSON = ROOT / "output" / "live_stale_line_signals.json"
LEDGER_CSV = ROOT / "output" / "paper_trading_ledger.csv"
SETTLED_CSV = ROOT / "output" / "tonight_full_market.csv"
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
        n_edges_1x2 = f.get("nesine_edges_1x2")
        n_edges_ou25 = f.get("nesine_edges_ou25")
        n_code = f.get("nesine_code")
        n_mbs = f.get("nesine_mbs")

        if n_1x2:
            n_1x2_html = (
                f"<strong>{n_1x2[0]:.2f} / <span style='color:#38bdf8'>{n_1x2[1]:.2f}</span> / {n_1x2[2]:.2f}</strong>"
                f"<br><span style='font-size:10px;color:#94a3b8'>Kod: {n_code} | MBS {n_mbs}</span>"
            )
        else:
            n_1x2_html = "<span style='color:#64748b'>Bültende Açılmadı</span>"

        if n_ou25:
            # n_ou25 is [Over, Under]
            n_ou_html = f"Üst: <strong>{n_ou25[0]:.2f}</strong> | Alt: <strong style='color:#38bdf8'>{n_ou25[1]:.2f}</strong>"
        else:
            n_ou_html = "<span style='color:#64748b'>-</span>"

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

        fix_rows.append(
            f"""
            <tr class="fixture-row"
                data-tier="{tier}"
                data-league="{f['league'].lower()}"
                data-search="{f['league'].lower()} {f['home'].lower()} {f['away'].lower()}">
              <td>
                <span class="tier-pill tier-{tier.lower()}">{tier}</span><br>
                <strong>{f['league']}</strong>
              </td>
              <td>
                <strong>{f['home']} vs {f['away']}</strong><br>
                <span style="color:#94a3b8;font-size:11px">{f['kickoff']}</span>
              </td>
              <td>{p1:.2f} / <strong>{px:.2f}</strong> / {p2:.2f}<br><span style="color:#94a3b8;font-size:11px">OU: {ou_pin_str}</span></td>
              <td>{f1:.2f} / <strong style="color:#38bdf8">{fx:.2f}</strong> / {f2:.2f}<br><span style="color:#94a3b8;font-size:11px">P(X)=%{spx*100:.1f}</span></td>
              <td style="background:#0f172a">{n_1x2_html}<br><span style="font-size:11px">{n_ou_html}</span></td>
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
    ledger_tr: list[str] = []
    for r in ledger_rows:
        st = r.get("status", "PENDING")
        cls = "ev-pos" if st == "WON" else ("ev-neg" if st == "LOST" else "")
        ledger_tr.append(
            f"""
            <tr>
              <td>{r.get('captured_at_utc','')}</td>
              <td>{r.get('league','')}</td>
              <td><strong>{r.get('home','')} vs {r.get('away','')}</strong></td>
              <td>{r.get('market','')} / <strong>{r.get('outcome','')}</strong></td>
              <td>{r.get('soft_book','').upper()} @ <strong>{r.get('soft_odds','')}</strong></td>
              <td>{r.get('shin_fair_odds','')} (%{float(r.get('shin_fair_prob') or 0)*100:.1f})</td>
              <td class="ev-pos">+{r.get('edge_pct','')}% (Kasa %{r.get('kelly_pct','')})</td>
              <td>{r.get('clv_ratio','-')}</td>
              <td>{r.get('result_score') or 'Bekliyor'}</td>
              <td class="{cls}"><strong>{st} ({r.get('pnl_units') or '0.00'} u)</strong></td>
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
    <div class="kpi-title">Canlı +EV Stale-Line Sinyali</div>
    <div class="kpi-val" style="color:#34d399">{live_data.get('positive_ev_signals_count', 0)} Sinyal</div>
    <div style="font-size:12px;color:#94a3b8;margin-top:4px">Steam Onaylı: {live_data.get('steam_confirmed_signals_count', 0)}</div>
  </div>
  <div class="kpi">
    <div class="kpi-title">İkincil Avrupa Draw Steam Alfası</div>
    <div class="kpi-val" style="color:#34d399">+%22.35 ROI</div>
    <div style="font-size:12px;color:#94a3b8;margin-top:4px">30.315 Maç Denetimi (t = +2.21)</div>
  </div>
  <div class="kpi">
    <div class="kpi-title">Paper-Trading Kütüğü</div>
    <div class="kpi-val">{ledger_meta.get('total_signals', len(ledger_rows))} Kayıt</div>
    <div style="font-size:12px;color:#94a3b8;margin-top:4px">Ort. CLV: {ledger_meta.get('avg_clv_ratio') or '-'}</div>
  </div>
</div>

<div class="section">
  <h2>🎯 1. Canlı Stale-Line & Steam Sinyalleri (Nesine + Global Yumuşak Bürolar)</h2>
  <div class="sig-grid">
    {sig_cards}
  </div>
</div>

<div class="section">
  <h2>📋 2. Canlı Fikstürler: Pinnacle Adil Oran vs. Otomatik Canlı Nesine Oranları ({len(fixtures)} Maç)</h2>

  <div class="filter-bar">
    <input type="text" id="searchInput" class="filter-input" placeholder="🔍 Takım veya lig ara (örn: Fenerbahçe, Serie B, Feyenoord)..." oninput="applyFilters()" />
    <button class="filter-btn active" onclick="setTierFilter('ALL', this)">Tümü ({len(fixtures)})</button>
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

function setTierFilter(tier, btn) {{
  currentTier = tier;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}}

function applyFilters() {{
  const q = (document.getElementById('searchInput').value || '').toLowerCase().trim();
  const rows = document.querySelectorAll('.fixture-row');
  rows.forEach(r => {{
    const t = r.getAttribute('data-tier');
    const s = r.getAttribute('data-search') || '';
    const matchTier = (currentTier === 'ALL') || (t === currentTier);
    const matchSearch = !q || s.includes(q);
    r.style.display = (matchTier && matchSearch) ? '' : 'none';
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
