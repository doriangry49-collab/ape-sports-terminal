"""Build enhanced 42k+ Odds Pattern Dataset with opening & closing odds, steam movements,
and multi-market results (Corners, Goals, HT/FT, Cards).
"""
import glob
import os
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd

RAW_DIR = Path("sports-engine/data/raw_odds")
OUT_PARQUET = Path("sports-engine/data/gold/odds_pattern_dataset_42k.parquet")

csv_files = sorted(RAW_DIR.glob("*.csv"))
print(f"Found {len(csv_files)} CSV files in {RAW_DIR}")

records = []
for f in csv_files:
    if f.name.endswith("manifest.csv"):
        continue
    try:
        df = pd.read_csv(f, encoding="latin1", on_bad_lines="skip")
        
        # Standardize column names
        cols = {c: c.strip() for c in df.columns}
        df.rename(columns=cols, inplace=True)
        
        # Basic check
        if "HomeTeam" not in df.columns or "AwayTeam" not in df.columns:
            continue
            
        for _, row in df.iterrows():
            home = str(row.get("HomeTeam", "")).strip()
            away = str(row.get("AwayTeam", "")).strip()
            if not home or not away or home == "nan":
                continue
                
            div = str(row.get("Div", ""))
            date_val = str(row.get("Date", ""))
            
            # Goals
            try:
                fthg = float(row.get("FTHG", np.nan))
                ftag = float(row.get("FTAG", np.nan))
            except (ValueError, TypeError):
                fthg, ftag = np.nan, np.nan
                
            if np.isnan(fthg) or np.isnan(ftag):
                continue
                
            try:
                hthg = float(row.get("HTHG", np.nan))
                htag = float(row.get("HTAG", np.nan))
            except (ValueError, TypeError):
                hthg, htag = np.nan, np.nan
                
            ft_goals = fthg + ftag
            ht_goals = (hthg + htag) if not np.isnan(hthg) and not np.isnan(htag) else np.nan
            
            # Corners
            try:
                hc = float(row.get("HC", np.nan))
                ac = float(row.get("AC", np.nan))
                tot_corners = hc + ac if not np.isnan(hc) and not np.isnan(ac) else np.nan
            except (ValueError, TypeError):
                hc, ac, tot_corners = np.nan, np.nan, np.nan
                
            # Cards
            try:
                hy = float(row.get("HY", 0.0))
                ay = float(row.get("AY", 0.0))
                hr = float(row.get("HR", 0.0))
                ar = float(row.get("AR", 0.0))
                tot_cards = (hy + ay + hr * 2.0 + ar * 2.0)
            except (ValueError, TypeError):
                tot_cards = np.nan
                
            # Odds Opening
            def to_float(val):
                try:
                    f = float(val)
                    return f if f > 1.0 else np.nan
                except:
                    return np.nan
                    
            open_1 = to_float(row.get("B365H")) or to_float(row.get("AvgH"))
            open_x = to_float(row.get("B365D")) or to_float(row.get("AvgD"))
            open_2 = to_float(row.get("B365A")) or to_float(row.get("AvgA"))
            open_o25 = to_float(row.get("B365>2.5")) or to_float(row.get("Avg>2.5"))
            open_u25 = to_float(row.get("B365<2.5")) or to_float(row.get("Avg<2.5"))
            
            # Odds Closing
            close_1 = to_float(row.get("B365CH")) or to_float(row.get("AvgCH")) or open_1
            close_x = to_float(row.get("B365CD")) or to_float(row.get("AvgCD")) or open_x
            close_2 = to_float(row.get("B365CA")) or to_float(row.get("AvgCA")) or open_2
            close_o25 = to_float(row.get("B365C>2.5")) or to_float(row.get("AvgC>2.5")) or open_o25
            close_u25 = to_float(row.get("B365C<2.5")) or to_float(row.get("AvgC<2.5")) or open_u25
            
            # Steam movements
            steam_1_pct = round(((close_1 / open_1) - 1.0) * 100, 2) if open_1 and close_1 else 0.0
            steam_o25_pct = round(((close_o25 / open_o25) - 1.0) * 100, 2) if open_o25 and close_o25 else 0.0

            records.append({
                "div_code": div,
                "date": date_val,
                "home_team": home,
                "away_team": away,
                "fthg": int(fthg),
                "ftag": int(ftag),
                "ft_goals": int(ft_goals),
                "exact_score": f"{int(fthg)}-{int(ftag)}",
                "ftr": "H" if fthg > ftag else ("A" if ftag > fthg else "D"),
                "hthg": int(hthg) if not np.isnan(hthg) else None,
                "htag": int(htag) if not np.isnan(htag) else None,
                "ht_goals": int(ht_goals) if not np.isnan(ht_goals) else None,
                "ht_exact_score": f"{int(hthg)}-{int(htag)}" if not np.isnan(hthg) and not np.isnan(htag) else None,
                "ht_goals_o15": 1 if (not np.isnan(ht_goals) and ht_goals > 1.5) else (0 if not np.isnan(ht_goals) else None),
                "ft_goals_o25": 1 if ft_goals > 2.5 else 0,
                "ft_goals_o35": 1 if ft_goals > 3.5 else 0,
                "ft_goals_o45": 1 if ft_goals > 4.5 else 0,
                "btts": 1 if (fthg > 0 and ftag > 0) else 0,
                "home_corners": hc if not np.isnan(hc) else None,
                "away_corners": ac if not np.isnan(ac) else None,
                "total_corners": tot_corners if not np.isnan(tot_corners) else None,
                "corners_o85": 1 if (not np.isnan(tot_corners) and tot_corners > 8.5) else (0 if not np.isnan(tot_corners) else None),
                "corners_o95": 1 if (not np.isnan(tot_corners) and tot_corners > 9.5) else (0 if not np.isnan(tot_corners) else None),
                "corners_o105": 1 if (not np.isnan(tot_corners) and tot_corners > 10.5) else (0 if not np.isnan(tot_corners) else None),
                "corners_o115": 1 if (not np.isnan(tot_corners) and tot_corners > 11.5) else (0 if not np.isnan(tot_corners) else None),
                "corners_12plus": 1 if (not np.isnan(tot_corners) and tot_corners >= 12.0) else (0 if not np.isnan(tot_corners) else None),
                "total_cards": tot_cards if not np.isnan(tot_cards) else None,
                "cards_o35": 1 if (not np.isnan(tot_cards) and tot_cards > 3.5) else (0 if not np.isnan(tot_cards) else None),
                "cards_o45": 1 if (not np.isnan(tot_cards) and tot_cards > 4.5) else (0 if not np.isnan(tot_cards) else None),
                "open_1": open_1,
                "open_x": open_x,
                "open_2": open_2,
                "open_o25": open_o25,
                "open_u25": open_u25,
                "close_1": close_1,
                "close_x": close_x,
                "close_2": close_2,
                "close_o25": close_o25,
                "close_u25": close_u25,
                "steam_1_pct": steam_1_pct,
                "steam_o25_pct": steam_o25_pct,
            })
    except Exception as e:
        print(f"Error reading {f.name}: {e}")

out_df = pd.DataFrame(records)
print(f"Successfully processed {len(out_df)} match records.")
OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
out_df.to_parquet(OUT_PARQUET, index=False)
print(f"Saved to {OUT_PARQUET} ({OUT_PARQUET.stat().st_size / 1024 / 1024:.2f} MB)")

