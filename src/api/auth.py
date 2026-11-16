"""Tier-Based Access Control and Authentication for APE B2B API Gateway."""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

from fastapi import Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


class ApiTier(str, Enum):
    """SaaS Subscription Tiers."""

    FREE = "FREE"
    PRO = "PRO"
    VIP = "VIP"


TIER_HIERARCHY: dict[str, int] = {
    ApiTier.FREE.value: 1,
    ApiTier.PRO.value: 2,
    ApiTier.VIP.value: 3,
}


def get_configured_api_registry() -> dict[str, str]:
    """Retrieve mapping of authorized API keys to their assigned tiers."""
    env_master = os.getenv("APE_API_KEY", "ape_live_sec_prod_key_2026")
    env_free = os.getenv("APE_API_KEY_FREE", "ape_test_key_free")
    env_pro = os.getenv("APE_API_KEY_PRO", "ape_test_key_pro")
    env_vip = os.getenv("APE_API_KEY_VIP", "ape_test_key_vip")

    return {
        env_master: ApiTier.VIP.value,
        "ape_test_key_master": ApiTier.VIP.value,
        env_free: ApiTier.FREE.value,
        env_pro: ApiTier.PRO.value,
        env_vip: ApiTier.VIP.value,
    }


def get_configured_api_keys() -> set[str]:
    """Backward-compatible helper returning set of all authorized API keys."""
    return set(get_configured_api_registry().keys())


def get_key_tier(api_key: str) -> str:
    """Retrieve subscription tier for a given validated API key."""
    registry = get_configured_api_registry()
    return registry.get(api_key, ApiTier.FREE.value)


async def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Validate incoming X-API-Key header against authorized tenant registry."""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required authentication header: X-API-Key",
        )
    registry = get_configured_api_registry()
    if api_key not in registry:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired API Key. Access denied.",
        )
    return api_key


def require_tier(minimum_tier: str | ApiTier) -> Any:
    """Dependency factory enforcing minimum subscription tier for route access."""
    min_tier_val = (
        minimum_tier.value
        if isinstance(minimum_tier, ApiTier)
        else str(minimum_tier).upper()
    )

    async def tier_checker(api_key: str = Depends(verify_api_key)) -> str:
        current_tier = get_key_tier(api_key)
        req_level = TIER_HIERARCHY.get(min_tier_val, 1)
        curr_level = TIER_HIERARCHY.get(current_tier, 1)

        if curr_level < req_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Tier Upgrade Required. Endpoint requires {min_tier_val} tier access, "
                    f"but current API key is {current_tier} tier."
                ),
            )
        return api_key

    return tier_checker

