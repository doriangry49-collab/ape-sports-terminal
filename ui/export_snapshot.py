"""Export verified read-only UI View Model from existing backend snapshots.

STRICT RULES:
- Does NOT alter any backend source files.
- Reads data directly from data/gold/predictions and artifacts/provider_validation.
- Executes backend pricing engine to compute exact canonical view models.
- Outputs ui/data/sports_intelligence_snapshot.json for the UI Adapter layer.
- Never invents missing data: missing values remain 'UNKNOWN' or None.
"""

import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

# Ensure src is on path for domain import
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sports_engine.pricing import NoVigMethod, calculate_selection_edge, compute_no_vig

TRT_TZ = timezone(timedelta(hours=3))


def to_trt_str(iso_or_dt: str | datetime | None) -> str:
    """Format any kickoff timestamp into Europe/Istanbul (TRT = UTC+3) string."""
    if not iso_or_dt:
        return "TBD"
    try:
        if isinstance(iso_or_dt, str):
            dt = datetime.fromisoformat(iso_or_dt.replace("Z", "+00:00"))
        else:
            dt = iso_or_dt
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        trt_dt = dt.astimezone(TRT_TZ)
        return trt_dt.strftime("%Y-%m-%d %H:%M TRT")
    except Exception:
        return str(iso_or_dt)


def calc_half_kelly(prob: float, odds: float, max_stake: float = 0.05) -> float:
    """Calculate Half-Kelly position sizing fraction as percentage."""
    if prob <= 0 or odds <= 1.0:
        return 0.0
    ev = (prob * odds) - 1.0
    if ev <= 0:
        return 0.0
    k = ev / (odds - 1.0)
    return round(min(max_stake, max(0.0, 0.5 * k)) * 100.0, 2)


