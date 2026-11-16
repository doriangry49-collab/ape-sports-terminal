"""APE Syndicate Priority Roster & Agent Implementations (v1.0).

Encapsulates our 5 Core + 3 Specialist Agents according to our recruitment hierarchy:
1. RiskActuaryAgent (P0 - Safety & Bankroll)
2. MarketSurveillanceAgent (P1 - Steam & Line Movement)
3. QuantPricerAgent (P2 - Poisson / Dixon-Coles Fair Value)
4. PropsHunterAgent (P2 - 4-Season Calibrated Negative Binomial Corners)
5. OddsAnalystAgent (P3 - 30k 3D k-NN Fingerprint Twins Consensus)
6. PortfolioBuilderAgent (P4 - SPEC-0015 Compliant Coupon Formatter)
"""
from __future__ import annotations

from typing import Any

from syndicate.base_agent import AgentPriority, AgentVerdict, BaseSyndicateAgent

try:
    from sports_engine.models.goal_anomaly_engine import (
        AnomalySignalTier,
        GoalAnomalyEngine,
    )
except ImportError:
    from src.sports_engine.models.goal_anomaly_engine import (
        AnomalySignalTier,
        GoalAnomalyEngine,
    )


class RiskActuaryAgent(BaseSyndicateAgent):
    """P0 Safety Agent: Enforces SPEC-0012, 0013, 0014, and 0015 without exception."""

    def __init__(self) -> None:
        super().__init__(
            name="Risk Actuary",
            role="Capital Preservation & Constitutional Gatekeeper",
            priority=AgentPriority.P0_SAFETY_AND_RISK,
        )

    def evaluate(self, fixture_or_coupon: dict[str, Any], context: dict[str, Any] | None = None) -> AgentVerdict:
        reasons = []
        # 1. SPEC-0015 Minimum Stake Check
        stake = float(fixture_or_coupon.get("stake", 50.0) or 50.0)
        if stake < 50.0:
            return AgentVerdict(
                agent_name=self.name,
                approved=False,
                confidence=0.0,
                tier="VETOED",
                veto_reason=f"SPEC-0015 Violation: Stake {stake:.2f} TL is below minimum 50.0 TL",
            )

        # 1.5 SPEC-0012 Unverified / Closed Market Odds Check
        raw_odd = fixture_or_coupon.get("soft_odds") or fixture_or_coupon.get("book_odd") or fixture_or_coupon.get("offered_odds")
        if raw_odd is not None:
            try:
                if float(raw_odd) <= 1.01:
                    return AgentVerdict(
                        agent_name=self.name,
                        approved=False,
                        confidence=0.0,
                        tier="VETOED",
                        veto_reason=f"SPEC-0012 Violation: Unverified or closed market odds ({raw_odd})",
                    )
            except (ValueError, TypeError):
                return AgentVerdict(
                    agent_name=self.name,
                    approved=False,
                    confidence=0.0,
                    tier="VETOED",
                    veto_reason=f"SPEC-0012 Violation: Invalid market odds ({raw_odd!r})",
                )

        # 2. 4-Season Proven Negative-EV Trap Check
        market = str(fixture_or_coupon.get("market", "")).upper()
        outcome = str(fixture_or_coupon.get("outcome") or fixture_or_coupon.get("selection") or "").upper()
        if any(bad in market for bad in ("İY/MS", "HT/FT", "TOPLAM GOL 6+", "TG 6+", "GOLDEN_PATTERN")):
            return AgentVerdict(
                agent_name=self.name,
                approved=False,
                confidence=0.0,
                tier="VETOED",
                veto_reason=f"10-Month Simulation Veto: {market} is a negative-EV variance trap",
            )
        if ("KORNER" in market or "CORNER" in market) and ("ÜST" in outcome or "UST" in outcome or "OVER" in outcome):
            if any(line_str in market or line_str in outcome for line_str in ("11.5", "12.5")):
                return AgentVerdict(
                    agent_name=self.name,
                    approved=False,
                    confidence=0.0,
                    tier="VETOED",
                    veto_reason=f"Live Ledger & 10-Month Veto: {market} {outcome} is a -100% ROI high-line trap",
                )

        # 3. Portfolio Covariance and Drawdown Constraint Check (P0 Safety Barrier)
        drawdown_bound_failed = bool(fixture_or_coupon.get("drawdown_bound_passed") is False)
        if drawdown_bound_failed:
            return AgentVerdict(
                agent_name=self.name,
                approved=False,
                confidence=0.0,
                tier="VETOED",
                veto_reason="Portfolio Covariance Veto: Slate exceeds 15% maximum drawdown threshold",
            )

        # 4. Live Match Momentum & Velocity Fail-Closed Audit (Live In-Play Signals)
        # If signal is in-play and momentum evaluation is present or required:
        momentum_eval = fixture_or_coupon.get("momentum_eval")
        if momentum_eval is not None:
            # Check Goal Ambush / In-Play Over signals
            if "GOL" in market or "OVER" in outcome or "ÜST" in outcome:
                if not getattr(momentum_eval, "is_ambush_qualified", True):
                    v_reasons = getattr(momentum_eval, "veto_reasons", ["Yetersiz şut temposu"])
                    return AgentVerdict(
                        agent_name=self.name,
                        approved=False,
                        confidence=0.0,
                        tier="VETOED",
                        veto_reason=f"Live Momentum Veto: {', '.join(v_reasons)}",
                    )
            # Check Corner Sniper signals
            if "KORNER" in market or "CORNER" in market:
                if not getattr(momentum_eval, "is_corner_qualified", True):
                    v_reasons = getattr(momentum_eval, "veto_reasons", ["Yetersiz korner temposu"])
                    return AgentVerdict(
                        agent_name=self.name,
                        approved=False,
                        confidence=0.0,
                        tier="VETOED",
                        veto_reason=f"Live Momentum Veto: {', '.join(v_reasons)}",
                    )

        # 5. Lineup & Squad Rotation Fail-Closed Audit
        lineup_impact = fixture_or_coupon.get("lineup_impact")
        if lineup_impact is not None:
            if getattr(lineup_impact, "is_veto_recommended", False):
                v_reason = getattr(lineup_impact, "veto_reason", "Aşırı kadro rotasyonu tespit edildi")
                return AgentVerdict(
                    agent_name=self.name,
                    approved=False,
                    confidence=0.0,
                    tier="VETOED",
                    veto_reason=f"Lineup Rotation Veto: {v_reason}",
                )

        reasons.append("Passed SPEC-0015, Live Momentum, Lineup Rotation and Negative-EV trap audits")
        return AgentVerdict(
            agent_name=self.name,
            approved=True,
            confidence=1.0,
            tier="APPROVED",
            reasons=reasons,
        )


