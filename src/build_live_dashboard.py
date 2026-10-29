import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

LEAGUES = {
    'I1': {'name': 'İtalya Serie A', 'tier': 'Tier 1', 'tier_class': 'tier-1', 'badge': '🔥 En Kârlı (+%19.6 ROI)'},
    'D1': {'name': 'Almanya Bundesliga', 'tier': 'Tier 1', 'tier_class': 'tier-1', 'badge': '🔥 En Kârlı (+%19.1 ROI)'},
    'T1': {'name': 'Türkiye Süper Lig', 'tier': 'Tier 2', 'tier_class': 'tier-2', 'badge': '⚡ Kârlı (+%9.4 ROI)'},
    'E0': {'name': 'İngiltere Premier League', 'tier': 'Tier 2', 'tier_class': 'tier-2', 'badge': '⚡ Kârlı (+%3.3 ROI)'},
    'SP1': {'name': 'İspanya La Liga', 'tier': 'Tier 3', 'tier_class': 'tier-3', 'badge': '⚪ Nötr (-%5.0 ROI)'},
    'F1': {'name': 'Fransa Ligue 1', 'tier': 'Tier 3', 'tier_class': 'tier-3', 'badge': '⚪ Filtrelenmeli'}
}

def remove_vig(h, d, a):
    if pd.isna(h) or pd.isna(d) or pd.isna(a):
        return np.nan, np.nan, np.nan
    rh, rd, ra = 1.0/h, 1.0/d, 1.0/a
    tot = rh + rd + ra
    return rh/tot, rd/tot, ra/tot

def build_web_dashboard():
    raw_dir = Path("sports-engine/data/raw_odds")
    output_dir = Path("sports-engine/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    signals = []
    files = list(raw_dir.glob("*_2526.csv"))
    
    for f in files:
        code = f.name.split('_')[0]
        l_info = LEAGUES.get(code, {'name': code, 'tier': 'Diğer', 'tier_class': 'tier-3', 'badge': 'Standart'})
        df = pd.read_csv(f, low_memory=False)
        
        fair_probs = df.apply(lambda r: remove_vig(r.get('PSCH', np.nan), r.get('PSCD', np.nan), r.get('PSCA', np.nan)), axis=1)
        df['fair_p_D'] = [p[1] for p in fair_probs]
        
        for idx, row in df.iterrows():
            b365_d = row.get('B365D', np.nan)
            fair_d = row.get('fair_p_D', np.nan)
            
            if pd.notna(b365_d) and pd.notna(fair_d):
                edge = (b365_d * fair_d) - 1.0
                if edge >= 0.02:
                    fair_odds = 1.0 / fair_d
                    kelly = edge / (b365_d - 1.0)
                    half_kelly_pct = round(max(0, kelly * 0.5) * 100, 2)
                    
                    signals.append({
                        'code': code,
                        'league': l_info['name'],
                        'tier': l_info['tier'],
                        'tier_class': l_info['tier_class'],
                        'badge': l_info['badge'],
                        'date': str(row.get('Date', 'Bülten')),
                        'home': str(row.get('HomeTeam', 'Ev')),
                        'away': str(row.get('AwayTeam', 'Dep')),
                        'odds': float(b365_d),
                        'fair_odds': round(float(fair_odds), 2),
                        'prob': round(float(fair_d * 100), 1),
                        'edge': round(float(edge * 100), 2),
                        'stake_pct': half_kelly_pct
                    })
                    
    sig_df = pd.DataFrame(signals)
    sig_df = sig_df.sort_values(by=['edge'], ascending=False).reset_index(drop=True)
    
    # Save as JSON for instant reactive UI
    json_path = output_dir / "signals.json"
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(signals, jf, ensure_ascii=False, indent=2)
        
    tier1_count = len([s for s in signals if s['tier'] == 'Tier 1'])
    tier2_count = len([s for s in signals if s['tier'] == 'Tier 2'])
    avg_edge = sig_df['edge'].mean() if len(sig_df) > 0 else 0
    top_edge = sig_df['edge'].max() if len(sig_df) > 0 else 0
    
    html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APE Sports Engine — Canlı Value Sinyal Terminali</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
  --bg: #090d16;
  --surface: #111827;
  --surface-hover: #1f2937;
  --border: #1f2937;
  --primary: #3b82f6;
  --success: #10b981;
  --warning: #f59e0b;
  --danger: #ef4444;
  --text: #f3f4f6;
  --text-muted: #9ca3af;
}}
body {{
  font-family: 'Inter', sans-serif;
  background: var(--bg);
  color: var(--text);
  padding: 24px;
  min-height: 100vh;
}}
.container {{ max-width: 1400px; margin: 0 auto; }}

