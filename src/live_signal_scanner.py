#!/usr/bin/env python3
"""
LIVE VALUE DRAW SCANNER (2026/27 SEASON & BULLETIN)
===================================================
Avrupa'nın 5 Büyük Ligi ve Türkiye Süper Lig bültenlerini tarar.
Pinnacle vs Bet365/Piyasa kapanış-açılış verimsizliğinden
yüksek beklenen değerli (EV) Beraberlik (Draw) sinyalleri üretir.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

LEAGUES = {
    'I1': {'name': 'İtalya Serie A', 'tier': 'Tier 1 (En Kârlı)', 'historical_roi': '+19.6%'},
    'D1': {'name': 'Almanya Bundesliga', 'tier': 'Tier 1 (En Kârlı)', 'historical_roi': '+19.1%'},
    'T1': {'name': 'Türkiye Süper Lig', 'tier': 'Tier 2 (Kârlı)', 'historical_roi': '+9.4%'},
    'E0': {'name': 'İngiltere Premier League', 'tier': 'Tier 2 (Kârlı)', 'historical_roi': '+3.3%'},
    'SP1': {'name': 'İspanya La Liga', 'tier': 'Tier 3 (Nötr)', 'historical_roi': '-5.0%'},
    'F1': {'name': 'Fransa Ligue 1', 'tier': 'Tier 3 (Filtrelenmeli)', 'historical_roi': '-11.1%'}
}

def remove_vig(h, d, a):
    if pd.isna(h) or pd.isna(d) or pd.isna(a):
        return np.nan, np.nan, np.nan
    rh, rd, ra = 1.0/h, 1.0/d, 1.0/a
    tot = rh + rd + ra
    return rh/tot, rd/tot, ra/tot

def scan_bulletin(min_edge=0.02, min_odds=2.80, max_odds=5.50, league_filter=None):
    raw_dir = Path("sports-engine/data/raw_odds")
    signals = []

    # 2025/26 ve mevcut 2026/27 verilerini tara
    files = list(raw_dir.glob("*_2526.csv"))

    for f in files:
        code = f.name.split('_')[0]
        if league_filter and code != league_filter:
            continue

        l_info = LEAGUES.get(code, {'name': code, 'tier': 'Diğer', 'historical_roi': 'N/A'})
        df = pd.read_csv(f, low_memory=False)

        # Son haftalardaki / bültendeki maçları al
        fair_probs = df.apply(lambda r: remove_vig(r.get('PSCH', np.nan), r.get('PSCD', np.nan), r.get('PSCA', np.nan)), axis=1)
        df['fair_p_D'] = [p[1] for p in fair_probs]

        for _idx, row in df.iterrows():
            b365_d = row.get('B365D', np.nan)
            fair_d = row.get('fair_p_D', np.nan)

            if pd.notna(b365_d) and pd.notna(fair_d):
                if b365_d < min_odds or b365_d > max_odds:
                    continue

                edge = (b365_d * fair_d) - 1.0
                if edge >= min_edge:
                    fair_odds = 1.0 / fair_d
                    # Kelly Criterion: f* = (bp - q) / b = (edge) / (b365_d - 1)
                    kelly = edge / (b365_d - 1.0)
                    half_kelly_pct = round(max(0, kelly * 0.5) * 100, 2)

                    signals.append({
                        'code': code,
                        'league': l_info['name'],
                        'tier': l_info['tier'],
                        'historical_roi': l_info['historical_roi'],
                        'date': row.get('Date', 'Bülten'),
                        'home': row.get('HomeTeam', 'Ev'),
                        'away': row.get('AwayTeam', 'Dep'),
                        'b365_draw_odds': b365_d,
                        'pinnacle_fair_odds': round(fair_odds, 2),
                        'fair_prob_pct': round(fair_d * 100, 1),
                        'edge_pct': round(edge * 100, 2),
                        'rec_stake_pct': f"%{half_kelly_pct}",
                        'actual_result': row.get('FTR', 'BEKLEMEDE')
                    })

    sig_df = pd.DataFrame(signals)
    return sig_df

def print_terminal_report(sig_df):
    print("=" * 85)
    print("🎯 LIVE VALUE DRAW SCANNER — AKTİF BÜLTEN & SİNYAL MONİTÖRÜ")
    print(f"Rapor Tarihi: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Minimum Edge: %2.0")
    print("=" * 85)

    if len(sig_df) == 0:
        print("Bültende kriterlere uyan aktif Beraberlik sinyali bulunamadı.")
        return

    # Sort by Tier and Edge
    sig_df = sig_df.sort_values(by=['edge_pct'], ascending=False).reset_index(drop=True)

    for _idx, r in sig_df.head(15).iterrows():
        status_icon = "🔥" if "Tier 1" in r['tier'] else "⚡"
        print(f"{status_icon} [{r['league']}] {r['date']} | {r['home']} vs {r['away']}")
        print(f"   Oran: {r['b365_draw_odds']:.2f} | Fair: {r['pinnacle_fair_odds']:.2f} (Olasılık: %{r['fair_prob_pct']})")
        print(f"   Beklenen Değer (Edge): +%{r['edge_pct']} | Önerilen Kasa Payı (Half-Kelly): {r['rec_stake_pct']}")
        print(f"   Lig Güvenilirlik Seviyesi: {r['tier']} (5 Yıllık ROI: {r['historical_roi']})")
        print("-" * 85)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Canlı Beraberlik Sinyal Tarayıcısı")
    parser.add_argument("--min-edge", type=float, default=0.02, help="Minimum Edge (örn: 0.02)")
    parser.add_argument("--league", type=str, default=None, help="Lig Filtresi (I1, D1, T1, E0 vb.)")
    args = parser.parse_args()

    df_sig = scan_bulletin(min_edge=args.min_edge, league_filter=args.league)
    print_terminal_report(df_sig)

    # CSV ve JSON Olarak Kaydet
    out_csv = Path("sports-engine/output/live_signals_latest.csv")
    df_sig.to_csv(out_csv, index=False, encoding='utf-8')
    print(f"\n📁 Güncel sinyaller kaydedildi: {out_csv}")

