"""Full overnight market log (Nesine, 28-29 Oct 2026) + morning settlement.

Purpose: NOT betting picks. Records every pre-match Nesine price from the user's
screenshots, de-vigs it, and next morning measures how the market's implied
probabilities compared to actual outcomes (draw rate, under rate, Brier score).
Live/in-play matches and matches with incomplete odds are excluded.

Usage:
  python tonight_full_market.py log      -> writes output/tonight_full_market.csv
  python tonight_full_market.py settle   -> fetches ESPN finals, fills results, prints calibration
"""
import csv
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("\\", 1)[0])

OUT = r"c:\Users\Thea-Aria\ .gemini\antigravity\scratch\ec2-file-explorer\sports-engine\output\tonight_full_market.csv"

# time, league, home, away, mbs, o1, ox, o2, alt, ust  (None = not offered)
M = [
    ("00:00", "Guatemala", "CSD Imperial", "CD Suchitepequez", 3, 1.24, 3.80, 6.00, 1.62, 1.62),
    ("00:00", "Nikaragua", "Sebaco", "Managua", 3, 3.67, 3.31, 1.52, 1.88, 1.42),
    ("01:30", "Brezilya Serie A", "Fluminense", "Internacional", 1, 1.67, 3.14, 3.71, 1.61, 1.76),
    ("01:30", "Brezilya Serie A", "Santos", "Palmeiras", 1, 3.01, 3.01, 1.91, 1.73, 1.65),
    ("01:30", "Brezilya Serie A", "Bragantino", "Chapecoense", 1, 1.12, 5.70, 8.28, 2.95, 1.18),
    ("01:30", "Paraguay Kupasi", "S. Luqueno", "CD Recoleta", 3, 1.97, 2.90, 2.63, 1.54, 1.71),
    ("02:00", "Kolombiya", "Once Caldas", "Alianza Valledupar", 3, 1.24, 3.75, 6.30, 1.61, 1.63),
    ("02:00", "Nikaragua", "Indigenas de Matagalpa", "ART Jalapa", 3, 2.23, 2.85, 2.30, 1.71, 1.54),
    ("02:30", "MLS", "Toronto", "DC United", 1, 1.71, 3.48, 3.18, 2.25, 1.34),
    ("02:30", "MLS", "Charlotte", "Montreal", 1, 1.43, 4.01, 4.21, 2.50, 1.28),
    ("02:30", "MLS", "New England Revolution", "New York Red Bulls", 1, 1.86, 3.57, 2.71, 2.62, 1.24),
    ("02:30", "MLS", "New York City", "Atlanta United", 1, 1.58, 3.50, 3.72, 2.06, 1.42),
    ("02:30", "MLS", "Inter Miami", "Cincinnati", 1, 1.36, 4.57, 4.24, 3.79, 1.08),
    ("02:30", "Sili", "Universidad Catolica", "Audax Italiano", 3, 1.42, 3.37, 4.27, 1.71, 1.54),
    ("02:30", "Uruguay Kupasi", "Porongo Flores", "Deportivo Maldonado", 3, 9.02, 4.66, 1.10, 1.94, 1.39),
    ("02:30", "Venezuela", "Carabobo", "Deportivo La Guaira", 3, 1.43, 3.15, 4.56, 1.41, 1.89),
    ("02:30", "Venezuela", "Metropolitanos", "Portuguesa", 3, 1.55, 3.11, 3.73, 1.59, 1.66),
    ("03:00", "Ekvador Kupasi", "Delfin", "Independiente del Valle", 3, 3.28, 2.92, 1.71, 1.46, 1.83),
    ("03:00", "Guatemala", "Malacateco", "Aurora", 3, 1.41, 3.30, 4.54, 1.67, 1.58),
    ("03:00", "Peru", "Cienciano", "Atletico Grau", 3, 1.08, 5.21, 8.85, None, None),
    ("03:15", "Arjantin Kupasi", "Atletico Tucuman", "Platense", 1, 2.65, 2.77, 2.22, 1.35, 2.24),
    ("03:30", "Brezilya Serie A", "Bahia", "Sao Paulo", 1, 1.72, 3.23, 3.38, 1.87, 1.54),
    ("03:30", "Brezilya Serie A", "Clube do Remo", "Botafogo", 1, 2.39, 3.17, 2.20, 1.90, 1.51),
    ("03:30", "MLS", "Dallas", "Columbus Crew", 1, 1.97, 3.37, 2.61, 2.41, 1.29),
    ("03:30", "MLS", "Minnesota United", "Sporting Kansas City", 1, 1.26, 4.70, 5.53, 2.89, 1.19),
    ("03:30", "MLS", "St. Louis City", "Portland Timbers", 1, 1.76, 3.49, 3.02, 2.46, 1.28),
    ("03:30", "MLS", "Austin", "Real Salt Lake", 1, 2.68, 3.29, 1.96, 2.13, 1.40),
    ("03:30", "MLS", "Chicago Fire", "Orlando City", 1, 1.35, 4.43, 4.47, 3.70, 1.09),
    ("03:30", "MLS", "Nashville", "Philadelphia Union", 1, 1.57, 3.54, 3.71, 2.07, 1.42),
    ("03:30", "Orta Amerika Kupasi", "Saprissa", "Angel Firpo", 3, 1.22, 4.12, 5.83, 2.00, 1.36),
    ("04:00", "Nikaragua", "Diriangen", "Real Esteli", 3, 2.05, 2.89, 2.51, 1.71, 1.54),
    ("04:05", "Kolombiya", "Internacional de Bogota", "Independiente Medellin", 3, 2.39, 2.87, 2.15, 1.65, 1.60),
    ("04:05", "Kolombiya B", "Deportes Quindio", "Real Santander Cundinamarca", 3, 1.56, 2.91, 4.00, 1.37, 1.99),
    ("05:00", "Guatemala", "Municipal", "Comunicaciones", 3, 1.24, 3.72, 6.42, 1.62, 1.62),
    ("05:30", "MLS", "Seattle Sounders", "Houston Dynamo", 1, 1.57, 3.53, 3.73, 2.00, 1.45),
    ("05:30", "MLS", "San Jose Earthquakes", "Colorado Rapids", 1, 2.02, 3.26, 2.59, 2.00, 1.46),
    ("05:30", "MLS", "Vancouver Whitecaps", "San Diego", 1, 1.28, 4.69, 5.31, 3.04, 1.16),
    ("06:00", "Meksika", "America", "Tijuana", 2, 1.26, 4.06, 5.22, 2.10, 1.32),
    ("06:00", "Orta Amerika Kupasi", "CD Olimpia", "Cartagines", 3, 1.69, 3.03, 3.19, 1.46, 1.82),
]
FIELDS = ["time", "league", "home", "away", "mbs", "o1", "ox", "o2", "alt", "ust",
          "p1", "px", "p2", "p_under", "margin_1x2", "score", "status"]


