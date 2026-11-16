"""High-Odds Market & System Parlay Engine for Sports-Engine.

Provides quantitative bivariate Poisson & Dixon-Coles pricing for high-multiplier markets:
  1. HT/FT (İlk Yarı / Maç Sonu: X/1, X/2, 1/X, 2/1, 1/2, 2/X)
  2. First Half BTTS (İlk Yarı Karşılıklı Gol Var)
  3. Total Goals 6+ / 7+ (TG 6+)
  4. Exact Correct Scores (Skor Tahmini: 2-1, 1-2, 2-0, 3-1, 1-1, 2-2)
  5. Combinatorial System Parlays (Sistem 2/3, 2/4, 3/4) with minimum 2-hit safety margins.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

HTFT_LABELS = {
    1: "1/1", 2: "1/X", 3: "1/2",
    4: "X/1", 5: "X/X", 6: "X/2",
    7: "2/1", 8: "2/X", 9: "2/2",
}


def poisson_pmf(k: int, lmbda: float) -> float:
    """Exact Poisson Probability Mass Function P(X = k)."""
    if lmbda <= 0.0:
        return 1.0 if k == 0 else 0.0
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)


def tau_dixon_coles(x: int, y: int, lambda_h: float, lambda_a: float, rho: float = -0.06) -> float:
    """Dixon-Coles adjustment factor for low-scoring match correlation (x, y <= 1)."""
    if x == 0 and y == 0:
        return max(0.01, 1.0 - lambda_h * lambda_a * rho)
    elif x == 0 and y == 1:
        return max(0.01, 1.0 + lambda_h * rho)
    elif x == 1 and y == 0:
        return max(0.01, 1.0 + lambda_a * rho)
    elif x == 1 and y == 1:
        return max(0.01, 1.0 - rho)
    return 1.0


def estimate_lambdas_from_odds(
    odds_1x2: tuple[float, float, float] | None,
    odds_ou25: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """Derive home and away expected goals (lambda_h, lambda_a) from 1X2 and 2.5 Over/Under odds.

    Uses implied probabilities with overround removal and goal-supremacy solving.
    """
    # Baseline defaults if odds not available
    base_total = 2.65
    p_h = 0.42
    p_a = 0.30

    if odds_ou25 and odds_ou25[0] > 1.01 and odds_ou25[1] > 1.01:
        inv_o = 1.0 / odds_ou25[0]
        inv_u = 1.0 / odds_ou25[1]
        p_over = inv_o / (inv_o + inv_u)
        # Map p_over (0.30 to 0.70) to total expected goals (1.80 to 3.60)
        base_total = max(1.60, min(3.80, 1.80 + (p_over - 0.35) * 4.5))

    if odds_1x2 and len(odds_1x2) == 3 and all(o > 1.01 for o in odds_1x2):
        inv_1 = 1.0 / odds_1x2[0]
        inv_x = 1.0 / odds_1x2[1]
        inv_2 = 1.0 / odds_1x2[2]
        total_inv = inv_1 + inv_x + inv_2
        p_h = inv_1 / total_inv
        p_a = inv_2 / total_inv

    # Split base_total between home and away proportional to win probability strength
    ratio = max(0.20, min(0.80, (p_h + 0.15) / (p_h + p_a + 0.30)))
    lambda_h = round(max(0.40, min(3.50, base_total * ratio)), 2)
    lambda_a = round(max(0.30, min(3.20, base_total * (1.0 - ratio))), 2)

    return lambda_h, lambda_a


def compute_bivariate_score_matrix(
    lambda_h: float,
    lambda_a: float,
    rho: float = -0.06,
    max_goals: int = 7,
) -> dict[tuple[int, int], float]:
    """Calculate exact Dixon-Coles 2D probability matrix for scores (x, y)."""
    matrix: dict[tuple[int, int], float] = {}
    total_prob = 0.0

    for x in range(max_goals + 1):
        for y in range(max_goals + 1):
            base_p = poisson_pmf(x, lambda_h) * poisson_pmf(y, lambda_a)
            adj = tau_dixon_coles(x, y, lambda_h, lambda_a, rho)
            p = base_p * adj
            matrix[(x, y)] = p
            total_prob += p

    # Normalize matrix to 1.0
    if total_prob > 0.0:
        for k in matrix:
            matrix[k] /= total_prob

    return matrix


def price_htft_transitions(
    lambda_h: float,
    lambda_a: float,
    nesine_htft: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Calculate exact theoretical probabilities and edges for all 9 HT/FT outcomes.

    Assumes ~44% of expected goals occur in the 1st half and ~56% in the 2nd half.
    """
    l_h1 = lambda_h * 0.44
    l_a1 = lambda_a * 0.44
    l_h2 = lambda_h * 0.56
    l_a2 = lambda_a * 0.56

    m1 = compute_bivariate_score_matrix(l_h1, l_a1, max_goals=5)
    m2 = compute_bivariate_score_matrix(l_h2, l_a2, max_goals=5)

    # 9 HT/FT transition probabilities
    htft_probs = dict.fromkeys(HTFT_LABELS.values(), 0.0)

    for (x1, y1), p1 in m1.items():
        ht_res = "1" if x1 > y1 else ("2" if y1 > x1 else "X")
        for (x2, y2), p2 in m2.items():
            total_x = x1 + x2
            total_y = y1 + y2
            ft_res = "1" if total_x > total_y else ("2" if total_y > total_x else "X")
            lbl = f"{ht_res}/{ft_res}"
            if lbl in htft_probs:
                htft_probs[lbl] += p1 * p2

    results: dict[str, Any] = {}
    for lbl, prob in htft_probs.items():
        fair_odd = round(1.0 / prob, 2) if prob > 0.0001 else 999.0
        book_odd = nesine_htft.get(lbl) if nesine_htft else None
        edge_pct = round(((book_odd / fair_odd) - 1.0) * 100, 2) if book_odd and fair_odd < 999.0 else None

        results[lbl] = {
            "label": lbl,
            "prob": round(prob, 4),
            "fair_odds": fair_odd,
            "book_odds": book_odd,
            "edge_pct": edge_pct,
        }

    return results


