"""Overnight Quantitative Research & Methodology Audit (2021/22 - 2025/26).

Audits:
1. Methodology & Look-Ahead Bias in `run_walkforward_5seasons.py` and `test_over_under_5seasons.py`:
   - Compares the biased setup (fair_p from Pinnacle CLOSING `PSC*` / `PC*` evaluated against Bet365 OPENING `B365*`)
     against synchronized time-point setups:
     (a) Opening Arbitrage: Pinnacle OPENING (`PS*` / `P*`) fair_p vs Bet365 OPENING (`B365*`)
     (b) Closing Arbitrage: Pinnacle CLOSING (`PSC*` / `PC*`) fair_p vs Bet365 CLOSING (`B365C*`)
     (c) Pure Zero-Lookahead Pre-Match Historical / Poisson Model: using strictly past matches before date `t`
         (rolling team & league draw rates + Dixon-Coles / Poisson expected goals) without peeking at closing odds.
2. Secondary European Leagues Expansion (Real Data):
   - Evaluates 17 European leagues across 5 seasons (2021/22 - 2025/26):
     Big 5 (`E0, SP1, I1, D1, F1`), Turkey (`T1`), and 11 Secondary European Leagues
     (`N1, P1, B1, E1, D2, I2, SP2, F2, E2, SC0, SC1`).
"""
import glob
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\Users\Thea-Aria\ .gemini\antigravity\scratch\ec2-file-explorer\sports-engine")
DATA_DIR = ROOT / "data" / "raw_odds"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STAKE = 1.0
MIN_EDGE = 0.02
MIN_ODDS = 1.25
MAX_ODDS = 10.0
MIN_ODDS_OU = 1.20

LEAGUE_META = {
    # Big 5
    "E0": ("Premier League", "Big5"),
    "SP1": ("La Liga", "Big5"),
    "I1": ("Serie A", "Big5"),
    "D1": ("Bundesliga", "Big5"),
    "F1": ("Ligue 1", "Big5"),
    # Turkey
    "T1": ("Süper Lig", "Turkey"),
    # Secondary European Leagues (Core 7 requested + 4 additional)
    "N1": ("Eredivisie (NL)", "Secondary"),
    "P1": ("Primeira Liga (PT)", "Secondary"),
    "B1": ("Jupiler Pro League (BE)", "Secondary"),
    "E1": ("Championship (ENG2)", "Secondary"),
    "D2": ("2. Bundesliga (GER2)", "Secondary"),
    "I2": ("Serie B (ITA2)", "Secondary"),
    "SP2": ("La Liga 2 (ESP2)", "Secondary"),
    "F2": ("Ligue 2 (FRA2)", "Secondary"),
    "E2": ("League One (ENG3)", "Secondary"),
    "SC0": ("Scottish Premiership", "Secondary"),
    "SC1": ("Scottish Championship", "Secondary"),
}


def remove_vig_3way(h, d, a):
    if pd.isna(h) or pd.isna(d) or pd.isna(a) or min(h, d, a) <= 1.0:
        return np.nan, np.nan, np.nan
    rh, rd, ra = 1.0 / h, 1.0 / d, 1.0 / a
    tot = rh + rd + ra
    return rh / tot, rd / tot, ra / tot


def remove_vig_2way(o1, o2):
    if pd.isna(o1) or pd.isna(o2) or min(o1, o2) <= 1.0:
        return np.nan, np.nan
    r1, r2 = 1.0 / o1, 1.0 / o2
    tot = r1 + r2
    return r1 / tot, r2 / tot


