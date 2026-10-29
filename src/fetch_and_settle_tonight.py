"""Fetch final scores from ESPN public scoreboard and settle tonight_test_bets.csv.

Usage: python fetch_and_settle_tonight.py
Unfinished / unmatched matches are reported and left PENDING (never guessed).
"""
import csv
import difflib
import json
import sys
import unicodedata
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from settle_tonight_results import settle  # noqa: E402

LEAGUES = ["usa.1", "bra.1", "arg.copa", "col.1", "chi.1", "mex.1", "gua.1", "ven.1", "per.1", "all"]
DATES = ["20261028", "20261029"]
CSV_PATH = r"c:\Users\Thea-Aria\ .gemini\antigravity\scratch\ec2-file-explorer\sports-engine\output\tonight_test_bets.csv"


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    for t in ["fc", "sc", "cf", "sp", "rj", "ba", "utd", "united", "red bull", ".", "-"]:
        s = s.replace(t, " ")
    return " ".join(s.split())


def fetch_finals():
    finals = []
    for lg in LEAGUES:
        for d in DATES:
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={d}&limit=1000"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                data = json.loads(urllib.request.urlopen(req, timeout=10).read())
            except Exception as e:  # fail visibly, do not invent data
                print(f"[WARN] {lg} {d}: {e}")
                continue
            for ev in data.get("events", []):
                comp = ev["competitions"][0]
                done = comp["status"]["type"].get("completed", False)
                teams = {c["homeAway"]: c for c in comp["competitors"]}
                finals.append({
                    "home": teams["home"]["team"]["displayName"],
                    "away": teams["away"]["team"]["displayName"],
                    "hg": int(teams["home"].get("score", 0) or 0),
                    "ag": int(teams["away"].get("score", 0) or 0),
                    "done": done,
                })
    return finals


def best_match(home, away, finals):
    best, best_score = None, 0.0
    for f in finals:
        sh = difflib.SequenceMatcher(None, norm(home), norm(f["home"])).ratio()
        sa = difflib.SequenceMatcher(None, norm(away), norm(f["away"])).ratio()
        if min(sh, sa) < 0.4:  # both sides must resemble, avoids false matches
            continue
        sc = (sh + sa) / 2
        if sc > best_score:
            best, best_score = f, sc
    return (best, best_score) if best_score >= 0.55 else (None, best_score)


def main():
    finals = fetch_finals()
    print(f"ESPN events fetched: {len(finals)}")
    with open(CSV_PATH, encoding="utf-8") as fh:
        bets = list(csv.DictReader(fh))
    scores = {}
    for b in bets:
        key = f"{b['home']}_{b['away']}"
        if key in scores:
            continue
        m, sc = best_match(b["home"], b["away"], finals)
        if not m:
            print(f"[UNMATCHED] {b['home']} - {b['away']} (best={sc:.2f})")
        elif not m["done"]:
            print(f"[NOT FINISHED] {b['home']} - {b['away']}")
        else:
            print(f"[OK] {b['home']} - {b['away']} => {m['home']} {m['hg']}-{m['ag']} {m['away']} (sim={sc:.2f})")
            scores[key] = (m["hg"], m["ag"])
    if scores:
        settle(scores)
    else:
        print("No finished matches to settle yet.")


if __name__ == "__main__":
    main()

