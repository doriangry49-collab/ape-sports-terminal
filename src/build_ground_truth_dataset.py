"""Ground Truth Dataset Builder for Sports-Engine.

Ingests and normalizes 42,000+ historical football matches from 87 league-season CSVs
(including ground truth corners, cards, shots, fouls, referees, and market odds)
into a unified high-performance Parquet dataset.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT_DIR / "data" / "raw_odds"
OUT_PARQUET = ROOT_DIR / "data" / "gold" / "ground_truth_matches_42k.parquet"
OUT_PROFILES = ROOT_DIR / "data" / "gold" / "team_corner_card_profiles.parquet"
OUT_REFEREES = ROOT_DIR / "data" / "gold" / "referee_profiles.parquet"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("GroundTruthBuilder")

DIV_LEAGUE_MAP: dict[str, tuple[str, str]] = {
    "E0": ("England", "Premier League"),
    "E1": ("England", "Championship"),
    "E2": ("England", "League One"),
    "E3": ("England", "League Two"),
    "SP1": ("Spain", "La Liga"),
    "SP2": ("Spain", "La Liga 2"),
    "D1": ("Germany", "Bundesliga"),
    "D2": ("Germany", "Bundesliga 2"),
    "I1": ("Italy", "Serie A"),
    "I2": ("Italy", "Serie B"),
    "F1": ("France", "Ligue 1"),
    "F2": ("France", "Ligue 2"),
    "N1": ("Netherlands", "Eredivisie"),
    "P1": ("Portugal", "Primeira Liga"),
    "B1": ("Belgium", "Pro League"),
    "T1": ("Turkey", "Super Lig"),
    "SC0": ("Scotland", "Premiership"),
    "SC1": ("Scotland", "Championship"),
}


def parse_date(date_val: Any) -> str | None:
    """Standardize date strings to YYYY-MM-DD."""
    if pd.isna(date_val):
        return None
    d_str = str(date_val).strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return pd.to_datetime(d_str, format=fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    try:
        return pd.to_datetime(d_str).strftime("%Y-%m-%d")
    except Exception:
        return None


def build_unified_dataset() -> pd.DataFrame:
    """Parse all raw CSV files into a unified clean DataFrame."""
    csv_files = sorted(RAW_DIR.glob("*.csv"))
    logger.info(f"Found {len(csv_files)} CSV files in {RAW_DIR}")

    all_records: list[dict[str, Any]] = []

    for f in csv_files:
        if f.name in ("extra_leagues_manifest.csv", "overnight_manifest.csv"):
            continue

        parts = f.stem.split("_")
        div_code = parts[0]
        season = parts[1] if len(parts) > 1 else "Unknown"

        country, league_name = DIV_LEAGUE_MAP.get(div_code, (div_code, div_code))

        try:
            df = pd.read_csv(f, encoding="utf-8", low_memory=False)
        except Exception:
            try:
                df = pd.read_csv(f, encoding="latin1", low_memory=False)
            except Exception as e:
                logger.warning(f"Could not read {f.name}: {e}")
                continue

        # Standardize column names
        df.columns = [c.strip() for c in df.columns]

        # Check required columns
        if "HomeTeam" not in df.columns or "AwayTeam" not in df.columns:
            continue

        for _, row in df.iterrows():
            ht = str(row.get("HomeTeam") or "").strip()
            at = str(row.get("AwayTeam") or "").strip()
            if not ht or not at or ht == "nan" or at == "nan":
                continue

            dt_parsed = parse_date(row.get("Date"))

            # Goals
            fthg = pd.to_numeric(row.get("FTHG"), errors="coerce")
            ftag = pd.to_numeric(row.get("FTAG"), errors="coerce")
            ftr = str(row.get("FTR") or "").strip().upper()
            if ftr not in ("H", "D", "A") and not np.isnan(fthg) and not np.isnan(ftag):
                ftr = "H" if fthg > ftag else ("A" if ftag > fthg else "D")

            # Corners
            hc = pd.to_numeric(row.get("HC"), errors="coerce")
            ac = pd.to_numeric(row.get("AC"), errors="coerce")
            total_corners = hc + ac if not np.isnan(hc) and not np.isnan(ac) else np.nan

            # Cards
            hy = pd.to_numeric(row.get("HY"), errors="coerce")
            ay = pd.to_numeric(row.get("AY"), errors="coerce")
            hr = pd.to_numeric(row.get("HR"), errors="coerce")
            ar = pd.to_numeric(row.get("AR"), errors="coerce")
            total_cards = (
                (hy if not np.isnan(hy) else 0)
                + (ay if not np.isnan(ay) else 0)
                + ((hr if not np.isnan(hr) else 0) * 2)
                + ((ar if not np.isnan(ar) else 0) * 2)
                if not np.isnan(hy) or not np.isnan(ay)
                else np.nan
            )

            # Shots
            hs = pd.to_numeric(row.get("HS"), errors="coerce")
            as_shots = pd.to_numeric(row.get("AS"), errors="coerce")
            hst = pd.to_numeric(row.get("HST"), errors="coerce")
            ast = pd.to_numeric(row.get("AST"), errors="coerce")

            # Fouls
            hf = pd.to_numeric(row.get("HF"), errors="coerce")
            af = pd.to_numeric(row.get("AF"), errors="coerce")

            # Referee
            ref = str(row.get("Referee") or "").strip()
            if ref in ("nan", "None", ""):
                ref = None

            # Pre-match odds (Bet365 / Pinnacle / Max)
            b365_h = pd.to_numeric(row.get("B365H"), errors="coerce")
            b365_d = pd.to_numeric(row.get("B365D"), errors="coerce")
            b365_a = pd.to_numeric(row.get("B365A"), errors="coerce")
            b365_over25 = pd.to_numeric(row.get("B365>2.5"), errors="coerce")
            b365_under25 = pd.to_numeric(row.get("B365<2.5"), errors="coerce")

            all_records.append({
                "country": country,
                "league": league_name,
                "div_code": div_code,
                "season": season,
                "date": dt_parsed,
                "home_team": ht,
                "away_team": at,
                "fthg": fthg,
                "ftag": ftag,
                "ftr": ftr,
                "home_corners": hc,
                "away_corners": ac,
                "total_corners": total_corners,
                "over_8_5_corners": 1 if total_corners > 8.5 else (0 if not np.isnan(total_corners) else np.nan),
                "over_9_5_corners": 1 if total_corners > 9.5 else (0 if not np.isnan(total_corners) else np.nan),
                "over_10_5_corners": 1 if total_corners > 10.5 else (0 if not np.isnan(total_corners) else np.nan),
                "home_yellows": hy,
                "away_yellows": ay,
                "home_reds": hr,
                "away_reds": ar,
                "total_cards": total_cards,
                "home_shots": hs,
                "away_shots": as_shots,
                "home_shots_target": hst,
                "away_shots_target": ast,
                "home_fouls": hf,
                "away_fouls": af,
                "referee": ref,
                "b365_h": b365_h,
                "b365_d": b365_d,
                "b365_a": b365_a,
                "b365_over25": b365_over25,
                "b365_under25": b365_under25,
            })

    df_all = pd.DataFrame(all_records)
    df_all = df_all.sort_values(by=["date", "country", "league"]).reset_index(drop=True)
    logger.info(f"Unified dataset built: {len(df_all):,} total matches")

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df_all.to_parquet(OUT_PARQUET, index=False)
    logger.info(f"Saved gold parquet dataset to {OUT_PARQUET}")
    return df_all


def compute_team_profiles(df: pd.DataFrame) -> pd.DataFrame:
    """Compute rolling team-level corner and card metrics."""
    logger.info("Computing team corner and card profiles...")
    teams = sorted(set(df["home_team"].dropna().unique()).union(set(df["away_team"].dropna().unique())))

    profiles: list[dict[str, Any]] = []
    for tm in teams:
        h_matches = df[df["home_team"] == tm]
        a_matches = df[df["away_team"] == tm]
        total_m = len(h_matches) + len(a_matches)
        if total_m < 10:
            continue

        # Corners
        h_corners_for = h_matches["home_corners"].dropna()
        h_corners_against = h_matches["away_corners"].dropna()
        a_corners_for = a_matches["away_corners"].dropna()
        a_corners_against = a_matches["home_corners"].dropna()

        all_for = pd.concat([h_corners_for, a_corners_for])
        all_against = pd.concat([h_corners_against, a_corners_against])

        # Cards
        h_cards = h_matches["home_yellows"].dropna() + (h_matches["home_reds"].dropna() * 2)
        a_cards = a_matches["away_yellows"].dropna() + (a_matches["away_reds"].dropna() * 2)
        all_cards = pd.concat([h_cards, a_cards])

        tot_c = pd.concat([
            h_matches["total_corners"].dropna(),
            a_matches["total_corners"].dropna(),
        ])

        profiles.append({
            "team": tm,
            "league": h_matches["league"].iloc[0] if len(h_matches) > 0 else a_matches["league"].iloc[0],
            "country": h_matches["country"].iloc[0] if len(h_matches) > 0 else a_matches["country"].iloc[0],
            "matches_played": total_m,
            "avg_corners_for": round(float(all_for.mean()), 2) if len(all_for) > 0 else np.nan,
            "avg_corners_against": round(float(all_against.mean()), 2) if len(all_against) > 0 else np.nan,
            "net_corner_diff": round(float(all_for.mean() - all_against.mean()), 2) if len(all_for) > 0 and len(all_against) > 0 else np.nan,
            "match_corners_avg": round(float(tot_c.mean()), 2) if len(tot_c) > 0 else np.nan,
            "pct_over_8_5_corners": round(float((tot_c > 8.5).mean() * 100), 1) if len(tot_c) > 0 else np.nan,
            "pct_over_9_5_corners": round(float((tot_c > 9.5).mean() * 100), 1) if len(tot_c) > 0 else np.nan,
            "pct_over_10_5_corners": round(float((tot_c > 10.5).mean() * 100), 1) if len(tot_c) > 0 else np.nan,
            "avg_cards": round(float(all_cards.mean()), 2) if len(all_cards) > 0 else np.nan,
        })

    prof_df = pd.DataFrame(profiles)
    prof_df = prof_df.sort_values(by=["matches_played", "avg_corners_for"], ascending=False).reset_index(drop=True)
    prof_df.to_parquet(OUT_PROFILES, index=False)
    logger.info(f"Saved {len(prof_df)} team profiles to {OUT_PROFILES}")
    return prof_df


def compute_referee_profiles(df: pd.DataFrame) -> pd.DataFrame:
    """Compute referee discipline metrics and tendencies."""
    logger.info("Computing referee profiles...")
    ref_df = df[df["referee"].notna() & (df["referee"] != "")]
    referees = ref_df["referee"].unique()

    ref_profiles: list[dict[str, Any]] = []
    for ref in referees:
        m = ref_df[ref_df["referee"] == ref]
        if len(m) < 10:
            continue

        tot_cards = m["total_cards"].dropna()
        fouls = (m["home_fouls"].dropna() + m["away_fouls"].dropna())

        ref_profiles.append({
            "referee": ref,
            "league": m["league"].iloc[0],
            "country": m["country"].iloc[0],
            "matches_officiated": len(m),
            "avg_yellows": round(float((m["home_yellows"] + m["away_yellows"]).mean()), 2),
            "avg_reds": round(float((m["home_reds"] + m["away_reds"]).mean()), 2),
            "avg_total_cards": round(float(tot_cards.mean()), 2) if len(tot_cards) > 0 else np.nan,
            "avg_fouls": round(float(fouls.mean()), 2) if len(fouls) > 0 else np.nan,
            "fouls_per_card": round(float(fouls.mean() / tot_cards.mean()), 2) if len(tot_cards) > 0 and tot_cards.mean() > 0 and len(fouls) > 0 else np.nan,
            "strictness_tier": "STRICT (>4.5 cards)" if tot_cards.mean() > 4.5 else ("LENIENT (<3.5 cards)" if tot_cards.mean() < 3.5 else "AVERAGE"),
        })

    out_ref_df = pd.DataFrame(ref_profiles).sort_values(by="matches_officiated", ascending=False).reset_index(drop=True)
    out_ref_df.to_parquet(OUT_REFEREES, index=False)
    logger.info(f"Saved {len(out_ref_df)} referee profiles to {OUT_REFEREES}")
    return out_ref_df


def main():
    df_all = build_unified_dataset()
    compute_team_profiles(df_all)
    compute_referee_profiles(df_all)
    logger.info("Ground Truth Dataset & Profiles complete!")


if __name__ == "__main__":
    main()