def parse_high_odds_markets(market_array: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract HT/FT, IY KG Var, and TG 6+ from Nesine Market Array (MA)."""
    result: dict[str, Any] = {
        "htft": {},
        "tg6": None,
        "iy_kg_var": None,
        "correct_scores": [],
    }

    for m in market_array:
        mtid = m.get("MTID")
        oca = {o.get("N"): float(o.get("O") or 0.0) for o in m.get("OCA", [])}

        # MTID 5: HT/FT
        if mtid == 5:
            for idx, lbl in HTFT_LABELS.items():
                val = oca.get(idx)
                if val and val > 1.01:
                    result["htft"][lbl] = val

        # MTID 43: TG Bands (N:4 is 6+ or 7+)
        elif mtid == 43:
            val = oca.get(4)
            if val and val > 1.01:
                result["tg6"] = val

        # MTID 225: First Half BTTS (N:1 is Var)
        elif mtid == 225:
            val = oca.get(1)
            if val and val > 1.01:
                result["iy_kg_var"] = val

        # MTID 777: Correct Score
        elif mtid == 777:
            for oc in m.get("OCA", []):
                nm = oc.get("ON")
                odd = float(oc.get("O") or 0.0)
                if nm and odd > 1.01:
                    result["correct_scores"].append({"score": nm, "odd": odd})

    if result["correct_scores"]:
        result["correct_scores"].sort(key=lambda x: x["odd"])
        result["correct_scores"] = result["correct_scores"][:6]

    return result


def find_high_value_longshots(
    fixture_name: str,
    league: str,
    high_odds: dict[str, Any],
    odds_1x2: tuple[float, float, float] | None = None,
    odds_ou25: tuple[float, float] | None = None,
) -> list[dict[str, Any]]:
    """Detect compelling high-odds candidates based on tactical match context and quantitative pricing."""
    candidates: list[dict[str, Any]] = []

    # Estimate match lambdas
    lambda_h, lambda_a = estimate_lambdas_from_odds(odds_1x2, odds_ou25)
    score_matrix = compute_bivariate_score_matrix(lambda_h, lambda_a)
    htft_eval = price_htft_transitions(lambda_h, lambda_a, high_odds.get("htft"))

    # 1. Evaluate HT/FT Longshots (X/1, X/2, 2/1, 1/2)
    htft = high_odds.get("htft", {})
    if htft:
        # Check X/1 (Draw HT / Home FT)
        home_odd = odds_1x2[0] if odds_1x2 else None
        x1_info = htft_eval.get("X/1")
        x1_odd = htft.get("X/1")
        if x1_odd and home_odd and 1.35 <= home_odd <= 1.85 and x1_odd >= 4.0:
            f_odd = x1_info["fair_odds"] if x1_info else round(home_odd * 2.8, 2)
            edge = x1_info["edge_pct"] if x1_info else 0.0
            prob = x1_info["prob"] if x1_info else round(1.0 / f_odd, 4)
            candidates.append({
                "match": fixture_name,
                "league": league,
                "market": "İlk Yarı / Maç Sonu",
                "selection": "X/1 (İY 0 / MS 1)",
                "odds": x1_odd,
                "fair_odds": f_odd,
                "edge_pct": edge,
                "prob": prob,
                "type": "HT_FT",
                "logic": f"Ev sahibi favori ({home_odd:.2f}) fakat ilk yarı düşük tempo, X/1 @ {x1_odd:.2f} (Adil: {f_odd:.2f}).",
            })

        # Check X/2 (Draw HT / Away FT)
        away_odd = odds_1x2[2] if odds_1x2 else None
        x2_odd = htft.get("X/2")
        x2_info = htft_eval.get("X/2")
        if x2_odd and away_odd and 1.35 <= away_odd <= 1.95 and x2_odd >= 4.5:
            f_odd = x2_info["fair_odds"] if x2_info else round(away_odd * 2.8, 2)
            edge = x2_info["edge_pct"] if x2_info else 0.0
            prob = x2_info["prob"] if x2_info else round(1.0 / f_odd, 4)
            candidates.append({
                "match": fixture_name,
                "league": league,
                "market": "İlk Yarı / Maç Sonu",
                "selection": "X/2 (İY 0 / MS 2)",
                "odds": x2_odd,
                "fair_odds": f_odd,
                "edge_pct": edge,
                "prob": prob,
                "type": "HT_FT",
                "logic": f"Deplasman favori ({away_odd:.2f}), ilk yarı direnç ve ikinci yarı çözüm @ {x2_odd:.2f}.",
            })

        # Check 2/1 or 1/2 Mega Comebacks (Odds usually >= 20.0)
        c21_odd = htft.get("2/1")
        if c21_odd and c21_odd >= 20.0:
            c21_info = htft_eval.get("2/1")
            candidates.append({
                "match": fixture_name,
                "league": league,
                "market": "İlk Yarı / Maç Sonu",
                "selection": "2/1 (İY 2 / MS 1)",
                "odds": c21_odd,
                "fair_odds": c21_info["fair_odds"] if c21_info else 25.0,
                "edge_pct": c21_info["edge_pct"] if c21_info else 0.0,
                "prob": c21_info["prob"] if c21_info else 0.04,
                "type": "HT_FT",
                "logic": f"Yüksek oranlı geri dönüş bahsi @ {c21_odd:.2f}.",
            })

    # 2. Evaluate First Half BTTS (İY KG Var)
    iy_kg = high_odds.get("iy_kg_var")
    over25_odd = odds_ou25[0] if odds_ou25 else None
    if iy_kg and ((over25_odd and over25_odd <= 1.55 and iy_kg >= 3.20) or iy_kg >= 3.0):
        p_iy_kg = (1.0 - math.exp(-lambda_h * 0.44)) * (1.0 - math.exp(-lambda_a * 0.44))
        fair_iy_kg = round(1.0 / p_iy_kg, 2) if p_iy_kg > 0.01 else 99.0
        edge_iy_kg = round(((iy_kg / fair_iy_kg) - 1.0) * 100, 2)

        odd_desc = f"{over25_odd:.2f}" if over25_odd else ""
        candidates.append({
            "match": fixture_name,
            "league": league,
            "market": "İlk Yarı KG",
            "selection": "İY Karşılıklı Gol Var",
            "odds": iy_kg,
            "fair_odds": fair_iy_kg,
            "edge_pct": edge_iy_kg,
            "prob": round(p_iy_kg, 4),
            "type": "IY_KG",
            "logic": f"Yüksek tempolu 2.5 Üst maçı ({odd_desc}), erken gol olasılığı yüksek @ {iy_kg:.2f}.",
        })

    # 3. Evaluate TG 6+ (Goal Explosion)
    tg6 = high_odds.get("tg6")
    if tg6:
        p_tg6 = sum(prob for (x, y), prob in score_matrix.items() if (x + y) >= 6)
        fair_tg6 = round(1.0 / p_tg6, 2) if p_tg6 > 0.001 else 999.0
        edge_tg6 = round(((tg6 / fair_tg6) - 1.0) * 100, 2) if fair_tg6 < 999.0 else None

        if tg6 >= 7.0 and (edge_tg6 is None or edge_tg6 >= -20.0):
            candidates.append({
                "match": fixture_name,
                "league": league,
                "market": "Toplam Gol",
                "selection": "6+ Gol (TG 6+)",
                "odds": tg6,
                "fair_odds": fair_tg6,
                "edge_pct": edge_tg6 or 0.0,
                "prob": round(p_tg6, 4),
                "type": "TG_6PLUS",
                "logic": f"Aşırı yüksek gol beklentili fikstür (Model %{p_tg6*100:.1f}) @ {tg6:.2f}.",
            })

    # 4. Evaluate Correct Scores
    correct_scores = high_odds.get("correct_scores") or []
    for cs in correct_scores:
        sc_str = cs.get("score", "").replace(":", "-").strip()
        odd = cs.get("odd", 0.0)
        parts = sc_str.split("-")
        if len(parts) == 2 and odd >= 5.0:
            try:
                hx, ay = int(parts[0]), int(parts[1])
                p_score = score_matrix.get((hx, ay), 0.0)
                if p_score > 0.04:  # At least 4% probability
                    fair_cs = round(1.0 / p_score, 2)
                    edge_cs = round(((odd / fair_cs) - 1.0) * 100, 2)
                    if edge_cs >= -5.0:
                        candidates.append({
                            "match": fixture_name,
                            "league": league,
                            "market": "Doğru Skor",
                            "selection": f"Skor {hx}-{ay}",
                            "odds": odd,
                            "fair_odds": fair_cs,
                            "edge_pct": edge_cs,
                            "prob": round(p_score, 4),
                            "type": "CORRECT_SCORE",
                            "logic": f"Yüksek olasılıklı skor kümesi (%{p_score*100:.1f}) @ {odd:.2f} (Adil: {fair_cs:.2f}).",
                        })
            except Exception:
                pass

    return candidates


def generate_system_coupon(
    selections: list[dict[str, Any]],
    k_combos: tuple[int, ...] = (2, 3),
    unit_stake: float = 10.0,
) -> dict[str, Any]:
    """Calculate system parlay matrix (e.g. Sistem 2-3 out of N selections)."""
    n = len(selections)
    if n < 2:
        return {"error": "En az 2 seçim gereklidir"}

    total_combinations = 0
    sub_combos: dict[str, list[dict[str, Any]]] = {}

    for k in k_combos:
        if k > n:
            continue
        k_list = list(itertools.combinations(range(n), k))
        total_combinations += len(k_list)
        rendered_k = []
        for combo in k_list:
            combined_odds = math.prod(selections[i]["odds"] for i in combo)
            payout = combined_odds * unit_stake
            names = [f"{selections[i]['match']} ({selections[i]['selection']})" for i in combo]
            rendered_k.append({
                "indices": list(combo),
                "combined_odds": round(combined_odds, 2),
                "payout": round(payout, 2),
                "picks": names,
            })
        sub_combos[f"sistem_{k}"] = rendered_k

    total_cost = total_combinations * unit_stake
    max_payout = sum(
        sum(item["payout"] for item in items)
        for items in sub_combos.values()
    )

    # Calculate minimum 2-hit payout to check safety cushion
    min_2hit_payout = 0.0
    if "sistem_2" in sub_combos and sub_combos["sistem_2"]:
        min_2hit_payout = min(item["payout"] for item in sub_combos["sistem_2"])

    return {
        "n_picks": n,
        "k_combos": list(k_combos),
        "total_combinations": total_combinations,
        "unit_stake": unit_stake,
        "total_cost": round(total_cost, 2),
        "max_payout": round(max_payout, 2),
        "min_2hit_payout": round(min_2hit_payout, 2),
        "safety_margin_pct": round(((min_2hit_payout - total_cost) / total_cost) * 100, 2) if total_cost > 0 else 0.0,
        "combos": sub_combos,
    }