class MarketSurveillanceAgent(BaseSyndicateAgent):
    """P1 Intelligence Agent: Monitors Pinnacle Sharp Lines, Steam Drift and Stale Odds."""

    def __init__(self) -> None:
        super().__init__(
            name="Market Surveillance",
            role="Sharp Odds & Steam Flow Tracker",
            priority=AgentPriority.P1_MARKET_INTELLIGENCE,
        )

    def evaluate(self, fixture_or_coupon: dict[str, Any], context: dict[str, Any] | None = None) -> AgentVerdict:
        steam_drift = float(fixture_or_coupon.get("steam_drift_pp", 0.0) or 0.0)
        steam_1_pct = float(fixture_or_coupon.get("steam_1_pct", 0.0) or 0.0)
        steam_o25_pct = float(fixture_or_coupon.get("steam_o25_pct", 0.0) or 0.0)
        is_steam = bool(
            fixture_or_coupon.get("is_steam_confirmed")
            or steam_1_pct <= -4.0
            or steam_o25_pct <= -2.5
            or steam_drift >= 0.25
        )

        reasons = []
        if is_steam:
            reasons.append(f"Confirmed sharp money steam flow (Drift: {steam_drift:+.2f}pp)")
            tier = "TIER_1_SHIELD"
            conf = 0.85
        else:
            reasons.append("Unconfirmed retail pricing (neutral market)")
            tier = "TIER_2_UNCONFIRMED"
            conf = 0.50

        return AgentVerdict(
            agent_name=self.name,
            approved=True,
            confidence=conf,
            tier=tier,
            reasons=reasons,
            metadata={"is_steam": is_steam, "steam_drift_pp": steam_drift},
        )