/* Header */
header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border);
  padding-bottom: 20px;
  margin-bottom: 24px;
}}
.brand {{ display: flex; align-items: center; gap: 12px; }}
.brand-badge {{
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  font-weight: 700;
  padding: 6px 12px;
  border-radius: 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.9em;
}}
.title h1 {{ font-size: 1.6em; font-weight: 700; color: #fff; letter-spacing: -0.5px; }}
.title p {{ font-size: 0.85em; color: var(--text-muted); margin-top: 2px; }}

.pulse-badge {{
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.3);
  color: var(--success);
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 0.8em;
  font-weight: 600;
}}
.pulse-dot {{
  width: 8px;
  height: 8px;
  background: var(--success);
  border-radius: 50%;
  box-shadow: 0 0 8px var(--success);
  animation: pulse 2s infinite;
}}
@keyframes pulse {{
  0% {{ opacity: 1; transform: scale(1); }}
  50% {{ opacity: 0.4; transform: scale(0.85); }}
  100% {{ opacity: 1; transform: scale(1); }}
}}

/* Stat Cards */
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
  padding: 20px;
  display: flex;
  flex-direction: column;
}}
.stat-card .lbl {{ font-size: 0.75em; text-transform: uppercase; letter-spacing: 1px; color: var(--text-muted); font-weight: 600; }}
.stat-card .val {{ font-size: 1.8em; font-weight: 700; margin-top: 6px; font-family: 'JetBrains Mono', monospace; }}
.val.green {{ color: var(--success); }}
.val.blue {{ color: var(--primary); }}
.val.orange {{ color: var(--warning); }}