def log():
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for t, lg, h, a, mbs, o1, ox, o2, alt, ust in M:
            s = 1 / o1 + 1 / ox + 1 / o2
            pu = ((1 / alt) / (1 / alt + 1 / ust)) if alt and ust else ""
            w.writerow({"time": t, "league": lg, "home": h, "away": a, "mbs": mbs,
                        "o1": o1, "ox": ox, "o2": o2, "alt": alt or "", "ust": ust or "",
                        "p1": round(1 / o1 / s, 4), "px": round(1 / ox / s, 4), "p2": round(1 / o2 / s, 4),
                        "p_under": round(pu, 4) if pu != "" else "", "margin_1x2": round((s - 1) * 100, 2),
                        "score": "", "status": "PENDING"})
    print(f"Logged {len(M)} matches -> {OUT}")


def settle():
    from fetch_and_settle_tonight import best_match, fetch_finals
    finals = fetch_finals()
    with open(OUT, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    n = brier = 0.0
    draws = exp_draw = unders = exp_under = n_ou = 0.0
    for r in rows:
        m, sc = best_match(r["home"], r["away"], finals)
        if not m:
            r["status"] = "NO_SOURCE"
            continue
        if not m["done"]:
            r["status"] = "NOT_FINISHED"
            continue
        hg, ag = m["hg"], m["ag"]
        r["score"], r["status"] = f"{hg}-{ag}", f"FINAL ({m['home']} v {m['away']}, sim={sc:.2f})"
        res = (1, 0, 0) if hg > ag else ((0, 1, 0) if hg == ag else (0, 0, 1))
        p = (float(r["p1"]), float(r["px"]), float(r["p2"]))
        brier += sum((pi - oi) ** 2 for pi, oi in zip(p, res))
        draws += res[1]
        exp_draw += p[1]
        n += 1
        if r["p_under"]:
            unders += 1 if hg + ag < 2.5 else 0
            exp_under += float(r["p_under"])
            n_ou += 1
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Settled {int(n)}/{len(rows)} | NO_SOURCE: {sum(r['status']=='NO_SOURCE' for r in rows)} | NOT_FINISHED: {sum(r['status']=='NOT_FINISHED' for r in rows)}")
    if n:
        print(f"Beraberlik: gerçek {int(draws)}/{int(n)} = %{draws/n*100:.1f} | piyasa beklentisi %{exp_draw/n*100:.1f}")
        print(f"1X2 Brier skoru (düşük=iyi, rastgele≈0.667): {brier/n:.3f}")
    if n_ou:
        print(f"2.5 Alt: gerçek {int(unders)}/{int(n_ou)} = %{unders/n_ou*100:.1f} | piyasa beklentisi %{exp_under/n_ou*100:.1f}")


if __name__ == "__main__":
    {"log": log, "settle": settle}[sys.argv[1] if len(sys.argv) > 1 else "log"]()

