import glob
import re
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def remove_vig(h, d, a):
    if pd.isna(h) or pd.isna(d) or pd.isna(a): return np.nan, np.nan, np.nan
    rh, rd, ra = 1.0/h, 1.0/d, 1.0/a
    tot = rh + rd + ra
    return rh/tot, rd/tot, ra/tot

t_files = sorted(glob.glob('sports-engine/data/raw_odds/T1_*.csv'))
t_bets = []

for f in t_files:
    m = re.search(r'T1_([0-9]{4})\.csv', f)
    s_str = f"20{m.group(1)[:2]}/{m.group(1)[2:]}"
    df = pd.read_csv(f, low_memory=False)
    fair_probs = df.apply(lambda r: remove_vig(r.get('PSCH', np.nan), r.get('PSCD', np.nan), r.get('PSCA', np.nan)), axis=1)
    df['fair_p_D'] = [p[1] for p in fair_probs]
    for _idx, r in df.iterrows():
        b365 = r.get('B365D', np.nan)
        fp = r.get('fair_p_D', np.nan)
        if pd.notna(b365) and pd.notna(fp):
            edge = (b365 * fp) - 1.0
            if edge >= 0.02:
                won = (r.get('FTR') == 'D')
                pnl = (b365 - 1.0) if won else -1.0
                t_bets.append({'season': s_str, 'won': won, 'pnl': pnl, 'odds': b365})

tdf = pd.DataFrame(t_bets)
print("=" * 60)
print("TÜRKİYE SÜPER LİG (5 SEZON) BERABERLİK (DRAW) PERFORMANSI")
print("=" * 60)
s_res = tdf.groupby('season').agg(bets=('pnl','count'), wins=('won','sum'), pnl=('pnl','sum')).reset_index()
s_res['hit_rate'] = (s_res['wins']/s_res['bets']*100).round(1)
s_res['roi'] = (s_res['pnl']/s_res['bets']*100).round(1)
print(s_res.to_string(index=False))
print("-" * 60)
wins = tdf['won'].sum()
tot = len(tdf)
pnl = tdf['pnl'].sum()
roi = (pnl / tot) * 100
print(f"SÜPER LİG GENEL: {tot} Bahis | {wins} Galibiyet (%{wins/tot*100:.1f}) | P&L: {pnl:+.2f}u | ROI: %{roi:+.1f}")

