import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add src to sys.path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "src"))

from live_stale_line_adapter import fetch_nesine_live_bulletin
from advanced_corner_model import AdvancedCornerEngine
from team_strength_engine import TeamStrengthEngine

TRT = timezone(timedelta(hours=3))
# Current local time: 2026-11-03 14:50
now = datetime(2026, 11, 3, 14, 50, tzinfo=TRT)
max_window = now + timedelta(hours=12)

bulletin = fetch_nesine_live_bulletin()
print(f"Total bulletin matches fetched: {len(bulletin)}")

corner_engine = AdvancedCornerEngine()

upcoming = []
for m in bulletin:
    d_str = m.get("date_str")
    t_str = m.get("time_str")
    if not d_str or not t_str:
        continue
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(f"{d_str} {t_str}", fmt).replace(tzinfo=TRT)
            # Must be starting >= 15:00 and within 12h
            if dt >= datetime(2026, 11, 3, 15, 0, tzinfo=TRT) and dt <= max_window:
                upcoming.append((dt, m))
            break
        except Exception:
            pass

upcoming.sort(key=lambda x: x[0])
print(f"Matches after 15:00 today (within 12h): {len(upcoming)}")

corner_signals = []
market_signals = []

for dt, m in upcoming:
    # 1. Corner evaluation
    if m.get("nesine_corners"):
        c_sigs = corner_engine.evaluate_live_fixture(m, min_edge_pct=2.0)
        for s in c_sigs:
            s["kickoff_dt"] = dt.strftime("%H:%M")
            corner_signals.append(s)

    # 2. General 1X2 and O/U analysis
    # Let's inspect prominent matches with odds
    if m.get("nesine_1x2"):
        h_odd, d_odd, a_odd = m["nesine_1x2"]
        mbs = m.get("mbs", 1)
        ou = m.get("nesine_ou25")
        market_signals.append({
            "match": f"{m['home']} vs {m['away']}",
            "time": dt.strftime("%H:%M"),
            "mbs": mbs,
            "1x2": (h_odd, d_odd, a_odd),
            "ou25": ou,
            "has_corners": bool(m.get("nesine_corners")),
            "corners": m.get("nesine_corners"),
            "raw": m
        })

print("\n=== TOP UPCOMING FIXTURES (Sample 25) ===")
for ms in market_signals[:25]:
    c_str = f"Corners: {list(ms['corners'].keys())}" if ms['has_corners'] else "No Corners"
    print(f"[{ms['time']}] MBS-{ms['mbs']} | {ms['match']} | 1X2: {ms['1x2']} | OU25: {ms['ou25']} | {c_str}")

print(f"\nTotal Corner Signals Detected: {len(corner_signals)}")
for cs in corner_signals:
    print(f"[{cs['time']}] {cs['match']} | Market: {cs['market']} {cs['side']} | Odd: {cs['book_odd']} | Fair: {cs['fair_odd']} | Prob: {cs['prob']*100:.1f}% | Edge: +{cs['edge_pct']}% | Tier: {cs['tier']}")

