"""APE Syndicate Agent Contracts and Base Protocols.

Defines the universal protocol that each specialized syndicate agent must implement:
name, role, priority, and evaluate_fixture / process_event methods.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class AgentPriority(IntEnum):
    """Execution and recruitment priority tier for Syndicate Agents."""
    P0_SAFETY_AND_RISK = 0      # Risk Actuary & Settlement (Non-negotiable fail-closed)
    P1_MARKET_INTELLIGENCE = 1  # Market Surveillance (Steam) & Scout (CDN / Lineup)
    P2_CORE_QUANT = 2           # Quant Pricer (Dixon-Coles) & Props Hunter (Corners)
    P3_CONSENSUS_AND_FINGERPRINT = 3  # Odds Analyst (3D k-NN Vector Twins)
    P4_PORTFOLIO_ARBITRAGEUR = 4      # Multi-Market Correlated Parlay & Coupon Builder


@dataclass(frozen=True)
class AgentVerdict:
    """Actionable assessment output from a Syndicate Agent on a fixture or coupon."""
    agent_name: str
    approved: bool
    confidence: float  # 0.0 to 1.0
    tier: str          # e.g. TIER_1_SHIELD, TIER_1_SHIN_QUANT, REJECTED
    reasons: list[str] = field(default_factory=list)
    suggested_picks: list[dict[str, Any]] = field(default_factory=list)
    veto_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseSyndicateAgent(ABC):
    """Abstract base class for all APE Syndicate Autonomous Agents."""

    def __init__(self, name: str, role: str, priority: AgentPriority) -> None:
        self.name = name
        self.role = role
        self.priority = priority

    @abstractmethod
    def evaluate(self, fixture_or_coupon: dict[str, Any], context: dict[str, Any] | None = None) -> AgentVerdict:
        """Evaluate a candidate fixture or coupon and return an immutable AgentVerdict."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} priority={self.priority.name}>"

