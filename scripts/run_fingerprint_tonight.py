"""Run OddsFingerprintEngine on tonight's marquee fixtures:
- Slavia Prag vs Arsenal (coupon_005)
- Fenerbahçe vs Liverpool
- Leipzig vs Man. City
"""
import sys
from pathlib import Path
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from odds_fingerprint_engine import (
    OddsFingerprintEngine,
    format_fingerprint_telegram_message,
)

engine = OddsFingerprintEngine()

fixtures = [
    {
        "name": "Slavia Prag vs Arsenal",
        "time": "23:00",
        "mbs": 1,
        "open_1": 9.93,
        "open_x": 5.40,
        "open_2": 1.11,
        "open_o25": 1.48,
        "open_u25": 1.95,
        "note": "Kupon #005 (Korner 8.5 Alt)",
    },
    {
        "name": "Fenerbahçe vs Liverpool",
        "time": "20:45",
        "mbs": 1,
        "open_1": 5.43,
        "open_x": 4.68,
        "open_2": 1.27,
        "open_o25": 1.21,
        "open_u25": 2.74,
        "note": "Ağır Deplasman Baskısı",
    },
    {
        "name": "Leipzig vs Man. City",
        "time": "23:00",
        "mbs": 1,
        "open_1": 4.41,
        "open_x": 4.35,
        "open_2": 1.37,
        "open_o25": 1.15,
        "open_u25": 3.11,
        "note": "Yüksek Gol & Korner Beklentisi",
    },
]

print("==================================================================")
print("🧬 BUGÜNKÜ ŞAMPİYONLAR LİGİ MAÇLARININ ORAN PARMAK İZİ ANALİZİ")
print("==================================================================\n")

for fix in fixtures:
    rep = engine.find_nearest_twins(
        open_1=fix["open_1"],
        open_x=fix["open_x"],
        open_2=fix["open_2"],
        open_o25=fix["open_o25"],
        open_u25=fix["open_u25"],
        k=50,
    )
    print(format_fingerprint_telegram_message(
        fixture_name=fix["name"],
        time_str=fix["time"],
        mbs=fix["mbs"],
        report=rep,
    ))
    print("\n" + "="*66 + "\n")