def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def poisson_match_probs(lam_h, lam_a, rho=-0.08, max_goals=8):
    """Dixon-Coles adjusted Poisson 1X2 and Over/Under 2.5 probabilities."""
    p_h, p_d, p_a = 0.0, 0.0, 0.0
    p_under25, p_over25 = 0.0, 0.0
    tot_prob = 0.0
    for i in range(max_goals + 1):
        pi = poisson_pmf(i, lam_h)
        for j in range(max_goals + 1):
            pj = poisson_pmf(j, lam_a)
            p = pi * pj
            # Dixon-Coles low-score correlation adjustment (tau)
            if i == 0 and j == 0:
                tau = 1.0 - lam_h * lam_a * rho
            elif i == 0 and j == 1:
                tau = 1.0 + lam_h * rho
            elif i == 1 and j == 0:
                tau = 1.0 + lam_a * rho
            elif i == 1 and j == 1:
                tau = 1.0 - rho
            else:
                tau = 1.0
            tau = max(0.0, tau)
            p *= tau
            tot_prob += p
            if i > j:
                p_h += p
            elif i == j:
                p_d += p
            else:
                p_a += p
            if (i + j) < 2.5:
                p_under25 += p
            else:
                p_over25 += p
    if tot_prob <= 0:
        return np.nan, np.nan, np.nan, np.nan, np.nan
    return (
        p_h / tot_prob,
        p_d / tot_prob,
        p_a / tot_prob,
        p_over25 / tot_prob,
        p_under25 / tot_prob,
    )


def calc_stats(df_bets):
    n = len(df_bets)
    if n == 0:
        return {
            "bets": 0,
            "wins": 0,
            "hit_rate": 0.0,
            "avg_odds": 0.0,
            "avg_edge": 0.0,
            "pnl": 0.0,
            "roi": 0.0,
            "t_stat": 0.0,
            "ci_lo": 0.0,
            "ci_hi": 0.0,
            "max_dd": 0.0,
        }
    pnl_arr = df_bets["pnl"].to_numpy(dtype=float)
    wins = int(df_bets["won"].sum())
    tot_pnl = float(pnl_arr.sum())
    mean_pnl = float(pnl_arr.mean())
    roi = mean_pnl * 100.0
    if n >= 2:
        std_pnl = float(pnl_arr.std(ddof=1))
        se = std_pnl / math.sqrt(n)
        t_stat = mean_pnl / se if se > 0 else 0.0
        ci_lo = (mean_pnl - 1.96 * se) * 100.0
        ci_hi = (mean_pnl + 1.96 * se) * 100.0
    else:
        t_stat, ci_lo, ci_hi = 0.0, np.nan, np.nan
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(np.insert(cum, 0, 0.0))[1:]
    max_dd = float(np.max(peak - cum)) if n > 0 else 0.0
    return {
        "bets": n,
        "wins": wins,
        "hit_rate": round(wins / n * 100.0, 2),
        "avg_odds": round(float(df_bets["odds"].mean()), 3),
        "avg_edge": round(float(df_bets["edge"].mean()) * 100.0, 2),
        "pnl": round(tot_pnl, 2),
        "roi": round(roi, 2),
        "t_stat": round(t_stat, 2),
        "ci_lo": round(ci_lo, 2) if pd.notna(ci_lo) else 0.0,
        "ci_hi": round(ci_hi, 2) if pd.notna(ci_hi) else 0.0,
        "max_dd": round(max_dd, 2),
    }


def load_all_matches():
    files = sorted(glob.glob(str(DATA_DIR / "*_*.csv")))
    frames = []
    odds_cols = [
        "B365H", "B365D", "B365A",
        "B365CH", "B365CD", "B365CA",
        "PSH", "PSD", "PSA",
        "PSCH", "PSCD", "PSCA",
        "B365>2.5", "B365<2.5",
        "B365C>2.5", "B365C<2.5",
        "P>2.5", "P<2.5",
        "PC>2.5", "PC<2.5",
    ]
    base_cols = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]

    for fpath in files:
        fname = Path(fpath).name
        m = re.match(r"^([A-Z0-9]+)_([0-9]{4})\.csv$", fname)
        if not m:
            continue
        code, season_code = m.groups()
        if code not in LEAGUE_META:
            continue
        season_str = f"20{season_code[:2]}/{season_code[2:]}"
        raw = pd.read_csv(fpath, encoding="utf-8-sig", low_memory=False)
        if "FTR" not in raw.columns or len(raw) == 0:
            continue

        keep = [c for c in base_cols + odds_cols if c in raw.columns]
        df = raw[keep].copy()
        for oc in odds_cols:
            if oc in df.columns:
                df[oc] = pd.to_numeric(df[oc], errors="coerce")
            else:
                df[oc] = np.nan

        d1 = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors="coerce")
        d2 = pd.to_datetime(df["Date"], format="%d/%m/%y", errors="coerce")
        df["match_date"] = d1.fillna(d2)
        df = df[df["match_date"].notna() & df["FTR"].isin(["H", "D", "A"])].copy()
        df["FTHG"] = pd.to_numeric(df["FTHG"], errors="coerce")
        df["FTAG"] = pd.to_numeric(df["FTAG"], errors="coerce")
        df = df[df["FTHG"].notna() & df["FTAG"].notna()].copy()
        df["total_goals"] = df["FTHG"] + df["FTAG"]
        df["div"] = code
        df["league_name"] = LEAGUE_META[code][0]
        df["tier"] = LEAGUE_META[code][1]
        df["season"] = season_str
        frames.append(df)

    full = pd.concat(frames, ignore_index=True)
    full = full.sort_values(["match_date", "div", "HomeTeam"]).reset_index(drop=True)
    return full


