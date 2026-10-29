"""TASK-014 — Dual Odds Provider Integration MVP

Adapter package for normalizing PropLine and Xiddaa odds
into a canonical NormalizedOddsRecord schema.

Provider roles:
  PropLine  → global bookmaker odds (h2h, totals, spreads, correct_score)
  Xiddaa    → Turkey/local market odds (1X2, HT/FT, 1H markets, BTTS, Handicap)
  Mackolik  → match discovery only (no odds)
  API-Football → fixture/metadata only (no odds)
"""