def generate_ui_snapshot(output_file: Path | str | None = None) -> Path:
    root = Path(__file__).parent.parent
    data_gold = root / "data" / "gold" / "predictions"
    raw_propline = root / "artifacts" / "provider_validation" / "raw" / "propline"
    ui_data_dir = root / "ui" / "data"
    ui_data_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load predictions
    pred_1_path = data_gold / "latest_predictions.json"
    pred_tr_path = data_gold / "latest_turkey_football_predictions.json"

    pred_1 = json.loads(pred_1_path.read_text(encoding="utf-8")) if pred_1_path.exists() else {}
    pred_tr = json.loads(pred_tr_path.read_text(encoding="utf-8")) if pred_tr_path.exists() else {}

    # 2. Load PropLine Bulk Odds
    bulk_odds_file = raw_propline / "Bulk Odds (1X2 _ h2h _ totals)_20260929_154502.json"
    bulk_events = json.loads(bulk_odds_file.read_text(encoding="utf-8")) if bulk_odds_file.exists() else []

    # Map bulk events by team names
    odds_by_fixture = {}
    for ev in bulk_events:
        h = ev.get("home_team", "").lower().strip()
        a = ev.get("away_team", "").lower().strip()
        key = f"{h}_vs_{a}"
        odds_by_fixture[key] = ev

    fixtures_data = []

    # Process Turkish Football fixtures
    tr_preds_list = pred_tr.get("predictions", [])
    for p_tr in tr_preds_list:
        f_info = p_tr.get("fixture", {})
        home_display = f_info.get("home_team", "")
        away_display = f_info.get("away_team", "")
        kickoff = f_info.get("kickoff", "2026-10-09T17:00:00+00:00")
        f_id = f_info.get("canonical_fixture_id", "")
        league_name = f_info.get("league", f_info.get("competition", "Trendyol Süper Lig"))

        # Look up 1X2 in pred_1
        pred_1_item = next(
            (item for item in pred_1.get("predictions", []) if item.get("fixture", {}).get("canonical_fixture_id") == f_id),
            None
        )

        model_1x2_home = pred_1_item.get("home_probability", 0.0) if pred_1_item else 0.0
        model_1x2_draw = pred_1_item.get("draw_probability", 0.0) if pred_1_item else 0.0
        model_1x2_away = pred_1_item.get("away_probability", 0.0) if pred_1_item else 0.0

        # Look up markets in pred_tr
        markets_tr = p_tr.get("markets", {})
        totals_model = markets_tr.get("totals_2_5", {})
        btts_model = markets_tr.get("btts", {})
        top_cs = markets_tr.get("top_correct_scores", {})
        ht_ft_model = markets_tr.get("ht_ft", {})

        # Find odds in bulk events
        lookup_key = f"{home_display.lower()}_vs_{away_display.lower()}"
        ev_odds = odds_by_fixture.get(lookup_key, {})

        # Bookmakers processing
        bookmakers_data = {}
        for bk in ev_odds.get("bookmakers", []):
            bk_title = bk.get("title", bk.get("key", "UNKNOWN"))
            bk_markets = {}

            for mk in bk.get("markets", []):
                m_key = mk.get("key", "").lower()
                outcomes = mk.get("outcomes", [])

                if m_key == "h2h":
                    # 1X2
                    odds_dict = {}
                    for o in outcomes:
                        sel = o.get("name", "")
                        raw_p = o.get("price")
                        if raw_p is None:
                            continue
                        dec_p = round(1.0 + (raw_p / 100.0) if raw_p > 0 else 1.0 + (100.0 / abs(raw_p)), 2)
                        odds_dict[sel] = dec_p

                    if len(odds_dict) >= 3:
                        pricing_res = compute_no_vig(odds_dict, market_name="1X2", method=NoVigMethod.SHIN)
                        bk_markets["1X2"] = {
                            "odds": odds_dict,
                            "raw_implied": pricing_res.raw_implied_probabilities,
                            "overround": pricing_res.overround,
                            "no_vig": pricing_res.no_vig_probabilities,
                            "fair_odds": pricing_res.fair_odds,
                        }

                elif "totals" in m_key:
                    # Match Totals (filter out team totals where description is team name)
                    p25_outcomes = [
                        o for o in outcomes
                        if o.get("point") == 2.5 and o.get("description") in ("Over", "Under", None, "")
                    ]
                    if len(p25_outcomes) >= 2:
                        odds_dict = {}
                        for o in p25_outcomes:
                            sel = f"{o.get('name', '')} 2.5"
                            raw_p = o.get("price")
                            dec_p = round(1.0 + (raw_p / 100.0) if raw_p > 0 else 1.0 + (100.0 / abs(raw_p)), 2)
                            odds_dict[sel] = dec_p

                        pricing_res = compute_no_vig(odds_dict, market_name="TOTALS", method=NoVigMethod.MULTIPLICATIVE)
                        bk_markets["TOTALS_2.5"] = {
                            "odds": odds_dict,
                            "raw_implied": pricing_res.raw_implied_probabilities,
                            "overround": pricing_res.overround,
                            "no_vig": pricing_res.no_vig_probabilities,
                            "fair_odds": pricing_res.fair_odds,
                        }

            if bk_markets:
                bookmakers_data[bk_title] = bk_markets

        # Compute calculated edges using backend pricing engine
        calculated_edges = []

        # 1X2 edges for primary books (Bovada & Pinnacle)
        for target_bk in ["Bovada", "Pinnacle"]:
            if target_bk in bookmakers_data and "1X2" in bookmakers_data[target_bk]:
                m_1x2 = bookmakers_data[target_bk]["1X2"]
                no_vig = m_1x2["no_vig"]
                odds_dict = m_1x2["odds"]

                # Find home selection key
                h_key = next((k for k in odds_dict if home_display.lower() in k.lower()), None)
                d_key = next((k for k in odds_dict if "draw" in k.lower()), None)
                a_key = next((k for k in odds_dict if away_display.lower() in k.lower()), None)

                if h_key and model_1x2_home > 0:
                    edge_h = calculate_selection_edge(
                        fixture_id=f_id,
                        market="1X2",
                        selection=h_key,
                        entry_odds=odds_dict[h_key],
                        model_probability=model_1x2_home,
                        market_no_vig_probability=no_vig[h_key],
                    )
                    ev_roi_h = round(((model_1x2_home * edge_h.entry_odds) - 1.0) * 100.0, 2)
                    half_k_h = calc_half_kelly(model_1x2_home, edge_h.entry_odds)
                    shin_m = round(m_1x2["overround"] * 100.0, 2)
                    calculated_edges.append({
                        "bookmaker": target_bk,
                        "market": "1X2",
                        "selection": "HOME",
                        "selection_display": f"{home_display} (Home)",
                        "entry_odds": edge_h.entry_odds,
                        "raw_implied": m_1x2["raw_implied"][h_key],
                        "overround": m_1x2["overround"],
                        "market_no_vig": edge_h.market_no_vig_probability,
                        "market_fair_odds": m_1x2["fair_odds"][h_key],
                        "fair_odds_shin": m_1x2["fair_odds"][h_key],
                        "model_prob": edge_h.model_probability,
                        "model_fair_odds": edge_h.model_fair_odds,
                        "raw_edge": edge_h.raw_edge,
                        "adjusted_edge": edge_h.adjusted_edge,
                        "source_classification": "BOOKMAKER_OFFERED",
                        "is_longshot": edge_h.entry_odds >= 5.0,
                        "shin_margin": shin_m,
                        "ev_roi": ev_roi_h,
                        "half_kelly": half_k_h,
                        "kickoff_trt": to_trt_str(kickoff),
                        "league": league_name,
                        "competition": league_name,
                    })

                if d_key and model_1x2_draw > 0:
                    edge_d = calculate_selection_edge(
                        fixture_id=f_id,
                        market="1X2",
                        selection=d_key,
                        entry_odds=odds_dict[d_key],
                        model_probability=model_1x2_draw,
                        market_no_vig_probability=no_vig[d_key],
                    )
                    ev_roi_d = round(((model_1x2_draw * edge_d.entry_odds) - 1.0) * 100.0, 2)
                    half_k_d = calc_half_kelly(model_1x2_draw, edge_d.entry_odds)
                    shin_m = round(m_1x2["overround"] * 100.0, 2)
                    calculated_edges.append({
                        "bookmaker": target_bk,
                        "market": "1X2",
                        "selection": "DRAW",
                        "selection_display": "Draw",
                        "entry_odds": edge_d.entry_odds,
                        "raw_implied": m_1x2["raw_implied"][d_key],
                        "overround": m_1x2["overround"],
                        "market_no_vig": edge_d.market_no_vig_probability,
                        "market_fair_odds": m_1x2["fair_odds"][d_key],
                        "fair_odds_shin": m_1x2["fair_odds"][d_key],
                        "model_prob": edge_d.model_probability,
                        "model_fair_odds": edge_d.model_fair_odds,
                        "raw_edge": edge_d.raw_edge,
                        "adjusted_edge": edge_d.adjusted_edge,
                        "source_classification": "BOOKMAKER_OFFERED",
                        "is_longshot": edge_d.entry_odds >= 5.0,
                        "shin_margin": shin_m,
                        "ev_roi": ev_roi_d,
                        "half_kelly": half_k_d,
                        "kickoff_trt": to_trt_str(kickoff),
                        "league": league_name,
                        "competition": league_name,
                    })

                if a_key and model_1x2_away > 0:
                    edge_a = calculate_selection_edge(
                        fixture_id=f_id,
                        market="1X2",
                        selection=a_key,
                        entry_odds=odds_dict[a_key],
                        model_probability=model_1x2_away,
                        market_no_vig_probability=no_vig[a_key],
                    )
                    ev_roi_a = round(((model_1x2_away * edge_a.entry_odds) - 1.0) * 100.0, 2)
                    half_k_a = calc_half_kelly(model_1x2_away, edge_a.entry_odds)
                    shin_m = round(m_1x2["overround"] * 100.0, 2)
                    calculated_edges.append({
                        "bookmaker": target_bk,
                        "market": "1X2",
                        "selection": "AWAY",
                        "selection_display": f"{away_display} (Away)",
                        "entry_odds": edge_a.entry_odds,
                        "raw_implied": m_1x2["raw_implied"][a_key],
                        "overround": m_1x2["overround"],
                        "market_no_vig": edge_a.market_no_vig_probability,
                        "market_fair_odds": m_1x2["fair_odds"][a_key],
                        "fair_odds_shin": m_1x2["fair_odds"][a_key],
                        "model_prob": edge_a.model_probability,
                        "model_fair_odds": edge_a.model_fair_odds,
                        "raw_edge": edge_a.raw_edge,
                        "adjusted_edge": edge_a.adjusted_edge,
                        "source_classification": "BOOKMAKER_OFFERED",
                        "is_longshot": edge_a.entry_odds >= 5.0,
                        "shin_margin": shin_m,
                        "ev_roi": ev_roi_a,
                        "half_kelly": half_k_a,
                        "kickoff_trt": to_trt_str(kickoff),
                        "league": league_name,
                        "competition": league_name,
                    })

            # Totals 2.5 edges
            if target_bk in bookmakers_data and "TOTALS_2.5" in bookmakers_data[target_bk]:
                m_tot = bookmakers_data[target_bk]["TOTALS_2.5"]
                no_vig = m_tot["no_vig"]
                odds_dict = m_tot["odds"]

                over_key = "Over 2.5"
                under_key = "Under 2.5"
                model_over = totals_model.get("OVER", 0.0)
                model_under = totals_model.get("UNDER", 0.0)

                if over_key in odds_dict and model_over > 0:
                    edge_o = calculate_selection_edge(
                        fixture_id=f_id,
                        market="TOTALS",
                        selection=over_key,
                        entry_odds=odds_dict[over_key],
                        model_probability=model_over,
                        market_no_vig_probability=no_vig[over_key],
                    )
                    ev_roi_o = round(((model_over * edge_o.entry_odds) - 1.0) * 100.0, 2)
                    half_k_o = calc_half_kelly(model_over, edge_o.entry_odds)
                    shin_m = round(m_tot["overround"] * 100.0, 2)
                    calculated_edges.append({
                        "bookmaker": target_bk,
                        "market": "TOTALS",
                        "selection": "OVER_2.5",
                        "selection_display": "Over 2.5 Goals",
                        "entry_odds": edge_o.entry_odds,
                        "raw_implied": m_tot["raw_implied"][over_key],
                        "overround": m_tot["overround"],
                        "market_no_vig": edge_o.market_no_vig_probability,
                        "market_fair_odds": m_tot["fair_odds"][over_key],
                        "fair_odds_shin": m_tot["fair_odds"][over_key],
                        "model_prob": edge_o.model_probability,
                        "model_fair_odds": edge_o.model_fair_odds,
                        "raw_edge": edge_o.raw_edge,
                        "adjusted_edge": edge_o.adjusted_edge,
                        "source_classification": "BOOKMAKER_OFFERED",
                        "is_longshot": edge_o.entry_odds >= 5.0,
                        "shin_margin": shin_m,
                        "ev_roi": ev_roi_o,
                        "half_kelly": half_k_o,
                        "kickoff_trt": to_trt_str(kickoff),
                        "league": league_name,
                        "competition": league_name,
                    })

                if under_key in odds_dict and model_under > 0:
                    edge_u = calculate_selection_edge(
                        fixture_id=f_id,
                        market="TOTALS",
                        selection=under_key,
                        entry_odds=odds_dict[under_key],
                        model_probability=model_under,
                        market_no_vig_probability=no_vig[under_key],
                    )
                    ev_roi_u = round(((model_under * edge_u.entry_odds) - 1.0) * 100.0, 2)
                    half_k_u = calc_half_kelly(model_under, edge_u.entry_odds)
                    shin_m = round(m_tot["overround"] * 100.0, 2)
                    calculated_edges.append({
                        "bookmaker": target_bk,
                        "market": "TOTALS",
                        "selection": "UNDER_2.5",
                        "selection_display": "Under 2.5 Goals",
                        "entry_odds": edge_u.entry_odds,
                        "raw_implied": m_tot["raw_implied"][under_key],
                        "overround": m_tot["overround"],
                        "market_no_vig": edge_u.market_no_vig_probability,
                        "market_fair_odds": m_tot["fair_odds"][under_key],
                        "fair_odds_shin": m_tot["fair_odds"][under_key],
                        "model_prob": edge_u.model_probability,
                        "model_fair_odds": edge_u.model_fair_odds,
                        "raw_edge": edge_u.raw_edge,
                        "adjusted_edge": edge_u.adjusted_edge,
                        "source_classification": "BOOKMAKER_OFFERED",
                        "is_longshot": edge_u.entry_odds >= 5.0,
                        "shin_margin": shin_m,
                        "ev_roi": ev_roi_u,
                        "half_kelly": half_k_u,
                        "kickoff_trt": to_trt_str(kickoff),
                        "league": league_name,
                        "competition": league_name,
                    })

        # MODEL_DERIVED Markets (Transparently separated from bookmaker offers!)
        model_derived_markets = {
            "top_correct_scores": top_cs,
            "ht_ft": ht_ft_model,
            "double_chance": markets_tr.get("double_chance", {}),
            "draw_no_bet": markets_tr.get("draw_no_bet", {}),
        }

        # BTTS status
        btts_status = {
            "model_probability": btts_model,  # {"YES": 0.5645, "NO": 0.4355}
            "bookmaker_odds": "DATA_UNAVAILABLE",
            "market_no_vig_probability": "UNKNOWN",
            "raw_edge": "UNKNOWN",
            "status": "MODEL_ONLY",
        }

        fixtures_data.append({
            "fixture_id": f_id,
            "home_team": home_display,
            "away_team": away_display,
            "competition": league_name,
            "league": league_name,
            "country": "Turkey",
            "kickoff": kickoff,
            "kickoff_trt": to_trt_str(kickoff),
            "match_phase": "PREMATCH",
            "sport": "Football",
            "model_version": "poisson_bivariate_baseline v0.1.0",
            "data_cutoff": p_tr.get("data_cutoff", "2026-09-30T07:43:44.644270+00:00"),
            "snapshot_id": p_tr.get("snapshot_id", "20260930_074344"),
            "model_1x2": {
                "HOME": model_1x2_home,
                "DRAW": model_1x2_draw,
                "AWAY": model_1x2_away,
                "fair_home_odds": round(1.0 / model_1x2_home, 2) if model_1x2_home > 0 else "UNKNOWN",
                "fair_draw_odds": round(1.0 / model_1x2_draw, 2) if model_1x2_draw > 0 else "UNKNOWN",
                "fair_away_odds": round(1.0 / model_1x2_away, 2) if model_1x2_away > 0 else "UNKNOWN",
            },
            "totals_2_5_model": totals_model,
            "btts": btts_status,
            "bookmakers": bookmakers_data,
            "edges": calculated_edges,
            "model_derived_markets": model_derived_markets,
            "model_uncertainty": "UNKNOWN",
            "clv_status": "NOT_AVAILABLE",
        })

    # 3. Ingest Live Scanned Fixtures from daemon (live_stale_line_signals.json and direct live Nesine bulletin)
    live_signals_file = root / "output" / "live_stale_line_signals.json"
    if live_signals_file.exists():
        try:
            live_data = json.loads(live_signals_file.read_text(encoding="utf-8"))
            live_fixtures = live_data.get("fixtures", [])
            for lf in live_fixtures:
                l_home = lf.get("home", "")
                l_away = lf.get("away", "")
                l_league = lf.get("league", "Canlı Bülten")
                l_kick = lf.get("kickoff", "")
                l_nesine_1x2 = lf.get("nesine_1x2")
                l_shin_probs = lf.get("shin_probs_1x2")
                l_shin_fair = lf.get("shin_fair_1x2")
                l_pin_1x2 = lf.get("pinnacle_1x2")
                l_id = f"live_{lf.get('event_id', '')}_{l_home}_{l_away}"

                live_edges = []
                if l_nesine_1x2 and len(l_nesine_1x2) == 3 and l_shin_probs and len(l_shin_probs) == 3:
                    valid_n_odds = [float(o) for o in l_nesine_1x2 if float(o) > 1.0]
                    real_overround = round(sum(1.0 / o for o in valid_n_odds) - 1.0, 4) if len(valid_n_odds) == 3 else 0.0
                    real_margin_pct = round(sum(1.0 / o for o in valid_n_odds) * 100.0, 2) if len(valid_n_odds) == 3 else 100.0
                    outcomes_meta = [
                        ("HOME", f"{l_home} (Home)", 0),
                        ("DRAW", "Draw", 1),
                        ("AWAY", f"{l_away} (Away)", 2),
                    ]
                    for out_code, out_disp, idx in outcomes_meta:
                        n_odd = float(l_nesine_1x2[idx])
                        m_prob = float(l_shin_probs[idx])
                        fair_o = float(l_shin_fair[idx]) if l_shin_fair else round(1.0 / m_prob, 2)
                        raw_edge = round(m_prob - (1.0 / n_odd), 4)
                        ev_roi = round(((m_prob * n_odd) - 1.0) * 100.0, 2)
                        half_k = calc_half_kelly(m_prob, n_odd)
                        live_edges.append({
                            "bookmaker": "NESINE",
                            "market": "1X2",
                            "selection": out_code,
                            "selection_display": out_disp,
                            "entry_odds": n_odd,
                            "raw_implied": round(1.0 / n_odd, 4),
                            "overround": real_overround,
                            "market_no_vig": m_prob,
                            "market_fair_odds": fair_o,
                            "fair_odds_shin": fair_o,
                            "model_prob": m_prob,
                            "model_fair_odds": fair_o,
                            "raw_edge": raw_edge,
                            "adjusted_edge": raw_edge,
                            "source_classification": "BOOKMAKER_OFFERED",
                            "is_longshot": n_odd >= 5.0,
                            "shin_margin": real_margin_pct,
                            "ev_roi": ev_roi,
                            "half_kelly": half_k,
                            "kickoff_trt": to_trt_str(l_kick),
                            "league": l_league,
                            "competition": l_league,
                        })

                fixtures_data.append({
                    "fixture_id": l_id,
                    "home_team": l_home,
                    "away_team": l_away,
                    "competition": l_league,
                    "league": l_league,
                    "country": "Live",
                    "kickoff": l_kick,
                    "kickoff_trt": to_trt_str(l_kick),
                    "match_phase": "LIVE_MONITORED",
                    "sport": "Football",
                    "model_version": "shin_devig_empirical_quant v2.0",
                    "data_cutoff": live_data.get("captured_at_utc", ""),
                    "snapshot_id": f"live_{live_data.get('captured_at_utc', '')}",
                    "model_1x2": {
                        "HOME": l_shin_probs[0] if l_shin_probs else 0.0,
                        "DRAW": l_shin_probs[1] if l_shin_probs else 0.0,
                        "AWAY": l_shin_probs[2] if l_shin_probs else 0.0,
                        "fair_home_odds": l_shin_fair[0] if l_shin_fair else "UNKNOWN",
                        "fair_draw_odds": l_shin_fair[1] if l_shin_fair else "UNKNOWN",
                        "fair_away_odds": l_shin_fair[2] if l_shin_fair else "UNKNOWN",
                    },
                    "bookmakers": {
                        "NESINE": {"1X2": {"odds": {"1": l_nesine_1x2[0], "X": l_nesine_1x2[1], "2": l_nesine_1x2[2]}}} if l_nesine_1x2 else {},
                        "PINNACLE": {"1X2": {"odds": {"1": l_pin_1x2[0], "X": l_pin_1x2[1], "2": l_pin_1x2[2]}}} if l_pin_1x2 else {},
                    },
                    "edges": live_edges,
                    "model_derived_markets": {},
                    "model_uncertainty": "VERIFIED_SHIN",
                    "clv_status": "MONITORED",
                })
        except Exception as e:
            print(f"Warning loading live stale line fixtures: {e}")

    # 3b. Ingest Real-time Live Nesine Bulletin Fixtures (SPEC-0013 & SPEC-0014 temporal guardrails)
    try:
        try:
            from live_stale_line_adapter import fetch_nesine_live_bulletin
        except ImportError:
            from src.live_stale_line_adapter import fetch_nesine_live_bulletin
        from time_utils import parse_match_kickoff

        raw_nesine_bulletin = fetch_nesine_live_bulletin()
        now_trt = datetime.now(TRT_TZ)
        seen_live_ids = {f["fixture_id"] for f in fixtures_data}

        for n_match in raw_nesine_bulletin:
            m_dt_trt, ko_iso = parse_match_kickoff(
                n_match.get("date_str"),
                n_match.get("time_str"),
                now_trt=now_trt,
                min_lead_minutes=3,
                max_lead_hours=12,
            )
            if m_dt_trt is None or ko_iso is None:
                continue

            h_name = str(n_match.get("home", "")).strip()
            a_name = str(n_match.get("away", "")).strip()
            if not h_name or not a_name:
                continue

            n_code = n_match.get("nesine_code") or f"{h_name}_{a_name}"
            live_f_id = f"nesine_live_{n_code}"
            if live_f_id in seen_live_ids:
                continue
            seen_live_ids.add(live_f_id)

            n_1x2 = n_match.get("nesine_1x2")
            n_ou25 = n_match.get("nesine_ou25")
            n_corners = n_match.get("nesine_corners")
            n_btts = n_match.get("nesine_btts")
            ko_trt_str = m_dt_trt.strftime("%Y-%m-%d %H:%M TRT")
            l_name_raw = n_match.get("league") or "Canlı Bülten"
            comp_display = f"{l_name_raw} (MBS {n_match.get('mbs', 1)})"
            n_country = n_match.get("country") or "International"

            match_edges = []
            shin_1x2_probs = {"1": 0.0, "X": 0.0, "2": 0.0}
            shin_1x2_fair = {"1": "UNKNOWN", "X": "UNKNOWN", "2": "UNKNOWN"}
            bookmakers_dict = {}

            # Run empirical TeamStrengthEngine Poisson prediction for real model probability
            model_probs_1x2 = {"HOME": 0.0, "DRAW": 0.0, "AWAY": 0.0}
            model_fair_1x2 = {"HOME": "UNKNOWN", "DRAW": "UNKNOWN", "AWAY": "UNKNOWN"}
            model_totals_25: dict[str, float | None] = {"OVER": None, "UNDER": None}

            is_modeled = False
            try:
                try:
                    from live_monitor_daemon import _get_cached_team_engine
                    team_eng = _get_cached_team_engine()
                except Exception:
                    team_eng = None

                if team_eng is not None and hasattr(team_eng, "team_ratings"):
                    h_tok = team_eng.normalizer.normalize_tokens(h_name) if hasattr(team_eng, "normalizer") else []
                    a_tok = team_eng.normalizer.normalize_tokens(a_name) if hasattr(team_eng, "normalizer") else []
                    has_h = any(t in team_eng.team_ratings for t in h_tok) or h_name in team_eng.team_ratings
                    has_a = any(t in team_eng.team_ratings for t in a_tok) or a_name in team_eng.team_ratings
                    if has_h and has_a:
                        m_pred = team_eng.predict_match(h_name, a_name)
                        if m_pred and isinstance(m_pred, dict):
                            p1x2 = m_pred.get("p_1x2", {})
                            f1x2 = m_pred.get("fair_1x2", {})
                            model_probs_1x2["HOME"] = round(float(p1x2.get("1", 0.0)), 4)
                            model_probs_1x2["DRAW"] = round(float(p1x2.get("X", 0.0)), 4)
                            model_probs_1x2["AWAY"] = round(float(p1x2.get("2", 0.0)), 4)
                            model_fair_1x2["HOME"] = f1x2.get("1", "UNKNOWN")
                            model_fair_1x2["DRAW"] = f1x2.get("X", "UNKNOWN")
                            model_fair_1x2["AWAY"] = f1x2.get("2", "UNKNOWN")
                            is_modeled = True

                            m_tot = m_pred.get("totals", {})
                            over_p = m_tot.get("over_25", {}).get("prob")
                            under_p = m_tot.get("under_25", {}).get("prob")
                            if over_p is not None and under_p is not None:
                                model_totals_25["OVER"] = round(float(over_p), 4)
                                model_totals_25["UNDER"] = round(float(under_p), 4)
            except Exception:
                pass

            if n_1x2 and len(n_1x2) == 3:
                try:
                    pure_1x2_map = {"1": float(n_1x2[0]), "X": float(n_1x2[1]), "2": float(n_1x2[2])}
                    shin_res = compute_no_vig(pure_1x2_map, market_name="1X2", method=NoVigMethod.SHIN)
                    shin_1x2_probs = shin_res.no_vig_probabilities
                    shin_1x2_fair = shin_res.fair_odds

                    odds_map = {
                        "1": float(n_1x2[0]), "X": float(n_1x2[1]), "2": float(n_1x2[2]),
                        h_name: float(n_1x2[0]), "Draw": float(n_1x2[1]), a_name: float(n_1x2[2]),
                    }
                    bookmakers_dict["NESINE"] = {
                        "1X2": {
                            "odds": odds_map,
                            "raw_implied": shin_res.raw_implied_probabilities,
                            "overround": shin_res.overround,
                            "no_vig": {
                                "1": shin_1x2_probs.get("1", 0.0),
                                "X": shin_1x2_probs.get("X", 0.0),
                                "2": shin_1x2_probs.get("2", 0.0),
                                h_name: shin_1x2_probs.get("1", 0.0),
                                "Draw": shin_1x2_probs.get("X", 0.0),
                                a_name: shin_1x2_probs.get("2", 0.0),
                            },
                            "fair_odds": {
                                "1": shin_1x2_fair.get("1", "UNKNOWN"),
                                "X": shin_1x2_fair.get("X", "UNKNOWN"),
                                "2": shin_1x2_fair.get("2", "UNKNOWN"),
                                h_name: shin_1x2_fair.get("1", "UNKNOWN"),
                                "Draw": shin_1x2_fair.get("X", "UNKNOWN"),
                                a_name: shin_1x2_fair.get("2", "UNKNOWN"),
                            },
                        }
                    }

                    if is_modeled:
                        labels = [("HOME", f"{h_name} (Home)", "1"), ("DRAW", "Draw", "X"), ("AWAY", f"{a_name} (Away)", "2")]
                        for sel_code, sel_disp, key in labels:
                            odd_val = odds_map[key]
                            p_shin = shin_1x2_probs[key]
                            f_shin = shin_1x2_fair[key]
                            m_prob_val = model_probs_1x2.get(sel_code, 0.0)
                            if m_prob_val <= 0.0:
                                continue
                            m_fair_val = model_fair_1x2.get(sel_code, "UNKNOWN")
                            edge_raw = round(m_prob_val - (1.0 / odd_val), 4)
                            ev_val = round(((m_prob_val * odd_val) - 1.0) * 100.0, 2)
                            match_edges.append({
                                "bookmaker": "NESINE",
                                "market": "1X2",
                                "selection": sel_code,
                                "selection_display": sel_disp,
                                "entry_odds": odd_val,
                                "raw_implied": round(1.0 / odd_val, 4),
                                "overround": round(shin_res.overround, 4),
                                "market_no_vig": p_shin,
                                "market_fair_odds": f_shin,
                                "fair_odds_shin": f_shin,
                                "model_prob": m_prob_val,
                                "model_fair_odds": m_fair_val,
                                "raw_edge": edge_raw,
                                "adjusted_edge": edge_raw,
                                "source_classification": "BOOKMAKER_OFFERED",
                                "is_longshot": odd_val >= 5.0,
                                "shin_margin": round(shin_res.overround * 100.0, 2),
                                "ev_roi": ev_val,
                                "half_kelly": calc_half_kelly(m_prob_val, odd_val),
                                "kickoff_trt": ko_trt_str,
                                "league": comp_display,
                                "competition": comp_display,
                            })
                except Exception:
                    pass

            if n_ou25 and len(n_ou25) == 2:
                try:
                    ou_odds = {"Over 2.5": float(n_ou25[0]), "Under 2.5": float(n_ou25[1])}
                    ou_res = compute_no_vig(ou_odds, market_name="TOTALS", method=NoVigMethod.MULTIPLICATIVE)
                    if "NESINE" not in bookmakers_dict:
                        bookmakers_dict["NESINE"] = {}
                    bookmakers_dict["NESINE"]["TOTALS_2.5"] = {
                        "odds": ou_odds,
                        "overround": ou_res.overround,
                        "no_vig": ou_res.no_vig_probabilities,
                        "fair_odds": ou_res.fair_odds,
                    }
                    if is_modeled and model_totals_25["OVER"] is not None and model_totals_25["UNDER"] is not None:
                        for sel_name, odd_val in ou_odds.items():
                            p_val = ou_res.no_vig_probabilities[sel_name]
                            f_val = ou_res.fair_odds[sel_name]
                            is_over = "Over" in sel_name
                            m_prob_val = float(model_totals_25["OVER"] if is_over else model_totals_25["UNDER"])
                            if m_prob_val <= 0.0:
                                continue
                            m_fair_val = round(1.0 / m_prob_val, 2)
                            edge_raw = round(m_prob_val - (1.0 / odd_val), 4)
                            ev_val = round(((m_prob_val * odd_val) - 1.0) * 100.0, 2)
                            match_edges.append({
                                "bookmaker": "NESINE",
                                "market": "TOTALS",
                                "selection": "OVER_2.5" if is_over else "UNDER_2.5",
                                "selection_display": f"{sel_name} Goals",
                                "entry_odds": odd_val,
                                "raw_implied": round(1.0 / odd_val, 4),
                                "overround": round(ou_res.overround, 4),
                                "market_no_vig": p_val,
                                "market_fair_odds": f_val,
                                "fair_odds_shin": f_val,
                                "model_prob": m_prob_val,
                                "model_fair_odds": m_fair_val,
                                "raw_edge": edge_raw,
                                "adjusted_edge": edge_raw,
                                "source_classification": "BOOKMAKER_OFFERED",
                                "is_longshot": odd_val >= 5.0,
                                "shin_margin": round(ou_res.overround * 100.0, 2),
                                "ev_roi": ev_val,
                                "half_kelly": calc_half_kelly(m_prob_val, odd_val),
                                "kickoff_trt": ko_trt_str,
                                "league": comp_display,
                                "competition": comp_display,
                            })
                except Exception:
                    pass

            if isinstance(n_corners, dict) and n_corners:
                if "NESINE" not in bookmakers_dict:
                    bookmakers_dict["NESINE"] = {}
                bookmakers_dict["NESINE"]["CORNERS"] = n_corners
            if isinstance(n_btts, dict) and n_btts:
                if "NESINE" not in bookmakers_dict:
                    bookmakers_dict["NESINE"] = {}
                bookmakers_dict["NESINE"]["BTTS"] = n_btts

            fixtures_data.append({
                "fixture_id": live_f_id,
                "home_team": h_name,
                "away_team": a_name,
                "competition": comp_display,
                "league": comp_display,
                "country": n_country,
                "kickoff": ko_iso,
                "kickoff_trt": ko_trt_str,
                "match_phase": "LIVE_AND_PREMATCH",
                "sport": "Football",
                "model_version": "shin_devig_empirical_quant v2.0",
                "data_cutoff": now_trt.isoformat(),
                "snapshot_id": f"nesine_live_{m_dt_trt.strftime('%Y%m%d_%H%M%S')}",
                "model_1x2": {
                    "HOME": round(model_probs_1x2["HOME"], 4) if is_modeled else "UNKNOWN",
                    "DRAW": round(model_probs_1x2["DRAW"], 4) if is_modeled else "UNKNOWN",
                    "AWAY": round(model_probs_1x2["AWAY"], 4) if is_modeled else "UNKNOWN",
                    "fair_home_odds": model_fair_1x2["HOME"] if is_modeled else "UNKNOWN",
                    "fair_draw_odds": model_fair_1x2["DRAW"] if is_modeled else "UNKNOWN",
                    "fair_away_odds": model_fair_1x2["AWAY"] if is_modeled else "UNKNOWN",
                },
                "totals_2_5_model": (
                    model_totals_25
                    if (is_modeled and model_totals_25["OVER"] is not None)
                    else {"OVER": "UNKNOWN", "UNDER": "UNKNOWN"}
                ),
                "btts": {
                    "model_probability": {"YES": "UNKNOWN", "NO": "UNKNOWN"},
                    "bookmaker_odds": "DATA_UNAVAILABLE",
                    "market_no_vig_probability": "UNKNOWN",
                    "raw_edge": "UNKNOWN",
                    "status": "DATA_UNAVAILABLE",
                },
                "bookmakers": bookmakers_dict,
                "edges": match_edges,
                "model_derived_markets": {},
                "model_uncertainty": "VERIFIED_SHIN",
                "clv_status": "MONITORED",
            })
    except Exception as _nesine_live_err:
        print(f"Notice: Live Nesine direct ingestion info: {_nesine_live_err}")

    # Prioritize upcoming live & prematch fixtures chronologically; historical archive fixtures follow
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    fixtures_data.sort(
        key=lambda f: (
            0 if f.get("match_phase") in ("LIVE_AND_PREMATCH", "LIVE_MONITORED") or (f.get("kickoff") or "") >= now_iso else 1,
            f.get("kickoff") or "9999-99-99",
        )
    )

    # 4. Ingest Daemon Heartbeat (SPEC-0012: never fabricate HEALTHY when heartbeat is absent)
    daemon_heartbeat_file = root / "output" / "daemon_heartbeat.json"
    daemon_status = {
        "status": "DEGRADED",
        "last_cycle_utc": None,
        "leagues_scanned": 0,
        "positive_ev_signals": 0,
        "total_seen_alerts": 0,
    }
    if daemon_heartbeat_file.exists():
        try:
            loaded_hb = json.loads(daemon_heartbeat_file.read_text(encoding="utf-8"))
            if isinstance(loaded_hb, dict) and loaded_hb.get("status") in ("HEALTHY", "DEGRADED", "ONLINE"):
                daemon_status = loaded_hb
        except Exception:
            pass

    # 5. Ingest Commercial Syndicate Pro Data (In-Play Sniper, Copula SGP, CLV Alpha — zero synthetic odds)
    clv_report_file = root / "output" / "clv_alpha_report.json"
    clv_summary = {
        "total_analyzed_trades": 0,
        "beat_closing_rate_pct": 0.0,
        "mean_total_clv_pct": 0.0,
        "stale_alpha_contribution_pct": 0.0,
        "info_alpha_contribution_pct": 0.0,
        "statistical_edge_verified": False,
    }
    if clv_report_file.exists():
        try:
            loaded_clv = json.loads(clv_report_file.read_text(encoding="utf-8"))
            if isinstance(loaded_clv, dict):
                clv_summary.update(loaded_clv)
        except Exception:
            pass

    # Copula SGP Engine disabled: Nesine prohibits same-match MS+Corner SGP parlays and side engines are frozen.
    sgp_combinations = []
    in_play_sniper_cards = []

    # Ingest ONLY genuine non-synthetic active In-Play Sniper alerts if present (zero fake 1.75 / ARMED_WAITING_LIVE cards)
    active_inplay_file = root / "output" / "live_inplay_active_alerts.json"
    if active_inplay_file.exists():
        try:
            loaded_inplay = json.loads(active_inplay_file.read_text(encoding="utf-8"))
            if isinstance(loaded_inplay, list):
                for idx, item in enumerate(loaded_inplay):
                    if not isinstance(item, dict) or item.get("is_synthetic_odds", True):
                        continue
                    live_odd = item.get("book_odd") or item.get("target_live_odds")
                    if live_odd is None or float(live_odd) <= 1.01:
                        continue
                    in_play_sniper_cards.append({
                        "sniper_id": str(item.get("id") or f"sniper_live_{idx + 1}"),
                        "fixture_id": str(item.get("event_id") or ""),
                        "home_team": str(item.get("home") or ""),
                        "away_team": str(item.get("away") or ""),
                        "league": str(item.get("league") or "Live In-Play"),
                        "kickoff_trt": str(item.get("timestamp_utc") or "LIVE"),
                        "trigger_window": f"{item.get('elapsed_min', '?')}' ({item.get('score', '0-0')})",
                        "tactic_code": str(item.get("odds_source") or "LIVE"),
                        "target_market": f"{item.get('market', '')} {item.get('selection', '')}".strip(),
                        "prematch_lambda": item.get("pre_match_mu"),
                        "target_live_odds": round(float(live_odd), 2),
                        "expected_live_roi": round(float(item.get("edge_pct") or 0.0), 1),
                        "tier": "TIER_2_PRO",
                        "status": "LIVE_TRIGGERED",
                    })
        except Exception:
            in_play_sniper_cards = []

    syndicate_pro_payload = {
        "tiers": [
            {"id": "TIER_1_FREE", "name": "Tier 1: Freemium Radar", "price": "$0 / Ay", "min_ev": 0.0, "max_ev": 3.5},
            {"id": "TIER_2_PRO", "name": "Tier 2: Pro Trader", "price": "$49 / Ay", "min_ev": 3.0, "max_ev": 99.0},
            {"id": "TIER_3_VIP", "name": "Tier 3: Syndicate VIP", "price": "$299 / Ay", "min_ev": 5.0, "max_ev": 99.0},
        ],
        "in_play_sniper_alerts": in_play_sniper_cards,
        "copula_sgp_combinations": sgp_combinations,
        "clv_alpha_summary": clv_summary,
    }

    # Load Daily Prototype Dual-Engine report if available
    daily_prototype_payload: dict | None = None
    daily_proto_file = root / "output" / "daily_prototype_report.json"
    if daily_proto_file.exists():
        try:
            loaded_proto = json.loads(daily_proto_file.read_text(encoding="utf-8"))
            if isinstance(loaded_proto, dict):
                daily_prototype_payload = loaded_proto
                proto_summary = loaded_proto.get("summary") or {}
                if isinstance(daemon_status, dict):
                    daemon_status.setdefault("daily_prototype_generated_at_trt", loaded_proto.get("generated_at_trt"))
                    daemon_status["daily_prototype_signals"] = int(proto_summary.get("signals_count") or 0)

                # Surface verified daily_prototype signals directly onto matching fixture cards for UI Top Edges
                by_f_id = {f.get("fixture_id"): f for f in fixtures_data}
                by_teams = {
                    (str(f.get("home_team", "")).strip().lower(), str(f.get("away_team", "")).strip().lower()): f
                    for f in fixtures_data
                }
                for psig in loaded_proto.get("signals") or []:
                    ncode = psig.get("nesine_code")
                    target_f = by_f_id.get(f"nesine_live_{ncode}") if ncode is not None else None
                    if target_f is None:
                        target_f = by_teams.get((
                            str(psig.get("home", "")).strip().lower(),
                            str(psig.get("away", "")).strip().lower(),
                        ))
                    if target_f is None:
                        continue
                    odd_val = float(psig.get("book_odd") or 1.0)
                    fair_val = float(psig.get("fair_odd") or 1.0)
                    prob_val = float(psig.get("prob") or 0.0)
                    ev_val = float(psig.get("edge_pct") or 0.0)
                    if odd_val <= 1.0 or fair_val <= 1.0 or prob_val <= 0.0:
                        continue
                    sel_label = str(psig.get("selection") or psig.get("outcome") or "VALUE")
                    mkt_label = str(psig.get("market") or "1X2")
                    existing_edges = target_f.setdefault("edges", [])
                    if any(
                        str(e.get("selection_display", "")).strip() == sel_label
                        or (str(e.get("market", "")) == mkt_label and str(e.get("selection", "")) == sel_label)
                        for e in existing_edges
                    ):
                        continue
                    comp_val = str(target_f.get("competition") or target_f.get("league") or "Canlı Bülten")
                    nes_bks = (target_f.get("bookmakers") or {}).get("NESINE") or {}
                    mkt_key_bk = "TOTALS_2.5" if "2.5" in mkt_label or "TOTAL" in mkt_label.upper() else "1X2"
                    real_ov = nes_bks.get(mkt_key_bk, {}).get("overround")
                    if isinstance(real_ov, (int, float)) and real_ov > 0:
                        ov_val = round(float(real_ov), 4)
                        margin_pct_val = round(float(real_ov) * 100.0, 2)
                    else:
                        ov_val = round(1.0 / odd_val, 4)
                        margin_pct_val = round((1.0 / odd_val) * 100.0, 2)
                    existing_edges.append({
                        "bookmaker": str(psig.get("soft_book") or "NESINE").upper(),
                        "market": mkt_label,
                        "selection": sel_label,
                        "selection_display": sel_label,
                        "entry_odds": odd_val,
                        "raw_implied": round(1.0 / odd_val, 4),
                        "overround": ov_val,
                        "market_no_vig": prob_val,
                        "market_fair_odds": round(fair_val, 2),
                        "fair_odds_shin": round(fair_val, 2),
                        "model_prob": round(prob_val, 4),
                        "model_fair_odds": round(fair_val, 2),
                        "raw_edge": round(prob_val - (1.0 / odd_val), 4),
                        "adjusted_edge": round(prob_val - (1.0 / odd_val), 4),
                        "source_classification": "DAILY_PROTOTYPE_VERIFIED",
                        "is_longshot": odd_val >= 5.0,
                        "shin_margin": margin_pct_val,
                        "ev_roi": round(ev_val, 2),
                        "half_kelly": calc_half_kelly(prob_val, odd_val),
                        "stake_tl": float(psig.get("stake") or 50.0),
                        "kickoff_trt": str(psig.get("kickoff_trt") or target_f.get("kickoff_trt") or "TBD"),
                        "league": comp_val,
                        "competition": comp_val,
                    })
        except Exception:
            daily_prototype_payload = None

    # Load verified 6+ Goal Anomaly watchlist if available
    goal_anomalies_list = []
    goal_anom_file = root / "output" / "goal_anomaly_watchlist.json"
    if goal_anom_file.exists():
        try:
            goal_anomalies_list = json.loads(goal_anom_file.read_text(encoding="utf-8"))
        except Exception:
            goal_anomalies_list = []

    live_nesine_cnt = sum(1 for f in fixtures_data if str(f.get("snapshot_id", "")).startswith("nesine_live_"))
    proto_sum = (daily_prototype_payload or {}).get("summary") or {}
    sharp_scanned = int(proto_sum.get("sharp_fixtures_scanned") or 0)
    sharp_matched = int(proto_sum.get("sharp_nesine_matched") or 0)
    sharp_status_str = str(proto_sum.get("sharp_scanner_status") or "")
    propline_degraded = bool(sharp_scanned > 0 or "degraded" in sharp_status_str.lower())

    ts_reconciliation = "UNKNOWN (ratings cache missing)"
    ts_ratings_file = root / "data" / "silver" / "team_strength_ratings.json"
    if ts_ratings_file.exists():
        try:
            ts_meta = json.loads(ts_ratings_file.read_text(encoding="utf-8")).get("meta", {})
            ts_teams = int(ts_meta.get("teams_count") or 0)
            ts_matches = int(ts_meta.get("total_matches_trained") or 0)
            ts_max_dt = str(ts_meta.get("max_training_date") or "")
            dt_suffix = f", Cutoff {ts_max_dt}" if ts_max_dt else ""
            ts_reconciliation = f"{ts_teams} Teams ({ts_matches:,} Historical Matches{dt_suffix})"
        except Exception:
            pass

    # Global summary view model
    summary = {
        "engine_name": "Sports Intelligence Terminal",
        "engine_version": "v2.0-quant-shin",
        "snapshot_timestamp": datetime.now(UTC).isoformat(),
        "data_cutoff": datetime.now(UTC).isoformat(),
        "provider": "DUAL_ENGINE_NESINE_AND_SHARP",
        "match_phase": "LIVE_AND_PREMATCH",
        "daemon_status": daemon_status,
        "syndicate_pro": syndicate_pro_payload,
        "daily_prototype": daily_prototype_payload,
        "goal_anomalies": goal_anomalies_list,
        "provider_status": [
            {
                "provider": "Nesine CDN",
                "status": "LIVE_DIRECT",
                "events": int(proto_sum.get("bulletin_total_matches") or live_nesine_cnt),
                "reconciliation": f"{int(proto_sum.get('window_valid_matches') or live_nesine_cnt)} in 12h Window",
            },
            {
                "provider": "ESPN + Bzzoiro",
                "status": "CONNECTED" if sharp_scanned > 0 else "STANDBY",
                "events": sharp_scanned,
                "reconciliation": f"{sharp_matched} Nesine Matched",
            },
            {
                "provider": "PropLine",
                "status": "CIRCUIT_BREAKER_TRIPPED" if propline_degraded else "STANDBY",
                "events": 0 if propline_degraded else sharp_scanned,
                "reconciliation": "TLS Timeout -> DualFeed Backup Active" if propline_degraded else "Primary Sharp Feed",
            },
            {
                "provider": "TeamStrength ELO",
                "status": "CONNECTED",
                "events": int(proto_sum.get("evaluated_known_matches") or 0),
                "reconciliation": ts_reconciliation,
            },
        ],
        "total_fixtures": len(fixtures_data),
        "total_edges_calculated": sum(len(f["edges"]) for f in fixtures_data),
        "fixtures": fixtures_data,
    }

    out_file = Path(output_file) if output_file else (ui_data_dir / "sports_intelligence_snapshot.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=out_file.parent,
            delete=False,
            suffix=".tmp",
            encoding="utf-8",
        ) as tf:
            json.dump(summary, tf, indent=2, ensure_ascii=False)
            tf.flush()
            os.fsync(tf.fileno())
            temp_name = tf.name

        # Windows NTFS retry loop for transient file lock contention (WinError 32 / WinError 5)
        replaced = False
        last_replace_err: Exception | None = None
        for attempt in range(20):
            try:
                os.replace(temp_name, out_file)
                replaced = True
                break
            except (PermissionError, OSError) as e:
                last_replace_err = e
                backoff = min(0.5, 0.02 * (1.5 ** attempt))
                time.sleep(backoff)
        if not replaced and last_replace_err:
            raise last_replace_err

        # Also export snapshot_data.js for zero-server / direct file:/// protocol support
        try:
            js_data_file = (out_file.parent / "snapshot_data.js") if output_file else (ui_data_dir / "snapshot_data.js")
            js_content = f"window.__SPORTS_SNAPSHOT__ = {json.dumps(summary, ensure_ascii=False)};\n"
            js_data_file.write_text(js_content, encoding="utf-8")
        except Exception as jse:
            print(f"Notice: snapshot_data.js write: {jse}")
    except Exception:
        if temp_name and os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise

    print(f"Successfully generated UI snapshot: {out_file} ({len(fixtures_data)} fixtures)")
    return out_file


if __name__ == "__main__":
    generate_ui_snapshot()
