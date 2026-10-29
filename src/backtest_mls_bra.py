"""MLS (USA) & Brazil Serie A — Draw / Under 2.5 retail-bias backtest.

Data: football-data.co.uk "extra leagues" files (USA.csv, BRA.csv), obtained via the
GitHub mirror huhao930422-debug/football-odds-mirror (see data/raw_odds/extra_leagues_manifest.csv).

Methodology mirrors src/run_walkforward_5seasons.py:
  fair_p  = Pinnacle closing 1X2 (PSCH/PSCD/PSCA) with proportional de-vig
  edge    = book_odds * fair_p - 1 ;  bet if edge >= MIN_EDGE and MIN_ODDS <= odds <= MAX_ODDS
  stake   = 1 unit flat
Differences forced by the data: extra-league files have NO B365 pre-closing odds and NO O/U 2.5 odds.
P&L book is therefore market-average closing (AvgC*) as primary; B365C* (only partial 2025) and
MaxC* (best price across books, an optimistic upper bound) are reported as sensitivity checks.
No data is simulated; rows with missing odds are skipped.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "raw_odds"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT = OUTPUT_DIR / "mls_bra_backtest_report.md"
BETS_CSV = OUTPUT_DIR / "mls_bra_backtest_bets.csv"

STAKE = 1.0
MIN_EDGE = 0.02
MIN_ODDS = 1.25
MAX_ODDS = 10.0
N_SEASONS = 5
MIN_BETS_FOR_VERDICT = 200

LEAGUES = {"USA": ("USA.csv", "USA MLS"), "BRA": ("BRA.csv", "Brazil Serie A")}
BOOKS = {"AvgC": "Avg closing (primary)", "B365C": "Bet365 closing", "MaxC": "Max closing (upper bound)"}


def remove_vig(h, d, a):
    if pd.isna(h) or pd.isna(d) or pd.isna(a) or min(h, d, a) <= 1.0:
        return np.nan, np.nan, np.nan
    rh, rd, ra = 1.0 / h, 1.0 / d, 1.0 / a
    s = rh + rd + ra
    return rh / s, rd / s, ra / s


def load(code):
    fname, _ = LEAGUES[code]
    fpath = DATA_DIR / fname
    if not fpath.exists():
        raise FileNotFoundError(f"{fpath} missing — run the download step (see manifest).")
    df = pd.read_csv(fpath, encoding='utf-8-sig', low_memory=False)
    df = df.loc[:, ~df.columns.str.startswith('Unnamed')]
    df['match_date'] = pd.to_datetime(df['Date'], format='%d/%m/%Y', errors='coerce')
    df = df.sort_values('match_date').reset_index(drop=True)
    for c in ['HG', 'AG']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    fp = df.apply(lambda r: remove_vig(r['PSCH'], r['PSCD'], r['PSCA']), axis=1)
    df['fair_p_H'] = [p[0] for p in fp]
    df['fair_p_D'] = [p[1] for p in fp]
    df['fair_p_A'] = [p[2] for p in fp]
    return df


def select_bets(df, book, outcome='D'):
    col = f"{book}{outcome}"
    if col not in df.columns:
        return pd.DataFrame()
    sub = df[df[col].notna() & df[f'fair_p_{outcome}'].notna() & df['Res'].notna()].copy()
    sub['odds'] = pd.to_numeric(sub[col], errors='coerce')
    sub = sub[(sub['odds'] >= MIN_ODDS) & (sub['odds'] <= MAX_ODDS)]
    sub['edge'] = sub['odds'] * sub[f'fair_p_{outcome}'] - 1.0
    sub = sub[sub['edge'] >= MIN_EDGE].copy()
    sub['won'] = sub['Res'] == outcome
    sub['pnl'] = np.where(sub['won'], STAKE * (sub['odds'] - 1.0), -STAKE)
    sub['book'] = book
    sub['selection'] = outcome
    return sub


def summarize(bets, by='Season'):
    if len(bets) == 0:
        return pd.DataFrame(columns=[by, 'bets', 'hit', 'avg_odds', 'pnl', 'roi'])
    g = bets.groupby(by).agg(bets=('pnl', 'size'), wins=('won', 'sum'),
                             avg_odds=('odds', 'mean'), pnl=('pnl', 'sum')).reset_index()
    g['hit'] = g['wins'] / g['bets'] * 100
    g['roi'] = g['pnl'] / g['bets'] * 100
    return g


def roi_ci(pnl):
    """Normal-approx 95% CI of ROI (%), plus t-stat."""
    n = len(pnl)
    if n < 2:
        return np.nan, np.nan, np.nan
    m, s = pnl.mean(), pnl.std(ddof=1)
    se = s / math.sqrt(n)
    return (m - 1.96 * se) * 100, (m + 1.96 * se) * 100, (m / se if se > 0 else np.nan)


def verdict(bets, season_tbl):
    n = len(bets)
    if n < MIN_BETS_FOR_VERDICT:
        return "INSUFFICIENT DATA", f"only {n} bets (< {MIN_BETS_FOR_VERDICT})"
    lo, hi, t = roi_ci(bets['pnl'])
    roi = bets['pnl'].mean() * 100
    pos = int((season_tbl['pnl'] > 0).sum())
    if lo > 0 and pos >= 4:
        return "EDGE", f"ROI {roi:+.2f}%, 95% CI [{lo:+.1f}, {hi:+.1f}], {pos}/{len(season_tbl)} seasons positive"
    return "NO EDGE", f"ROI {roi:+.2f}%, 95% CI [{lo:+.1f}, {hi:+.1f}] includes/below 0, {pos}/{len(season_tbl)} seasons positive"


def fmt_tbl(tbl, by='Season'):
    lines = [f"| {by} | Bets | Hit % | Avg odds | Net units | ROI % |", "|---|---:|---:|---:|---:|---:|"]
    for r in tbl.to_dict('records'):
        lines.append(f"| {r[by]} | {int(r['bets'])} | {r['hit']:.1f} | {r['avg_odds']:.2f} | {r['pnl']:+.2f} | {r['roi']:+.2f} |")
    return "\n".join(lines)


def main():
    md = []
    md.append("# MLS & Brazil Serie A — Draw / Under 2.5 Backtest (real data)\n")
    md.append("Source: football-data.co.uk extra-league files `USA.csv`, `BRA.csv` via GitHub mirror "
              "`huhao930422-debug/football-odds-mirror` (SHA-256 in `data/raw_odds/extra_leagues_manifest.csv`).\n")
    md.append(f"Method (same as `run_walkforward_5seasons.py`): fair prob = Pinnacle closing 1X2 de-vigged; "
              f"bet Draw when `odds × fair_p − 1 ≥ {MIN_EDGE}`, odds in [{MIN_ODDS}, {MAX_ODDS}], 1u flat. "
              "Primary P&L book = **Avg closing** (AvgCD). Sensitivity: B365 closing (only part of 2025), "
              "Max closing (best price across books — not realistically achievable for every bet).\n")
    md.append("> **Data limits:** extra-league files contain **no Over/Under 2.5 odds** and **no B365 pre-closing odds**; "
              "Pinnacle closing is **absent for season 2026** (and ~3–12% of 2025). Seasons evaluated = last 5 with Pinnacle closing.\n")

    all_bets = []
    verdicts = []
    for code, (_, lname) in LEAGUES.items():
        df = load(code)
        seasons_psc = sorted(df.loc[df['fair_p_D'].notna(), 'Season'].unique())
        seasons = seasons_psc[-N_SEASONS:]
        d5 = df[df['Season'].isin(seasons)].copy()
        print(f"\n=== {lname}: seasons {seasons}, matches {len(d5)} (with PSC: {d5['fair_p_D'].notna().sum()}) ===")
        md.append(f"\n## {lname}\n")
        md.append(f"Seasons: {', '.join(map(str, seasons))} — {len(d5)} matches "
                  f"({d5['fair_p_D'].notna().sum()} with Pinnacle closing).\n")

        # --- base rates
        md.append("### Base rates (actual vs market-implied)\n")
        md.append("| Season | Matches | Actual draw % | Pinnacle fair draw % | Avg-close implied draw % (with vig) | z (actual − fair) | Actual Under 2.5 % | Market-implied Under 2.5 % |")
        md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for s in seasons + ['ALL']:
            x = d5 if s == 'ALL' else d5[d5['Season'] == s]
            xp = x[x['fair_p_D'].notna()]
            n = len(xp)
            act = (xp['Res'] == 'D').mean() * 100
            fair = xp['fair_p_D'].mean() * 100
            var = (xp['fair_p_D'] * (1 - xp['fair_p_D'])).sum()
            z = ((xp['Res'] == 'D').sum() - xp['fair_p_D'].sum()) / math.sqrt(var) if var > 0 else np.nan
            avg_impl = (1 / x['AvgCD']).mean() * 100
            under = ((x['HG'] + x['AG']) < 2.5).mean() * 100
            md.append(f"| {s} | {n} | {act:.1f} | {fair:.1f} | {avg_impl:.1f} | {z:+.2f} | {under:.1f} | n/a (no O/U odds) |")
            print(f"  base {s}: n={n} draw {act:.1f}% vs fair {fair:.1f}% z={z:+.2f} | under2.5 {under:.1f}%")

        # --- flat "back every draw" reference
        md.append("\n### Reference: back EVERY draw (no filter)\n")
        md.append("| Book | Bets | Hit % | Avg odds | Net units | ROI % |")
        md.append("|---|---:|---:|---:|---:|---:|")
        for book in ['PSC', 'AvgC', 'MaxC']:
            x = d5[d5[f'{book}D'].notna() & d5['fair_p_D'].notna()]
            won = x['Res'] == 'D'
            pnl = np.where(won, x[f'{book}D'] - 1, -1.0)
            md.append(f"| {book} | {len(x)} | {won.mean()*100:.1f} | {x[f'{book}D'].mean():.2f} | {pnl.sum():+.2f} | {pnl.mean()*100:+.2f} |")

        # --- strategy
        for book, bdesc in BOOKS.items():
            bets = select_bets(d5, book, 'D')
            if len(bets):
                bets['league'] = lname
                all_bets.append(bets)
            tbl = summarize(bets)
            md.append(f"\n### Draw value strategy — {bdesc}\n")
            if len(bets) == 0:
                md.append("No qualifying bets (column missing or no edge ≥ 2%).\n")
                v, why = "INSUFFICIENT DATA", "0 bets"
            else:
                md.append(fmt_tbl(tbl))
                lo, hi, t = roi_ci(bets['pnl'])
                roi = bets['pnl'].mean() * 100
                md.append(f"\n**Total:** {len(bets)} bets | hit {bets['won'].mean()*100:.1f}% | avg odds {bets['odds'].mean():.2f} | "
                          f"net {bets['pnl'].sum():+.2f}u | ROI {roi:+.2f}% (95% CI {lo:+.1f}…{hi:+.1f}, t={t:+.2f}) | "
                          f"avg claimed edge {bets['edge'].mean()*100:.1f}%\n")
                v, why = verdict(bets, tbl)
            n_elig = int((d5[f'{book}D'].notna() & d5['fair_p_D'].notna()).sum()) if f'{book}D' in d5 else 0
            if v == "INSUFFICIENT DATA" and n_elig >= 1000:
                # Plenty of priced matches but the filter (almost) never fires: the book's closing
                # draw price does not exceed Pinnacle fair value -> no exploitable mispricing.
                v = "NO EDGE"
                why = (f"filter fired on only {len(bets)} of {n_elig} priced matches — "
                       f"{book} draw price ≥2% above Pinnacle fair value essentially never occurs")
                n0 = int((d5[f'{book}D'] * d5['fair_p_D'] - 1 >= 0).sum())
                md.append(f"\nSensitivity: with edge threshold 0% instead of 2%, {n0} of {n_elig} matches qualify.\n")
            print(f"  Draw/{book}: {len(bets)} bets -> {v} ({why})")
            verdicts.append((lname, f"Draw — {bdesc}", v, why))
        verdicts.append((lname, "Under 2.5", "INSUFFICIENT DATA",
                         "no O/U 2.5 odds in football-data extra-league files; only actual under-rate reported"))

    md.append("\n## Verdicts\n")
    md.append("| League | Market / book | Verdict | Basis |")
    md.append("|---|---|---|---|")
    for lg, m, v, why in verdicts:
        md.append(f"| {lg} | {m} | **{v}** | {why} |")
    md.append(f"\nVerdict rule: EDGE only if ≥{MIN_BETS_FOR_VERDICT} bets, 95% CI of ROI entirely > 0 and ≥4/5 seasons positive; "
              f"otherwise NO EDGE; < {MIN_BETS_FOR_VERDICT} bets → INSUFFICIENT DATA. The primary (realistic) verdict is the **Avg closing** row; "
              "Max closing assumes always getting the best price in the market and B365 closing covers only part of 2025.\n")
    md.append("\n## Caveats\n")
    md.append("- Sample sizes are small (≈380–540 matches/season); a ±5% ROI cannot be distinguished from zero with a few hundred bets at draw odds (~3.3, σ≈1.4u/bet).\n"
              "- European study priced bets at B365 *pre-closing* vs Pinnacle *closing*; here both are closing, which removes the "
              "line-movement component — results are therefore not perfectly comparable (and the European set-up has a look-ahead element, since closing Pinnacle is not known at bet time).\n"
              "- Avg closing is a market average; a bettor at a single soft book may get worse prices.\n"
              "- Under 2.5 cannot be backtested from this source; an alternative legitimate free source with O/U odds for MLS/BRA would be needed.\n")

    REPORT.write_text("\n".join(md), encoding='utf-8')
    if all_bets:
        out = pd.concat(all_bets)
        out[['league', 'Season', 'match_date', 'Home', 'Away', 'HG', 'AG', 'Res', 'book', 'selection', 'odds',
             'fair_p_D', 'edge', 'won', 'pnl']].to_csv(BETS_CSV, index=False, encoding='utf-8')
    print(f"\nReport: {REPORT}\nBets: {BETS_CSV}")


if __name__ == '__main__':
    main()
