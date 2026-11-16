"""Universal Market Correlation & Odds Anatomy Explorer.

Extracts empirical joint and conditional probabilities across all major markets:
1X2, Totals (1.5, 2.5, 3.5, 4.5, 6+), BTTS, HT Goals, Corners, Cards, and Steam.
"""

from __future__ import annotations

import json
from pathlib import Path
import duckdb
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
PARQUET_PATH = ROOT_DIR / "data" / "gold" / "odds_pattern_dataset_42k.parquet"
OUTPUT_DIR = ROOT_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def analyze_universal_odds_matrix():
    con = duckdb.connect()
    parquet_str = str(PARQUET_PATH).replace("\\", "/")

    print(f"Loading gold dataset: {parquet_str}")
    total_count = con.execute(f"SELECT count(*) FROM '{parquet_str}'").fetchone()[0]
    print(f"Total historical matches: {total_count}")

    # 1. 1X2 Market Brackets vs All Other Markets
    print("\n=======================================================")
    print("1. 1X2 EV SAHİBİ ORAN BANTLARI VE TÜM PAZARLARIN GERÇEKLEŞME ORANLARI")
    print("=======================================================")

    home_bands_sql = f"""
    SELECT 
        CASE 
            WHEN close_1 >= 1.10 AND close_1 <= 1.40 THEN '1. Ağır Favori (1.10-1.40)'
            WHEN close_1 > 1.40 AND close_1 <= 1.75 THEN '2. Güçlü Favori (1.41-1.75)'
            WHEN close_1 > 1.75 AND close_1 <= 2.20 THEN '3. Orta Favori (1.76-2.20)'
            WHEN close_1 > 2.20 AND close_1 <= 3.00 THEN '4. Dengeli Maç (2.21-3.00)'
            ELSE '5. Ev Sürpriz / Plase (3.01+)'
        END as home_band,
        count(*) as match_count,
        ROUND(AVG(CASE WHEN ftr = 'H' THEN 1.0 ELSE 0.0 END) * 100, 1) as ms_1_pct,
        ROUND(AVG(CASE WHEN ftr = 'D' THEN 1.0 ELSE 0.0 END) * 100, 1) as ms_x_pct,
        ROUND(AVG(CASE WHEN ftr = 'A' THEN 1.0 ELSE 0.0 END) * 100, 1) as ms_2_pct,
        ROUND(AVG(CASE WHEN btts = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as btts_pct,
        ROUND(AVG(CASE WHEN ft_goals_o25 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as o25_pct,
        ROUND(AVG(CASE WHEN ft_goals_o35 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as o35_pct,
        ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 1) as tg6_pct,
        ROUND(AVG(CASE WHEN ht_goals >= 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as iy05_pct,
        ROUND(AVG(CASE WHEN ht_goals_o15 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as iy15_pct,
        ROUND(AVG(total_corners), 2) as avg_corners,
        ROUND(AVG(CASE WHEN corners_o95 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as c95_pct,
        ROUND(AVG(CASE WHEN corners_12plus = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as c12_pct,
        ROUND(AVG(total_cards), 2) as avg_cards
    FROM '{parquet_str}'
    WHERE close_1 IS NOT NULL AND close_1 > 1.05
    GROUP BY 1
    ORDER BY 1
    """
    df_home = con.execute(home_bands_sql).df()
    print(df_home.to_string(index=False))

    # 2. 2.5 Alt / Üst Oran Bantları vs Diğer Pazarlar
    print("\n=======================================================")
    print("2. 2.5 ALT / ÜST ORAN BANTLARININ DİĞER PAZARLARA ETKİSİ")
    print("=======================================================")

    ou_bands_sql = f"""
    SELECT 
        CASE 
            WHEN close_o25 <= 1.40 THEN '1. Aşırı Yüksek Tempo (O2.5 <= 1.40)'
            WHEN close_o25 > 1.40 AND close_o25 <= 1.65 THEN '2. Yüksek Tempo (1.41-1.65)'
            WHEN close_o25 > 1.65 AND close_o25 <= 1.95 THEN '3. Standart Dengeli (1.66-1.95)'
            WHEN close_o25 > 1.95 AND close_o25 <= 2.30 THEN '4. Kısır / Alt Meyilli (1.96-2.30)'
            ELSE '5. Aşırı Kısır (O2.5 > 2.30)'
        END as tempo_band,
        count(*) as match_count,
        ROUND(AVG(ft_goals), 2) as avg_goals,
        ROUND(AVG(CASE WHEN ft_goals_o25 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as o25_pct,
        ROUND(AVG(CASE WHEN ft_goals_o35 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as o35_pct,
        ROUND(AVG(CASE WHEN ft_goals >= 6 THEN 1.0 ELSE 0.0 END) * 100, 1) as tg6_pct,
        ROUND(AVG(CASE WHEN btts = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as btts_pct,
        ROUND(AVG(CASE WHEN ht_goals_o15 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as iy15_pct,
        ROUND(AVG(total_corners), 2) as avg_corners,
        ROUND(AVG(CASE WHEN total_corners > 8.5 THEN 1.0 ELSE 0.0 END) * 100, 1) as c85_pct,
        ROUND(AVG(CASE WHEN corners_o95 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as c95_pct,
        ROUND(AVG(CASE WHEN corners_12plus = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as c12_pct,
        ROUND(AVG(total_cards), 2) as avg_cards
    FROM '{parquet_str}'
    WHERE close_o25 IS NOT NULL AND close_o25 > 1.05
    GROUP BY 1
    ORDER BY 1
    """
    df_ou = con.execute(ou_bands_sql).df()
    print(df_ou.to_string(index=False))

    # 3. KOMBİNE ALTIN KESİŞİMLER (1X2 + GOL + KORNER)
    print("\n=======================================================")
    print("3. KOMBİNE ALTIN KESİŞİMLER (1X2 + GOL + KORNER)")
    print("=======================================================")

    combo_sql = f"""
    SELECT 
        CASE 
            WHEN close_1 <= 1.45 AND close_o25 <= 1.55 THEN 'A. Büyük Takım Evinde & Tempolu (1 <= 1.45 & O2.5 <= 1.55)'
            WHEN close_1 <= 1.45 AND close_o25 > 1.85 THEN 'B. Büyük Takım Evinde & Savunmacı (1 <= 1.45 & O2.5 > 1.85)'
            WHEN close_1 >= 2.30 AND close_2 >= 2.30 AND close_o25 <= 1.75 THEN 'C. Denk İki Tempolu Takım (1X2 Dengeli & O2.5 <= 1.75)'
            WHEN close_1 >= 2.30 AND close_2 >= 2.30 AND close_o25 >= 2.10 THEN 'D. Denk İki Defansif Takım (1X2 Dengeli & O2.5 >= 2.10)'
            WHEN close_2 <= 1.50 AND close_o25 <= 1.60 THEN 'E. Güçlü Deplasman Baskısı (2 <= 1.50 & O2.5 <= 1.60)'
            ELSE 'F. Diğer Standart Eşleşmeler'
        END as archetype,
        count(*) as match_count,
        ROUND(AVG(CASE WHEN ftr = 'H' THEN 1.0 ELSE 0.0 END) * 100, 1) as ms_1_pct,
        ROUND(AVG(CASE WHEN ftr = 'A' THEN 1.0 ELSE 0.0 END) * 100, 1) as ms_2_pct,
        ROUND(AVG(CASE WHEN ft_goals_o25 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as o25_pct,
        ROUND(AVG(CASE WHEN btts = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as btts_pct,
        ROUND(AVG(CASE WHEN ht_goals_o15 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as iy15_pct,
        ROUND(AVG(total_corners), 2) as avg_corners,
        ROUND(AVG(CASE WHEN corners_o95 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as c95_pct,
        ROUND(AVG(CASE WHEN corners_12plus = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as c12_pct,
        ROUND(AVG(total_cards), 2) as avg_cards
    FROM '{parquet_str}'
    WHERE close_1 IS NOT NULL AND close_2 IS NOT NULL AND close_o25 IS NOT NULL
    GROUP BY 1
    ORDER BY 1
    """
    df_combo = con.execute(combo_sql).df()
    print(df_combo.to_string(index=False))

    # 4. STEAM (ORAN HAREKETİ) ETKİSİ
    print("\n=======================================================")
    print("4. STEAM (ORAN HAREKETİ) ETKİSİ")
    print("=======================================================")
    steam_sql = f"""
    SELECT 
        CASE 
            WHEN steam_o25_pct <= -5.0 THEN '1. Üst Oranı Çöktü (Steam O2.5 <= -5%)'
            WHEN steam_o25_pct >= 5.0 THEN '2. Üst Oranı Şişti / Alt Çöktü (Steam O2.5 >= +5%)'
            WHEN steam_1_pct <= -7.0 THEN '3. Ev Sahibi Oranı Çöktü (Steam MS1 <= -7%)'
            WHEN ((close_2 - open_2) / NULLIF(open_2, 0) * 100) <= -7.0 THEN '4. Deplasman Oranı Çöktü (Steam MS2 <= -7%)'
            ELSE '5. Stabil Oranlar'
        END as steam_event,
        count(*) as match_count,
        ROUND(AVG(CASE WHEN ft_goals_o25 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as o25_pct,
        ROUND(AVG(CASE WHEN btts = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as btts_pct,
        ROUND(AVG(CASE WHEN ht_goals_o15 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as iy15_pct,
        ROUND(AVG(total_corners), 2) as avg_corners,
        ROUND(AVG(CASE WHEN corners_o95 = 1 THEN 1.0 ELSE 0.0 END) * 100, 1) as c95_pct,
        ROUND(AVG(total_cards), 2) as avg_cards
    FROM '{parquet_str}'
    WHERE steam_1_pct IS NOT NULL AND steam_o25_pct IS NOT NULL AND open_2 IS NOT NULL AND close_2 IS NOT NULL
    GROUP BY 1
    ORDER BY 1
    """
    df_steam = con.execute(steam_sql).df()
    print(df_steam.to_string(index=False))

    # Save to JSON
    report_data = {
        "total_records": total_count,
        "home_bands": df_home.to_dict(orient="records"),
        "ou_bands": df_ou.to_dict(orient="records"),
        "combos": df_combo.to_dict(orient="records"),
        "steam": df_steam.to_dict(orient="records"),
    }
    with open(OUTPUT_DIR / "universal_market_matrix.json", "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"\nSaved matrix to: {OUTPUT_DIR / 'universal_market_matrix.json'}")

if __name__ == "__main__":
    analyze_universal_odds_matrix()
