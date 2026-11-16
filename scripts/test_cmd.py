from unittest.mock import patch
import sys
import time
sys.path.insert(0, "sports-engine/src")

from telegram_notifier import process_user_command

MOCK_PARSED_MATCHES = [
    {
        "home": "Arsenal",
        "away": "Chelsea",
        "nesine_1x2": (1.95, 3.40, 3.60),
        "nesine_ou25": (1.80, 1.85),
        "date_str": "05.11.2026",
        "time_str": "23:00",
        "mbs": 1,
    }
]

with patch("telegram_notifier.fetch_nesine_live_bulletin", return_value=MOCK_PARSED_MATCHES):
    t0 = time.time()
    print("Testing /parmakizi...")
    res = process_user_command("/parmakizi")
    print(f"Done in {time.time()-t0:.2f}s:")
    print(res[:200])
