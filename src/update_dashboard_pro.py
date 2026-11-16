import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

LEAGUES = {
    'I1': {'name': 'İtalya Serie A', 'tier': 'Tier 1'},
    'D1': {'name': 'Almanya Bundesliga', 'tier': 'Tier 1'},
    'T1': {'name': 'Türkiye Süper Lig', 'tier': 'Tier 2'},
    'E0': {'name': 'İngiltere Premier League', 'tier': 'Tier 2'},
    'SP1': {'name': 'İspanya La Liga', 'tier': 'Tier 3'},
    'F1': {'name': 'Fransa Ligue 1', 'tier': 'Tier 3'}
}

def remove_vig_3way(h, d, a):
    if pd.isna(h) or pd.isna(d) or pd.isna(a): return np.nan, np.nan, np.nan
    rh, rd, ra = 1.0/h, 1.0/d, 1.0/a
    tot = rh + rd + ra
    return rh/tot, rd/tot, ra/tot

def remove_vig_2way(o1, o2):
    if pd.isna(o1) or pd.isna(o2) or o1 <= 1.0 or o2 <= 1.0: return np.nan, np.nan
    r1, r2 = 1.0/o1, 1.0/o2
    tot = r1 + r2
    return r1/tot, r2/tot

def update_pro_dashboard():
    raw_dir = Path("sports-engine/data/raw_odds")
    output_dir = Path("sports-engine/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    signals = []
    files = list(raw_dir.glob("*_2526.csv"))

    for f in files:
        code = f.name.split('_')[0]
        l_info = LEAGUES.get(code, {'name': code, 'tier': 'Diğer'})
        df = pd.read_csv(f, low_memory=False)

        # 1. DRAW SCAN
        fair_probs_3w = df.apply(lambda r: remove_vig_3way(r.get('PSCH', np.nan), r.get('PSCD', np.nan), r.get('PSCA', np.nan)), axis=1)
        df['fair_p_D'] = [p[1] for p in fair_probs_3w]

        # 2. OVER/UNDER SCAN
        p_over = df.get('PC>2.5', df.get('P>2.5', pd.Series(np.nan, index=df.index)))
        p_under = df.get('PC<2.5', df.get('P<2.5', pd.Series(np.nan, index=df.index)))
        b_over = df.get('B365>2.5', pd.Series(np.nan, index=df.index))
        b_under = df.get('B365<2.5', pd.Series(np.nan, index=df.index))

        for idx, row in df.iterrows():
            date_str = str(row.get('Date', 'Bülten'))
            home_team = str(row.get('HomeTeam', 'Ev'))
            away_team = str(row.get('AwayTeam', 'Dep'))

            # --- Check Draw ---
            b365_d = row.get('B365D', np.nan)
            fair_d = row.get('fair_p_D', np.nan)
            if pd.notna(b365_d) and pd.notna(fair_d) and 2.8 <= b365_d <= 5.5:
                edge_d = (b365_d * fair_d) - 1.0
                if edge_d >= 0.02:
                    kelly = (edge_d / (b365_d - 1.0)) * 0.5 * 100
                    signals.append({
                        'league': l_info['name'],
                        'tier': l_info['tier'],
                        'market': 'BERABERLİK (X)',
                        'market_type': 'DRAW',
                        'date': date_str,
                        'home': home_team,
                        'away': away_team,
                        'odds': float(b365_d),
                        'fair_odds': round(1.0 / fair_d, 2),
                        'prob': round(fair_d * 100, 1),
                        'edge': round(edge_d * 100, 2),
                        'stake_pct': round(max(0.5, min(4.0, kelly)), 2),
                        'alpha_note': '🔥 5 Yılda %19+ ROI (Serie A/Bundesliga)' if l_info['tier'] == 'Tier 1' else '⚡ İstikrarlı Değer'
                    })

            # --- Check Over/Under 2.5 ---
            po, pu = p_over.iloc[idx], p_under.iloc[idx]
            bo, bu = b_over.iloc[idx], b_under.iloc[idx]
            if pd.notna(po) and pd.notna(pu):
                fo, fu = remove_vig_2way(po, pu)
                if pd.notna(fo):
                    # Over 2.5
                    if pd.notna(bo) and bo > 1.3:
                        edge_o = (bo * fo) - 1.0
                        if edge_o >= 0.02:
                            kelly = (edge_o / (bo - 1.0)) * 0.5 * 100
                            signals.append({
                                'league': l_info['name'],
                                'tier': l_info['tier'],
                                'market': '2.5 ÜST (OVER)',
                                'market_type': 'OVER',
                                'date': date_str,
                                'home': home_team,
                                'away': away_team,
                                'odds': float(bo),
                                'fair_odds': round(1.0 / fo, 2),
                                'prob': round(fo * 100, 1),
                                'edge': round(edge_o * 100, 2),
                                'stake_pct': round(max(0.5, min(4.0, kelly)), 2),
                                'alpha_note': '⚽ Yüksek Skor Eğilimi' if code in ['D1', 'T1'] else 'İstatistiksel Fırsat'
                            })
                    # Under 2.5
                    if pd.notna(bu) and bu > 1.3:
                        edge_u = (bu * fu) - 1.0
                        if edge_u >= 0.02:
                            kelly = (edge_u / (bu - 1.0)) * 0.5 * 100
                            signals.append({
                                'league': l_info['name'],
                                'tier': l_info['tier'],
                                'market': '2.5 ALT (UNDER)',
                                'market_type': 'UNDER',
                                'date': date_str,
                                'home': home_team,
                                'away': away_team,
                                'odds': float(bu),
                                'fair_odds': round(1.0 / fu, 2),
                                'prob': round(fu * 100, 1),
                                'edge': round(edge_u * 100, 2),
                                'stake_pct': round(max(0.5, min(4.0, kelly)), 2),
                                'alpha_note': '🛡️ Süper Lig/Ligue 1 Alt Fırsatı (%18 ROI)' if code in ['T1', 'F1'] else 'Defansif Fiyatlama'
                            })

    sig_df = pd.DataFrame(signals)
    sig_df = sig_df.sort_values(by=['edge'], ascending=False).reset_index(drop=True)

    # JSON dump
    with open(output_dir / "signals_pro.json", "w", encoding="utf-8") as jf:
        json.dump(signals, jf, ensure_ascii=False, indent=2)

    draw_count = len([s for s in signals if s['market_type'] == 'DRAW'])
    ou_count = len([s for s in signals if s['market_type'] in ['OVER', 'UNDER']])
    t1_count = len([s for s in signals if 'Türkiye' in s['league']])

    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APE Sports Engine — Çok Pazarlı Value Terminali (2026/27)</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
  --bg: #080b11;
  --surface: #0f172a;
  --surface-card: #131e36;
  --border: #1e293b;
  --primary: #3b82f6;
  --success: #10b981;
  --warning: #f59e0b;
  --accent-purple: #8b5cf6;
  --text: #f8fafc;
  --text-muted: #94a3b8;
}}
body {{
  font-family: 'Inter', sans-serif;
  background: var(--bg);
  color: var(--text);
  padding: 24px;
}}
.container {{ max-width: 1450px; margin: 0 auto; }}

