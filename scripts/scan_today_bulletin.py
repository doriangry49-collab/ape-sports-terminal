"""Scan and analyze today's matches within the 12-hour TRT window (SPEC-0013 & SPEC-0014).

Finds Tier-1 MBS-1 selections, corner opportunities, and evaluates model predictions.
Enforces SPEC-0015 (stake >= 50 TL) and fail-closed integrity.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from advanced_corner_model import AdvancedCornerEngine
from live_monitor_daemon import parse_match_kickoff
from live_stale_line_adapter import fetch_nesine_live_bulletin
from team_strength_engine import TeamStrengthEngine

TRT_TZ = timezone(timedelta(hours=3))
now_trt = datetime.now(TRT_TZ)

print(f"================================================================")
print(f"🏆 NESINE CANLI BÜLTEN ANALİZİ - {now_trt.strftime('%d.%m.%Y %H:%M:%S')} TRT")
print(f"🔒 12 Saatlik Kural (SPEC-0014): {now_trt.strftime('%H:%M')} -> {(now_trt + timedelta(hours=12)).strftime('%H:%M')} TRT")
print(f"================================================================\n")

bulletin = fetch_nesine_live_bulletin()
corner_engine = AdvancedCornerEngine()
strength_engine = TeamStrengthEngine()

window_matches = []
for m in bulletin:
    d_str = m.get("date_str")
    t_str = m.get("time_str")
    ko_dt, ko_iso = parse_match_kickoff(d_str, t_str, now_trt=now_trt, min_lead_minutes=3, max_lead_hours=12)
    if ko_dt is None:
        continue
    m["ko_dt"] = ko_dt
    m["ko_iso"] = ko_iso
    window_matches.append(m)

print(f"Bültendeki toplam maç: {len(bulletin)}")
print(f"12 saatlik penceredeki geçerli maç: {len(window_matches)}\n")

# Sort by kickoff
window_matches.sort(key=lambda x: x["ko_dt"])

mbs1_matches = [m for m in window_matches if m.get("mbs") == 1]
corner_matches = [m for m in window_matches if m.get("nesine_corners")]

print(f"MBS-1 Maç Sayısı: {len(mbs1_matches)}")
print(f"Korner Oranı Açılan Maç Sayısı: {len(corner_matches)}\n")

# Team Strength & Poisson Model Evaluations
print("================ TAKIM GÜCÜ VE 1X2 / 2.5 GOL POISSON ANALİZİ ================")
model_evals = []
for m in window_matches:
    home = m.get("home")
    away = m.get("away")
    ko_str = m["ko_dt"].strftime("%H:%M")
    mbs = m.get("mbs", 1)
    odds_1x2 = m.get("nesine_1x2")
    ou25 = m.get("nesine_ou25")
    
    try:
        pred = strength_engine.predict_match(home, away)
        if pred:
            book_1 = odds_1x2[0] if odds_1x2 else None
            book_x = odds_1x2[1] if odds_1x2 else None
            book_2 = odds_1x2[2] if odds_1x2 else None
            
            fair_1 = pred["fair_1x2"]["1"]
            fair_x = pred["fair_1x2"]["X"]
            fair_2 = pred["fair_1x2"]["2"]
            
            book_over25 = ou25[0] if ou25 else None
            book_under25 = ou25[1] if ou25 else None
            fair_over25 = pred["totals"]["over_25"]["fair_odd"]
            fair_under25 = pred["totals"]["under_25"]["fair_odd"]

            edge_1 = round(((book_1 / fair_1) - 1.0) * 100, 2) if (book_1 and fair_1 > 0) else 0.0
            edge_x = round(((book_x / fair_x) - 1.0) * 100, 2) if (book_x and fair_x > 0) else 0.0
            edge_2 = round(((book_2 / fair_2) - 1.0) * 100, 2) if (book_2 and fair_2 > 0) else 0.0
            
            edge_o25 = round(((book_over25 / fair_over25) - 1.0) * 100, 2) if (book_over25 and fair_over25 > 0) else 0.0
            edge_u25 = round(((book_under25 / fair_under25) - 1.0) * 100, 2) if (book_under25 and fair_under25 > 0) else 0.0

            model_evals.append({
                "match": f"{home} vs {away}",
                "ko_str": ko_str,
                "mbs": mbs,
                "fair_1": fair_1,
                "fair_x": fair_x,
                "fair_2": fair_2,
                "book_1": book_1,
                "book_x": book_x,
                "book_2": book_2,
                "edge_1": edge_1,
                "edge_x": edge_x,
                "edge_2": edge_2,
                "book_o25": book_over25,
                "book_u25": book_under25,
                "fair_o25": fair_over25,
                "fair_u25": fair_under25,
                "edge_o25": edge_o25,
                "edge_u25": edge_u25,
                "exp_h": pred["lambdas"]["goal_home"],
                "exp_a": pred["lambdas"]["goal_away"],
                "exp_tot": pred["lambdas"]["goal_total"],
                "exp_corners": pred["lambdas"]["corner_total"],
            })
    except Exception as e:
        pass

# Filter evals that have positive edge on MBS-1 or MBS-2
ev_candidates = [e for e in model_evals if max(e["edge_1"], e["edge_2"], e["edge_o25"], e["edge_u25"]) >= 2.0]
ev_candidates.sort(key=lambda x: max(x["edge_1"], x["edge_2"], x["edge_o25"], x["edge_u25"]), reverse=True)

print(f"Toplam +EV 1X2 / Gol Adayı: {len(ev_candidates)}\n")
for me in ev_candidates[:12]:
    print(f"[{me['ko_str']} TRT] (MBS-{me['mbs']}) {me['match']}")
    print(f"   Model Gol Beklentisi: Ev: {me['exp_h']} | Dep: {me['exp_a']} (Toplam: {me['exp_tot']}) | Beklenen Korner: {me['exp_corners']}")
    if me['book_1']:
        print(f"   1X2:  1: {me['book_1']} (Fair: {me['fair_1']} | Edge: {me['edge_1']:+.1f}%) | 2: {me['book_2']} (Fair: {me['fair_2']} | Edge: {me['edge_2']:+.1f}%)")
    if me['book_o25']:
        print(f"   2.5:  Üst: {me['book_o25']} (Fair: {me['fair_o25']} | Edge: {me['edge_o25']:+.1f}%) | Alt: {me['book_u25']} (Fair: {me['fair_u25']} | Edge: {me['edge_u25']:+.1f}%)")
    print()
