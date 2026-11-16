"""Comprehensive test suite for all 4 providers executing Phases 1 to 9."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
load_dotenv(PROJECT_ROOT / ".env")

import httpx

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
PROPLINE_KEY = os.getenv("PROPLINE_KEY", "")
BZZOIRO_KEY = os.getenv("BZZOIRO_KEY", "")
XIDDAA_KEY = os.getenv("XIDDAA_KEY", "")

ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "provider_validation"
RAW_DIR = ARTIFACTS_DIR / "raw"
for sub in ["api_football", "propline", "bzzoiro", "xiddaa"]:
    (RAW_DIR / sub).mkdir(parents=True, exist_ok=True)

client = httpx.Client(timeout=25.0)

def save_raw_response(provider: str, slug: str, data: dict | list) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    clean_slug = slug.replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "_")
    filename = f"{clean_slug}_{ts}.json"
    target = RAW_DIR / provider / filename
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(target.relative_to(PROJECT_ROOT)).replace("\\", "/")


def test_endpoint(provider: str, name: str, method: str, url: str, headers: dict, params: dict = None) -> dict:
    result = {
        "capability": name,
        "endpoint": url,
        "method": method,
        "status_code": None,
        "result_count": 0,
        "has_content": False,
        "status": "FAIL",
        "evidence_file": None,
        "rate_limit_info": None,
        "fields": [],
        "notes": "",
    }
    try:
        if method == "GET":
            r = client.get(url, headers=headers, params=params)
        else:
            r = client.post(url, headers=headers, json=params)

        result["status_code"] = r.status_code
        rate_headers = {k: v for k, v in r.headers.items() if any(rl in k.lower() for rl in ["ratelimit", "requests", "quota", "limit"])}
        if rate_headers:
            result["rate_limit_info"] = rate_headers

        if r.status_code == 200:
            try:
                data = r.json()
            except Exception:
                data = {"raw_text": r.text}

            ev_path = save_raw_response(provider, name, data)
            result["evidence_file"] = ev_path
            result["has_content"] = bool(data)

            if isinstance(data, list):
                result["result_count"] = len(data)
                if data and isinstance(data[0], dict):
                    result["fields"] = list(data[0].keys())[:12]
            elif isinstance(data, dict):
                # Count inner results
                for k in ["response", "data", "results", "events", "sports"]:
                    if k in data and isinstance(data[k], list):
                        result["result_count"] = len(data[k])
                        if data[k] and isinstance(data[k][0], dict):
                            result["fields"] = list(data[k][0].keys())[:12]
                        break
                else:
                    result["result_count"] = 1
                    result["fields"] = list(data.keys())[:12]

            if result["result_count"] > 0:
                result["status"] = "PASS"
            else:
                result["status"] = "NOT_AVAILABLE"
                result["notes"] = "Response 200 OK but returned empty list/data"

        elif r.status_code in [401, 403]:
            result["status"] = "ENTITLEMENT_REQUIRED"
            try:
                err_data = r.json()
            except Exception:
                err_data = {"error": r.text}
            ev_path = save_raw_response(provider, f"{name}_error_{r.status_code}", err_data)
            result["evidence_file"] = ev_path
            result["notes"] = f"HTTP {r.status_code} - Plan restriction or entitlement required"
        elif r.status_code == 404:
            result["status"] = "NOT_AVAILABLE"
            result["notes"] = f"HTTP 404 - Endpoint not found or not supported"
        else:
            result["status"] = "FAIL"
            result["notes"] = f"HTTP {r.status_code}"
    except Exception as e:
        result["status"] = "FAIL"
        result["notes"] = f"Request Exception: {type(e).__name__} {str(e)[:80]}"

    return result

print("Starting provider capability testing...")
all_provider_results = {}

# =============================================================================
# 1. API-FOOTBALL
# =============================================================================
print("\n" + "="*50)
print("TESTING API-FOOTBALL (Free Plan)")
print("="*50)
af_headers = {"x-apisports-key": API_FOOTBALL_KEY}
af_tests = [
    ("League / Season Discovery", "GET", "https://v3.football.api-sports.io/leagues", {"country": "Turkey"}),
    ("Coverage Flags", "GET", "https://v3.football.api-sports.io/leagues", {"id": 203}),
    ("Upcoming Fixtures", "GET", "https://v3.football.api-sports.io/fixtures", {"league": 203, "next": 10}),
    ("Past Fixtures (2024)", "GET", "https://v3.football.api-sports.io/fixtures", {"league": 203, "season": 2024, "last": 5}),
    ("Live Fixtures (Global)", "GET", "https://v3.football.api-sports.io/fixtures", {"live": "all"}),
    ("H2H", "GET", "https://v3.football.api-sports.io/fixtures/headtohead", {"h2h": "645-649"}), # Galatasaray - Fenerbahce
    ("Standings", "GET", "https://v3.football.api-sports.io/standings", {"league": 203, "season": 2024}),
    ("Injuries", "GET", "https://v3.football.api-sports.io/injuries", {"league": 203, "season": 2024}),
    ("Odds", "GET", "https://v3.football.api-sports.io/odds", {"league": 203, "season": 2024}),
    ("Predictions", "GET", "https://v3.football.api-sports.io/predictions", {"fixture": 1208000}), # Sample ID
]

af_results = []
for name, m, u, p in af_tests:
    res = test_endpoint("api_football", name, m, u, af_headers, p)
    print(f"  [{res['status']}] {name}: status={res['status_code']} count={res['result_count']}")
    af_results.append(res)
all_provider_results["api_football"] = af_results

# =============================================================================
# 2. PROPLINE
# =============================================================================
print("\n" + "="*50)
print("TESTING PROPLINE")
print("="*50)
pl_headers = {"x-api-key": PROPLINE_KEY}
pl_tests = [
    ("Sport Discovery", "GET", "https://api.prop-line.com/v1/sports", None),
    ("Upcoming Event Discovery", "GET", "https://api.prop-line.com/v1/sports/soccer_turkey_super_lig/events", None),
    ("Bulk Odds (1X2 / h2h & totals)", "GET", "https://api.prop-line.com/v1/sports/soccer_turkey_super_lig/odds", {"markets": "h2h,totals", "regions": "eu"}),
    ("Per-Event Odds (240567)", "GET", "https://api.prop-line.com/v1/sports/soccer_turkey_super_lig/events/240567/odds", {"markets": "h2h,totals", "regions": "eu"}),
    ("Spreads Odds", "GET", "https://api.prop-line.com/v1/sports/soccer_turkey_super_lig/events/240567/odds", {"markets": "spreads"}),
    ("BTTS Odds", "GET", "https://api.prop-line.com/v1/sports/soccer_turkey_super_lig/events/240567/odds", {"markets": "btts"}),
    ("Freshness Endpoint", "GET", "https://api.prop-line.com/v1/sports/soccer_turkey_super_lig/freshness", None),
    ("Historical Odds Entitlement", "GET", "https://api.prop-line.com/v1/sports/soccer_turkey_super_lig/events/240567/odds/history", {"markets": "h2h"}),
    ("Closing Odds Entitlement", "GET", "https://api.prop-line.com/v1/sports/soccer_turkey_super_lig/events/240567/odds/closing", None),
]

pl_results = []
for name, m, u, p in pl_tests:
    res = test_endpoint("propline", name, m, u, pl_headers, p)
    print(f"  [{res['status']}] {name}: status={res['status_code']} count={res['result_count']}")
    pl_results.append(res)
all_provider_results["propline"] = pl_results

# =============================================================================
# 3. BZZOIRO / BSD
# =============================================================================
print("\n" + "="*50)
print("TESTING BZZOIRO / BSD (API v2)")
print("="*50)
bz_headers = {"Authorization": f"Token {BZZOIRO_KEY}"}
bz_tests = [
    ("Coverage", "GET", "https://sports.bzzoiro.com/api/v2/coverage/", None),
    ("League Discovery", "GET", "https://sports.bzzoiro.com/api/v2/leagues/11/", None),
    ("Current Season", "GET", "https://sports.bzzoiro.com/api/v2/seasons/1539/", None),
    ("Event Discovery", "GET", "https://sports.bzzoiro.com/api/v2/events/", {"league": 11, "limit": 10}),
    ("Event Detail (216009)", "GET", "https://sports.bzzoiro.com/api/v2/events/216009/", None),
    ("Event Stats (216009)", "GET", "https://sports.bzzoiro.com/api/v2/events/216009/stats/", None),
    ("Event Lineups (216009)", "GET", "https://sports.bzzoiro.com/api/v2/events/216009/lineups/", None),
    ("Event Predictions (216009)", "GET", "https://sports.bzzoiro.com/api/v2/events/216009/predictions/", None),
    ("Consensus Odds (216009)", "GET", "https://sports.bzzoiro.com/api/v2/events/216009/odds/", None),
    ("Per-Bookmaker Odds Comparison", "GET", "https://sports.bzzoiro.com/api/v2/events/216009/odds/comparison/", None),
    ("Event H2H (216009)", "GET", "https://sports.bzzoiro.com/api/v2/events/216009/h2h/", None),
    ("Event Shotmap (216009)", "GET", "https://sports.bzzoiro.com/api/v2/events/216009/shotmap/", None),
    ("Event Momentum (216009)", "GET", "https://sports.bzzoiro.com/api/v2/events/216009/momentum/", None),
]

bz_results = []
for name, m, u, p in bz_tests:
    res = test_endpoint("bzzoiro", name, m, u, bz_headers, p)
    print(f"  [{res['status']}] {name}: status={res['status_code']} count={res['result_count']}")
    bz_results.append(res)
all_provider_results["bzzoiro"] = bz_results

# =============================================================================
# 4. XIDDAA
# =============================================================================
print("\n" + "="*50)
print("TESTING XIDDAA")
print("="*50)
xi_headers = {"X-API-Key": XIDDAA_KEY}
xi_tests = [
    ("Sports Endpoint", "GET", "https://xiddaa.com/api/v1/sports", None),
    ("Competitions Endpoint", "GET", "https://xiddaa.com/api/v1/competitions", {"sportId": 1}),
    ("Events Prematch", "GET", "https://xiddaa.com/api/v1/events", {"competitionId": 584, "classification": "prematch"}),
    ("Events by Competition (584)", "GET", "https://xiddaa.com/api/v1/events", {"competitionId": 584}),
    ("Single Event Detail (3065471)", "GET", "https://xiddaa.com/api/v1/events/3065471", None),
    ("Full History Event (3065471)", "GET", "https://xiddaa.com/api/v1/events/3065471", {"includeHistory": "true", "historyMode": "full"}),
    ("Recent Event Detail (3144759)", "GET", "https://xiddaa.com/api/v1/events/3144759", None),
    ("Recent Event Full History (3144759)", "GET", "https://xiddaa.com/api/v1/events/3144759", {"includeHistory": "true", "historyMode": "full"}),
]

xi_results = []
for name, m, u, p in xi_tests:
    res = test_endpoint("xiddaa", name, m, u, xi_headers, p)
    print(f"  [{res['status']}] {name}: status={res['status_code']} count={res['result_count']}")
    xi_results.append(res)
all_provider_results["xiddaa"] = xi_results

# Save full results json
with open(ARTIFACTS_DIR / "provider_capabilities_test.json", "w", encoding="utf-8") as f:
    json.dump(all_provider_results, f, ensure_ascii=False, indent=2)

print("\nSaved artifacts/provider_validation/provider_capabilities_test.json")
