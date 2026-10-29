import sys
import glob, re
from pathlib import Path
import pandas as pd
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = Path("sports-engine/data/raw_odds")
files = sorted(glob.glob(str(DATA_DIR / "*.csv")))

STAKE = 1.0
MIN_EDGE = 0.02

def remove_vig_2way(o1, o2):
    if pd.isna(o1) or pd.isna(o2) or o1 <= 1.0 or o2 <= 1.0:
        return np.nan, np.nan
    r1, r2 = 1.0 / o1, 1.0 / o2
    tot = r1 + r2
    return r1 / tot, r2 / tot

ou_bets = []

print("=" * 70)
print("5 SEZONLUK OVER/UNDER 2.5 (ALT/ÜST) VALUE BACKTEST (6 LİG)")
print("=" * 70)

for fpath in files:
    fname = Path(fpath).name
    m = re.match(r"([A-Z0-9]+)_([0-9]{4})\.csv", fname)
    if not m: continue
    code, season_code = m.groups()
    season_str = f"20{season_code[:2]}/{season_code[2:]}"
    
    df = pd.read_csv(fpath, low_memory=False)
    if 'FTHG' not in df.columns or 'FTAG' not in df.columns:
        continue
        
    # Pinnacle closing or regular O/U 2.5
    # Football-Data columns: PC>2.5, PC<2.5 (closing) or P>2.5, P<2.5 (prematch)
    # Bet365: B365>2.5, B365<2.5
    p_over = df.get('PC>2.5', df.get('P>2.5', pd.Series(np.nan, index=df.index)))
    p_under = df.get('PC<2.5', df.get('P<2.5', pd.Series(np.nan, index=df.index)))
    
    b_over = df.get('B365>2.5', pd.Series(np.nan, index=df.index))
    b_under = df.get('B365<2.5', pd.Series(np.nan, index=df.index))
    
    df['total_goals'] = pd.to_numeric(df['FTHG'], errors='coerce') + pd.to_numeric(df['FTAG'], errors='coerce')
    
    for idx, row in df.iterrows():
        po, pu = p_over.iloc[idx], p_under.iloc[idx]
        bo, bu = b_over.iloc[idx], b_under.iloc[idx]
        tot_goals = row['total_goals']
        
        if pd.isna(tot_goals) or pd.isna(po) or pd.isna(pu):
            continue
            
        fair_over, fair_under = remove_vig_2way(po, pu)
        if pd.isna(fair_over):
            continue
            
        # Test Over 2.5
        if pd.notna(bo) and bo > 1.2:
            edge_o = (bo * fair_over) - 1.0
            if edge_o >= MIN_EDGE:
                won = (tot_goals > 2.5)
                pnl = (bo - 1.0) if won else -STAKE
                ou_bets.append({
                    'season': season_str,
                    'league': code,
                    'market': 'OVER 2.5 (ÜST)',
                    'odds': bo,
                    'fair_odds': 1.0 / fair_over,
                    'edge': edge_o,
                    'won': won,
                    'pnl': pnl
                })
                
        # Test Under 2.5
        if pd.notna(bu) and bu > 1.2:
            edge_u = (bu * fair_under) - 1.0
            if edge_u >= MIN_EDGE:
                won = (tot_goals < 2.5)
                pnl = (bu - 1.0) if won else -STAKE
                ou_bets.append({
                    'season': season_str,
                    'league': code,
                    'market': 'UNDER 2.5 (ALT)',
                    'odds': bu,
                    'fair_odds': 1.0 / fair_under,
                    'edge': edge_u,
                    'won': won,
                    'pnl': pnl
                })

ou_df = pd.DataFrame(ou_bets)

if len(ou_df) == 0:
    print("O/U verisi bulunamadı.")
    sys.exit()

print(f"\nToplam O/U Bahis Sayısı: {len(ou_df)}")

# Market Summary (OVER vs UNDER)
m_res = ou_df.groupby('market').agg(
    bets=('pnl', 'count'),
    wins=('won', 'sum'),
    pnl=('pnl', 'sum'),
    avg_odds=('odds', 'mean'),
    avg_edge=('edge', 'mean')
).reset_index()
m_res['hit_rate'] = (m_res['wins'] / m_res['bets'] * 100).round(1)
m_res['roi'] = (m_res['pnl'] / m_res['bets'] * 100).round(2)

print("\n--- MARKET BAZINDA PERFORMANS (OVER vs UNDER) ---")
print(m_res.to_string(index=False))

# League Breakdown
l_res = ou_df.groupby(['league', 'market']).agg(
    bets=('pnl', 'count'),
    wins=('won', 'sum'),
    pnl=('pnl', 'sum'),
    avg_odds=('odds', 'mean')
).reset_index()
l_res['hit_rate'] = (l_res['wins'] / l_res['bets'] * 100).round(1)
l_res['roi'] = (l_res['pnl'] / l_res['bets'] * 100).round(2)

print("\n--- LİG VE MARKET KIRILIMI ---")
print(l_res.sort_values(by='pnl', ascending=False).to_string(index=False))

# Season Breakdown
s_res = ou_df.groupby(['season', 'market']).agg(
    bets=('pnl', 'count'),
    wins=('won', 'sum'),
    pnl=('pnl', 'sum')
).reset_index()
s_res['roi'] = (s_res['pnl'] / s_res['bets'] * 100).round(2)
print("\n--- SEZONLUK GELİŞİM ---")
print(s_res.to_string(index=False))

total_pnl = ou_df['pnl'].sum()
total_roi = (total_pnl / len(ou_df)) * 100
print("=" * 70)
print(f"OVER/UNDER GENEL BİLANÇO: {len(ou_df)} Bahis | P&L: {total_pnl:+.2f}u | Net ROI: %{total_roi:+.2f}")
print("=" * 70)

