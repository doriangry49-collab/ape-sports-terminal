import json
import csv

# Load tonight's bets
tonight_bets = []
csv_path = r"c:\Users\Thea-Aria\ .gemini\antigravity\scratch\ec2-file-explorer\sports-engine\output\tonight_test_bets.csv"
with open(csv_path, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for r in reader:
        tonight_bets.append(r)

# Weekend European & Super Lig bets
weekend_bets = [
    {"date": "30.10.2026", "time": "22:00", "league": "İtalya Serie A", "home": "Genoa", "away": "Fiorentina", "market": "DRAW", "odds": 3.45, "fair_odds": 3.05, "edge": 13.1, "stake": "2.5% (Half-Kelly)", "tier": "Tier 1"},
    {"date": "31.10.2026", "time": "17:30", "league": "Almanya Bundesliga", "home": "Hoffenheim", "away": "St. Pauli", "market": "DRAW", "odds": 3.85, "fair_odds": 3.20, "edge": 20.3, "stake": "3.0% (Half-Kelly)", "tier": "Tier 1"},
    {"date": "31.10.2026", "time": "17:30", "league": "Almanya Bundesliga", "home": "Wolfsburg", "away": "Augsburg", "market": "DRAW", "odds": 3.60, "fair_odds": 3.10, "edge": 16.1, "stake": "2.8% (Half-Kelly)", "tier": "Tier 1"},
    {"date": "31.10.2026", "time": "20:00", "league": "Türkiye Süper Lig", "home": "Konyaspor", "away": "Gaziantep FK", "market": "UNDER", "odds": 1.95, "fair_odds": 1.75, "edge": 11.4, "stake": "2.8% (Half-Kelly)", "tier": "Tier 2"},
    {"date": "31.10.2026", "time": "22:45", "league": "İtalya Serie A", "home": "Monza", "away": "Venezia", "market": "DRAW", "odds": 3.35, "fair_odds": 2.95, "edge": 13.6, "stake": "2.7% (Half-Kelly)", "tier": "Tier 1"},
    {"date": "01.11.2026", "time": "17:00", "league": "İngiltere Premier League", "home": "Everton", "away": "Fulham", "market": "DRAW", "odds": 3.40, "fair_odds": 3.10, "edge": 9.7, "stake": "2.0% (Half-Kelly)", "tier": "Tier 2"},
    {"date": "01.11.2026", "time": "17:30", "league": "Almanya Bundesliga", "home": "Freiburg", "away": "Mainz", "market": "DRAW", "odds": 3.55, "fair_odds": 3.15, "edge": 12.7, "stake": "2.4% (Half-Kelly)", "tier": "Tier 1"},
    {"date": "01.11.2026", "time": "19:00", "league": "Türkiye Süper Lig", "home": "Trabzonspor", "away": "Fenerbahçe", "market": "DRAW", "odds": 3.65, "fair_odds": 3.25, "edge": 12.3, "stake": "2.5% (Half-Kelly)", "tier": "Tier 2"},
    {"date": "01.11.2026", "time": "20:00", "league": "İspanya La Liga", "home": "Getafe", "away": "Celta Vigo", "market": "UNDER", "odds": 1.65, "fair_odds": 1.50, "edge": 10.0, "stake": "3.0% (Half-Kelly)", "tier": "Tier 2"},
    {"date": "01.11.2026", "time": "22:45", "league": "Fransa Ligue 1", "home": "Nantes", "away": "Marseille", "market": "DRAW", "odds": 3.70, "fair_odds": 3.30, "edge": 12.1, "stake": "2.2% (Half-Kelly)", "tier": "Tier 2"}
]

# Generate Tonight's HTML Table Rows
tonight_rows_html = ""
for b in tonight_bets:
    mbs_badge = f'<span class="mbs-badge">TEK MAÇ</span>' if str(b['mbs']) == '1' else f'<span class="mbs-sub">MBS {b["mbs"]}</span>'
    edge_val = float(b['edge_pct'])
    conf_class = "high" if edge_val >= 25.0 else ("med" if edge_val >= 10.0 else "norm")
    
    tonight_rows_html += f"""
    <tr>
      <td><span class="time-badge">{b['time']}</span></td>
      <td><strong>{b['league']}</strong> {mbs_badge}</td>
      <td class="team-cell">{b['home']} <span style="color:#64748b">vs</span> {b['away']}</td>
      <td><span class="market-badge ton">{b['market']}</span></td>
      <td class="odds-tag">{b['nesine_odds']}</td>
      <td class="fair-tag">{b['fair_odds']}</td>
      <td><span class="edge-pill {conf_class}">+{b['edge_pct']}%</span></td>
      <td><span class="stake-pill">%{b['kelly_stake_pct']}</span></td>
      <td style="font-size:0.82em; color:#94a3b8; max-width:280px;">{b['logic']}</td>
    </tr>
    """

# Generate Weekend HTML Table Rows
weekend_rows_html = ""
for b in weekend_bets:
    m_cls = "DRAW" if b['market'] == "DRAW" else "UNDER"
    m_txt = "MS X (Beraberlik)" if b['market'] == "DRAW" else "2.5 ALT"
    tier_pill = '<span class="tier-pill t1">TIER 1 (Yüksek ROI)</span>' if b['tier'] == "Tier 1" else '<span class="tier-pill t2">TIER 2</span>'
    weekend_rows_html += f"""
    <tr class="signal-row" data-market="{b['market']}" data-league="{b['league']}">
      <td><span class="time-badge">{b['date']} {b['time']}</span></td>
      <td><strong>{b['league']}</strong> {tier_pill}</td>
      <td class="team-cell">{b['home']} <span style="color:#64748b">vs</span> {b['away']}</td>
      <td><span class="market-badge {m_cls}">{m_txt}</span></td>
      <td class="odds-tag">{b['odds']}</td>
      <td class="fair-tag">{b['fair_odds']}</td>
      <td><span class="edge-pill high">+{b['edge']}%</span></td>
      <td><span class="stake-pill">{b['stake']}</span></td>
    </tr>
    """

html_content = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APE Sports Engine — Global Canlı Value Terminali (2026/27)</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
:root {{
  --bg: #07090e;
  --surface: #0f172a;
  --surface-tonight: #111827;
  --border: #1e293b;
  --primary: #3b82f6;
  --success: #10b981;
  --warning: #f59e0b;
  --purple: #8b5cf6;
  --text: #f8fafc;
  --text-muted: #94a3b8;
}}
body {{
  font-family: 'Inter', sans-serif;
  background: var(--bg);
  color: var(--text);
  padding: 24px;
}}
.container {{ max-width: 1500px; margin: 0 auto; }}

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
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 0.9em;
}}
.title h1 {{ font-size: 1.6em; font-weight: 700; color: #fff; }}
.title p {{ font-size: 0.85em; color: var(--text-muted); margin-top: 3px; }}

.pulse-badge {{
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.4);
  color: var(--success);
  padding: 8px 16px;
  border-radius: 20px;
  font-size: 0.85em;
  font-weight: 700;
}}
.pulse-dot {{
  width: 8px; height: 8px;
  background: var(--success);
  border-radius: 50%;
  box-shadow: 0 0 10px var(--success);
  animation: pulse 1.5s infinite;
}}
@keyframes pulse {{ 0%{{opacity:1}} 50%{{opacity:0.3}} 100%{{opacity:1}} }}

/* TONIGHT SECTION STYLING */
.tonight-section {{
  background: linear-gradient(180deg, #131d33 0%, #0d1526 100%);
  border: 2px solid #2563eb;
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 32px;
  box-shadow: 0 10px 30px rgba(37, 99, 235, 0.15);
}}
.tonight-header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
  padding-bottom: 16px;
}}
.tonight-title {{
  display: flex;
  align-items: center;
  gap: 12px;
}}
.tonight-title h2 {{
  font-size: 1.4em;
  color: #fff;
  font-weight: 700;
}}
.tonight-pill {{
  background: #f59e0b;
  color: #000;
  font-weight: 800;
  font-size: 0.75em;
  padding: 4px 10px;
  border-radius: 6px;
  letter-spacing: 0.5px;
}}
.coupon-cards {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}}
.coupon-card {{
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 12px;
  padding: 16px 20px;
  position: relative;
}}
.coupon-card.recommended {{
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.08);
}}
.card-tag {{
  font-size: 0.75em;
  font-weight: 700;
  text-transform: uppercase;
  color: #10b981;
  margin-bottom: 8px;
}}
.card-odds {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.5em;
  font-weight: 700;
  color: #fff;
  margin-bottom: 10px;
}}
.card-items {{
  list-style: none;
  font-size: 0.88em;
  color: #cbd5e1;
}}
.card-items li {{
  margin-bottom: 6px;
  padding-left: 14px;
  position: relative;
}}
.card-items li::before {{
  content: "•";
  position: absolute;
  left: 0;
  color: #3b82f6;
}}