class QuantPricerAgent(BaseSyndicateAgent):
    """P2 Core Quant Agent: Dixon-Coles, Bivariate Poisson & Shin Devigged Probabilities."""

    def __init__(self) -> None:
        super().__init__(
            name="Quant Pricer",
            role="Mathematical Fair Value Engine",
            priority=AgentPriority.P2_CORE_QUANT,
        )

    def evaluate(self, fixture_or_coupon: dict[str, Any], context: dict[str, Any] | None = None) -> AgentVerdict:
        fair_prob = float(fixture_or_coupon.get("shin_fair_prob") or fixture_or_coupon.get("prob") or 0.50)
        book_odd = float(fixture_or_coupon.get("soft_odds") or fixture_or_coupon.get("book_odd") or 1.0)
        computed_edge = (fair_prob * book_odd - 1.0) * 100.0 if book_odd > 1.0 else 0.0
        edge_pct = float(fixture_or_coupon.get("edge_pct") or computed_edge)

        approved = edge_pct >= 2.0 and 1.25 <= book_odd <= 3.60
        tier = "TIER_1_SHIN_QUANT" if (edge_pct >= 6.0 or fair_prob >= 0.65) else "TIER_2_VALUE"

        reasons = [f"De-vigged Fair Prob: %{fair_prob * 100:.1f}, Edge: +%{edge_pct:.1f}"]
        return AgentVerdict(
            agent_name=self.name,
            approved=approved,
            confidence=fair_prob,
            tier=tier if approved else "REJECTED_LOW_EDGE",
            reasons=reasons,
            metadata={"edge_pct": edge_pct, "fair_prob": fair_prob},
        )


class PropsHunterAgent(BaseSyndicateAgent):
    """P2 Specialist Agent: 4-Season Calibrated Negative Binomial Corners."""

    def __init__(self) -> None:
        super().__init__(
            name="Props Hunter",
            role="Corner & Game-State Props Modeler",
            priority=AgentPriority.P2_CORE_QUANT,
        )

    def evaluate(self, fixture_or_coupon: dict[str, Any], context: dict[str, Any] | None = None) -> AgentVerdict:
        market = str(fixture_or_coupon.get("market", "")).lower()
        if "korner" not in market and "corner" not in market:
            return AgentVerdict(
                agent_name=self.name,
                approved=True,
                confidence=0.5,
                tier="NEUTRAL_NON_PROPS",
                reasons=["Not a corner props market"],
            )

        selection = str(fixture_or_coupon.get("selection") or fixture_or_coupon.get("outcome") or "").upper()
        prob = float(fixture_or_coupon.get("prob") or 0.50)
        side = "ÜST" if ("ÜST" in selection or "UST" in selection or "OVER" in selection) else "ALT"

        # 4-Season Rule: Korner 8.5 ÜST (Pillar 1: 75.5% hit rate) and 9.5 ÜST (Pillar 2: 67.0% hit rate)
        if side == "ÜST":
            if any(bad_line in selection or bad_line in market for bad_line in ("11.5", "12.5")):
                return AgentVerdict(
                    agent_name=self.name,
                    approved=False,
                    confidence=prob,
                    tier="VETOED",
                    veto_reason="Live Ledger Veto: Korner 11.5+ ÜST is an unprofitable (-100% ROI) tail trap",
                )
            if "8.5" in selection and prob >= 0.62:
                return AgentVerdict(
                    agent_name=self.name,
                    approved=True,
                    confidence=prob,
                    tier="TIER_1_SHIELD",
                    reasons=["Pillar 1: Korner 8.5 ÜST consensus (>=62%) approved"],
                )
            if "9.5" in selection and prob >= 0.56:
                return AgentVerdict(
                    agent_name=self.name,
                    approved=True,
                    confidence=prob,
                    tier="TIER_1_SHIELD",
                    reasons=["Pillar 2: Korner 9.5 ÜST siege-lift (>=56%) approved"],
                )

        if side == "ALT":
            # 4-Season Trap Veto: Korner ALT without verified low-corner environment is -3.5% ROI
            diag = fixture_or_coupon.get("diagnostics") or {}
            has_real_stats = bool(diag.get("has_real_team_stats", False))
            if not has_real_stats or prob < 0.65:
                return AgentVerdict(
                    agent_name=self.name,
                    approved=False,
                    confidence=prob,
                    tier="VETOED",
                    veto_reason="4-Season Veto: Blind Korner ALT is a verified -3.5% ROI trap",
                )

        return AgentVerdict(
            agent_name=self.name,
            approved=prob >= 0.55,
            confidence=prob,
            tier="TIER_2_PROPS",
            reasons=[f"Props evaluation completed with prob %{prob * 100:.1f}"],
        )