def compute_probabilities_and_prematch_features(full_df):
    """Computes:
    1) Pinnacle Closing fair_p (`psc_fair_*`, `pc_fair_*`)
    2) Pinnacle Opening fair_p (`ps_fair_*`, `p_fair_*`)
    3) Zero-Lookahead Pre-Match Historical / Poisson Model (`hist_fair_*`, `pois_fair_*`)
       strictly grouped by date so matches on the same date `t` never see results from date `t`.
    """
    n = len(full_df)
    psc_h, psc_d, psc_a = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    ps_h, ps_d, ps_a = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    pc_over, pc_under = np.full(n, np.nan), np.full(n, np.nan)
    p_over, p_under = np.full(n, np.nan), np.full(n, np.nan)

    pois_h, pois_d, pois_a = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    pois_over, pois_under = np.full(n, np.nan), np.full(n, np.nan)
    hist_d = np.full(n, np.nan)

    for idx, row in full_df.iterrows():
        fh, fd, fa = remove_vig_3way(row["PSCH"], row["PSCD"], row["PSCA"])
        psc_h[idx], psc_d[idx], psc_a[idx] = fh, fd, fa

        oh, od, oa = remove_vig_3way(row["PSH"], row["PSD"], row["PSA"])
        ps_h[idx], ps_d[idx], ps_a[idx] = oh, od, oa

        f_ov, f_un = remove_vig_2way(row["PC>2.5"], row["PC<2.5"])
        pc_over[idx], pc_under[idx] = f_ov, f_un

        o_ov, o_un = remove_vig_2way(row["P>2.5"], row["P<2.5"])
        p_over[idx], p_under[idx] = o_ov, o_un

    full_df["psc_fair_H"] = psc_h
    full_df["psc_fair_D"] = psc_d
    full_df["psc_fair_A"] = psc_a
    full_df["ps_fair_H"] = ps_h
    full_df["ps_fair_D"] = ps_d
    full_df["ps_fair_A"] = ps_a
    full_df["pc_fair_over"] = pc_over
    full_df["pc_fair_under"] = pc_under
    full_df["p_fair_over"] = p_over
    full_df["p_fair_under"] = p_under

    MIN_LEAGUE_MATCHES = 30
    MIN_TEAM_MATCHES = 8
    WINDOW_TEAM = 20
    SHRINK_K = 10.0

    for _div_code, ldf in full_df.groupby("div", sort=False):
        league_hg_hist = []
        league_ag_hist = []
        league_draw_hist = []

        team_home_gf = defaultdict(list)
        team_home_ga = defaultdict(list)
        team_away_gf = defaultdict(list)
        team_away_ga = defaultdict(list)
        team_all_draws = defaultdict(list)

        for _match_date, date_batch in ldf.groupby("match_date", sort=True):
            if len(league_draw_hist) >= MIN_LEAGUE_MATCHES:
                lg_hg = float(np.mean(league_hg_hist[-380:]))
                lg_ag = float(np.mean(league_ag_hist[-380:]))
                lg_draw = float(np.mean(league_draw_hist[-380:]))

                for idx, row in date_batch.iterrows():
                    ht = row["HomeTeam"]
                    at = row["AwayTeam"]
                    h_total_n = len(team_all_draws[ht])
                    a_total_n = len(team_all_draws[at])
                    if h_total_n < MIN_TEAM_MATCHES or a_total_n < MIN_TEAM_MATCHES:
                        continue

                    h_gf_list = team_home_gf[ht][-WINDOW_TEAM:]
                    h_ga_list = team_home_ga[ht][-WINDOW_TEAM:]
                    a_gf_list = team_away_gf[at][-WINDOW_TEAM:]
                    a_ga_list = team_away_ga[at][-WINDOW_TEAM:]

                    nh = len(h_gf_list)
                    na = len(a_gf_list)
                    if nh < 3 or na < 3:
                        continue

                    h_gf_reg = (sum(h_gf_list) + SHRINK_K * lg_hg) / (nh + SHRINK_K)
                    h_ga_reg = (sum(h_ga_list) + SHRINK_K * lg_ag) / (nh + SHRINK_K)
                    a_gf_reg = (sum(a_gf_list) + SHRINK_K * lg_ag) / (na + SHRINK_K)
                    a_ga_reg = (sum(a_ga_list) + SHRINK_K * lg_hg) / (na + SHRINK_K)

                    lam_h = (h_gf_reg / lg_hg) * (a_ga_reg / lg_hg) * lg_hg if lg_hg > 0 else 1.35
                    lam_a = (a_gf_reg / lg_ag) * (h_ga_reg / lg_ag) * lg_ag if lg_ag > 0 else 1.10

                    ph, pd_pois, pa, pov, pun = poisson_match_probs(lam_h, lam_a, rho=-0.08)
                    pois_h[idx] = ph
                    pois_d[idx] = pd_pois
                    pois_a[idx] = pa
                    pois_over[idx] = pov
                    pois_under[idx] = pun

                    h_dr_list = team_all_draws[ht][-WINDOW_TEAM:]
                    a_dr_list = team_all_draws[at][-WINDOW_TEAM:]
                    h_dr_reg = (sum(h_dr_list) + SHRINK_K * lg_draw) / (len(h_dr_list) + SHRINK_K)
                    a_dr_reg = (sum(a_dr_list) + SHRINK_K * lg_draw) / (len(a_dr_list) + SHRINK_K)
                    emp_draw = 0.5 * (h_dr_reg + a_dr_reg)
                    hist_d[idx] = 0.5 * pd_pois + 0.5 * emp_draw

            for idx, row in date_batch.iterrows():
                ht = row["HomeTeam"]
                at = row["AwayTeam"]
                hg = float(row["FTHG"])
                ag = float(row["FTAG"])
                is_draw = 1.0 if row["FTR"] == "D" else 0.0

                league_hg_hist.append(hg)
                league_ag_hist.append(ag)
                league_draw_hist.append(is_draw)

                team_home_gf[ht].append(hg)
                team_home_ga[ht].append(ag)
                team_away_gf[at].append(ag)
                team_away_ga[at].append(hg)
                team_all_draws[ht].append(is_draw)
                team_all_draws[at].append(is_draw)

    full_df["pois_fair_H"] = pois_h
    full_df["pois_fair_D"] = pois_d
    full_df["pois_fair_A"] = pois_a
    full_df["pois_fair_over"] = pois_over
    full_df["pois_fair_under"] = pois_under
    full_df["hist_fair_D"] = hist_d
    return full_df


