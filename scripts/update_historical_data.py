"""Historical Match Dataset Updater (2026/27 Season + Extra Leagues).

Updates:
1. Extra leagues (`BRA.csv`, `USA.csv`): tries official football-data.co.uk first,
   then falls back to the verified GitHub mirror (`huhao930422-debug/football-odds-mirror`)
   referenced in `data/raw_odds/extra_leagues_manifest.csv`.
2. European & Turkish `2627` season CSVs (`B1, D1, D2, E0, E1, E2, F1, F2, I1, I2,
   N1, P1, SC0, SC1, SP1, SP2, T1`): tries `football-data.co.uk/mmz4281/2627/{div}.csv`
   first; when blocked/unreachable, fetches completed 2026-27 matchdays from the
   public ESPN Soccer Scoreboard API (`site.api.espn.com`) with full shot/corner/foul
   stats and aligns team names against historical `football-data` canonical spellings.
3. Rebuilds `data/gold/ground_truth_matches_42k.parquet`, team/referee profiles,
   and retrains `data/silver/team_strength_ratings.json` (`TeamStrengthEngine`).
"""
from __future__ import annotations

import concurrent.futures
import csv
import difflib
import hashlib
import io
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from build_ground_truth_dataset import (  # noqa: E402
    build_unified_dataset,
    compute_referee_profiles,
    compute_team_profiles,
)
from team_normalizer import TeamNormalizer  # noqa: E402
from team_strength_engine import TeamStrengthEngine  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw_odds"
SEASON_CODE = "2627"
SEASON_START_DATE = "2026-07-01"

FOOTBALL_DATA_2627_URL = "https://www.football-data.co.uk/mmz4281/2627/{div}.csv"
FOOTBALL_DATA_EXTRA_URLS = {
    "BRA.csv": [
        "https://www.football-data.co.uk/new/BRA.csv",
        "https://raw.githubusercontent.com/huhao930422-debug/football-odds-mirror/main/data/brazil/all-seasons.csv",
    ],
    "USA.csv": [
        "https://www.football-data.co.uk/new/USA.csv",
        "https://raw.githubusercontent.com/huhao930422-debug/football-odds-mirror/main/data/usa/all-seasons.csv",
    ],
}

DIV_TO_ESPN_SLUG: dict[str, str] = {
    "E0": "eng.1",
    "E1": "eng.2",
    "E2": "eng.3",
    "SP1": "esp.1",
    "SP2": "esp.2",
    "D1": "ger.1",
    "D2": "ger.2",
    "I1": "ita.1",
    "I2": "ita.2",
    "F1": "fra.1",
    "F2": "fra.2",
    "N1": "ned.1",
    "P1": "por.1",
    "B1": "bel.1",
    "T1": "tur.1",
    "SC0": "sco.1",
    "SC1": "sco.2",
}

CSV_COLUMNS = [
    "Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR",
    "HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC",
]

# Explicit deterministic map where ESPN spellings collide with other clubs (e.g. PSG vs Paris FC,
# Istanbul Basaksehir vs Istanbulspor, Cercle vs Club Brugge) or use abbreviated football-data keys.
ESPN_TO_FOOTBALL_DATA_EXACT: dict[str, str] = {
    "Athletic Club": "Ath Bilbao",
    "Atlético Madrid": "Ath Madrid",
    "Caykur Rizespor": "Rizespor",
    "Cercle Brugge KSV": "Cercle Brugge",
    "Deportivo": "La Coruna",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "Espanyol": "Espanol",
    "FC Cologne": "FC Koln",
    "Fortuna Sittard": "For Sittard",
    "Goztepe": "Goztep",
    "Heart of Midlothian": "Hearts",
    "Istanbul Basaksehir": "Buyuksehyr",
    "Nottingham Forest": "Nott'm Forest",
    "OH Leuven": "Oud-Heverlee Leuven",
    "Paris Saint-Germain": "Paris SG",
    "Peterborough United": "Peterboro",
    "Queen's Park": "Queens Park",
    "Raith Rovers": "Raith Rvs",
    "Real Sociedad II": "Sociedad B",
    "Saint-Étienne": "St Etienne",
    "Sheffield Wednesday": "Sheffield Weds",
    "Sint-Truidense": "St Truiden",
    "Stade Rennais": "Rennes",
    "West Bromwich Albion": "West Brom",
}


