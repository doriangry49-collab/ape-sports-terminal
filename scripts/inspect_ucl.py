import sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "src"))

from live_stale_line_adapter import fetch_nesine_live_bulletin

bulletin = fetch_nesine_live_bulletin()
for m in bulletin:
    h = m.get("home", "")
    if any(k in h for k in ["Man. Utd", "Atl Madrid", "Barcelona", "Feyenoord", "Bodo", "W. Bromwich", "Preston"]):
        print(f"{h} vs {m.get('away')} | MBS: {m.get('mbs')} | 1X2: {m.get('nesine_1x2')} | Corners: {m.get('nesine_corners')}")

