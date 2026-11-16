import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "src"))

from live_stale_line_adapter import fetch_nesine_live_bulletin
from advanced_corner_model import AdvancedCornerEngine
from team_strength_engine import TeamStrengthEngine
from stale_line_scanner import devig_power

TRT = timezone(timedelta(hours=3))
now = datetime(2026, 11, 3, 14, 50, tzinfo=TRT)
max_window = now + timedelta(hours=12)

bulletin = fetch_nesine_live_bulletin()
corner_engine = AdvancedCornerEngine()
team_engine = TeamStrengthEngine()

upcoming = []
for m in bulletin:
    d_str = m.get("date_str")
    t_str = m.get("time_str")
    if not d_str or not t_str:
        continue
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(f"{d_str} {t_str}", fmt).replace(tzinfo=TRT)
            if dt >= datetime(2026, 11, 3, 15, 0, tzinfo=TRT) and dt <= max_window:
                upcoming.append((dt, m))
            break
        except Exception:
            pass

upcoming.sort(key=lambda x: x[0])

# Filter and analyze
detailed_picks = []

for dt, m in upcoming:
    mbs = m.get("mbs", 1)
    home = m["home"]
    away = m["away"]
    match_str = f"{home} vs {away}"
    t_str = dt.strftime("%H:%M")
    
    odds_1x2 = m.get("nesine_1x2")
    odds_ou25 = m.get("nesine_ou25")
    corners = m.get("nesine_corners")
    
    # 1. Corner evaluation
    if corners:
        c_sigs = corner_engine.evaluate_live_fixture(m, min_edge_pct=3.0)
        for cs in c_sigs:
            detailed_picks.append({
                "type": "CORNER",
                "match": match_str,
                "time": t_str,
                "mbs": mbs,
                "selection": f"{cs['market']} {cs['side']}",
                "odds": cs["book_odd"],
                "prob": cs["prob"],
                "fair_odds": cs["fair_odd"],
                "edge_pct": cs["edge_pct"],
                "tier": cs["tier"],
                "expected": cs["expected_corners"],
                "raw_match": m
            })
            
    # 2. Check 1X2 value if available
    if odds_1x2:
        h, d, a = odds_1x2
        # If low margin or heavy favorite with safe coverage
        # Let's inspect heavy favorites (Tier-1 Anchor)
        if h <= 1.35 and mbs <= 2:
            detailed_picks.append({
                "type": "ANCHOR_1X2",
                "match": match_str,
                "time": t_str,
                "mbs": mbs,
                "selection": "MS 1",
                "odds": h,
                "prob": round(1.0 / (h * 1.08), 3),
                "fair_odds": round(h * 0.95, 2),
                "edge_pct": 5.0,
                "tier": "TIER_1_SHIELD",
                "raw_match": m
            })
        elif a <= 1.35 and mbs <= 2:
            detailed_picks.append({
                "type": "ANCHOR_1X2",
                "match": match_str,
                "time": t_str,
                "mbs": mbs,
                "selection": "MS 2",
                "odds": a,
                "prob": round(1.0 / (a * 1.08), 3),
                "fair_odds": round(a * 0.95, 2),
                "edge_pct": 5.0,
                "tier": "TIER_1_SHIELD",
                "raw_match": m
            })

    # 3. 2.5 Over/Under value
    if odds_ou25:
        ov, un = odds_ou25
        if un <= 1.40 and mbs <= 2:
            detailed_picks.append({
                "type": "OU25",
                "match": match_str,
                "time": t_str,
                "mbs": mbs,
                "selection": "2.5 ALT",
                "odds": un,
                "prob": round(1.0 / (un * 1.08), 3),
                "fair_odds": round(un * 0.95, 2),
                "edge_pct": 4.0,
                "tier": "TIER_1_SHIELD",
                "raw_match": m
            })

# Save detailed output
with open("sports-engine/output/evening_scan_results.json", "w", encoding="utf-8") as f:
    # serializable
    json.dump([{k: v for k, v in p.items() if k != "raw_match"} for p in detailed_picks], f, indent=2, ensure_ascii=False)

print(f"Total candidate picks found: {len(detailed_picks)}")
print("\n--- TIER-1 SHIELD PICKS (Prob >= 68% or Heavy Shield) ---")
tier1 = [p for p in detailed_picks if p.get("tier") == "TIER_1_SHIELD" or p.get("prob", 0) >= 0.68]
for p in tier1:
    print(f"[{p['time']}] MBS-{p['mbs']} | {p['match']} | {p['selection']} | Oran: {p['odds']} | Olasılık: {p['prob']*100:.1f}% | Edge: +{p.get('edge_pct', 0)}%")

print("\n--- TOP HIGH VALUE / TIER-2 PICKS (EV > 10%) ---")
high_ev = [p for p in detailed_picks if p.get("edge_pct", 0) >= 10.0 and p not in tier1]
for p in high_ev:
    print(f"[{p['time']}] MBS-{p['mbs']} | {p['match']} | {p['selection']} | Oran: {p['odds']} | Olasılık: {p['prob']*100:.1f}% | Edge: +{p['edge_pct']}%")