def evaluate_1x2_strategy(df, prob_col_prefix, book_col_prefix, outcome="D", min_edge=MIN_EDGE):
    p_col = f"{prob_col_prefix}_{outcome}" if not prob_col_prefix.endswith(f"_{outcome}") else prob_col_prefix
    b_col = f"{book_col_prefix}{outcome}"
    sub = df[df[p_col].notna() & df[b_col].notna()].copy()
    sub = sub[(sub[b_col] >= MIN_ODDS) & (sub[b_col] <= MAX_ODDS)].copy()
    sub["odds"] = sub[b_col]
    sub["fair_p"] = sub[p_col]
    sub["edge"] = (sub["odds"] * sub["fair_p"]) - 1.0
    sub = sub[sub["edge"] >= min_edge].copy()
    sub["won"] = sub["FTR"] == outcome
    sub["pnl"] = np.where(sub["won"], STAKE * (sub["odds"] - 1.0), -STAKE)
    return sub


def evaluate_ou_strategy(df, prob_col, book_col, is_under=True, min_edge=MIN_EDGE):
    sub = df[df[prob_col].notna() & df[book_col].notna()].copy()
    sub = sub[sub[book_col] > MIN_ODDS_OU].copy()
    sub["odds"] = sub[book_col]
    sub["fair_p"] = sub[prob_col]
    sub["edge"] = (sub["odds"] * sub["fair_p"]) - 1.0
    sub = sub[sub["edge"] >= min_edge].copy()
    if is_under:
        sub["won"] = sub["total_goals"] < 2.5
    else:
        sub["won"] = sub["total_goals"] > 2.5
    sub["pnl"] = np.where(sub["won"], STAKE * (sub["odds"] - 1.0), -STAKE)
    return sub


