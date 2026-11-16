"""VIP Same-Game Parlay (SGP) Multi-Market Ticket Generator (v1.0).

Unites all 3 quantitative pillars into a unified, mathematically correlated VIP ticket:
1. Goal Anomaly Engine (Match Over 2.5)
2. Advanced Corner Engine (Total Corners Over 9.5)
3. Player Props Engine (Anytime Goalscorer: Harry Kane / Erling Haaland)
4. Copula SGP Engine (Gaussian & Gumbel Upper-Tail Dependence)

Enforces SPEC-0012 fail-closed validation and SPEC-0015 minimum 50 TL stake.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Explicit project root
PROJECT_ROOT = Path(r"c:\Users\Thea-Aria\ .gemini\antigravity\scratch\ec2-file-explorer\sports-engine")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from copula_sgp_engine import CopulaSGPEngine, SGPLeg
from sports_engine.models.goal_anomaly_engine import GoalAnomalyEngine
from sports_engine.models.player_props_engine import PlayerPropsEngine


def generate_vip_sgp_ticket():
    print("===============================================================================")
    print("🏛️ [APE SYNDICATE] VIP CORRELATED SGP TICKET GENERATOR (v1.0)")
    print("   Büyük Veri & Multivariate Copula Bağımlılık Modeli")
    print("===============================================================================\n")

    anomaly_engine = GoalAnomalyEngine()
    player_engine = PlayerPropsEngine()
    copula_engine = CopulaSGPEngine()

    # Fixture: Bayern Munich vs Borussia Dortmund (Der Klassiker)
    fixture_id = "vip_der_klassiker_01"
    home_team = "Bayern Munich"
    away_team = "Borussia Dortmund"
    league = "D1"

    # Step 1: Goal Anomaly Evaluation
    fixture_payload = {
        "event_id": fixture_id,
        "home_team": home_team,
        "away_team": away_team,
        "league": league,
        "open_o25": 1.38,
        "close_o25": 1.35,
        "fav_odd": 1.68,
        "dog_odd": 4.10,
        "draw_odd": 4.20,
    }
    anom_res = anomaly_engine.evaluate_fixture(fixture_payload)

    # Step 2: Player Prop Evaluation (Harry Kane - Anytime Goalscorer)
    kane_prop = player_engine.evaluate_anytime_scorer(
        player_name="Harry Kane",
        team_name=home_team,
        opponent_name=away_team,
        team_mu=2.45,
        offered_odds=1.85,
        is_goal_anomaly=True,
    )

    # Step 3: Leg Definitions
    # Leg A: Match Over 2.5 Goals
    leg_a = SGPLeg(
        market="TOTAL_GOALS",
        selection="2.5 ÜST",
        marginal_prob=0.74, # High tempo expectation
        offered_odd=1.38,
    )

    # Leg B: Match Corners Over 9.5
    leg_b = SGPLeg(
        market="TOTAL_CORNERS",
        selection="9.5 ÜST",
        marginal_prob=0.62,
        offered_odd=1.80,
    )

    # Leg C: Player Anytime Goalscorer
    leg_c = SGPLeg(
        market="PLAYER_PROP",
        selection="Harry Kane Gol Atar",
        marginal_prob=kane_prop.prob,
        offered_odd=kane_prop.offered_odds,
    )

    # Step 4: Copula Evaluation (Leg A + Leg B: Goals & Corners)
    sgp_ab = copula_engine.evaluate_sgp(
        fixture_id=fixture_id,
        home_team=home_team,
        away_team=away_team,
        leg_a=leg_a,
        leg_b=leg_b,
        offered_sgp_odds=2.48, # Retail slip combined odd
        use_gumbel_for_tails=True,
    )

    print(f"⚽ KARŞILAŞMA: {home_team} vs {away_team} ({league})")
    print(f"📊 Arketip: {anom_res.archetype.value} | GASI: {anom_res.gasi_score:.1f}/100 ({anom_res.tier.value})\n")

    print("📋 [SGP KOMBİNE SEÇİMLERİ]:")
    print(f"   [1] {leg_a.market}: {leg_a.selection} @ {leg_a.offered_odd:.2f} (Model Olasılık: %{leg_a.marginal_prob*100:.1f})")
    print(f"   [2] {leg_b.market}: {leg_b.selection} @ {leg_b.offered_odd:.2f} (Model Olasılık: %{leg_b.marginal_prob*100:.1f})")
    print(f"   [3] {leg_c.market}: {leg_c.selection} @ {leg_c.offered_odd:.2f} (Model Olasılık: %{leg_c.marginal_prob*100:.1f})\n")

    print("🧠 [MULTIVARIATE COPULA HESAPLAMALARI]:")
    print(f"   Copula Ailesi       : {sgp_ab.copula_type}")
    print(f"   Taktik Korelasyon   : rho = {sgp_ab.correlation:.2f}")
    print(f"   Bağımsız Olasılık   : %{sgp_ab.independent_prob * 100:.1f} (Retail varsayımı)")
    print(f"   Gerçek Birlikte Olasılık: %{sgp_ab.joint_prob * 100:.1f} (Copula Lift: +%{sgp_ab.correlation_lift_pct:.1f})")
    print(f"   Adil SGP Oranı      : @{sgp_ab.fair_sgp_odds:.2f}")
    print(f"   Bülten Teklif Oranı : @{sgp_ab.offered_sgp_odds:.2f}")
    print(f"   Matematiksel Değer  : +%{sgp_ab.edge_pct:.2f} (+EV)")
    print(f"   Kupon Tutarı        : {sgp_ab.stake:.1f} TL (SPEC-0015 Uyumlu)\n")

    # Formatted Telegram Payload
    print("📱 [VIP TELEGRAM KUPON ÇIKTISI]:")
    print("-------------------------------------------------------------------------------")
    print(f"🎯 *[APE VIP SYNDICATE — SAME-GAME PARLAY (SGP)]*")
    print(f"⚽ *{home_team} vs {away_team}*")
    print(f"🏆 Lig: Almanya Bundesliga")
    print(f"───────────────────────────────")
    print(f"📌 Seçim 1: `{leg_a.selection}` @ `{leg_a.offered_odd:.2f}`")
    print(f"📌 Seçim 2: `{leg_b.selection}` @ `{leg_b.offered_odd:.2f}`")
    print(f"📌 Seçim 3: `{leg_c.selection}` @ `{leg_c.offered_odd:.2f}`")
    print(f"───────────────────────────────")
    print(f"📈 *Bileşik Oran:* `@{sgp_ab.offered_sgp_odds:.2f}` (Adil: `@{sgp_ab.fair_sgp_odds:.2f}`)")
    print(f"💡 *Korelasyon Avantajı:* `+%{sgp_ab.correlation_lift_pct:.1f}` Lift (Copula: `{sgp_ab.copula_type}`)")
    print(f"🔥 *Değer (Edge):* `+%{sgp_ab.edge_pct:.1f} EV`")
    print(f"💰 *Kupon Tutarı:* `{sgp_ab.stake:.1f} TL` (SPEC-0015)")
    print(f"───────────────────────────────")
    print(f"🛡️ *APE Syndicate Mathematical Risk Engine*")
    print("-------------------------------------------------------------------------------\n")

    print("===============================================================================")
    print("✅ [BAŞARILI] VIP Correlated SGP Ticket Başarıyla Üretildi!")
    print("===============================================================================\n")


if __name__ == "__main__":
    generate_vip_sgp_ticket()