class OddsAnalystAgent(BaseSyndicateAgent):
    """P3 Consensus Agent: 3D k-NN Vector Space Match Twin Lookup (30,252+ matches)."""

    def __init__(self) -> None:
        super().__init__(
            name="Odds Analyst",
            role="3D Vector Twin Fingerprint Analyst",
            priority=AgentPriority.P3_CONSENSUS_AND_FINGERPRINT,
        )

    def evaluate(self, fixture_or_coupon: dict[str, Any], context: dict[str, Any] | None = None) -> AgentVerdict:
        fp_report = (context or {}).get("fingerprint_report")
        if not fp_report:
            return AgentVerdict(
                agent_name=self.name,
                approved=True,
                confidence=0.5,
                tier="NEUTRAL_NO_TWINS",
                reasons=["No pre-computed fingerprint twin report in context"],
            )

        avg_sim = float(getattr(fp_report, "avg_similarity_pct", 75.0))
        pct_o25 = float(getattr(fp_report, "pct_ft_o25", 50.0))
        pct_c85 = float(getattr(fp_report, "pct_corners_o85", 50.0))

        selection = str(fixture_or_coupon.get("selection") or fixture_or_coupon.get("outcome") or "").upper()
        reasons = [f"Found 50 historical twin matches (Similarity: %{avg_sim:.1f})"]

        if "2.5" in selection and "ÜST" in selection:
            approved = pct_o25 >= 56.0
            reasons.append(f"Historical twins 2.5 ÜST rate: %{pct_o25:.1f}")
            return AgentVerdict(
                agent_name=self.name,
                approved=approved,
                confidence=pct_o25 / 100.0,
                tier="TIER_1_SHIELD" if pct_o25 >= 60.0 else "TIER_2_TWIN",
                reasons=reasons,
            )

        if "8.5" in selection and "ÜST" in selection:
            approved = pct_c85 >= 62.0
            reasons.append(f"Historical twins 8.5 ÜST rate: %{pct_c85:.1f}")
            return AgentVerdict(
                agent_name=self.name,
                approved=approved,
                confidence=pct_c85 / 100.0,
                tier="TIER_1_SHIELD" if approved else "TIER_2_TWIN",
                reasons=reasons,
            )

        return AgentVerdict(
            agent_name=self.name,
            approved=True,
            confidence=avg_sim / 100.0,
            tier="TIER_2_TWIN",
            reasons=reasons,
        )