def run_audit():
    print("Loading 5-season dataset across all 17 leagues...")
    full_df = load_all_matches()
    print(f"Loaded {len(full_df)} completed matches across {full_df['div'].nunique()} leagues.")
    full_df = compute_probabilities_and_prematch_features(full_df)

    big5_df = full_df[full_df["tier"] == "Big5"].copy()
    big5_t1_df = full_df[full_df["tier"].isin(["Big5", "Turkey"])].copy()
    sec_df = full_df[full_df["tier"] == "Secondary"].copy()

    # =========================================================================
    # PART 1: LOOK-AHEAD BIAS DECONSTRUCTION ON BIG 5 (1X2 DRAW & O/U 2.5)
    # =========================================================================
    audit_1x2_variants = [
        ("1. Biased Baseline: Pinnacle Closing (PSCD) vs B365 Opening (B365D) [LOOK-AHEAD]", "psc_fair", "B365", "D"),
        ("2. Opening Arbitrage: Pinnacle Opening (PSD) vs B365 Opening (B365D) [ZERO LOOK-AHEAD]", "ps_fair", "B365", "D"),
        ("3. Closing Arbitrage: Pinnacle Closing (PSCD) vs B365 Closing (B365CD) [ZERO LOOK-AHEAD]", "psc_fair", "B365C", "D"),
        ("4. Pure Pre-Match Dixon-Coles Poisson vs B365 Opening (B365D) [ZERO LOOK-AHEAD]", "pois_fair", "B365", "D"),
        ("5. Pure Pre-Match Rolling Draw + Poisson Blend vs B365 Opening (B365D) [ZERO LOOK-AHEAD]", "hist_fair_D", "B365", "D"),
        ("6. Pure Pre-Match Rolling Draw + Poisson Blend vs Pinnacle Opening (PSD) [ZERO LOOK-AHEAD]", "hist_fair_D", "PS", "D"),
    ]

    print("\n" + "=" * 95)
    print("PART 1A: BIG 5 LEAGUES — 1X2 DRAW LOOK-AHEAD BIAS DECONSTRUCTION (2021/22 - 2025/26)")
    print("=" * 95)
    part1_draw_results = []
    for label, p_pref, b_pref, outc in audit_1x2_variants:
        bets = evaluate_1x2_strategy(big5_df, p_pref, b_pref, outcome=outc)
        st = calc_stats(bets)
        st["variant"] = label
        part1_draw_results.append(st)
        print(
            f"{label:88s} | Bets={st['bets']:4d} | Hit={st['hit_rate']:5.1f}% | "
            f"PnL={st['pnl']:+7.2f}u | ROI={st['roi']:+6.2f}% | t={st['t_stat']:+5.2f}"
        )

    # Quantify exact steam / line-movement bias on the biased Draw bets (both Big 5 and All 17 Leagues)
    wf_draw_bets = evaluate_1x2_strategy(big5_df, "psc_fair", "B365", outcome="D")
    wf_draw_with_open = wf_draw_bets[wf_draw_bets["PSD"].notna() & wf_draw_bets["B365CD"].notna()].copy()
    steam_shortened_pct = float((wf_draw_with_open["PSCD"] < wf_draw_with_open["PSD"]).mean() * 100.0)
    avg_b365_open = float(wf_draw_with_open["B365D"].mean())
    avg_b365_close = float(wf_draw_with_open["B365CD"].mean())
    avg_ps_open = float(wf_draw_with_open["PSD"].mean())
    avg_ps_close = float(wf_draw_with_open["PSCD"].mean())

    wf_draw_settled_at_b365c = wf_draw_with_open.copy()
    wf_draw_settled_at_b365c["pnl_at_close"] = np.where(
        wf_draw_settled_at_b365c["won"],
        wf_draw_settled_at_b365c["B365CD"] - 1.0,
        -1.0,
    )
    pnl_same_matches_at_close = float(wf_draw_settled_at_b365c["pnl_at_close"].sum())
    roi_same_matches_at_close = float(wf_draw_settled_at_b365c["pnl_at_close"].mean() * 100.0)

    # All 17 leagues steam diagnostic
    all_draw_bets = evaluate_1x2_strategy(full_df, "psc_fair", "B365", outcome="D")
    all_draw_open = all_draw_bets[all_draw_bets["PSD"].notna() & all_draw_bets["B365CD"].notna()].copy()
    all_steam_pct = float((all_draw_open["PSCD"] < all_draw_open["PSD"]).mean() * 100.0)
    all_draw_open["pnl_at_close"] = np.where(all_draw_open["won"], all_draw_open["B365CD"] - 1.0, -1.0)
    all_pnl_at_close = float(all_draw_open["pnl_at_close"].sum())
    all_roi_at_close = float(all_draw_open["pnl_at_close"].mean() * 100.0)

    print("\n--- STEAM / LINE MOVEMENT DIAGNOSTIC ON BIASED DRAW BETS ---")
    print(f"[Big 5] Qualified Draw bets: {len(wf_draw_with_open)} | PSCD < PSD: {steam_shortened_pct:.2f}%")
    print(f"[Big 5] Avg Pinnacle Open (PSD): {avg_ps_open:.3f} -> Close (PSCD): {avg_ps_close:.3f}")
    print(f"[Big 5] Avg Bet365 Open (B365D): {avg_b365_open:.3f} -> Close (B365CD): {avg_b365_close:.3f}")
    print(
        f"[Big 5] If those exact {len(wf_draw_with_open)} bets were placed at B365 Closing (B365CD): "
        f"PnL = {pnl_same_matches_at_close:+.2f}u (ROI = {roi_same_matches_at_close:+.2f}%)"
    )
    print(
        f"[All 17] Qualified Draw bets: {len(all_draw_open)} | PSCD < PSD: {all_steam_pct:.2f}% | "
        f"If placed at B365CD: PnL = {all_pnl_at_close:+.2f}u (ROI = {all_roi_at_close:+.2f}%)"
    )

    # Part 1B: O/U 2.5 Look-Ahead Deconstruction on Big 5 + T1
    print("\n" + "=" * 95)
    print("PART 1B: 6 LEAGUES (BIG 5 + T1) — OVER/UNDER 2.5 LOOK-AHEAD DECONSTRUCTION")
    print("=" * 95)
    audit_ou_variants = [
        ("1. Biased Baseline: PC<2.5 (Close) vs B365<2.5 (Open) [UNDER 2.5 - LOOK-AHEAD]", "pc_fair_under", "B365<2.5", True),
        ("2. Opening Arbitrage: P<2.5 (Open) vs B365<2.5 (Open) [UNDER 2.5 - ZERO LOOK-AHEAD]", "p_fair_under", "B365<2.5", True),
        ("3. Closing Arbitrage: PC<2.5 (Close) vs B365C<2.5 (Close) [UNDER 2.5 - ZERO LOOK-AHEAD]", "pc_fair_under", "B365C<2.5", True),
        ("4. Pure Pre-Match Poisson vs B365<2.5 (Open) [UNDER 2.5 - ZERO LOOK-AHEAD]", "pois_fair_under", "B365<2.5", True),
        ("5. Biased Baseline: PC>2.5 (Close) vs B365>2.5 (Open) [OVER 2.5 - LOOK-AHEAD]", "pc_fair_over", "B365>2.5", False),
        ("6. Opening Arbitrage: P>2.5 (Open) vs B365>2.5 (Open) [OVER 2.5 - ZERO LOOK-AHEAD]", "p_fair_over", "B365>2.5", False),
        ("7. Closing Arbitrage: PC>2.5 (Close) vs B365C>2.5 (Close) [OVER 2.5 - ZERO LOOK-AHEAD]", "pc_fair_over", "B365C>2.5", False),
        ("8. Pure Pre-Match Poisson vs B365>2.5 (Open) [OVER 2.5 - ZERO LOOK-AHEAD]", "pois_fair_over", "B365>2.5", False),
    ]
    part1_ou_results = []
    for label, p_col, b_col, is_un in audit_ou_variants:
        bets = evaluate_ou_strategy(big5_t1_df, p_col, b_col, is_under=is_un)
        st = calc_stats(bets)
        st["variant"] = label
        part1_ou_results.append(st)
        print(
            f"{label:88s} | Bets={st['bets']:4d} | Hit={st['hit_rate']:5.1f}% | "
            f"PnL={st['pnl']:+7.2f}u | ROI={st['roi']:+6.2f}% | t={st['t_stat']:+5.2f}"
        )

    # =========================================================================
    # PART 2: ALL 17 LEAGUES EXPANSION — LEAGUE BY LEAGUE COMPARISON
    # =========================================================================
    print("\n" + "=" * 95)
    print("PART 2: ALL 17 LEAGUES (BIG 5 + T1 + 11 SECONDARY) — DRAW & UNDER 2.5 ACROSS METHODS")
    print("=" * 95)

    league_rows = []
    for code in LEAGUE_META:
        ldf = full_df[full_df["div"] == code]
        lname, tier = LEAGUE_META[code]
        n_matches = len(ldf)
        draw_rate = float((ldf["FTR"] == "D").mean() * 100.0) if n_matches else 0.0
        under_rate = float((ldf["total_goals"] < 2.5).mean() * 100.0) if n_matches else 0.0

        d_biased = calc_stats(evaluate_1x2_strategy(ldf, "psc_fair", "B365", "D"))
        d_open_arb = calc_stats(evaluate_1x2_strategy(ldf, "ps_fair", "B365", "D"))
        d_close_arb = calc_stats(evaluate_1x2_strategy(ldf, "psc_fair", "B365C", "D"))
        d_prematch = calc_stats(evaluate_1x2_strategy(ldf, "hist_fair_D", "B365", "D"))

        u_biased = calc_stats(evaluate_ou_strategy(ldf, "pc_fair_under", "B365<2.5", is_under=True))
        u_open_arb = calc_stats(evaluate_ou_strategy(ldf, "p_fair_under", "B365<2.5", is_under=True))
        u_close_arb = calc_stats(evaluate_ou_strategy(ldf, "pc_fair_under", "B365C<2.5", is_under=True))
        u_prematch = calc_stats(evaluate_ou_strategy(ldf, "pois_fair_under", "B365<2.5", is_under=True))

        row_dict = {
            "code": code,
            "league": lname,
            "tier": tier,
            "matches": n_matches,
            "base_draw_pct": round(draw_rate, 1),
            "base_under_pct": round(under_rate, 1),
            "d_biased": d_biased,
            "d_open_arb": d_open_arb,
            "d_close_arb": d_close_arb,
            "d_prematch": d_prematch,
            "u_biased": u_biased,
            "u_open_arb": u_open_arb,
            "u_close_arb": u_close_arb,
            "u_prematch": u_prematch,
        }
        league_rows.append(row_dict)
        print(
            f"{code:4s} ({lname:23s}) | Matches={n_matches:4d} | "
            f"Draw[Biased: {d_biased['bets']:3d}b/{d_biased['roi']:+6.1f}% | OpenArb: {d_open_arb['bets']:3d}b/{d_open_arb['roi']:+6.1f}% | CloseArb: {d_close_arb['bets']:3d}b/{d_close_arb['roi']:+6.1f}% | PreMatch: {d_prematch['bets']:3d}b/{d_prematch['roi']:+6.1f}%]"
        )

    tier_summaries = {}
    for tier_label, subset_df in [
        ("Big 5 Leagues (5 Lig)", big5_df),
        ("Secondary European Leagues (11 İkincil Lig)", sec_df),
        ("All 17 European Leagues (Tüm 17 Lig)", full_df),
    ]:
        tier_summaries[tier_label] = {
            "matches": len(subset_df),
            "draw_biased": calc_stats(evaluate_1x2_strategy(subset_df, "psc_fair", "B365", "D")),
            "draw_open_arb": calc_stats(evaluate_1x2_strategy(subset_df, "ps_fair", "B365", "D")),
            "draw_close_arb": calc_stats(evaluate_1x2_strategy(subset_df, "psc_fair", "B365C", "D")),
            "draw_prematch_pois": calc_stats(evaluate_1x2_strategy(subset_df, "pois_fair", "B365", "D")),
            "draw_prematch_blend": calc_stats(evaluate_1x2_strategy(subset_df, "hist_fair_D", "B365", "D")),
            "under_biased": calc_stats(evaluate_ou_strategy(subset_df, "pc_fair_under", "B365<2.5", True)),
            "under_open_arb": calc_stats(evaluate_ou_strategy(subset_df, "p_fair_under", "B365<2.5", True)),
            "under_close_arb": calc_stats(evaluate_ou_strategy(subset_df, "pc_fair_under", "B365C<2.5", True)),
            "under_prematch_pois": calc_stats(evaluate_ou_strategy(subset_df, "pois_fair_under", "B365<2.5", True)),
            "over_biased": calc_stats(evaluate_ou_strategy(subset_df, "pc_fair_over", "B365>2.5", False)),
            "over_open_arb": calc_stats(evaluate_ou_strategy(subset_df, "p_fair_over", "B365>2.5", False)),
            "over_close_arb": calc_stats(evaluate_ou_strategy(subset_df, "pc_fair_over", "B365C>2.5", False)),
            "over_prematch_pois": calc_stats(evaluate_ou_strategy(subset_df, "pois_fair_over", "B365>2.5", False)),
        }

    season_stability = {}
    for strat_key, strat_fn in [
        ("draw_biased", lambda d: evaluate_1x2_strategy(d, "psc_fair", "B365", "D")),
        ("draw_open_arb", lambda d: evaluate_1x2_strategy(d, "ps_fair", "B365", "D")),
        ("draw_close_arb", lambda d: evaluate_1x2_strategy(d, "psc_fair", "B365C", "D")),
        ("draw_prematch_blend", lambda d: evaluate_1x2_strategy(d, "hist_fair_D", "B365", "D")),
        ("under_biased", lambda d: evaluate_ou_strategy(d, "pc_fair_under", "B365<2.5", True)),
        ("under_open_arb", lambda d: evaluate_ou_strategy(d, "p_fair_under", "B365<2.5", True)),
        ("under_close_arb", lambda d: evaluate_ou_strategy(d, "pc_fair_under", "B365C<2.5", True)),
        ("under_prematch_pois", lambda d: evaluate_ou_strategy(d, "pois_fair_under", "B365<2.5", True)),
    ]:
        s_list = []
        for s_name, sdf in full_df.groupby("season"):
            st = calc_stats(strat_fn(sdf))
            st["season"] = s_name
            s_list.append(st)
        season_stability[strat_key] = s_list

    summary_payload = {
        "total_matches": len(full_df),
        "total_leagues": full_df["div"].nunique(),
        "steam_diagnostic": {
            "qualified_draw_bets": len(wf_draw_with_open),
            "psc_shortened_pct": round(steam_shortened_pct, 2),
            "avg_ps_open": round(avg_ps_open, 3),
            "avg_ps_close": round(avg_ps_close, 3),
            "avg_b365_open": round(avg_b365_open, 3),
            "avg_b365_close": round(avg_b365_close, 3),
            "pnl_at_b365_close": round(pnl_same_matches_at_close, 2),
            "roi_at_b365_close": round(roi_same_matches_at_close, 2),
            "all17_qualified_draw_bets": len(all_draw_open),
            "all17_psc_shortened_pct": round(all_steam_pct, 2),
            "all17_pnl_at_b365_close": round(all_pnl_at_close, 2),
            "all17_roi_at_b365_close": round(all_roi_at_close, 2),
        },
        "part1_draw_results": part1_draw_results,
        "part1_ou_results": part1_ou_results,
        "league_rows": league_rows,
        "tier_summaries": tier_summaries,
        "season_stability": season_stability,
    }
    json_out = OUTPUT_DIR / "overnight_quant_audit_summary.json"
    json_out.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved full audit JSON payload to: {json_out}")


if __name__ == "__main__":
    run_audit()