def _http_get_text(url: str, timeout: float = 8.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} for {url}")
        return resp.read().decode("utf-8-sig", errors="replace")


def _build_canonical_team_catalog(raw_dir: Path = RAW_DIR) -> dict[str, set[str]]:
    """Collect known historical football-data team names per division (e.g. 'T1', 'E0')."""
    by_div: dict[str, set[str]] = {}
    for csv_path in sorted(raw_dir.glob("*_*.csv")):
        if csv_path.name in ("extra_leagues_manifest.csv", "overnight_manifest.csv"):
            continue
        div_code, _, season = csv_path.stem.partition("_")
        if season == SEASON_CODE:
            continue
        try:
            df = pd.read_csv(csv_path, usecols=["HomeTeam", "AwayTeam"], low_memory=False)
        except Exception:
            continue
        names = by_div.setdefault(div_code, set())
        for col in ("HomeTeam", "AwayTeam"):
            names.update(str(v).strip() for v in df[col].dropna() if str(v).strip())
    return by_div


def resolve_canonical_team_name(
    raw_name: str,
    candidate_names: set[str],
    normalizer: TeamNormalizer,
    min_similarity: float = 0.85,
) -> str:
    """Map an external provider team name (e.g. ESPN) to historical football-data spelling."""
    cleaned = raw_name.strip()
    if not cleaned:
        return cleaned
    explicit = ESPN_TO_FOOTBALL_DATA_EXACT.get(cleaned)
    if explicit:
        return explicit
    if not candidate_names:
        return cleaned
    if cleaned in candidate_names:
        return cleaned

    best_name: str | None = None
    best_score: tuple[float, float, str] = (0.0, 0.0, "")
    cleaned_low = cleaned.lower()
    for cand in sorted(candidate_names):
        sim = normalizer.compute_similarity(cleaned, cand)
        seq = difflib.SequenceMatcher(None, cleaned_low, cand.lower()).ratio()
        score = (sim, seq, cand)
        if score > best_score:
            best_score = score
            best_name = cand

    return best_name if (best_name and best_score[0] >= min_similarity) else cleaned


def update_extra_league_csvs(
    raw_dir: Path = RAW_DIR,
    direct_timeout: float = 4.0,
) -> dict[str, dict[str, Any]]:
    """Update BRA.csv and USA.csv atomically from official source or verified GitHub mirror."""
    results: dict[str, dict[str, Any]] = {}
    manifest_rows: list[dict[str, Any]] = []

    for filename, urls in FOOTBALL_DATA_EXTRA_URLS.items():
        target = raw_dir / filename
        chosen_url = None
        payload_text = None

        for idx, url in enumerate(urls):
            timeout = direct_timeout if idx == 0 else 20.0
            try:
                text = _http_get_text(url, timeout=timeout)
                lines = [ln for ln in text.splitlines() if ln.strip()]
                if len(lines) > 100 and lines[0].startswith("Country,"):
                    chosen_url = url
                    payload_text = text
                    break
            except Exception:
                continue

        if payload_text and chosen_url:
            existing_rows = len(target.read_text(encoding="utf-8", errors="replace").splitlines()) - 1 if target.exists() else 0
            new_rows = len([ln for ln in payload_text.splitlines() if ln.strip()]) - 1
            if new_rows >= existing_rows:
                tmp_path = target.with_suffix(".csv.tmp")
                raw_bytes = payload_text.encode("utf-8")
                tmp_path.write_bytes(raw_bytes)
                tmp_path.replace(target)
                sha = hashlib.sha256(raw_bytes).hexdigest()
                results[filename] = {
                    "status": "updated",
                    "rows": new_rows,
                    "delta_rows": new_rows - existing_rows,
                    "source": chosen_url,
                }
                manifest_rows.append({
                    "file": filename,
                    "source_url": chosen_url,
                    "original_source": f"mirror of https://www.football-data.co.uk/new/{filename}",
                    "bytes": len(raw_bytes),
                    "sha256": sha,
                    "downloaded_utc": datetime.now(UTC).isoformat(),
                })
            else:
                results[filename] = {"status": "kept_existing", "rows": existing_rows}
        else:
            results[filename] = {"status": "failed_all_sources"}

    if manifest_rows:
        manifest_path = raw_dir / "extra_leagues_manifest.csv"
        tmp_m = manifest_path.with_suffix(".csv.tmp")
        with open(tmp_m, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["file", "source_url", "original_source", "bytes", "sha256", "downloaded_utc"],
            )
            writer.writeheader()
            writer.writerows(manifest_rows)
        tmp_m.replace(manifest_path)

    return results


