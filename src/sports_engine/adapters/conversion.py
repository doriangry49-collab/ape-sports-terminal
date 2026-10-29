"""TASK-014 — Odds Format Conversion Utilities

American ↔ Decimal conversion and format detection.

Rules:
  - American format is identified by: abs(value) >= 100
  - Decimal format: value > 1.0 and abs(value) < 100
  - Conversion applied ONLY after format is confirmed
  - Original value always preserved in odds_raw

Evidence from TASK-013:
  PropLine returns American odds for most bookmakers (bovada, fanduel, fliff, etc.)
  Some PropLine bookmakers return decimal (smarkets, kalshi, polymarket use probability-like values)
  Xiddaa always returns decimal odds
"""

from __future__ import annotations

from sports_engine.adapters.schema import OddsFormat


def detect_odds_format(raw_value: float | int) -> OddsFormat:
    """Detect whether a numeric odds value is American or Decimal.

    American odds: abs(value) >= 100  (e.g. +250, -150, +5500)
    Decimal odds:  1.0 < value < 100  (e.g. 3.50, 1.45, 45.5)

    Returns OddsFormat.UNKNOWN if value cannot be classified.
    """
    try:
        v = float(raw_value)
    except (TypeError, ValueError):
        return OddsFormat.UNKNOWN

    if abs(v) >= 100:
        return OddsFormat.AMERICAN
    elif v > 1.0:
        return OddsFormat.DECIMAL
    else:
        return OddsFormat.UNKNOWN


def american_to_decimal(american: float) -> float:
    """Convert American odds to decimal.

    American +250  → decimal 3.50   (250/100 + 1)
    American -150  → decimal 1.667  (100/150 + 1)

    Raises ValueError if conversion yields <= 1.0 (invalid).
    """
    if american > 0:
        decimal = (american / 100.0) + 1.0
    elif american < 0:
        decimal = (100.0 / abs(american)) + 1.0
    else:
        raise ValueError(f"American odds cannot be 0. Received: {american}")

    if decimal <= 1.0:
        raise ValueError(
            f"Conversion error: American {american} yielded decimal {decimal} <= 1.0"
        )
    return round(decimal, 6)


def to_decimal(raw_value: float | int, fmt: OddsFormat) -> float:
    """Convert raw odds to canonical decimal format.

    Raises ValueError if odds_decimal <= 1.0 after conversion.
    Raises TypeError if format is UNKNOWN.
    """
    v = float(raw_value)

    if fmt == OddsFormat.DECIMAL:
        if v <= 1.0:
            raise ValueError(f"Decimal odds must be > 1.0. Got: {v}")
        return round(v, 6)

    elif fmt == OddsFormat.AMERICAN:
        return american_to_decimal(v)

    else:
        raise TypeError(f"Cannot convert odds with unknown format. raw_value={raw_value}")


def normalize_correct_score_selection(raw: str) -> str:
    """Normalize Correct Score selection string to canonical 'H-A' format.

    Examples:
      "1-0"   → "1-0"
      "1 - 0" → "1-0"
      "0:1"   → "0-1"
      "1:0"   → "1-0"
      "2 - 1" → "2-1"
    """
    clean = raw.strip().replace(" ", "").replace(":", "-")
    return clean


def normalize_htft_selection(raw: str) -> str:
    """Normalize HT/FT selection to canonical 'HT/FT' format.

    Xiddaa Turkish labels:
      "1/1" → "1/1"
      "1/0" → "1/X"   (0 = draw)
      "0/2" → "X/2"
      etc.

    PropLine / English labels:
      "Home/Home" → "1/1"
      "Draw/Away" → "X/2"

    For now: pass-through with whitespace normalization.
    Callers receive original label if no mapping exists.
    """
    return raw.strip().replace(" ", "")
