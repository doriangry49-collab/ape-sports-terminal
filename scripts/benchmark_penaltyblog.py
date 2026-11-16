import sys
import math
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "src"))

import penaltyblog.implied as pbi
from stale_line_scanner import devig_power, devig_shin
from advanced_corner_model import neg_binomial_cdf, neg_binomial_pmf

print("=== 1. SHIN DEVIGGING COMPARISON ===")
test_odds_sets = [
    (1.50, 4.20, 6.50),
    (2.10, 3.40, 3.50),
    (1.15, 7.50, 19.00),
    (3.20, 3.40, 2.25)
]

for odds in test_odds_sets:
    # Our engine devig_shin returns list of fair probabilities
    our_probs = tuple(round(p, 5) for p in devig_shin(odds))
    
    # penaltyblog shin
    pb_res = pbi.calculate_implied(list(odds), method="shin")
    pb_probs = tuple(round(p, 5) for p in pb_res.probabilities)
    
    diff = max(abs(a - b) for a, b in zip(our_probs, pb_probs))
    z_val = pb_res.method_params.get("z", 0.0) if pb_res.method_params else 0.0
    print(f"Odds: {odds} | Our: {our_probs} | PB: {pb_probs} | Diff: {diff:.6f} | z: {z_val:.4f} | Pass: {diff < 0.005}")

print("\n=== 2. POWER DEVIGGING COMPARISON ===")
for odds in test_odds_sets:
    # Our engine devig_power returns list of fair probabilities
    our_probs_p = tuple(round(p, 5) for p in devig_power(odds))
    
    # penaltyblog power
    pb_p = pbi.calculate_implied(list(odds), method="power")
    pb_probs_p = tuple(round(p, 5) for p in pb_p.probabilities)
    
    diff_p = max(abs(a - b) for a, b in zip(our_probs_p, pb_probs_p))
    k_val = pb_p.method_params.get("k", 0.0) if pb_p.method_params else 0.0
    print(f"Odds: {odds} | Our: {our_probs_p} | PB: {pb_probs_p} | Diff: {diff_p:.6f} | k: {k_val:.4f} | Pass: {diff_p < 0.005}")

print("\n=== 3. NEGATIVE BINOMIAL CORNER MATH COMPARISON ===")
import scipy.stats as stats
test_mus = [8.5, 9.85, 11.2]
all_nb_pass = True
for mu in test_mus:
    k_targets = [7, 9, 11]
    for k in k_targets:
        our_pmf = neg_binomial_pmf(k, mu, 0.14)
        our_cdf = neg_binomial_cdf(k, mu, 0.14)
        
        # Scipy exact Negative Binomial:
        r = 1.0 / 0.14
        p = 1.0 / (1.0 + 0.14 * mu)
        scipy_pmf = stats.nbinom.pmf(k, r, p)
        scipy_cdf = stats.nbinom.cdf(k, r, p)
        
        diff_pmf = abs(our_pmf - scipy_pmf)
        diff_cdf = abs(our_cdf - scipy_cdf)
        match = diff_pmf < 1e-5 and diff_cdf < 1e-5
        if not match:
            all_nb_pass = False
        print(f"Mu: {mu}, k: {k} | PMF Diff: {diff_pmf:.8f} | CDF Diff: {diff_cdf:.8f} | Pass: {match}")

print(f"\nAll Negative Binomial Tests Passed: {all_nb_pass}")
print("=== BENCHMARK SUITE COMPLETE ===")
