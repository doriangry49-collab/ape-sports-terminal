"""Script to scan Nesine bulletin for Saturday, run Syndicate Committee audit,
and output ranked picks across the 4 Pillars.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from live_monitor_daemon import scan_quant_engine_signals
from live_stale_line_adapter import fetch_nesine_live_bulletin
from syndicate.committee import SyndicateCommittee

TRT = timezone(timedelta(hours=3))
now_trt = datetime.now(TRT)

print("=== APE SYNDICATE CUMARTESİ BÜLTEN TARAMASI ===")
print(f"Zaman (TRT): {now_trt.strftime('%Y-%m-%d %H:%M:%S')}")

bulletin = fetch_nesine_live_bulletin()
print(f"Nesine canlı bültendeki toplam futbol maçı: {len(bulletin)}")

committee = SyndicateCommittee()
raw_sigs = scan_quant_engine_signals(bulletin=bulletin, min_edge_pct=2.0)
print(f"Filtre öncesi ham model sinyalleri: {len(raw_sigs)}")

approved = []
vetoed_count = 0

for s in raw_sigs:
    # Check kickoff window (SPEC-0013 & SPEC-0014: now + 3m < kickoff <= now + 12h)
    ko = s.get("kickoff")
    if ko:
        try:
            ko_dt = datetime.fromisoformat(str(ko).replace("Z", "+00:00"))
            now_utc = datetime.now(UTC)
            if ko_dt <= now_utc + timedelta(minutes=3) or ko_dt > now_utc + timedelta(hours=14):
                continue
        except Exception:
            continue

    rev = committee.review_signal(s)
    if rev.get("approved"):
        s["committee_rev"] = rev
        approved.append(s)
    else:
        vetoed_count += 1

print(f"Komite tarafından veto edilen: {vetoed_count}")
print(f"Komite onayından geçen (Konsensüs): {len(approved)}")

# Group and categorize by Pillar
pillar_corners = []
pillar_goals = []
pillar_dc = []
pillar_1x2 = []

for s in approved:
    mkt = str(s.get("market", "")).lower()
    sel = str(s.get("selection") or s.get("outcome") or "")
    odd = float(s.get("soft_odds") or 0.0)
    score = float(s["committee_rev"]["consensus_score"])
    tier = str(s["committee_rev"]["final_tier"])

    entry = {
        "time": s.get("time", ""),
        "home": s.get("home", ""),
        "away": s.get("away", ""),
        "market": s.get("market", ""),
        "selection": sel,
        "odds": odd,
        "tier": tier,
        "consensus_score": score,
        "edge_pct": float(s.get("edge_pct", 0.0)),
        "prob": float(s.get("prob", 0.0)),
        "votes": s["committee_rev"]["agent_verdicts"],
    }

    if "korner" in mkt or "corner" in mkt:
        pillar_corners.append(entry)
    elif "2.5" in mkt or "gol" in mkt or "ou" in mkt:
        pillar_goals.append(entry)
    elif "çifte" in mkt or "cifte" in mkt or "dc" in mkt:
        pillar_dc.append(entry)
    elif "1x2" in mkt:
        pillar_1x2.append(entry)

pillar_corners.sort(key=lambda x: (x["consensus_score"], x["edge_pct"]), reverse=True)
pillar_goals.sort(key=lambda x: (x["consensus_score"], x["edge_pct"]), reverse=True)
pillar_dc.sort(key=lambda x: (x["consensus_score"], x["edge_pct"]), reverse=True)
pillar_1x2.sort(key=lambda x: (x["consensus_score"], x["edge_pct"]), reverse=True)

out = {
    "generated_at": now_trt.strftime("%Y-%m-%d %H:%M:%S"),
    "matches_in_bulletin": len(bulletin),
    "corners": pillar_corners,
    "goals": pillar_goals,
    "double_chance": pillar_dc,
    "match_1x2": pillar_1x2,
}

out_file = Path("sports-engine/output/saturday_syndicate_board.json")
out_file.parent.mkdir(parents=True, exist_ok=True)
out_file.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Bülten analizi kaydedildi: {out_file}")

