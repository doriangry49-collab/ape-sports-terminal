"""Comprehensive quantitative investigation of 6+ Goal matches (TG 6+ / Total Goals >= 6).

Analyzes:
- Baseline frequency of 6+ goal games
- Opening and closing odds distributions (1X2, 2.5 Over/Under)
- Steam movements / smart money behavior
- Half-time goal transitions and most frequent exact scores
- Corner correlations
- High-probability sweet spots for 6+ goal explosions
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import duckdb
import numpy as np
import pandas as pd

con = duckdb.connect()
dataset_path = "sports-engine/data/gold/odds_pattern_dataset_42k.parquet"

print("==================================================================")
print("🔍 6+ GOL (TG 6+) BİTEN MAÇLARIN TARİHSEL ORAN & İSTATİSTİK ANALİZİ")
print("==================================================================\n")

# 1. Genel Evren ve 6+ Gol Frekansı
q_base = f"""
SELECT 
    COUNT(*) as total_matches,
    SUM(CASE WHEN ft_goals >= 6 THEN 1 ELSE 0 END) as matches_6plus,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as pct_6plus,
    ROUND(AVG(ft_goals), 2) as avg_goals_all,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN ft_goals ELSE NULL END), 2) as avg_goals_6plus
FROM '{dataset_path}'
"""
df_base = con.execute(q_base).df()
tot = df_base['total_matches'].iloc[0]
m6 = df_base['matches_6plus'].iloc[0]
pct6 = df_base['pct_6plus'].iloc[0]
print(f"Toplam İncelenen Maç: {tot:,}")
print(f"6+ Gol Biten Maç Sayısı: {m6:,}")
print(f"Genel Bülten 6+ Gol Olasılığı (Taban Çizgi): %{pct6} (Yaklaşık her {int(round(100/pct6))} maçta bir)")
print(f"6+ Gol Biten Maçların Ortalama Gol Sayısı: {df_base['avg_goals_6plus'].iloc[0]}\n")

# 2. Oran Profili: 6+ Gol Biten Maçlar ile Genel Maçların Oran Karşılaştırması
q_odds_comp = f"""
SELECT 
    'Genel Bülten (Tüm Maçlar)' as kategori,
    ROUND(AVG(open_1), 2) as ort_ev_orani,
    ROUND(AVG(open_2), 2) as ort_dep_orani,
    ROUND(AVG(open_o25), 2) as ort_25_ust_orani,
    ROUND(AVG(open_u25), 2) as ort_25_alt_orani,
    ROUND(AVG(close_o25), 2) as ort_kapanis_25_ust,
    ROUND(AVG(steam_o25_pct), 2) as ort_steam_o25_pct,
    ROUND(AVG(total_corners), 2) as ort_korner
FROM '{dataset_path}'

UNION ALL

SELECT 
    '6+ Gol Biten Maçlar' as kategori,
    ROUND(AVG(open_1), 2) as ort_ev_orani,
    ROUND(AVG(open_2), 2) as ort_dep_orani,
    ROUND(AVG(open_o25), 2) as ort_25_ust_orani,
    ROUND(AVG(open_u25), 2) as ort_25_alt_orani,
    ROUND(AVG(close_o25), 2) as ort_kapanis_25_ust,
    ROUND(AVG(steam_o25_pct), 2) as ort_steam_o25_pct,
    ROUND(AVG(total_corners), 2) as ort_korner
FROM '{dataset_path}'
WHERE ft_goals >= 6
"""
df_odds = con.execute(q_odds_comp).df()
print("--- ORAN KARŞILAŞTIRMASI ---")
print(df_odds.to_string(index=False))
print()

# 3. 2.5 Üst Oran Dilimlerine Göre 6+ Gol Patlama Olasılığı
q_o25_bands = f"""
SELECT 
    CASE 
        WHEN open_o25 <= 1.40 THEN '1. Aşırı Düşük (<= 1.40)'
        WHEN open_o25 <= 1.60 THEN '2. Düşük (1.41 - 1.60)'
        WHEN open_o25 <= 1.85 THEN '3. Orta / Dengeli (1.61 - 1.85)'
        WHEN open_o25 <= 2.10 THEN '4. Yüksek (1.86 - 2.10)'
        ELSE '5. Çok Kısır Beklenen (> 2.10)'
    END as o25_dilimi,
    COUNT(*) as mac_sayisi,
    SUM(CASE WHEN ft_goals >= 6 THEN 1 ELSE 0 END) as g6_sayisi,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as g6_olasilik_pct,
    ROUND(AVG(total_corners), 2) as ort_korner
FROM '{dataset_path}'
WHERE open_o25 IS NOT NULL
GROUP BY 1
ORDER BY 1
"""
df_bands = con.execute(q_o25_bands).df()
print("--- 2.5 ÜST AÇILIŞ ORANINA GÖRE 6+ GOL İHTİMALİ ---")
print(df_bands.to_string(index=False))
print()

# 4. Maç Yapısı: Favori Dağılımı (Ağır Favorili vs Dengeli Maçlar)
q_fav_profile = f"""
SELECT 
    CASE 
        WHEN open_1 <= 1.35 THEN 'Ağır Ev Favorisi (MS1 <= 1.35)'
        WHEN open_2 <= 1.45 THEN 'Ağır Deplasman Favorisi (MS2 <= 1.45)'
        WHEN ABS(open_1 - open_2) <= 0.50 THEN 'Dengeli Maç (|MS1-MS2| <= 0.50)'
        ELSE 'Diğer / Orta Sıklet'
    END as mac_karakteri,
    COUNT(*) as toplam_mac,
    SUM(CASE WHEN ft_goals >= 6 THEN 1 ELSE 0 END) as g6_sayisi,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as g6_olasilik_pct