def _stat_val(competitor: dict[str, Any], stat_name: str) -> int | str:
    for st in competitor.get("statistics") or []:
        if st.get("name") == stat_name:
            try:
                return int(float(st.get("displayValue")))
            except (TypeError, ValueError):
                return ""
    return ""


def _parse_espn_scoreboard_events(
    data: dict[str, Any],
    div_code: str,
    cutoff_ymd: str,
    canonical_names: set[str],
    normalizer: TeamNormalizer,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ev in data.get("events") or []:
        comps = ev.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        if not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        ko_raw = str(comp.get("date") or ev.get("date") or "")
        if len(ko_raw) < 10:
            continue
        ymd = ko_raw[:10]
        if not (SEASON_START_DATE <= ymd <= cutoff_ymd):
            continue

        by_side = {c.get("homeAway"): c for c in (comp.get("competitors") or [])}
        home_comp = by_side.get("home")
        away_comp = by_side.get("away")
        if not home_comp or not away_comp:
            continue

        try:
            fthg = int(float(home_comp.get("score")))
            ftag = int(float(away_comp.get("score")))
        except (TypeError, ValueError):
            continue

        ftr = "H" if fthg > ftag else ("A" if ftag > fthg else "D")
        raw_home = str(home_comp.get("team", {}).get("displayName") or "").strip()
        raw_away = str(away_comp.get("team", {}).get("displayName") or "").strip()
        if not raw_home or not raw_away:
            continue

        dt_str = f"{ymd[8:10]}/{ymd[5:7]}/{ymd[:4]}"
        rows.append({
            "Div": div_code,
            "Date": dt_str,
            "HomeTeam": resolve_canonical_team_name(raw_home, canonical_names, normalizer),
            "AwayTeam": resolve_canonical_team_name(raw_away, canonical_names, normalizer),
            "FTHG": fthg,
            "FTAG": ftag,
            "FTR": ftr,
            "HS": _stat_val(home_comp, "totalShots"),
            "AS": _stat_val(away_comp, "totalShots"),
            "HST": _stat_val(home_comp, "shotsOnTarget"),
            "AST": _stat_val(away_comp, "shotsOnTarget"),
            "HF": _stat_val(home_comp, "foulsCommitted"),
            "AF": _stat_val(away_comp, "foulsCommitted"),
            "HC": _stat_val(home_comp, "wonCorners"),
            "AC": _stat_val(away_comp, "wonCorners"),
        })
    return rows


def fetch_2627_division_csv(
    div_code: str,
    espn_slug: str,
    cutoff_ymd: str,
    canonical_names: set[str],
    normalizer: TeamNormalizer,
    direct_timeout: float = 3.5,
) -> tuple[str, list[dict[str, Any]] | str]:
    """Fetch 2026-27 division results via football-data.co.uk first, else ESPN Scoreboard."""
    fd_url = FOOTBALL_DATA_2627_URL.format(div=div_code)
    try:
        csv_text = _http_get_text(fd_url, timeout=direct_timeout)
        first_line = csv_text.splitlines()[0] if csv_text else ""
        if "HomeTeam" in first_line and "AwayTeam" in first_line:
            return "football-data.co.uk", csv_text
    except Exception:
        pass

    base_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{espn_slug}/scoreboard"
    root_data = json.loads(_http_get_text(base_url, timeout=10.0))
    cal_items = (root_data.get("leagues") or [{}])[0].get("calendar") or []
    match_days = sorted({str(c)[:10].replace("-", "") for c in cal_items if SEASON_START_DATE <= str(c)[:10] <= cutoff_ymd})

    seen_keys: set[tuple[str, str, str]] = set()
    all_rows: list[dict[str, Any]] = []

    def _fetch_day(yyyymmdd: str) -> list[dict[str, Any]]:
        try:
            day_data = json.loads(_http_get_text(f"{base_url}?dates={yyyymmdd}", timeout=8.0))
            return _parse_espn_scoreboard_events(day_data, div_code, cutoff_ymd, canonical_names, normalizer)
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for day_rows in ex.map(_fetch_day, match_days):
            for r in day_rows:
                dedup_key = (r["Date"], r["HomeTeam"], r["AwayTeam"])
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    all_rows.append(r)

    all_rows.sort(key=lambda r: f"{r['Date'][6:10]}-{r['Date'][3:5]}-{r['Date'][:2]}")
    return f"espn:{espn_slug}", all_rows


def update_european_2627_csvs(
    raw_dir: Path = RAW_DIR,
    cutoff_ymd: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch & atomically save `{DIV}_2627.csv` for all 17 European & Turkish leagues."""
    cutoff = cutoff_ymd or datetime.now(UTC).strftime("%Y-%m-%d")
    catalog = _build_canonical_team_catalog(raw_dir)
    normalizer = TeamNormalizer()
    summary: dict[str, dict[str, Any]] = {}

    for div_code, espn_slug in DIV_TO_ESPN_SLUG.items():
        # Include cross-division teams in the same country prefix (E0/E1/E2, SP1/SP2, etc.)
        country_prefix = div_code[0] if div_code != "SC0" and div_code != "SC1" else "SC"
        cand_names: set[str] = set()
        for k, names in catalog.items():
            if k == div_code or k.startswith(country_prefix):
                cand_names.update(names)

        try:
            source, payload = fetch_2627_division_csv(
                div_code=div_code,
                espn_slug=espn_slug,
                cutoff_ymd=cutoff,
                canonical_names=cand_names,
                normalizer=normalizer,
            )
            target = raw_dir / f"{div_code}_{SEASON_CODE}.csv"
            if isinstance(payload, str):
                tmp_path = target.with_suffix(".csv.tmp")
                tmp_path.write_text(payload, encoding="utf-8")
                tmp_path.replace(target)
                row_cnt = max(0, len([ln for ln in payload.splitlines() if ln.strip()]) - 1)
                max_dt = ""
            else:
                if not payload:
                    summary[div_code] = {"status": "empty_skipped", "source": source, "rows": 0}
                    continue
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
                writer.writeheader()
                writer.writerows(payload)
                tmp_path = target.with_suffix(".csv.tmp")
                tmp_path.write_text(buf.getvalue(), encoding="utf-8")
                tmp_path.replace(target)
                row_cnt = len(payload)
                last_d = payload[-1]["Date"]
                max_dt = f"{last_d[6:10]}-{last_d[3:5]}-{last_d[:2]}"

            summary[div_code] = {"status": "updated", "source": source, "rows": row_cnt, "max_date": max_dt}
            print(f"  ✅ {div_code}_{SEASON_CODE}.csv -> {row_cnt} maç (Son: {max_dt or 'fd'}) [{source}]")
        except Exception as exc:
            summary[div_code] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            print(f"  ⚠️ {div_code}_{SEASON_CODE}.csv hatası: {exc}")

    return summary


def run_full_historical_refresh(cutoff_ymd: str | None = None) -> dict[str, Any]:
    """Update extra + 2627 CSVs, rebuild gold parquets, and retrain TeamStrengthEngine."""
    print("[1/4] BRA.csv & USA.csv güncelleniyor...")
    extra_res = update_extra_league_csvs()
    for fn, info in extra_res.items():
        print(f"  -> {fn}: {info}")

    print("\n[2/4] 2026/27 (2627) Avrupa & Türkiye ligleri çekiliyor...")
    eu_res = update_european_2627_csvs(cutoff_ymd=cutoff_ymd)

    print("\n[3/4] Gold parquet ve takım/hakem profilleri yeniden derleniyor...")
    df_all = build_unified_dataset()
    compute_team_profiles(df_all)
    compute_referee_profiles(df_all)

    print("\n[4/4] TeamStrengthEngine modeli yeniden eğitiliyor (silver cache)...")
    engine = TeamStrengthEngine()
    engine.fit_from_data()
    print(
        f" ✅ Model güncellendi: {engine.total_matches_trained} maç, {len(engine.team_ratings)} takım "
        f"| Son veri tarihi: {engine.max_training_date}"
    )

    return {
        "extra_leagues": extra_res,
        "european_2627": eu_res,
        "gold_total_matches": int(len(df_all)),
        "gold_max_date": str(df_all["date"].max()),
        "model_total_matches": engine.total_matches_trained,
        "model_max_date": engine.max_training_date,
        "model_teams_count": len(engine.team_ratings),
    }


if __name__ == "__main__":
    run_full_historical_refresh()
