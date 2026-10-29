"""TASK-014 — Market Name Normalization

Maps provider-specific market key strings to CanonicalMarket values.

Only VERIFIED_REAL_ODDS markets from TASK-013 (PropLine) and TASK-013B (Xiddaa)
are included. Unknown provider markets map to CanonicalMarket.UNKNOWN —
they are NOT silently dropped but tagged for diagnostic review.

PropLine market keys (from API response field `markets[].key`):
  TASK-013 VERIFIED: h2h, totals, spreads, correct_score

Xiddaa market names (Turkish, from `markets[].name`):
  TASK-013B VERIFIED pre-match:
    Maç Sonucu              → 1X2
    Alt/Üst                 → TOTALS
    Karşılıklı Gol          → BTTS
    Handikapl Maç Sonucu    → HANDICAP
    1. Yarı Sonucu          → H1_1X2
    1. Yarı Alt/Üst         → H1_TOTALS
    1. Yarı Karşılıklı Gol  → H1_BTTS
    1. Yarı Skoru           → H1_CORRECT_SCORE
    1. Yarı / Maç Sonucu    → HT_FT
    1. Yarı/Maç Sonucu Skorları → HT_FT_SCORE
    Maç Skoru               → CORRECT_SCORE
"""

from __future__ import annotations

from sports_engine.adapters.schema import CanonicalMarket, MarketPeriod

# ── PropLine market keys → canonical ──────────────────────────────────────────
PROPLINE_MARKET_MAP: dict[str, tuple[str, str]] = {
    # key: (CanonicalMarket, MarketPeriod)
    "h2h":               (CanonicalMarket.H1X2,          MarketPeriod.FULL_MATCH),
    "totals":            (CanonicalMarket.TOTALS,         MarketPeriod.FULL_MATCH),
    "spreads":           (CanonicalMarket.SPREAD,         MarketPeriod.FULL_MATCH),
    "correct_score":     (CanonicalMarket.CORRECT_SCORE,  MarketPeriod.FULL_MATCH),
    # Half markets — TASK-013 showed VERIFIED_BUT_EMPTY; listed for completeness
    # but will produce 0 records in practice (no bookmaker returns them currently)
    "h2h_h1":            (CanonicalMarket.H1_1X2,         MarketPeriod.FIRST_HALF),
    "h2h_h2":            (CanonicalMarket.H1_1X2,         MarketPeriod.SECOND_HALF),
    "totals_h1":         (CanonicalMarket.H1_TOTALS,      MarketPeriod.FIRST_HALF),
    "totals_h2":         (CanonicalMarket.H1_TOTALS,      MarketPeriod.SECOND_HALF),
    "btts":              (CanonicalMarket.BTTS,            MarketPeriod.FULL_MATCH),
    "correct_score_h1":  (CanonicalMarket.H1_CORRECT_SCORE, MarketPeriod.FIRST_HALF),
    "halftime_fulltime": (CanonicalMarket.HT_FT,          MarketPeriod.FULL_MATCH),
}

# ── Xiddaa market names → canonical ───────────────────────────────────────────
# Exact Turkish strings as returned by Xiddaa API (case-insensitive match applied)
# TASK-013B VERIFIED pre-match events only
XIDDAA_MARKET_MAP: dict[str, tuple[str, str]] = {
    "maç sonucu":                         (CanonicalMarket.H1X2,             MarketPeriod.FULL_MATCH),
    "alt/üst":                            (CanonicalMarket.TOTALS,           MarketPeriod.FULL_MATCH),
    "karşılıklı gol":                     (CanonicalMarket.BTTS,             MarketPeriod.FULL_MATCH),
    "handikapl maç sonucu":               (CanonicalMarket.HANDICAP,         MarketPeriod.FULL_MATCH),
    "1. yarı sonucu":                     (CanonicalMarket.H1_1X2,           MarketPeriod.FIRST_HALF),
    "1. yarı alt/üst":                    (CanonicalMarket.H1_TOTALS,        MarketPeriod.FIRST_HALF),
    "1. yarı karşılıklı gol":             (CanonicalMarket.H1_BTTS,          MarketPeriod.FIRST_HALF),
    "1. yarı skoru":                      (CanonicalMarket.H1_CORRECT_SCORE, MarketPeriod.FIRST_HALF),
    "1. yarı / maç sonucu":               (CanonicalMarket.HT_FT,            MarketPeriod.FULL_MATCH),
    "1. yarı/maç sonucu skorları":        (CanonicalMarket.HT_FT_SCORE,      MarketPeriod.FULL_MATCH),
    "maç skoru":                          (CanonicalMarket.CORRECT_SCORE,    MarketPeriod.FULL_MATCH),
    # Common variants seen in raw data
    "1. yarı tek/çift":                   (CanonicalMarket.UNKNOWN,          MarketPeriod.FIRST_HALF),
    "toplam gol":                         (CanonicalMarket.TOTALS,           MarketPeriod.FULL_MATCH),
}


def normalize_propline_market(key: str) -> tuple[str, str]:
    """Return (CanonicalMarket, MarketPeriod) for a PropLine market key.

    Falls back to (UNKNOWN, UNKNOWN) for unmapped keys.
    """
    return PROPLINE_MARKET_MAP.get(
        key.lower(),
        (CanonicalMarket.UNKNOWN, MarketPeriod.UNKNOWN)
    )


def normalize_xiddaa_market(name: str) -> tuple[str, str]:
    """Return (CanonicalMarket, MarketPeriod) for a Xiddaa market name.

    Matching is case-insensitive and strips leading/trailing whitespace.
    Partial matches (e.g. "Handikapl Maç Sonucu 0:1") use prefix matching.
    Falls back to (UNKNOWN, UNKNOWN) for unmapped names.
    """
    cleaned = name.strip().lower()

    # Exact match first
    if cleaned in XIDDAA_MARKET_MAP:
        return XIDDAA_MARKET_MAP[cleaned]

    # Prefix match for handicap variants like "Handikapl Maç Sonucu 0:2"
    if cleaned.startswith("handikapl"):
        return (CanonicalMarket.HANDICAP, MarketPeriod.FULL_MATCH)
    if cleaned.startswith("1. yarı alt/üst"):
        return (CanonicalMarket.H1_TOTALS, MarketPeriod.FIRST_HALF)
    if cleaned.startswith("alt/üst"):
        return (CanonicalMarket.TOTALS, MarketPeriod.FULL_MATCH)
    if "yarı / maç sonucu" in cleaned or "yarı/maç sonucu skoru" in cleaned:
        return (CanonicalMarket.HT_FT_SCORE, MarketPeriod.FULL_MATCH)

    return (CanonicalMarket.UNKNOWN, MarketPeriod.UNKNOWN)