header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border);
  padding-bottom: 20px;
  margin-bottom: 24px;
}}
.brand {{ display: flex; align-items: center; gap: 14px; }}
.brand-badge {{
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 1em;
  letter-spacing: 1px;
}}
.title h1 {{ font-size: 1.6em; font-weight: 700; color: #fff; }}
.title p {{ font-size: 0.85em; color: var(--text-muted); margin-top: 3px; }}

.pulse-badge {{
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: var(--success);
  padding: 8px 16px;
  border-radius: 20px;
  font-size: 0.85em;
  font-weight: 600;
}}
.pulse-dot {{
  width: 8px; height: 8px;
  background: var(--success);
  border-radius: 50%;
  box-shadow: 0 0 10px var(--success);
  animation: pulse 2s infinite;
}}
@keyframes pulse {{ 0%{{opacity:1}} 50%{{opacity:0.4}} 100%{{opacity:1}} }}

.stats-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}}
.stat-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 22px;
}}
.stat-card .lbl {{ font-size: 0.75em; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); font-weight: 600; }}
.stat-card .val {{ font-size: 1.8em; font-weight: 700; margin-top: 6px; font-family: 'JetBrains Mono', monospace; }}
.val.green {{ color: var(--success); }}
.val.blue {{ color: var(--primary); }}
.val.purple {{ color: var(--accent-purple); }}
.val.orange {{ color: var(--warning); }}

