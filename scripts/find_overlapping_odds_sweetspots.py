"""Granular Odds Bracket & Sweet Spot Discovery Engine.

Scans 30k+ matches across narrow odds intervals (0.05 - 0.10 steps) to identify
exact overlapping odds ranges with anomalous hit rates for:
- 9.5 Corners Over / Under
- 10.5 Corners Over / Under
- 12+ Corners
- First Half 1.5 Over
- 6+ Goals
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import duckdb
import pandas as pd

con = duckdb.connect()
dataset_path = "sports-engine/data/gold/odds_pattern_dataset_42k.parquet"

print("==================================================================")
print("🔬 SPESİFİK ÖRTÜŞEN ORAN ARALIKLARI VE KORNER/GOL ALTIN BANTLARI")
print("==================================================================\n")

# 1. 2.5 ÜST AÇILIŞ ORANININ 0.05'LİK DAR BANTLARINDA 9.5 VE 10.5 KORNER DAĞILIMI
q_brackets = f"""
SELECT 
    CASE 
        WHEN open_o25 BETWEEN 1.25 AND 1.35 THEN '1. [1.25 - 1.35] (Ekstrem Hücum)'
        WHEN open_o25 BETWEEN 1.36 AND 1.45 THEN '2. [1.36 - 1.45] (Çok Yüksek Hücum)'
        WHEN open_o25 BETWEEN 1.46 AND 1.55 THEN '3. [1.46 - 1.55] (Yüksek Hücum)'
        WHEN open_o25 BETWEEN 1.56 AND 1.65 THEN '4. [1.56 - 1.65] (Hücum Eğilimli)'
        WHEN open_o25 BETWEEN 1.66 AND 1.75 THEN '5. [1.66 - 1.75] (Orta-Üst)'
        WHEN open_o25 BETWEEN 1.76 AND 1.85 THEN '6. [1.76 - 1.85] (Dengeli Piyasa)'
        WHEN open_o25 BETWEEN 1.86 AND 2.00 THEN '7. [1.86 - 2.00] (Hafif Kısır)'
        WHEN open_o25 BETWEEN 2.01 AND 2.20 THEN '8. [2.01 - 2.20] (Kısır Beklenen)'
        WHEN open_o25 > 2.20 THEN '9. [> 2.20] (Aşırı Kısır/Defansif)'
        ELSE 'Diğer'
    END as o25_bant,
    COUNT(*) as mac_sayisi,
    ROUND(AVG(total_corners), 2) as ort_korner,
    ROUND(AVG(corners_o85) * 100, 2) as pct_85_ust,
    ROUND(AVG(corners_o95) * 100, 2) as pct_95_ust,
    ROUND(AVG(corners_o105) * 100, 2) as pct_105_ust,
    ROUND(AVG(corners_12plus) * 100, 2) as pct_12_arti,
    ROUND(AVG(ht_goals_o15) * 100, 2) as pct_iy_15_ust,
    ROUND(AVG(btts) * 100, 2) as pct_kg_var
FROM '{dataset_path}'
WHERE open_o25 IS NOT NULL AND total_corners IS NOT NULL
GROUP BY 1
ORDER BY 1
"""
df_brk = con.execute(q_brackets).df()
print("--- 1. 2.5 ÜST AÇILIŞ ORANININ DAR BANTLARINDA KORNER & İY GOL BAŞARISI ---")
print(df_brk.to_string(index=False))
print()

# 2. EV SAHİBİ ORANI İLE 2.5 ÜST ORANININ KESİŞTİĞİ MATRİS (9.5 KORNER ÜST İÇİN)
q_matrix = f"""
SELECT 
    CASE 
        WHEN open_1 <= 1.30 THEN 'Ev Ağır Favori (<= 1.30)'
        WHEN open_1 BETWEEN 1.31 AND 1.55 THEN 'Ev Net Favori (1.31 - 1.55)'
        WHEN open_1 BETWEEN 1.56 AND 1.90 THEN 'Ev Hafif Favori (1.56 - 1.90)'
        ELSE 'Dengeli / Dep Favori (> 1.90)'
    END as ev_orani_bandi,
    CASE 
        WHEN open_o25 <= 1.50 THEN '2.5 Üst <= 1.50 (Yüksek Gol)'
        WHEN open_o25 BETWEEN 1.51 AND 1.80 THEN '2.5 Üst 1.51-1.80 (Orta)'
        ELSE '2.5 Üst > 1.80 (Kısır)'
    END as gol_bandi,
    COUNT(*) as mac_sayisi,
    ROUND(AVG(total_corners), 2) as ort_korner,
    ROUND(AVG(corners_o95) * 100, 2) as pct_95_ust,
    ROUND(AVG(corners_o85) * 100, 2) as pct_85_ust,
    ROUND(AVG(corners_12plus) * 100, 2) as pct_12_arti
