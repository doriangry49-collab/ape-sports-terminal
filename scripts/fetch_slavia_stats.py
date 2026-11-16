import urllib.request
import json

url = "https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/scoreboard?dates=20261104"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
data = json.loads(urllib.request.urlopen(req, timeout=10).read())

for ev in data.get("events", []):
    if "Slavia" in ev.get("name", ""):
        ev_id = ev["id"]
        print(f"Match: {ev['name']}, ID: {ev_id}")
        # Fetch event summary/stats
        sum_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/summary?event={ev_id}"
        req_sum = urllib.request.Request(sum_url, headers={"User-Agent": "Mozilla/5.0"})
        sum_data = json.loads(urllib.request.urlopen(req_sum, timeout=10).read())
        
        # Look for stats in boxscore
        boxscore = sum_data.get("boxscore", {})
        teams = boxscore.get("teams", [])
        for t in teams:
            team_name = t.get("team", {}).get("displayName")
            stats = {s.get("name"): s.get("displayValue") for s in t.get("statistics", [])}
            print(f"Team: {team_name}, Stats: {stats}")

