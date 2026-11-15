"""Time and Kickoff Utilities for Sports-Engine.

Provides centralized kickoff parsing and constitutional temporal guardrails:
- SPEC-0013: Rejection of started/finished matches (minimum lead time).
- SPEC-0014: Maximum 12-hour forward horizon enforcement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

TRT_TZ = timezone(timedelta(hours=3))


def parse_match_kickoff(
    date_str: str | None,
    time_str: str | None,
    now_trt: datetime | None = None,
    min_lead_minutes: int = 3,
    max_lead_hours: int = 12,
) -> tuple[datetime | None, str | None]:
    """Parse raw bulletin date/time strings into TRT timezone datetime and UTC ISO kickoff string.

    Enforces SPEC-0013 and SPEC-0014 fail-closed kickoff validation:
    - Matches starting within min_lead_minutes (default 3m) or in the past return (None, None).
    - Matches starting more than max_lead_hours (default 12h) in the future return (None, None).
    Returns (match_dt_trt, kickoff_iso_utc) if valid upcoming fixture in window, else (None, None).
    """
    if not date_str or not time_str:
        return None, None

    if now_trt is None:
        now_trt = datetime.now(TRT_TZ)

    d_clean = str(date_str).strip()
    t_clean = str(time_str).strip().lstrip("T")
    dt_combined = f"{d_clean} {t_clean}"

    match_dt = None
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            match_dt = datetime.strptime(dt_combined, fmt).replace(tzinfo=TRT_TZ)
            break
        except ValueError:
            pass

    if match_dt is None:
        return None, None

    # SPEC-0013: Skip finished or ongoing matches
    if match_dt <= now_trt + timedelta(minutes=min_lead_minutes):
        return None, None

    # SPEC-0014: Maximum 12-hour window limit
    if match_dt > now_trt + timedelta(hours=max_lead_hours):
        return None, None

    kickoff_iso = match_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return match_dt, kickoff_iso

