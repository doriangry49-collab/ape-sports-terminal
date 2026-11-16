"""APE Syndicate Registry & Committee Consensus Engine.

Coordinates all Syndicate Agents in strict priority sequence:
1. P0 Risk Actuary (Constitutional veto)
2. P1 Market Surveillance (Steam)
3. P2 Quant Pricer & Props Hunter (Fair probability & edge)
4. P3 Odds Analyst (Historical 3D twin consensus)
"""
from __future__ import annotations

import logging
from typing import Any

from syndicate.agents import (
    GoalAnomalyAgent,
    MarketSurveillanceAgent,
    OddsAnalystAgent,
    PropsHunterAgent,
    QuantPricerAgent,
    RiskActuaryAgent,
)
from syndicate.base_agent import AgentPriority, AgentVerdict, BaseSyndicateAgent

logger = logging.getLogger("SyndicateRegistry")


class SyndicateCommittee:
    """The Quantitative Syndicate Decision Council."""

    def __init__(self, include_anomaly_specialist: bool = False) -> None:
        self.agents: list[BaseSyndicateAgent] = [
            RiskActuaryAgent(),
            MarketSurveillanceAgent(),
            QuantPricerAgent(),
            PropsHunterAgent(),
            OddsAnalystAgent(),
        ]
        if include_anomaly_specialist:
            self.agents.append(GoalAnomalyAgent())
        # Sort by priority tier ascending (P0 -> P1 -> P2 -> P3)
        self.agents.sort(key=lambda a: a.priority.value)
        logger.info(f"Syndicate Committee initialized with {len(self.agents)} active agents.")

    def review_signal(
        self,
        signal: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Review an incoming +EV signal across all agents in priority sequence."""
        verdicts: list[AgentVerdict] = []
        is_vetoed = False
        veto_reason = None

        for agent in self.agents:
            verdict = agent.evaluate(signal, context=context)
            verdicts.append(verdict)

            # Strict P0 Veto Power
            if not verdict.approved and agent.priority == AgentPriority.P0_SAFETY_AND_RISK:
                is_vetoed = True
                veto_reason = verdict.veto_reason or f"Vetoed by {agent.name}"
                break

            # Specialist Props Veto
            if not verdict.approved and agent.priority == AgentPriority.P2_CORE_QUANT and verdict.veto_reason:
                is_vetoed = True
                veto_reason = verdict.veto_reason
                break

        # Calculate Consensus Score
        approved_verdicts = [v for v in verdicts if v.approved]
        avg_confidence = (
            sum(v.confidence for v in approved_verdicts) / len(approved_verdicts)
            if approved_verdicts
            else 0.0
        )
        has_shield = any("TIER_1_SHIELD" in v.tier for v in approved_verdicts)

        final_tier = "REJECTED" if is_vetoed else ("TIER_1_SHIELD" if has_shield else "TIER_2_VALUE")

        return {
            "signal": signal,
            "approved": not is_vetoed and len(approved_verdicts) >= 3,
            "final_tier": final_tier,
            "consensus_score": round(avg_confidence, 3),
            "veto_reason": veto_reason,
            "agent_verdicts": [
                {
                    "agent": v.agent_name,
                    "approved": v.approved,
                    "tier": v.tier,
                    "reasons": v.reasons,
                }
                for v in verdicts
            ],
        }

    def roster_summary(self) -> list[dict[str, Any]]:
        """Return recruitment and duty status for each agent."""
        return [
            {
                "name": a.name,
                "role": a.role,
                "priority_tier": a.priority.name,
                "priority_level": a.priority.value,
                "status": "ON_DUTY_ACTIVE",
            }
            for a in self.agents
        ]

