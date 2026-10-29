"""
MVP BACKTEST ENGINE — La Liga 2023/24
=====================================
İlk çalışan ürün. Veriyi okur, strateji uygular, sonuç üretir.

Strateji: Pinnacle Closing Line Value (CLV) Based Value Betting
- Pinnacle kapanış oranları "gerçek olasılığa" en yakın referanstır (sharp bookmaker)
- Pinnacle kapanış oranından implied probability hesaplanır (vig çıkarılır)
- Bet365 pre-match oranı Pinnacle fair odds'tan yüksekse → value bet sinyali
- Flat 1 birim stake ile tüm value bet'ler alınır
- P&L, ROI, hit rate, max drawdown hesaplanır
"""

import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
import json

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ─── CONFIG ───────────────────────────────────────────────────
DATA_FILE = Path("sports-engine/scratch/task076_odds_pilot/raw/SP1_2324.csv")
OUTPUT_DIR = Path("sports-engine/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STAKE = 1.0           # Flat stake per bet (units)
MIN_EDGE = 0.02       # Minimum edge threshold (2%) to trigger a bet
MIN_ODDS = 1.20       # Don't bet below this odds
MAX_ODDS = 15.0       # Don't bet above this odds

# ─── DATA LOADING ─────────────────────────────────────────────
print("=" * 60)
print("MVP BACKTEST ENGINE — La Liga 2023/24")
print("=" * 60)

df = pd.read_csv(DATA_FILE)
df['match_date'] = pd.to_datetime(df['Date'], format='%d/%m/%Y')
df = df.sort_values('match_date').reset_index(drop=True)

print(f"\nVeri yüklendi: {len(df)} maç")
print(f"Tarih araligi: {df['match_date'].min().date()} - {df['match_date'].max().date()}")

# ─── PINNACLE VIG REMOVAL ────────────────────────────────────
# Pinnacle closing odds → fair probabilities (vig removed)
def remove_vig(h_odds, d_odds, a_odds):
    """Remove bookmaker overround to get fair probabilities."""
    if pd.isna(h_odds) or pd.isna(d_odds) or pd.isna(a_odds):
        return np.nan, np.nan, np.nan
    raw_h = 1.0 / h_odds
    raw_d = 1.0 / d_odds
    raw_a = 1.0 / a_odds
    total = raw_h + raw_d + raw_a  # overround (e.g., 1.02-1.04 for Pinnacle)
    return raw_h / total, raw_d / total, raw_a / total

# Calculate fair probabilities from Pinnacle CLOSING odds
fair_probs = df.apply(lambda r: remove_vig(r['PSCH'], r['PSCD'], r['PSCA']), axis=1)
df['fair_prob_H'] = [p[0] for p in fair_probs]
df['fair_prob_D'] = [p[1] for p in fair_probs]
df['fair_prob_A'] = [p[2] for p in fair_probs]
df['fair_odds_H'] = 1.0 / df['fair_prob_H']
df['fair_odds_D'] = 1.0 / df['fair_prob_D']
df['fair_odds_A'] = 1.0 / df['fair_prob_A']

# Pinnacle overround check
overrounds = df.apply(lambda r: (1/r['PSCH'] + 1/r['PSCD'] + 1/r['PSCA']) if pd.notna(r['PSCH']) else np.nan, axis=1)
print(f"Pinnacle kapanış overround: ortalama {overrounds.mean():.4f} (ideal: 1.0000)")

# ─── STRATEGY: VALUE DETECTION ───────────────────────────────
bets = []

for idx, row in df.iterrows():
    if pd.isna(row['fair_prob_H']) or pd.isna(row['B365H']):
        continue
    
    match_info = {
        'match_idx': idx,
        'date': row['match_date'],
        'home': row['HomeTeam'],
        'away': row['AwayTeam'],
        'ft_result': row['FTR'],
        'score': f"{int(row['FTHG'])}-{int(row['FTAG'])}",
    }
    
    # Check each outcome (H, D, A) for value
    selections = [
        ('H', row['B365H'], row['fair_prob_H'], row['fair_odds_H'], row['MaxH']),
        ('D', row['B365D'], row['fair_prob_D'], row['fair_odds_D'], row['MaxD']),
        ('A', row['B365A'], row['fair_prob_A'], row['fair_odds_A'], row['MaxA']),
    ]
    
    for outcome, b365_odds, fair_prob, fair_odds, max_odds in selections:
        if pd.isna(b365_odds) or pd.isna(fair_prob):
            continue
        if b365_odds < MIN_ODDS or b365_odds > MAX_ODDS:
            continue
        
        # Edge = (b365_odds * fair_prob) - 1
        # This is the expected value per unit staked
        edge = (b365_odds * fair_prob) - 1.0
        
        if edge >= MIN_EDGE:
            won = (row['FTR'] == outcome)
            pnl = STAKE * (b365_odds - 1) if won else -STAKE
            
            bets.append({
                **match_info,
                'selection': outcome,
                'b365_odds': b365_odds,
                'fair_odds': round(fair_odds, 3),
                'fair_prob': round(fair_prob, 4),
                'edge': round(edge, 4),
                'max_market_odds': max_odds,
                'stake': STAKE,
                'won': won,
                'pnl': round(pnl, 2),
            })

bets_df = pd.DataFrame(bets)

if len(bets_df) == 0:
    print("\n⚠️ Hiç value bet bulunamadı! Edge threshold'u düşürmeyi dene.")
    exit()

# ─── RESULTS CALCULATION ─────────────────────────────────────
bets_df = bets_df.sort_values('date').reset_index(drop=True)
bets_df['cumulative_pnl'] = bets_df['pnl'].cumsum()
bets_df['bet_number'] = range(1, len(bets_df) + 1)

total_bets = len(bets_df)
wins = bets_df['won'].sum()
losses = total_bets - wins
hit_rate = wins / total_bets
total_staked = total_bets * STAKE
total_pnl = bets_df['pnl'].sum()
roi = (total_pnl / total_staked) * 100
avg_odds = bets_df['b365_odds'].mean()
avg_edge = bets_df['edge'].mean()
max_drawdown = (bets_df['cumulative_pnl'].cummax() - bets_df['cumulative_pnl']).max()
peak_profit = bets_df['cumulative_pnl'].max()

# By selection type
by_sel = bets_df.groupby('selection').agg(
    count=('pnl', 'count'),
    wins=('won', 'sum'),
    total_pnl=('pnl', 'sum'),
    avg_odds=('b365_odds', 'mean'),
    avg_edge=('edge', 'mean'),
).reset_index()
by_sel['hit_rate'] = (by_sel['wins'] / by_sel['count'] * 100).round(1)
by_sel['roi'] = (by_sel['total_pnl'] / by_sel['count'] * 100).round(2)

# Monthly breakdown
bets_df['month'] = bets_df['date'].dt.to_period('M')
monthly = bets_df.groupby('month').agg(
    bets=('pnl', 'count'),
    wins=('won', 'sum'),
    pnl=('pnl', 'sum'),
    avg_odds=('b365_odds', 'mean'),
).reset_index()
monthly['roi'] = (monthly['pnl'] / monthly['bets'] * 100).round(2)
monthly['month_str'] = monthly['month'].astype(str)

# ─── CONSOLE OUTPUT ──────────────────────────────────────────
print(f"\n{'─' * 60}")
print(f"STRATEJİ: Pinnacle CLV → Bet365 Value Betting")
print(f"Minimum Edge: {MIN_EDGE*100:.1f}%  |  Stake: {STAKE} birim (flat)")
print(f"{'─' * 60}")
print(f"Toplam bahis sayısı:    {total_bets}")
print(f"Kazanan / Kaybeden:     {wins} / {losses}")
print(f"İsabet oranı (hit%):    {hit_rate*100:.1f}%")
print(f"Toplam yatırılan:       {total_staked:.0f} birim")
print(f"Toplam P&L:             {total_pnl:+.2f} birim")
print(f"ROI:                    {roi:+.2f}%")
print(f"Ortalama odds:          {avg_odds:.2f}")
print(f"Ortalama edge:          {avg_edge*100:.2f}%")
print(f"Max drawdown:           {max_drawdown:.2f} birim")
print(f"Peak profit:            {peak_profit:.2f} birim")

print(f"\n{'─' * 60}")
print("SEÇİM BAZLI DÖKÜM:")
print(by_sel.to_string(index=False))

print(f"\n{'─' * 60}")
print("AYLIK DÖKÜM:")
print(monthly[['month_str', 'bets', 'wins', 'pnl', 'roi']].to_string(index=False))

# ─── STRATEGY 2: MAX ODDS VALUE ──────────────────────────────
# Same logic but using market max odds instead of B365
bets2 = []
for idx, row in df.iterrows():
    if pd.isna(row['fair_prob_H']) or pd.isna(row['MaxH']):
        continue
    
    selections = [
        ('H', row['MaxH'], row['fair_prob_H'], row['fair_odds_H']),
        ('D', row['MaxD'], row['fair_prob_D'], row['fair_odds_D']),
        ('A', row['MaxA'], row['fair_prob_A'], row['fair_odds_A']),
    ]
    
    for outcome, max_odds, fair_prob, fair_odds in selections:
        if pd.isna(max_odds) or pd.isna(fair_prob):
            continue
        if max_odds < MIN_ODDS or max_odds > MAX_ODDS:
            continue
        edge = (max_odds * fair_prob) - 1.0
        if edge >= MIN_EDGE:
            won = (row['FTR'] == outcome)
            pnl = STAKE * (max_odds - 1) if won else -STAKE
            bets2.append({
                'date': row['match_date'],
                'home': row['HomeTeam'],
                'away': row['AwayTeam'],
                'selection': outcome,
                'max_odds': max_odds,
                'fair_odds': round(fair_odds, 3),
                'edge': round(edge, 4),
                'won': won,
                'pnl': round(pnl, 2),
            })

bets2_df = pd.DataFrame(bets2)
if len(bets2_df) > 0:
    bets2_df = bets2_df.sort_values('date').reset_index(drop=True)
    bets2_df['cumulative_pnl'] = bets2_df['pnl'].cumsum()
    bets2_df['bet_number'] = range(1, len(bets2_df) + 1)
    
    print(f"\n{'=' * 60}")
    print(f"STRATEJİ 2: Pinnacle CLV → Market MAX Odds Value")
    print(f"{'─' * 60}")
    print(f"Toplam bahis: {len(bets2_df)}  |  Kazanan: {bets2_df['won'].sum()}")
    print(f"Hit rate: {bets2_df['won'].mean()*100:.1f}%")
    print(f"P&L: {bets2_df['pnl'].sum():+.2f}  |  ROI: {bets2_df['pnl'].sum()/len(bets2_df)*100:+.2f}%")
    print(f"Max drawdown: {(bets2_df['cumulative_pnl'].cummax() - bets2_df['cumulative_pnl']).max():.2f}")

# ─── HTML REPORT GENERATION ──────────────────────────────────
# P&L data for chart
pnl_data = bets_df[['bet_number', 'cumulative_pnl']].values.tolist()
pnl2_data = bets2_df[['bet_number', 'cumulative_pnl']].values.tolist() if len(bets2_df) > 0 else []

# Monthly data for bar chart
monthly_labels = monthly['month_str'].tolist()
monthly_pnl = monthly['pnl'].round(2).tolist()
monthly_bets_count = monthly['bets'].tolist()

# Selection breakdown for pie chart
sel_labels = by_sel['selection'].tolist()
sel_counts = by_sel['count'].tolist()
sel_pnls = by_sel['total_pnl'].round(2).tolist()

html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MVP Backtest — La Liga 2023/24</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f0f0f; color: #e0e0e0; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
h1 {{ font-size: 2em; margin-bottom: 5px; color: #fff; }}
.subtitle {{ color: #888; margin-bottom: 30px; font-size: 0.95em; }}
.hero {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }}
.card {{ background: #1a1a1a; border-radius: 12px; padding: 20px; border: 1px solid #2a2a2a; }}
.card.positive {{ border-left: 4px solid #00c853; }}
.card.negative {{ border-left: 4px solid #ff1744; }}
.card.neutral {{ border-left: 4px solid #448aff; }}
.card .label {{ font-size: 0.8em; color: #888; text-transform: uppercase; letter-spacing: 1px; }}
.card .value {{ font-size: 2em; font-weight: 700; margin-top: 5px; }}
.card .value.green {{ color: #00c853; }}
.card .value.red {{ color: #ff1744; }}
.card .value.blue {{ color: #448aff; }}
.chart-container {{ background: #1a1a1a; border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid #2a2a2a; }}
.chart-title {{ font-size: 1.1em; font-weight: 600; margin-bottom: 15px; color: #ccc; }}
.chart-row {{ display: grid; grid-template-columns: 2fr 1fr; gap: 20px; margin-bottom: 20px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #2a2a2a; }}
th {{ color: #888; font-weight: 600; text-transform: uppercase; font-size: 0.75em; letter-spacing: 1px; }}
td {{ color: #ccc; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: 600; }}
.tag.win {{ background: #00c85322; color: #00c853; }}
.tag.loss {{ background: #ff174422; color: #ff1744; }}
.footer {{ text-align: center; color: #555; margin-top: 40px; font-size: 0.8em; padding: 20px 0; border-top: 1px solid #222; }}
.strategy-badge {{ display: inline-block; background: #448aff22; color: #448aff; padding: 4px 12px; border-radius: 20px; font-size: 0.85em; margin-bottom: 15px; }}
@media (max-width: 768px) {{ .chart-row {{ grid-template-columns: 1fr; }} .hero {{ grid-template-columns: 1fr 1fr; }} }}
</style>
</head>
<body>
<div class="container">

<h1>⚽ MVP Backtest — La Liga 2023/24</h1>
<p class="subtitle">Pinnacle CLV Value Betting | Bet365 Pre-match Odds | Flat {STAKE:.0f} Unit Stake | Min Edge {MIN_EDGE*100:.0f}%</p>

<div class="hero">
  <div class="card {'positive' if total_pnl >= 0 else 'negative'}">
    <div class="label">Net P&L</div>
    <div class="value {'green' if total_pnl >= 0 else 'red'}">{total_pnl:+.2f}u</div>
  </div>
  <div class="card {'positive' if roi >= 0 else 'negative'}">
    <div class="label">ROI</div>
    <div class="value {'green' if roi >= 0 else 'red'}">{roi:+.1f}%</div>
  </div>
  <div class="card neutral">
    <div class="label">Toplam Bahis</div>
    <div class="value blue">{total_bets}</div>
  </div>
  <div class="card neutral">
    <div class="label">İsabet Oranı</div>
    <div class="value blue">{hit_rate*100:.1f}%</div>
  </div>
  <div class="card neutral">
    <div class="label">Ort. Odds / Edge</div>
    <div class="value blue" style="font-size:1.4em">{avg_odds:.2f} / {avg_edge*100:.1f}%</div>
  </div>
  <div class="card negative">
    <div class="label">Max Drawdown</div>
    <div class="value red">{max_drawdown:.1f}u</div>
  </div>
</div>

<div class="chart-row">
  <div class="chart-container">
    <div class="chart-title">📈 Kümülatif P&L Eğrisi</div>
    <canvas id="pnlChart" height="250"></canvas>
  </div>
  <div class="chart-container">
    <div class="chart-title">📊 Aylık P&L</div>
    <canvas id="monthlyChart" height="250"></canvas>
  </div>
</div>

<div class="chart-container">
  <div class="chart-title">📋 Aylık Performans Detayı</div>
  <table>
    <thead><tr><th>Ay</th><th>Bahis</th><th>Kazanan</th><th>Hit%</th><th>P&L</th><th>ROI</th></tr></thead>
    <tbody>
    {"".join(f'<tr><td>{m["month_str"]}</td><td>{m["bets"]}</td><td>{m["wins"]}</td><td>{m["wins"]/m["bets"]*100:.0f}%</td><td style="color:{"#00c853" if m["pnl"]>=0 else "#ff1744"}">{m["pnl"]:+.2f}</td><td style="color:{"#00c853" if m["roi"]>=0 else "#ff1744"}">{m["roi"]:+.1f}%</td></tr>' for _, m in monthly.iterrows())}
    </tbody>
  </table>
</div>

<div class="chart-row">
  <div class="chart-container">
    <div class="chart-title">🎯 Seçim Bazlı Performans</div>
    <table>
      <thead><tr><th>Seçim</th><th>Bahis</th><th>Kazanan</th><th>Hit%</th><th>Ort. Odds</th><th>Ort. Edge</th><th>P&L</th><th>ROI</th></tr></thead>
      <tbody>
      {"".join(f'<tr><td><strong>{"Ev Sahibi" if s["selection"]=="H" else "Beraberlik" if s["selection"]=="D" else "Deplasman"}</strong> ({s["selection"]})</td><td>{s["count"]}</td><td>{int(s["wins"])}</td><td>{s["hit_rate"]:.0f}%</td><td>{s["avg_odds"]:.2f}</td><td>{s["avg_edge"]*100:.1f}%</td><td style="color:{"#00c853" if s["total_pnl"]>=0 else "#ff1744"}">{s["total_pnl"]:+.2f}</td><td style="color:{"#00c853" if s["roi"]>=0 else "#ff1744"}">{s["roi"]:+.1f}%</td></tr>' for _, s in by_sel.iterrows())}
      </tbody>
    </table>
  </div>
  <div class="chart-container">
    <div class="chart-title">📐 Strateji Parametreleri</div>
    <table>
      <tr><td>Referans Bookmaker</td><td><strong>Pinnacle (Closing)</strong></td></tr>
      <tr><td>Bahis Bookmaker'ı</td><td><strong>Bet365 (Pre-match)</strong></td></tr>
      <tr><td>Edge Hesabı</td><td><code>(B365_odds × fair_prob) - 1</code></td></tr>
      <tr><td>Vig Kaldırma</td><td>Multiplicative (Power method)</td></tr>
      <tr><td>Min Edge Threshold</td><td>{MIN_EDGE*100:.0f}%</td></tr>
      <tr><td>Odds Aralığı</td><td>{MIN_ODDS:.2f} — {MAX_ODDS:.2f}</td></tr>
      <tr><td>Stake Modeli</td><td>Flat {STAKE:.0f} birim</td></tr>
      <tr><td>Pinnacle Ort. Overround</td><td>{overrounds.mean():.4f}</td></tr>
    </table>
  </div>
</div>

{"" if len(bets2_df) == 0 else f'''
<div class="chart-container">
  <div class="strategy-badge">Karşılaştırma: Market Max Odds Stratejisi</div>
  <div class="chart-title">📈 Strateji 2: Pinnacle CLV → Market Max Odds</div>
  <p style="color:#888;margin-bottom:10px">Aynı sinyal mantığı, ama Bet365 yerine piyasadaki en yüksek oran kullanılıyor.</p>
  <div class="hero" style="margin-bottom:0">
    <div class="card {"positive" if bets2_df["pnl"].sum() >= 0 else "negative"}">
      <div class="label">Net P&L</div>
      <div class="value {"green" if bets2_df["pnl"].sum() >= 0 else "red"}">{bets2_df["pnl"].sum():+.2f}u</div>
    </div>
    <div class="card {"positive" if bets2_df["pnl"].sum()/len(bets2_df)*100 >= 0 else "negative"}">
      <div class="label">ROI</div>
      <div class="value {"green" if bets2_df["pnl"].sum()/len(bets2_df)*100 >= 0 else "red"}">{bets2_df["pnl"].sum()/len(bets2_df)*100:+.1f}%</div>
    </div>
    <div class="card neutral">
      <div class="label">Toplam Bahis</div>
      <div class="value blue">{len(bets2_df)}</div>
    </div>
    <div class="card neutral">
      <div class="label">İsabet Oranı</div>
      <div class="value blue">{bets2_df["won"].mean()*100:.1f}%</div>
    </div>
  </div>
</div>
'''}

<div class="chart-container">
  <div class="chart-title">📜 Son 20 Bahis Detayı</div>
  <table>
    <thead><tr><th>#</th><th>Tarih</th><th>Maç</th><th>Skor</th><th>Seçim</th><th>B365 Odds</th><th>Fair Odds</th><th>Edge</th><th>Sonuç</th><th>P&L</th></tr></thead>
    <tbody>
    {"".join(f'<tr><td>{b["bet_number"]}</td><td>{b["date"].strftime("%d/%m")}</td><td>{b["home"]} vs {b["away"]}</td><td>{b["score"]}</td><td>{b["selection"]}</td><td>{b["b365_odds"]:.2f}</td><td>{b["fair_odds"]:.2f}</td><td>{b["edge"]*100:.1f}%</td><td><span class="tag {"win" if b["won"] else "loss"}">{"✓" if b["won"] else "✗"}</span></td><td style="color:{"#00c853" if b["pnl"]>=0 else "#ff1744"}">{b["pnl"]:+.2f}</td></tr>' for _, b in bets_df.tail(20).iterrows())}
    </tbody>
  </table>
</div>

<div class="footer">
  MVP Backtest Engine — APE Sports Engine | La Liga 2023/24 | Veri: Football-Data.co.uk<br>
  Oluşturulma: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 380 maç, {total_bets} value bet sinyali
</div>

</div>

<script>
// P&L Chart
const pnlCtx = document.getElementById('pnlChart').getContext('2d');
const pnlData = {json.dumps(pnl_data)};
new Chart(pnlCtx, {{
  type: 'line',
  data: {{
    labels: pnlData.map(d => d[0]),
    datasets: [
      {{
        label: 'Bet365 Value',
        data: pnlData.map(d => d[1]),
        borderColor: '#448aff',
        backgroundColor: 'rgba(68,138,255,0.1)',
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        borderWidth: 2,
      }},
      {"" if len(pnl2_data) == 0 else f"""{{
        label: 'Market Max Value',
        data: {json.dumps(pnl2_data)}.map(d => d[1]),
        borderColor: '#ff9800',
        backgroundColor: 'rgba(255,152,0,0.05)',
        fill: false,
        tension: 0.3,
        pointRadius: 0,
        borderWidth: 2,
        borderDash: [5, 3],
      }},"""}
      {{
        label: 'Break-even',
        data: pnlData.map(() => 0),
        borderColor: '#555',
        borderWidth: 1,
        borderDash: [3, 3],
        pointRadius: 0,
        fill: false,
      }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ labels: {{ color: '#888' }} }},
    }},
    scales: {{
      x: {{ display: true, title: {{ display: true, text: 'Bahis #', color: '#666' }}, ticks: {{ color: '#666' }}, grid: {{ color: '#222' }} }},
      y: {{ title: {{ display: true, text: 'P&L (birim)', color: '#666' }}, ticks: {{ color: '#666' }}, grid: {{ color: '#222' }} }}
    }}
  }}
}});

// Monthly Chart
const monthCtx = document.getElementById('monthlyChart').getContext('2d');
new Chart(monthCtx, {{
  type: 'bar',
  data: {{
    labels: {json.dumps(monthly_labels)},
    datasets: [{{
      label: 'Aylık P&L',
      data: {json.dumps(monthly_pnl)},
      backgroundColor: {json.dumps(monthly_pnl)}.map(v => v >= 0 ? 'rgba(0,200,83,0.7)' : 'rgba(255,23,68,0.7)'),
      borderRadius: 4,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#666', maxRotation: 45 }}, grid: {{ display: false }} }},
      y: {{ ticks: {{ color: '#666' }}, grid: {{ color: '#222' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""

html_path = OUTPUT_DIR / "backtest_laliga_2324.html"
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"\n{'=' * 60}")
print(f"✅ HTML rapor oluşturuldu: {html_path}")
print(f"{'=' * 60}")

# Also save raw bets to CSV for further analysis
bets_csv = OUTPUT_DIR / "backtest_bets_detail.csv"
bets_df.to_csv(bets_csv, index=False, encoding='utf-8')
print(f"📄 Bahis detayları: {bets_csv}")