FROM '{dataset_path}'
WHERE open_1 IS NOT NULL AND open_o25 IS NOT NULL AND total_corners IS NOT NULL
GROUP BY 1, 2
ORDER BY pct_95_ust DESC
"""
df_mat = con.execute(q_matrix).df()
print("--- 2. EV SAHİBİ ORANI x GOL ORANI KESİŞİM MATRİSİ (9.5 KORNER ÜST İÇİN) ---")
print(df_mat.to_string(index=False))
print()

# 3. KORNER 9.5 ALTININ EN GÜVENLİ OLDUĞU "DEFANSİF KALE" BANTLARI
q_under_shield = f"""
SELECT 
    CASE 
        WHEN open_u25 <= 1.50 THEN '2.5 Alt <= 1.50 (Aşırı Kısır)'
        WHEN open_u25 BETWEEN 1.51 AND 1.65 THEN '2.5 Alt 1.51 - 1.65 (Net Kısır)'
        WHEN open_u25 BETWEEN 1.66 AND 1.80 THEN '2.5 Alt 1.66 - 1.80 (Hafif Kısır)'
        ELSE '2.5 Alt > 1.80 (Tempolu)'
    END as alt_orani_bandi,
    COUNT(*) as mac_sayisi,
    ROUND(AVG(total_corners), 2) as ort_korner,
    ROUND(AVG(CASE WHEN total_corners <= 9.0 THEN 1.0 ELSE 0.0 END) * 100, 2) as pct_95_alt,
    ROUND(AVG(CASE WHEN total_corners <= 10.0 THEN 1.0 ELSE 0.0 END) * 100, 2) as pct_105_alt,
    ROUND(AVG(CASE WHEN total_corners >= 12.0 THEN 1.0 ELSE 0.0 END) * 100, 2) as pct_12_arti
FROM '{dataset_path}'
WHERE open_u25 IS NOT NULL AND total_corners IS NOT NULL
GROUP BY 1
ORDER BY pct_95_alt DESC
"""
df_und = con.execute(q_under_shield).df()
print("--- 3. 9.5 KORNER ALT KALKANI İÇİN SPESİFİK ORAN BANTLARI ---")
print(df_und.to_string(index=False))
print()

# 4. KAPANIS ORANINDA DÜŞÜŞ (STEAM) İLE 9.5 KORNERİN KESİŞTİĞİ BANTLAR
q_steam_cross = f"""
SELECT 
    CASE 
        WHEN steam_o25_pct <= -5.0 THEN '2.5 Üst Steam (Oran %5+ Düşen)'
        WHEN steam_o25_pct BETWEEN -4.99 AND 0.0 THEN '2.5 Üst Hafif Düşen (0% - %5%)'
        WHEN steam_o25_pct BETWEEN 0.01 AND 5.0 THEN '2.5 Üst Hafif Artan (0% - %5%)'
        ELSE '2.5 Üst Drift (Oran %5+ Yükselen)'
    END as buhar_hareketi,
    COUNT(*) as mac_sayisi,
    ROUND(AVG(total_corners), 2) as ort_korner,
    ROUND(AVG(corners_o95) * 100, 2) as pct_95_ust,
    ROUND(AVG(corners_12plus) * 100, 2) as pct_12_arti
FROM '{dataset_path}'
WHERE steam_o25_pct IS NOT NULL AND total_corners IS NOT NULL AND open_o25 IS NOT NULL
GROUP BY 1
ORDER BY pct_95_ust DESC
"""
df_stm = con.execute(q_steam_cross).df()
print("--- 4. STEAM (ORAN DÜŞÜŞÜ) İLE KORNER VE 9.5 ÜST KESİŞİMİ ---")
print(df_stm.to_string(index=False))