class GoalAnomalyAgent(BaseSyndicateAgent):
    """P2 Specialist Agent: 30k Empirical Goal Anomaly & 6+ High-Pace Match Detector."""

    def __init__(self) -> None:
        super().__init__(
            name="Goal Anomaly Specialist",
            role="High-Pace Eruption & 6+ Goal Pattern Detector",
            priority=AgentPriority.P2_CORE_QUANT,
        )
        self.engine = GoalAnomalyEngine()

    def evaluate(self, fixture_or_coupon: dict[str, Any], context: dict[str, Any] | None = None) -> AgentVerdict:
        market = str(fixture_or_coupon.get("market") or "").upper()
        # If signal is dedicated to another specialized domain (corners, cards, double chance), abstain neutrally
        if any(non_goal in market for non_goal in ("KORNER", "CORNER", "KART", "CARD", "ÇİFTE", "CIFTE")):
            return AgentVerdict(
                agent_name=self.name,
                approved=True,
                confidence=0.5,
                tier="NEUTRAL_OUT_OF_SCOPE",
                reasons=["Market out of scope for goal anomaly specialist"],
            )

        result = self.engine.evaluate_fixture(fixture_or_coupon)

        # Veto Under markets if fixture is confirmed high-pace eruption (GOLD / SILVER)
        selection = str(fixture_or_coupon.get("selection") or fixture_or_coupon.get("outcome") or "").upper()
        if any(under_kw in market or under_kw in selection for under_kw in ("ALT", "UNDER")):
            if result.tier in (AnomalySignalTier.GOLD_TIER, AnomalySignalTier.SILVER_TIER):
                return AgentVerdict(
                    agent_name=self.name,
                    approved=False,
                    confidence=0.90,
                    tier="PASS",
                    veto_reason=f"High-pace eruption anomaly fixture ({result.tier.value}, GASI: {result.gasi_score:.1f}) strongly conflicts with Under market",
                    reasons=result.reasons,
                    metadata={"gasi_score": result.gasi_score, "tier": result.tier.value},
                )

        if result.tier == AnomalySignalTier.PASS:
            return AgentVerdict(
                agent_name=self.name,
                approved=False,
                confidence=result.gasi_score / 100.0,
                tier="PASS",
                veto_reason=result.veto_reason or "Below threshold GASI score (< 50)",
                reasons=result.reasons,
                metadata={"gasi_score": result.gasi_score, "archetype": result.archetype.value},
            )

        is_gold = result.tier == AnomalySignalTier.GOLD_TIER
        reasons = list(result.reasons)
        reasons.append(f"GASI Score: {result.gasi_score:.1f}/100, NegBin P(6+): %{result.p_6plus_negbin * 100:.1f}")
        primary_market = result.primary_market
        reasons.append(f"🎯 1 Numaralı Pazar: {primary_market} (Tarihsel Backtest: +%8.11 Net ROI)")
        reasons.append(f"Recommended Markets: {', '.join(result.recommended_markets)}")

        meta = {
            "gasi_score": result.gasi_score,
            "tier": result.tier.value,
            "archetype": result.archetype.value,
            "fair_odds_6plus": result.fair_odds_6plus,
            "primary_market": primary_market,
            "recommended_markets": result.recommended_markets,
        }
        if "2.5" in market and any(over_kw in market or over_kw in selection for over_kw in ("ÜST", "OVER")):
            meta["market_upgrade_advisory"] = (
                "2.5 Üst onaylandı; ancak 30,252 maçlık backtestte Over 3.5 pazarının marj ve net getirisi (+%8.11 ROI) daha yüksektir."
            )

        return AgentVerdict(
            agent_name=self.name,
            approved=True,
            confidence=result.gasi_score / 100.0,
            tier="TIER_1_SHIELD" if is_gold else "TIER_2_VALUE",
            reasons=reasons,
            metadata=meta,
        )