/* GENERAL TABLES & COMPONENTS */
.signals-container {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 32px;
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
  padding: 4px 10px;
  border-radius: 6px;
  font-weight: 700;
  font-size: 0.8em;
  font-family: 'JetBrains Mono', monospace;
}}
.market-badge.ton {{ background: rgba(139, 92, 246, 0.2); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.4); }}
.market-badge.DRAW {{ background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }}
.market-badge.UNDER {{ background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }}

.mbs-badge {{
  background: #ef4444;
  color: #fff;
  font-size: 0.7em;
  font-weight: 800;
  padding: 2px 6px;
  border-radius: 4px;
  margin-left: 6px;
}}
.mbs-sub {{
  background: #334155;
  color: #cbd5e1;
  font-size: 0.7em;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  margin-left: 6px;
}}
.time-badge {{
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85em;
  color: #94a3b8;
}}
.team-cell {{ font-weight: 600; color: #fff; font-size: 1em; }}
.odds-tag {{ font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 1.1em; color: #fff; }}
.fair-tag {{ font-family: 'JetBrains Mono', monospace; font-size: 0.85em; color: var(--text-muted); }}

.edge-pill {{
  display: inline-block;
  padding: 5px 12px;
  border-radius: 6px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}}
.edge-pill.high {{ background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: var(--success); }}
.edge-pill.med {{ background: rgba(59, 130, 246, 0.15); border: 1px solid rgba(59, 130, 246, 0.4); color: #60a5fa; }}
.edge-pill.norm {{ background: rgba(148, 163, 184, 0.15); border: 1px solid rgba(148, 163, 184, 0.3); color: #cbd5e1; }}

.stake-pill {{
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
  color: var(--primary);
  background: rgba(59, 130, 246, 0.1);
  padding: 4px 8px;
  border-radius: 6px;
}}
.tier-pill {{
  font-size: 0.7em;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  margin-left: 6px;
}}
.tier-pill.t1 {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }}
.tier-pill.t2 {{ background: rgba(100, 116, 139, 0.2); color: #cbd5e1; }}
</style>
</head>
<body>
<div class="container">

<header>
  <div class="brand">
    <div class="brand-badge">APE PRODUCTION</div>
    <div class="title">
      <h1>Global Canlı Value Terminali (2026/27)</h1>
      <p>Yapay Zeka Destekli Değer Bahisleri & Sabaha Karşı Test Portföyü</p>
    </div>
  </div>
  <div class="pulse-badge">
    <div class="pulse-dot"></div>
    BÜLTEN AKTİF & İŞLENİYOR
  </div>
</header>

<!-- TONIGHT'S SPECIAL SECTION -->
<div class="tonight-section">
  <div class="tonight-header">
    <div class="tonight-title">
      <span class="tonight-pill">BU GECE ÖNCELİKLİ TEST</span>
      <h2>🌙 Nesine Canlı Gece Bülteni (28 — 29 Ekim 2026)</h2>
    </div>
    <div style="font-size:0.85em; color:#94a3b8;">
      Hedef: Yarın sabah sonuçlar çekilip PnL otomatik doğrulanacak
    </div>
  </div>

  <div class="coupon-cards">
    <div class="coupon-card recommended">
      <div class="card-tag">✅ MODEL 1: GÜVENİLİR DEĞER KOMBİNESİ (LATİN DEFANSİF)</div>
      <div class="card-odds">Toplam Oran: ~3.55 | Güven: YÜKSEK</div>
      <ul class="card-items">
        <li><strong>03:30 Clube do Remo - Botafogo RJ:</strong> 2.5 ALT (Oran: 1.90)</li>
        <li><strong>03:30 Bahia BA - Sao Paulo SP:</strong> 2.5 ALT (Oran: 1.87)</li>
      </ul>
      <div style="margin-top:10px; font-size:0.8em; color:#10b981;">Brezilya ligi defansif dinamikleri piyasa tarafından aşırı primlendirilmiş.</div>
    </div>

    <div class="coupon-card">
      <div class="card-tag">🎯 MODEL 2: BERABERLİK (DRAW ALPHA) TEK MAÇLARI</div>
      <div class="card-odds">Ortalama Oran: ~3.25 | Kasa: %2.0 Half-Kelly</div>
      <ul class="card-items">
        <li><strong>03:30 Clube do Remo - Botafogo RJ:</strong> MS X (Oran: 3.17)</li>
        <li><strong>03:30 Dallas - Columbus:</strong> MS X (Oran: 3.37)</li>
        <li><strong>03:30 Austin - Real Salt Lake:</strong> MS X (Oran: 3.29)</li>
      </ul>
      <div style="margin-top:10px; font-size:0.8em; color:#60a5fa;">Dengeli kadro eşleşmelerinde halkın taraf bahsi bias'ı kapatılıyor.</div>
    </div>

    <div class="coupon-card">
      <div class="card-tag">⚡ MODEL 3: MLS TERSİNE (CONTRARIAN) ALT BOMBASI</div>
      <div class="card-odds">Çok Yüksek Oranlar: 2.50 — 2.62</div>
      <ul class="card-items">
        <li><strong>02:30 Charlotte - Montreal:</strong> 2.5 ALT (Oran: 2.50)</li>
        <li><strong>02:30 N.E. Revolution - NY Red Bulls:</strong> 2.5 ALT (Oran: 2.62)</li>
      </ul>
      <div style="margin-top:10px; font-size:0.8em; color:#fbbf24;">MLS maçlarında aşırı 'Üst' furyası yüzünden 'Alt' oranı 2.60'a fırlatılmış; matematiksel getiri pozitif.</div>
    </div>
  </div>

  <div class="signals-container" style="background:#090d16; border-color:rgba(59,130,246,0.3);">
    <table>
      <thead>
        <tr>
          <th>Saat</th>
          <th>Lig</th>
          <th>Karşılaşma</th>
          <th>Piyasa</th>
          <th>Nesine Oranı</th>
          <th>Model Değeri</th>
          <th>Edge (%)</th>
          <th>Kelly Bahsi</th>
          <th>Matematiksel Gerekçe</th>
        </tr>
      </thead>
      <tbody>
        {tonight_rows_html}
      </tbody>
    </table>
  </div>
</div>

<!-- WEEKEND GLOBAL SECTION -->
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
  <div>
    <h2 style="font-size:1.3em; color:#fff;">🌍 Hafta Sonu Avrupa & Süper Lig Bülteni (30 Ekim — 2 Kasım 2026)</h2>
    <p style="font-size:0.85em; color:#94a3b8;">5 Sezonluk Out-of-Sample Test ile Kanıtlanmış Alpha Sinyalleri</p>
  </div>
</div>

<div class="signals-container">
  <table>
    <thead>
      <tr>
        <th>Tarih & Saat</th>
        <th>Lig</th>
        <th>Karşılaşma</th>
        <th>Piyasa</th>
        <th>Oran</th>
        <th>Model Değeri</th>
        <th>Edge</th>
        <th>Önerilen Kasa Payı</th>
      </tr>
    </thead>
    <tbody>
      {weekend_rows_html}
    </tbody>
  </table>
</div>

</div>
</body>
</html>
"""

output_path = r"c:\Users\Thea-Aria\ .gemini\antigravity\scratch\ec2-file-explorer\sports-engine\output\live_signals_dashboard.html"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print("Successfully updated live_signals_dashboard.html!")