FROM '{dataset_path}'
WHERE open_1 IS NOT NULL AND open_2 IS NOT NULL
GROUP BY 1
ORDER BY g6_olasilik_pct DESC
"""
df_fav = con.execute(q_fav_profile).df()
print("--- FAVORİ DURUMUNA GÖRE 6+ GOL İHTİMALİ ---")
print(df_fav.to_string(index=False))
print()

# 5. En Çok Görülen Kesin Skorlar (6+ Gol Bitenler Arasında)
q_top_scores = f"""
SELECT 
    exact_score,
    COUNT(*) as frekans,
    ROUND(COUNT(*) * 100.0 / {m6}, 2) as yuzde
FROM '{dataset_path}'
WHERE ft_goals >= 6
GROUP BY exact_score
ORDER BY frekans DESC
LIMIT 10
"""
df_scores = con.execute(q_top_scores).df()
print("--- 6+ GOL BİTEN MAÇLARDA EN ÇOK GÖRÜLEN SKORLAR ---")
print(df_scores.to_string(index=False))
print()

# 6. İlk Yarı Davranışı (6+ Gol Biten Maçların İY Skor Dağılımı)
q_ht = f"""
SELECT 
    ROUND(AVG(CASE WHEN ht_goals >= 2 THEN 1.0 ELSE 0.0 END) * 100, 2) as pct_ht_2plus_goals,
    ROUND(AVG(CASE WHEN ht_goals >= 3 THEN 1.0 ELSE 0.0 END) * 100, 2) as pct_ht_3plus_goals,
    ROUND(AVG(CASE WHEN ht_goals = 0 THEN 1.0 ELSE 0.0 END) * 100, 2) as pct_ht_0_0_kalan,
    ROUND(AVG(ht_goals), 2) as ort_iy_gol
FROM '{dataset_path}'
WHERE ft_goals >= 6 AND ht_goals IS NOT NULL
"""
df_ht = con.execute(q_ht).df()
print("--- 6+ GOL BİTEN MAÇLARDA İLK YARI GÖRÜNÜMÜ ---")
print(f"İlk Yarıda En Az 2 Gol Olma Oranı: %{df_ht['pct_ht_2plus_goals'].iloc[0]}")
print(f"İlk Yarıda En Az 3 Gol Olma Oranı: %{df_ht['pct_ht_3plus_goals'].iloc[0]}")
print(f"İlk Yarısı 0-0 Bitip İkinci Yarıda 6+ Olanların Oranı (Mucize Geri Dönüşler): %{df_ht['pct_ht_0_0_kalan'].iloc[0]}")
print(f"6+ Gol Biten Maçların Ortalama İlk Yarı Golü: {df_ht['ort_iy_gol'].iloc[0]}\n")

# 7. Altın Kesişim: 6+ Gol İhtimalinin Tavan Yaptığı "Sweet Spot" Kombinasyonu
q_sweet = f"""
SELECT 
    'Ağır Ev Favori (MS1 <= 1.35) + 2.5 Üst <= 1.45' as senaryo,
    COUNT(*) as mac_sayisi,
    SUM(CASE WHEN ft_goals >= 6 THEN 1 ELSE 0 END) as g6_sayisi,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as g6_pct
FROM '{dataset_path}'
WHERE open_1 <= 1.35 AND open_o25 <= 1.45

UNION ALL

SELECT 
    'Açılış 2.5 Üst <= 1.50 + Kapanışta Steam Yiyenler (Steam <= -3%)' as senaryo,
    COUNT(*) as mac_sayisi,
    SUM(CASE WHEN ft_goals >= 6 THEN 1 ELSE 0 END) as g6_sayisi,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as g6_pct
FROM '{dataset_path}'
WHERE open_o25 <= 1.50 AND steam_o25_pct <= -3.0

UNION ALL

SELECT 
    'Almanya Bundesliga (D1) + 2.5 Üst <= 1.50' as senaryo,
    COUNT(*) as mac_sayisi,
    SUM(CASE WHEN ft_goals >= 6 THEN 1 ELSE 0 END) as g6_sayisi,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as g6_pct
FROM '{dataset_path}'
WHERE div_code = 'D1' AND open_o25 <= 1.50

UNION ALL

SELECT 
    'Hollanda Eredivisie (N1) + 2.5 Üst <= 1.50' as senaryo,
    COUNT(*) as mac_sayisi,
    SUM(CASE WHEN ft_goals >= 6 THEN 1 ELSE 0 END) as g6_sayisi,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as g6_pct
FROM '{dataset_path}'
WHERE div_code = 'N1' AND open_o25 <= 1.50
"""
df_sweet = con.execute(q_sweet).df()
print("--- 6+ GOL İHTİMALİNİN EN YÜKSEK OLDUĞU ALTIN KOMBİNASYONLAR ---")
print(df_sweet.to_string(index=False))
