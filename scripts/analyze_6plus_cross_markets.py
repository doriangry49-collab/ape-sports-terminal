"""Analyze cross-market relationships for 6+ goal matches:
- KG Var (BTTS) occurrence & odds
- First Half 1.5 Over / Under
- First Half BTTS (İY KG Var)
- HT/FT Transition breakdowns
- Exact correlation matrix and sweet spot filters
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import duckdb
import pandas as pd

con = duckdb.connect()
dataset_path = "sports-engine/data/gold/odds_pattern_dataset_42k.parquet"

print("==================================================================")
print("🔍 6+ GOL İÇİN ÇAPRAZ PAZAR (KG VAR, İLK YARI, İY/MS) DERİN ANALİZİ")
print("==================================================================\n")

# 1. 6+ Gol Biten Maçlarda KG Var (BTTS) Oranı
q_btts = f"""
SELECT 
    'Genel Bülten (Tüm Maçlar)' as kategori,
    COUNT(*) as toplam_mac,
    ROUND(AVG(btts) * 100, 2) as kg_var_pct,
    ROUND(AVG(CASE WHEN fthg = 0 OR ftag = 0 THEN 1.0 ELSE 0.0 END) * 100, 2) as kg_yok_pct
FROM '{dataset_path}'

UNION ALL

SELECT 
    '6+ Gol Biten Maçlar' as kategori,
    COUNT(*) as toplam_mac,
    ROUND(AVG(btts) * 100, 2) as kg_var_pct,
    ROUND(AVG(CASE WHEN fthg = 0 OR ftag = 0 THEN 1.0 ELSE 0.0 END) * 100, 2) as kg_yok_pct
FROM '{dataset_path}'
WHERE ft_goals >= 6
"""
df_btts = con.execute(q_btts).df()
print("--- 1. KG VAR (KARŞILIKLI GOL) DAVRANIŞI ---")
print(df_btts.to_string(index=False))
print()

# 2. 6+ Gol Biten Maçlarda İY KG Var (İlk Yarıda İki Takımın da Gol Atması)
q_iy_btts = f"""
SELECT 
    'Genel Bülten' as kategori,
    COUNT(*) as toplam_mac,
    ROUND(AVG(CASE WHEN hthg > 0 AND htag > 0 THEN 1.0 ELSE 0.0 END) * 100, 2) as iy_kg_var_pct,
    ROUND(AVG(CASE WHEN ht_goals >= 2 THEN 1.0 ELSE 0.0 END) * 100, 2) as iy_15_ust_pct
FROM '{dataset_path}'
WHERE hthg IS NOT NULL AND htag IS NOT NULL

UNION ALL

SELECT 
    '6+ Gol Biten Maçlar' as kategori,
    COUNT(*) as toplam_mac,
    ROUND(AVG(CASE WHEN hthg > 0 AND htag > 0 THEN 1.0 ELSE 0.0 END) * 100, 2) as iy_kg_var_pct,
    ROUND(AVG(CASE WHEN ht_goals >= 2 THEN 1.0 ELSE 0.0 END) * 100, 2) as iy_15_ust_pct
FROM '{dataset_path}'
WHERE ft_goals >= 6 AND hthg IS NOT NULL AND htag IS NOT NULL
"""
df_iy = con.execute(q_iy_btts).df()
print("--- 2. İLK YARI TEMPOSU (İY 1.5 ÜST VE İY KG VAR) ---")
print(df_iy.to_string(index=False))
print()

# 3. İY/MS (İlk Yarı / Maç Sonu) Dağılımı (6+ Gol Bitenlerde)
q_htft = f"""
SELECT 
    CASE 
        WHEN hthg > htag AND fthg > ftag THEN '1/1 (Ev/Ev)'
        WHEN hthg < htag AND fthg < ftag THEN '2/2 (Dep/Dep)'
        WHEN hthg = htag AND fthg = ftag THEN 'X/X (Ber/Ber)'
        WHEN hthg = htag AND fthg > ftag THEN 'X/1 (Ber/Ev)'
        WHEN hthg = htag AND fthg < ftag THEN 'X/2 (Ber/Dep)'
        WHEN hthg > htag AND fthg = ftag THEN '1/X (Ev/Ber)'
        WHEN hthg < htag AND fthg = ftag THEN '2/X (Dep/Ber)'
        WHEN hthg > htag AND fthg < ftag THEN '1/2 (Şok Çevirme Ev->Dep)'
        WHEN hthg < htag AND fthg > ftag THEN '2/1 (Şok Çevirme Dep->Ev)'
        ELSE 'Diğer'
    END as htft_tipi,
    COUNT(*) as mac_sayisi,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM '{dataset_path}' WHERE ft_goals >= 6 AND hthg IS NOT NULL), 2) as yuzde