.controls-bar {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 20px;
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}}
.filter-group {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
.filter-btn {{
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text-muted);
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 0.85em;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.2s;
}}
.filter-btn:hover {{ background: #1e293b; color: #fff; }}
.filter-btn.active {{ background: var(--primary); color: #fff; border-color: var(--primary); }}

.search-input {{
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 0.85em;
  width: 250px;
  outline: none;
}}
.search-input:focus {{ border-color: var(--primary); }}

.signals-container {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9em;
}}
th {{
  background: #0b1120;
  color: var(--text-muted);
  font-weight: 600;
  font-size: 0.75em;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}}
td {{
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}}
tr:hover td {{ background: rgba(30, 41, 59, 0.4); }}

.market-badge {{
  display: inline-block;
  padding: 5px 10px;
  border-radius: 6px;
  font-weight: 700;
  font-size: 0.8em;
  font-family: 'JetBrains Mono', monospace;
}}
.market-badge.DRAW {{ background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }}
.market-badge.OVER {{ background: rgba(139, 92, 246, 0.15); color: #a78bfa; border: 1px solid rgba(139, 92, 246, 0.3); }}
.market-badge.UNDER {{ background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }}

.team-cell {{ font-weight: 600; color: #fff; font-size: 0.95em; }}
.odds-tag {{ font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 1.05em; color: #fff; }}
.fair-tag {{ font-family: 'JetBrains Mono', monospace; font-size: 0.85em; color: var(--text-muted); }}
.edge-pill {{
  display: inline-block;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: var(--success);
  padding: 4px 10px;
  border-radius: 6px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}}
.stake-pill {{
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  color: var(--primary);
  background: rgba(59, 130, 246, 0.1);
  padding: 4px 8px;
  border-radius: 6px;
}}
.note-text {{ font-size: 0.8em; color: #94a3b8; display: block; margin-top: 3px; }}
</style>
</head>
<body>
<div class="container">

<header>
  <div class="brand">
    <div class="brand-badge">APE PRO</div>
    <div class="title">
      <h1>Çok Pazarlı Canlı Value Sinyal Terminali</h1>
      <p>1X2 Beraberlik & 2.5 Alt/Üst Pazar Arbitrajı | 6 Büyük Lig (2026/27)</p>
    </div>
  </div>
  <div class="pulse-badge">
    <div class="pulse-dot"></div>
    BÜLTEN TARANDI & AKTİF
  </div>
</header>

<div class="stats-grid">
  <div class="stat-card">
    <div class="lbl">Toplam Değerli Fırsat</div>
    <div class="val blue">{len(signals)}</div>
  </div>
  <div class="stat-card">
    <div class="lbl">Value Draw (Beraberlik)</div>
    <div class="val orange">{draw_count}</div>
  </div>
  <div class="stat-card">
    <div class="lbl">Value 2.5 Alt / Üst</div>
    <div class="val purple">{ou_count}</div>
  </div>
  <div class="stat-card">
    <div class="lbl">Türkiye Süper Lig Sinyali</div>
    <div class="val green">{t1_count}</div>
  </div>
</div>

<div class="controls-bar">
  <div class="filter-group">
    <span style="font-size:0.75em; text-transform:uppercase; color:var(--text-muted); font-weight:700;">Pazar Filtresi:</span>
    <button class="filter-btn active" onclick="filterMarket('ALL')">Tümü ({len(signals)})</button>
    <button class="filter-btn" onclick="filterMarket('DRAW')">🤝 Beraberlik ({draw_count})</button>
    <button class="filter-btn" onclick="filterMarket('OVER')">⚽ 2.5 Üst</button>
    <button class="filter-btn" onclick="filterMarket('UNDER')">🛡️ 2.5 Alt</button>
    <button class="filter-btn" onclick="filterLeague('Türkiye Süper Lig')">🇹🇷 Süper Lig</button>
  </div>
  <div>
    <input type="text" id="searchInput" class="search-input" placeholder="Takım, lig veya pazar ara..." onkeyup="searchTable()">
  </div>
</div>

<div class="signals-container">
  <table id="signalsTable">
    <thead>
      <tr>
        <th>Hedef Pazar</th>
        <th>Lig</th>
        <th>Tarih</th>
        <th>Karşılaşma</th>
        <th>Büro Oranı</th>
        <th>Pinnacle Fair Odds</th>
        <th>Beklenen Değer (Edge)</th>
        <th>Önerilen Stake</th>
      </tr>
    </thead>
    <tbody>
      {"".join(f'''<tr data-market="{s['market_type']}" data-league="{s['league']}">
        <td>
          <span class="market-badge {s['market_type']}">{s['market']}</span>
          <span class="note-text">{s['alpha_note']}</span>
        </td>
        <td style="color:var(--text-muted); font-size:0.85em;">{s['league']}</td>
        <td style="font-family:'JetBrains Mono'; font-size:0.85em; color:var(--text-muted);">{s['date']}</td>
        <td class="team-cell">{s['home']} <span style="color:#64748b; font-weight:400">vs</span> {s['away']}</td>
        <td><span class="odds-tag">{s['odds']:.2f}</span></td>
        <td><span class="fair-tag">{s['fair_odds']:.2f} (%{s['prob']})</span></td>
        <td><span class="edge-pill">+{s['edge']}%</span></td>
        <td><span class="stake-pill">%{s['stake_pct']}</span></td>
      </tr>''' for s in signals)}
    </tbody>
  </table>
</div>

</div>

<script>
let currentMarket = 'ALL';
let currentLeague = 'ALL';

function filterMarket(m) {{
  currentMarket = m;
  currentLeague = 'ALL';
  updateBtn();
  applyFilters();
}}

function filterLeague(l) {{
  currentLeague = l;
  currentMarket = 'ALL';
  updateBtn();
  applyFilters();
}}

function updateBtn() {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
}}

function searchTable() {{
  applyFilters();
}}

function applyFilters() {{
  const query = document.getElementById('searchInput').value.toLowerCase();
  const rows = document.querySelectorAll('#signalsTable tbody tr');

  rows.forEach(r => {{
    const m = r.getAttribute('data-market');
    const l = r.getAttribute('data-league');
    const text = r.innerText.toLowerCase();

    let matchM = (currentMarket === 'ALL' || m === currentMarket);
    let matchL = (currentLeague === 'ALL' || l === currentLeague);
    let matchS = (!query || text.includes(query));

    r.style.display = (matchM && matchL && matchS) ? '' : 'none';
  }});
}}
</script>
</body>
</html>
"""
    html_file = output_dir / "live_signals_dashboard.html"
    with open(html_file, "w", encoding="utf-8") as hf:
        hf.write(html)

    print(f"✅ Gelişmiş Çok Pazarlı Web Dashboard Güncellendi: {html_file}")

if __name__ == "__main__":
    update_pro_dashboard()