/* Filter Controls */
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
.filter-group {{ display: flex; align-items: center; gap: 10px; }}
.filter-btn {{
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text-muted);
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 0.85em;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.2s;
}}
.filter-btn:hover {{ background: var(--surface-hover); color: #fff; }}
.filter-btn.active {{ background: var(--primary); color: #fff; border-color: var(--primary); }}

.search-input {{
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 0.85em;
  width: 240px;
  outline: none;
}}
.search-input:focus {{ border-color: var(--primary); }}

/* Signal Cards / Table */
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
  text-align: left;
}}
th {{
  background: #0d131f;
  color: var(--text-muted);
  font-weight: 600;
  font-size: 0.75em;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}}
td {{
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}}
tr:hover td {{ background: var(--surface-hover); }}

.team-cell {{ font-weight: 600; color: #fff; }}
.team-vs {{ color: var(--text-muted); font-weight: 400; margin: 0 4px; }}
.date-cell {{ color: var(--text-muted); font-size: 0.85em; font-family: 'JetBrains Mono', monospace; }}

.badge {{
  display: inline-block;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 0.75em;
  font-weight: 600;
}}
.badge.tier-1 {{ background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }}
.badge.tier-2 {{ background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }}
.badge.tier-3 {{ background: rgba(156, 163, 175, 0.1); color: var(--text-muted); border: 1px solid var(--border); }}

.odds-tag {{
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  font-size: 1.05em;
  color: #fff;
}}
.fair-tag {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85em;
  color: var(--text-muted);
}}
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
</style>
</head>
<body>
<div class="container">

<header>
  <div class="brand">
    <div class="brand-badge">APE</div>
    <div class="title">
      <h1>Canlı Value Draw Sinyal Monitörü</h1>
      <p>Pinnacle CLV & Açılış-Kapanış Verimsizlik Tarayıcısı (2026/27 Sezonu)</p>
    </div>
  </div>
  <div class="pulse-badge">
    <div class="pulse-dot"></div>
    CANLI AKTİF BÜLTEN
  </div>
</header>

<div class="stats-grid">
  <div class="stat-card">
    <div class="lbl">Aktif Değerli Sinyal</div>
    <div class="val blue">{len(signals)}</div>
  </div>
  <div class="stat-card">
    <div class="lbl">Tier 1 Sinyal (Serie A & Bundesliga)</div>
    <div class="val orange">{tier1_count}</div>
  </div>
  <div class="stat-card">
    <div class="lbl">En Yüksek Beklenen Değer (Edge)</div>
    <div class="val green">+{top_edge:.1f}%</div>
  </div>
  <div class="stat-card">
    <div class="lbl">Ortalama Beklenen Değer</div>
    <div class="val green">+{avg_edge:.1f}%</div>
  </div>
</div>

<div class="controls-bar">
  <div class="filter-group">
    <span style="font-size: 0.8em; color: var(--text-muted); text-transform: uppercase; font-weight:600;">Lig Filtresi:</span>
    <button class="filter-btn active" onclick="filterTier('ALL')">Tümü ({len(signals)})</button>
    <button class="filter-btn" onclick="filterTier('Tier 1')">🔥 Tier 1 ({tier1_count})</button>
    <button class="filter-btn" onclick="filterTier('Tier 2')">⚡ Tier 2 ({tier2_count})</button>
    <button class="filter-btn" onclick="filterLeague('Türkiye Süper Lig')">🇹🇷 Süper Lig</button>
  </div>
  <div>
    <input type="text" id="searchInput" class="search-input" placeholder="Takım veya lig ara..." onkeyup="searchTable()">
  </div>
</div>

<div class="signals-container">
  <table id="signalsTable">
    <thead>
      <tr>
        <th>Lig & Kategori</th>
        <th>Tarih</th>
        <th>Karşılaşma</th>
        <th>Büro Oranı (Draw)</th>
        <th>Pinnacle Fair Odds</th>
        <th>Beklenen Değer (Edge)</th>
        <th>Önerilen Kasa Payı</th>
      </tr>
    </thead>
    <tbody>
      {"".join(f'''<tr data-tier="{s['tier']}" data-league="{s['league']}">
        <td>
          <span class="badge {s['tier_class']}">{s['badge']}</span><br>
          <span style="font-size: 0.8em; color: var(--text-muted); margin-top: 4px; display:inline-block;">{s['league']}</span>
        </td>
        <td class="date-cell">{s['date']}</td>
        <td class="team-cell">{s['home']}<span class="team-vs">vs</span>{s['away']}</td>
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
let currentTier = 'ALL';
let currentLeague = 'ALL';

function filterTier(tier) {{
  currentTier = tier;
  currentLeague = 'ALL';
  updateButtons();
  applyFilters();
}}

function filterLeague(league) {{
  currentLeague = league;
  currentTier = 'ALL';
  updateButtons();
  applyFilters();
}}

function updateButtons() {{
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
    const tier = r.getAttribute('data-tier');
    const league = r.getAttribute('data-league');
    const text = r.innerText.toLowerCase();
    
    let matchesTier = (currentTier === 'ALL' || tier === currentTier);
    let matchesLeague = (currentLeague === 'ALL' || league === currentLeague);
    let matchesSearch = (!query || text.includes(query));
    
    if (matchesTier && matchesLeague && matchesSearch) {{
      r.style.display = '';
    }} else {{
      r.style.display = 'none';
    }}
  }});
}}
</script>
</body>
</html>
"""
    
    html_file = output_dir / "live_signals_dashboard.html"
    with open(html_file, "w", encoding="utf-8") as hf:
        hf.write(html_content)
        
    print(f"✅ Canlı Web Arayüzü Üretildi: {html_file}")
    return html_file

if __name__ == "__main__":
    build_web_dashboard()