FROM '{dataset_path}'
WHERE ft_goals >= 6 AND hthg IS NOT NULL AND htag IS NOT NULL
GROUP BY 1
ORDER BY mac_sayisi DESC
"""
df_htft = con.execute(q_htft).df()
print("--- 3. 6+ GOL BİTEN MAÇLARDA İY/MS (İLK YARI / MAÇ SONU) DAĞILIMI ---")
print(df_htft.to_string(index=False))
print()

# 4. Çapraz Kombinasyon: KG Var + İY 1.5 Üst Olan Maçlarda 6+ Gol İhtimali
q_cross = f"""
SELECT 
    'Genel Maçlar' as profil,
    COUNT(*) as mac_sayisi,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as g6_olasilik_pct
FROM '{dataset_path}'

UNION ALL

SELECT 
    'Sadece KG Var Bitenler' as profil,
    COUNT(*) as mac_sayisi,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as g6_olasilik_pct
FROM '{dataset_path}'
WHERE btts = 1

UNION ALL

SELECT 
    'İlk Yarısında 2+ Gol (İY 1.5 Üst) Olanlar' as profil,
    COUNT(*) as mac_sayisi,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as g6_olasilik_pct
FROM '{dataset_path}'
WHERE ht_goals >= 2

UNION ALL

SELECT 
    'İlk Yarısı KG Var Bitenler (Her İki Takım da İY Gol Attı)' as profil,
    COUNT(*) as mac_sayisi,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as g6_olasilik_pct
FROM '{dataset_path}'
WHERE hthg > 0 AND htag > 0

UNION ALL

SELECT 
    'ALTIN KOMBİNASYON: İY KG Var + İY 2+ Gol (Yüksek Tempo Yangını)' as profil,
    COUNT(*) as mac_sayisi,
    ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 2) as g6_olasilik_pct
FROM '{dataset_path}'
WHERE hthg > 0 AND htag > 0 AND ht_goals >= 3
"""
df_cross = con.execute(q_cross).df()
print("--- 4. ÇAPRAZ GELİŞİM: HANGİ ERKEN SİNYALLER 6+ GOLÜ TETİKLİYOR? ---")
print(df_cross.to_string(index=False))
print()

# 5. Tek Taraflı Hezimete Karşı Karşılıklı Düello (KG Var vs KG Yok 6+ Goller)
q_hezimet = f"""
SELECT 
    CASE 
        WHEN btts = 1 THEN 'Karşılıklı Gol Düellosu (Her İki Takım da Attı)'
        ELSE 'Tek Taraflı Hezimet (6-0, 7-0 vb. - KG YOK)'
    END as mac_turu,
    COUNT(*) as mac_sayisi,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM '{dataset_path}' WHERE ft_goals >= 6), 2) as yuzde
FROM '{dataset_path}'
WHERE ft_goals >= 6
GROUP BY 1
"""
df_hez = con.execute(q_hezimet).df()
print("--- 5. 6+ GOL BİTENLERİN İÇ DAĞILIMI: DÜELLO MU, TEK TARAFLI HEZİMET Mİ? ---")
print(df_hez.to_string(index=False))

