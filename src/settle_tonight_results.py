import csv
import sys

def settle(scores_dict):
    """
    scores_dict: mapping from 'home_away' to (home_goals, away_goals)
    e.g. {'Clube do Remo_Botafogo RJ': (1, 1)}
    """
    csv_path = r"c:\Users\Thea-Aria\ .gemini\antigravity\scratch\ec2-file-explorer\sports-engine\output\tonight_test_bets.csv"
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
            
    total_bets = 0
    won_bets = 0
    total_staked_u = 0.0
    total_pnl_u = 0.0
    
    for r in rows:
        key = f"{r['home']}_{r['away']}"
        if key in scores_dict:
            hg, ag = scores_dict[key]
            r['result_score'] = f"{hg}-{ag}"
            odds = float(r['nesine_odds'])
            kelly_pct = float(r['kelly_stake_pct'])
            stake_u = 1.0 # 1 unit base
            total_staked_u += stake_u
            total_bets += 1
            
            won = False
            if "ALT" in r['market']:
                if hg + ag < 2.5:
                    won = True
            elif "UST" in r['market']:
                if hg + ag > 2.5:
                    won = True
            elif "Beraberlik" in r['market'] or "MS X" in r['market']:
                if hg == ag:
                    won = True
            elif "MS 1" in r['market']:
                if hg > ag:
                    won = True
            elif "MS 2" in r['market']:
                if ag > hg:
                    won = True
                    
            if won:
                pnl = (odds - 1.0) * stake_u
                r['bet_settled'] = "KAZANDI"
                r['pnl'] = f"+{round(pnl, 2)}"
                total_pnl_u += pnl
                won_bets += 1
            else:
                pnl = -stake_u
                r['bet_settled'] = "KAYBETTİ"
                r['pnl'] = f"{round(pnl, 2)}"
                total_pnl_u += pnl
                
    # Save back
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        
    print(f"Sonuçlandırma Tamamlandı:")
    print(f"Toplam Bahis: {total_bets} | Kazanan: {won_bets} | Kaybeden: {total_bets - won_bets}")
    if total_staked_u > 0:
        roi = (total_pnl_u / total_staked_u) * 100
        print(f"Net PnL: {'+' if total_pnl_u > 0 else ''}{round(total_pnl_u, 2)}u | ROI: %{round(roi, 2)}")

if __name__ == "__main__":
    print("Settle script hazır. Skorlar girildiğinde otomatik çalıştırılacak.")

