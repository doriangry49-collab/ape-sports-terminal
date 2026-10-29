"""CLI Formatter and terminal display for Live Prediction Product."""

from __future__ import annotations

from typing import Any


def print_prediction_product_dashboard(payload: dict[str, Any]) -> None:
    """Print high-fidelity, human-readable terminal dashboard conforming to TASK-019."""
    summary = payload.get("summary", {})
    preds = payload.get("predictions", [])
    insufficient = payload.get("insufficient_history_events", [])
    val_cands = payload.get("value_candidates", [])
    high_odds = payload.get("high_odds_candidates", [])
    meta = payload.get("model_metadata", {})

    print("\n" + "=" * 92)
    print(" 🏆 SPORTS INTELLIGENCE ENGINE — LIVE PREDICTION PRODUCT (TASK-019)")
    print(f" Run ID:          {payload.get('run_id')} | Generated: {payload.get('generated_at')}")
    print(f" Active Model:    {meta.get('model_name')} (v{meta.get('model_version')})")
    print(f" Rating Version:  {meta.get('rating_version')} [decay: 180d, shrinkage: k=3]")
    print(f" Zero-Cost Mode:  ACTIVE | Historical Blocker: DEPRECATED | Paid Backfill: NONE")
    print("=" * 92)

    # 1. Provider Status
    provs = summary.get("providers", {})
    print("\n[LIVE PROVIDERS STATUS]")
    for p_name, p_stat in provs.items():
        status_symbol = "✅" if p_stat == "AVAILABLE" else "⚠️"
        print(f"  {status_symbol} {p_name.upper():<12} -> {p_stat}")

    # 2. Executive Metrics
    print("\n[EXECUTIVE SUMMARY METRICS]")
    print(f"  • Total Matches Scanned:          {summary.get('total_events_scanned')}")
    print(f"  • Matches with Real Odds:         {summary.get('matches_with_real_odds')}")
    print(f"  • Model C Available Matches:      {summary.get('model_c_available_matches')} (History >= 30 matches)")
    print(f"  • Insufficient History Matches:   {summary.get('insufficient_history_matches')} (Model C Skipped; No Silent Baseline)")
    print(f"  • Unique Bookmakers Represented:  {summary.get('unique_bookmakers_count')}")
    print(f"  • Unique Betting Markets:         {summary.get('unique_markets_count')}")
    print(f"  • Total Selections Evaluated:     {summary.get('total_evaluated_selections')}")
    print(f"  • Positive-EV Candidates:         {summary.get('total_positive_ev_candidates')}")
    print(f"  • High-Odds (>=2.0) Candidates:   {summary.get('total_high_odds_candidates')}")
    print(f"  • Correct Score High-Odds:        {summary.get('correct_score_high_odds_count')} (Pos EV: {summary.get('correct_score_pos_ev_count')})")

    # 3. Odds Band Breakdown
    bands = summary.get("odds_bands_distribution", {})
    print("\n[HIGH-ODDS BANDS DISTRIBUTION (REAL BOOKMAKER ODDS)]")
    band_row = " | ".join(f"{b}: {cnt}" for b, cnt in bands.items())
    print(f"  {band_row}")

    # 4. Model C Match Predictions
    print("\n" + "-" * 92)
    print(" 📊 MODEL C MATCH RATINGS & FAIR 1X2 EXPECTANCY")
    print("-" * 92)
    header_m = f"{'FIXTURE':<34} | {'COMPETITION':<20} | {'xG (H-A)':<10} | {'MODEL 1X2 PROB (H/D/A)'}"
    print(header_m)
    print("-" * 92)

    for p in preds:
        fix = p["fixture"][:32]
        comp = p["competition"][:18]
        xg = f"{p['expected_goals']['home']:.2f}-{p['expected_goals']['away']:.2f}"
        probs = p.get("1x2_probabilities", {})
        ph = probs.get("HOME", 0) * 100
        pd = probs.get("DRAW", 0) * 100
        pa = probs.get("AWAY", 0) * 100
        p_str = f"H:{ph:>4.1f}% D:{pd:>4.1f}% A:{pa:>4.1f}%"
        print(f"{fix:<34} | {comp:<20} | {xg:<10} | {p_str}")

    # 5. Insufficient History Matches
    if insufficient:
        print("\n" + "-" * 92)
        print(" ⚠️ DISCOVERED MATCHES WITH INSUFFICIENT HISTORY (MODEL C GUARD)")
        print("-" * 92)
        for ie in insufficient[:6]:
            print(f"  • {ie['match']} ({ie['competition']}) -> Status: {ie['model_status']} (Odds Available: {ie['odds_available']})")

    # 6. Value Candidates Table (Positive EV)
    print("\n" + "=" * 92)
    print(" 💎 VALUE CANDIDATES & MODEL EDGES (EV > 0%)")
    print(" Note: Labeled strictly as VALUE CANDIDATE. Never 'Guaranteed' or 'Winner'.")
    print("=" * 92)
    val_header = f"{'MATCH':<24} | {'MARKET':<14} | {'SEL':<8} | {'BOOKMAKER':<10} | {'ODDS':<6} | {'FAIR':<6} | {'EV %':<8} | {'CLASS'}"
    print(val_header)
    print("-" * 92)

    for v in val_cands[:12]:
        m_str = v["match"][:22]
        mkt = v["market"][:12]
        sel = v["selection"][:6]
        bm = v["bookmaker"][:9]
        odds = f"{v['bookmaker_odds']:.2f}"
        fair = f"{v['model_fair_odds']:.2f}"
        ev = f"+{v['expected_value_percent']:.1f}%"
        cls_str = "VALUE" if "VALUE" in v["candidate_classification"] else "SPECULATIVE"
        print(f"{m_str:<24} | {mkt:<14} | {sel:<8} | {bm:<10} | {odds:<6} | {fair:<6} | {ev:<8} | {cls_str}")

    # 7. Correct Score High-Odds Scanner
    cs_high = [h for h in high_odds if h["market"] == "CORRECT_SCORE"]
    print("\n" + "=" * 92)
    print(" 🎯 CORRECT SCORE HIGH-ODDS SCANNER (TIERED DISCOVERY)")
    print("=" * 92)
    cs_header = f"{'MATCH':<24} | {'SCORE':<7} | {'BOOKMAKER':<10} | {'ODDS':<6} | {'MODEL PROB':<10} | {'FAIR':<6} | {'EV %':<8} | {'TIER'}"
    print(cs_header)
    print("-" * 92)

    for c in cs_high[:10]:
        m_str = c["match"][:22]
        sel = c["selection"][:5]
        bm = c["bookmaker"][:9]
        odds = f"{c['bookmaker_odds']:.2f}"
        prob = f"{c['model_probability']*100:.2f}%"
        fair = f"{c['model_fair_odds']:.2f}"
        ev_sign = "+" if c["expected_value_percent"] >= 0 else ""
        ev = f"{ev_sign}{c['expected_value_percent']:.1f}%"
        tier = c["odds_band"]
        print(f"{m_str:<24} | {sel:<7} | {bm:<10} | {odds:<6} | {prob:<10} | {fair:<6} | {ev:<8} | {tier}")

    # 8. Artifacts Footprint
    print("\n" + "=" * 92)
    print(" 💾 IMMUTABLE PREDICTION ARTIFACTS PERSISTED")
    print(f"  • Predictions:    artifacts/predictions/TASK-019/predictions.json")
    print(f"  • Odds Snapshot:  artifacts/predictions/TASK-019/odds_snapshot.json")
    print(f"  • Model Metadata: artifacts/predictions/TASK-019/model_metadata.json")
    print(f"  • Immutable Run:  artifacts/predictions/TASK-019/{payload.get('run_id')}/predictions.json")
    print(f"  • Odds Archive:   artifacts/odds/historical/ (auto-appended SELF_CAPTURED)")
    print("=" * 92 + "\n")
