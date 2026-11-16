from live_settlement_engine import fetch_espn_scores

for lg in ['ger.1', 'ita.1', 'eng.1', 'ger.2']:
    scores = fetch_espn_scores(lg)
    print(f"=== {lg} ===")
    for m in scores:
        print(f"{m['home']} {m['hg']}-{m['ag']} {m['away']} | Status: {m['status']} | Done: {m['is_completed']}")

