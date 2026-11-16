"""Pricing and Devigging API endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

SRC_DIR = Path(__file__).resolve().parent.parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from advanced_devig import DevigError, devig_odds_multi
    from api.schemas import DevigRequest, DevigResponse
except ImportError:
    from src.advanced_devig import DevigError, devig_odds_multi
    from src.api.schemas import DevigRequest, DevigResponse

router = APIRouter(prefix="/pricing", tags=["Pricing & Devigging"])


@router.post(
    "/devig",
    response_model=DevigResponse,
    summary="Strip bookmaker margin and extract true Kolmogorov probabilities",
)
def api_devig_odds(req: DevigRequest) -> DevigResponse:
    """Computes true vig-free fair probabilities from bookmaker odds using Shin, Power,

    Multiplicative, Additive, or Logarithmic algorithms.
    """
    if any(o <= 1.0 for o in req.odds):
        raise HTTPException(
            status_code=422,
            detail="SPEC-0012: All odds must be strictly greater than 1.0",
        )

    try:
        res = devig_odds_multi(req.odds, method=req.method)
    except DevigError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Devigging computation failed: {e}",
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected pricing engine error: {e}",
        ) from e

    probs = res["probabilities"]
    fair_odds = [round(1.0 / p, 3) if p > 0 else 999.0 for p in probs]
    margin = res.get("margin", 0.0)
    z_param = res.get("z") or (res.get("method_params") or {}).get("z")
    if z_param is not None:
        z_param = float(z_param)

    return DevigResponse(
        method=res.get("method", req.method),
        odds=req.odds,
        probabilities=[round(p, 4) for p in probs],
        fair_odds=fair_odds,
        margin=round(margin, 4),
        margin_pct=round(margin * 100.0, 2),
        z_parameter=z_param,
    )
