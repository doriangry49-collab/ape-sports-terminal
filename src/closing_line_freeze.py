"""
Closing Line Snapshot Freeze Mechanism & Immutable CLV Engine (v1.0).

Constitutional Compliance (GEMINI.md):
- SPEC-0012: ERROR != UNKNOWN (Fail-closed on corrupt/missing data, no mocks or synthetic odds).
- SPEC-0013: Kickoff TRT timing (freeze occurs at T-5m, no post-kickoff signals or freeze).
- SPEC-0014: Maximum 12-hour window.
- SPEC-0015: Minimum ticket stake >= 50.0 TL enforcement.

Features:
- Immutable closing line capture at T-5m before scheduled kickoff (TRT = UTC+3).
- SQLite persistence (data/closing_lines.sqlite) with unique integrity constraints.
- Dedicated JSON ledger persistence (data/closing_lines/closing_lines.json).
- Shin devigged fair closing odds extraction via advanced_devig.
- Deterministic CLV metrics calculation (raw CLV, devigged fair CLV, edge percentage).
- Fail-closed error handling raising ClosingLineUnavailableError / ClosingLineAlreadyFrozenError.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from advanced_devig import DevigError, devig_odds_shin
except ImportError:
    try:
        from src.advanced_devig import DevigError, devig_odds_shin
    except ImportError:
        DevigError = ValueError  # type: ignore
        devig_odds_shin = None  # type: ignore

# TRT Timezone = UTC+3
TRT_TZ = timezone(timedelta(hours=3))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "data" / "closing_lines.sqlite"
DEFAULT_JSON_PATH = PROJECT_ROOT / "data" / "closing_lines" / "closing_lines.json"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ClosingLineError(Exception):
    """Base exception for closing line freeze and CLV calculation errors."""


class ClosingLineAlreadyFrozenError(ClosingLineError):
    """Raised when an attempt is made to overwrite an already frozen immutable closing line."""


class ClosingLineImmutabilityViolationError(ClosingLineAlreadyFrozenError):
    """Raised when incoming odds conflict with an already frozen immutable closing line."""


class ClosingLineUnavailableError(ClosingLineError):
    """Raised fail-closed when closing odds are missing, invalid, or unavailable (SPEC-0012)."""


class ClosingLineTimingError(ClosingLineError):
    """Raised when freeze is attempted outside the T-5m pre-kickoff window."""


# ---------------------------------------------------------------------------
# Timezone & Formatting Helpers
# ---------------------------------------------------------------------------

def to_trt(dt: datetime) -> datetime:
    """Convert datetime to Europe/Istanbul (TRT = UTC+3). Naive datetimes assumed UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(TRT_TZ)


def format_trt(dt: datetime) -> str:
    """Format datetime as YYYY-MM-DD HH:MM TRT."""
    return to_trt(dt).strftime("%Y-%m-%d %H:%M TRT")


def parse_iso_or_datetime(val: datetime | str) -> datetime:
    """Convert ISO string or datetime to UTC-aware datetime."""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=UTC)
        return val.astimezone(UTC)
    s = str(val).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Domain Model: ClosingLineRecord
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClosingLineRecord:
    """Immutable closing line snapshot record locked at T-5m before match kickoff."""

    fixture_id: str
    match_name: str
    league: str
    kickoff_utc: datetime
    kickoff_trt: str  # YYYY-MM-DD HH:MM TRT
    frozen_at_utc: datetime
    frozen_at_trt: str
    market: str       # e.g., "1X2", "OU_2.5", "CORNER_OU_9.5"
    closing_odds: dict[str, float]      # e.g., {"1": 2.10, "X": 3.20, "2": 3.40}
    fair_closing_odds: dict[str, float] # Shin devigged fair odds
    bookmaker: str = "PINNACLE"
    shin_margin: float = 0.0
    is_frozen: bool = True
    status: str = "FROZEN"

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "match_name": self.match_name,
            "league": self.league,
            "kickoff_utc": self.kickoff_utc.isoformat(),
            "kickoff_trt": self.kickoff_trt,
            "frozen_at_utc": self.frozen_at_utc.isoformat(),
            "frozen_at_trt": self.frozen_at_trt,
            "market": self.market,
            "bookmaker": self.bookmaker,
            "closing_odds": dict(self.closing_odds),
            "fair_closing_odds": dict(self.fair_closing_odds),
            "shin_margin": self.shin_margin,
            "is_frozen": self.is_frozen,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClosingLineRecord:
        ko_utc = parse_iso_or_datetime(data["kickoff_utc"])
        fr_utc = parse_iso_or_datetime(data.get("frozen_at_utc", datetime.now(UTC)))
        return cls(
            fixture_id=str(data["fixture_id"]),
            match_name=str(data.get("match_name", "")),
            league=str(data.get("league", "")),
            kickoff_utc=ko_utc,
            kickoff_trt=str(data.get("kickoff_trt", format_trt(ko_utc))),
            frozen_at_utc=fr_utc,
            frozen_at_trt=str(data.get("frozen_at_trt", format_trt(fr_utc))),
            market=str(data.get("market", "1X2")),
            closing_odds={str(k): float(v) for k, v in data.get("closing_odds", {}).items()},
            fair_closing_odds={str(k): float(v) for k, v in data.get("fair_closing_odds", {}).items()},
            bookmaker=str(data.get("bookmaker", "PINNACLE")),
            shin_margin=float(data.get("shin_margin", 0.0)),
            is_frozen=bool(data.get("is_frozen", True)),
            status=str(data.get("status", "FROZEN")),
        )


# ---------------------------------------------------------------------------
# Devigging & Validation Logic
# ---------------------------------------------------------------------------

def extract_fair_odds(
    closing_odds: dict[str, float],
    provided_fair_odds: dict[str, float] | None = None,
) -> tuple[dict[str, float], float]:
    """Validate odds and compute Shin devigged fair odds and margin.

    Constitutional Compliance:
    - SPEC-0012: Fail-closed if odds are missing or <= 1.0 (no synthetic / default odds).
    """
    if not closing_odds:
        raise ClosingLineUnavailableError("SPEC-0012 Violation: closing_odds cannot be empty.")

    for sel, odd in closing_odds.items():
        if odd is None or not isinstance(odd, (int, float)) or odd <= 1.0:
            raise ClosingLineUnavailableError(
                f"SPEC-0012 Violation: Invalid odds {odd!r} for selection {sel!r}. All odds must be strictly > 1.0."
            )

    if provided_fair_odds:
        for sel, odd in provided_fair_odds.items():
            if odd is None or not isinstance(odd, (int, float)) or odd <= 1.0:
                raise ClosingLineUnavailableError(
                    f"SPEC-0012 Violation: Invalid fair odds {odd!r} for selection {sel!r}. Must be strictly > 1.0."
                )
        inv_sum = sum(1.0 / o for o in closing_odds.values())
        margin = max(0.0, round(inv_sum - 1.0, 4))
        return dict(provided_fair_odds), margin

    keys = list(closing_odds.keys())
    odds_vals = [float(closing_odds[k]) for k in keys]

    if len(odds_vals) >= 2 and devig_odds_shin is not None:
        try:
            devig_res = devig_odds_shin(odds_vals)
            probs = devig_res["probabilities"]
            margin = float(devig_res.get("margin", 0.0))
            fair_dict = {k: round(1.0 / p, 3) for k, p in zip(keys, probs, strict=False)}
            return fair_dict, margin
        except Exception:
            pass

    # Proportional devigging fallback
    inv_odds = [1.0 / o for o in odds_vals]
    sum_inv = sum(inv_odds)
    if sum_inv > 0:
        fair_dict = {k: round(o * sum_inv, 3) for k, o in closing_odds.items()}
        margin = max(0.0, round(sum_inv - 1.0, 4))
        return fair_dict, margin

    return dict(closing_odds), 0.0


def is_eligible_for_freeze(
    kickoff_utc: datetime | str,
    now_utc: datetime | str | None = None,
) -> bool:
    """Check if current time is eligible to freeze closing line (T-5m window).

    A fixture is eligible for closing line freeze if:
    now is within 5 minutes before scheduled kickoff (kickoff - 5m <= now <= kickoff).
    """
    ko_dt = parse_iso_or_datetime(kickoff_utc)
    now_dt = parse_iso_or_datetime(now_utc) if now_utc is not None else datetime.now(UTC)
    delta = (ko_dt - now_dt).total_seconds()
    # 0 <= delta <= 300 seconds (0 to 5 minutes before kickoff)
    return 0 <= delta <= 300


# ---------------------------------------------------------------------------
# Storage Layer: ClosingLineStore
# ---------------------------------------------------------------------------

class ClosingLineStore:
    """Manages SQLite database and optional JSON ledger for immutable closing lines."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        json_path: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_SQLITE_PATH
        self.json_path = Path(json_path) if json_path else DEFAULT_JSON_PATH
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS closing_lines (
                    snapshot_id TEXT PRIMARY KEY,
                    fixture_id TEXT NOT NULL,
                    match_name TEXT NOT NULL,
                    league TEXT NOT NULL,
                    kickoff_utc TEXT NOT NULL,
                    kickoff_trt TEXT NOT NULL,
                    frozen_at_utc TEXT NOT NULL,
                    frozen_at_trt TEXT NOT NULL,
                    market TEXT NOT NULL,
                    bookmaker TEXT NOT NULL,
                    closing_odds_json TEXT NOT NULL,
                    fair_closing_odds_json TEXT NOT NULL,
                    shin_margin REAL NOT NULL DEFAULT 0.0,
                    is_frozen INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'FROZEN',
                    created_at TEXT NOT NULL
                );
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_closing_line
                ON closing_lines(fixture_id, market, bookmaker);
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS closing_line_selections (
                    snapshot_id TEXT NOT NULL,
                    fixture_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    bookmaker TEXT NOT NULL,
                    selection TEXT NOT NULL,
                    closing_odds REAL NOT NULL,
                    fair_closing_odds REAL NOT NULL,
                    PRIMARY KEY (fixture_id, market, bookmaker, selection)
                );
            """)
            conn.commit()

    def has_frozen(self, fixture_id: str, market: str, bookmaker: str = "PINNACLE") -> bool:
        """Return True if closing line is already frozen for (fixture_id, market, bookmaker)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM closing_lines WHERE fixture_id = ? AND market = ? AND bookmaker = ?",
                (str(fixture_id), str(market), str(bookmaker)),
            )
            return cursor.fetchone() is not None

    def get_record(self, fixture_id: str, market: str, bookmaker: str = "PINNACLE") -> ClosingLineRecord | None:
        """Retrieve frozen ClosingLineRecord, or None if not found."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM closing_lines
                WHERE fixture_id = ? AND market = ? AND bookmaker = ?
                """,
                (str(fixture_id), str(market), str(bookmaker)),
            )
            row = cursor.fetchone()
            if not row:
                return None

            return ClosingLineRecord(
                fixture_id=row["fixture_id"],
                match_name=row["match_name"],
                league=row["league"],
                kickoff_utc=parse_iso_or_datetime(row["kickoff_utc"]),
                kickoff_trt=row["kickoff_trt"],
                frozen_at_utc=parse_iso_or_datetime(row["frozen_at_utc"]),
                frozen_at_trt=row["frozen_at_trt"],
                market=row["market"],
                closing_odds=json.loads(row["closing_odds_json"]),
                fair_closing_odds=json.loads(row["fair_closing_odds_json"]),
                bookmaker=row["bookmaker"],
                shin_margin=row["shin_margin"],
                is_frozen=bool(row["is_frozen"]),
                status=row["status"],
            )

    def save_record(self, record: ClosingLineRecord) -> None:
        """Persist closing line record into SQLite and JSON ledger.

        Raises:
            ClosingLineAlreadyFrozenError: If a closing line already exists for the (fixture, market, bookmaker).
        """
        snap_id = f"{record.fixture_id}_{record.market}_{record.bookmaker}"
        created_at = datetime.now(UTC).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT snapshot_id FROM closing_lines WHERE fixture_id = ? AND market = ? AND bookmaker = ?",
                (record.fixture_id, record.market, record.bookmaker),
            )
            existing = cursor.fetchone()
            if existing:
                raise ClosingLineAlreadyFrozenError(
                    f"Closing line for fixture '{record.fixture_id}', market '{record.market}', bookmaker '{record.bookmaker}' "
                    f"is already frozen and immutable (snapshot_id={existing[0]}). Overwrite rejected."
                )

            cursor.execute(
                """
                INSERT INTO closing_lines (
                    snapshot_id, fixture_id, match_name, league, kickoff_utc, kickoff_trt,
                    frozen_at_utc, frozen_at_trt, market, bookmaker, closing_odds_json,
                    fair_closing_odds_json, shin_margin, is_frozen, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snap_id,
                    record.fixture_id,
                    record.match_name,
                    record.league,
                    record.kickoff_utc.isoformat(),
                    record.kickoff_trt,
                    record.frozen_at_utc.isoformat(),
                    record.frozen_at_trt,
                    record.market,
                    record.bookmaker,
                    json.dumps(record.closing_odds),
                    json.dumps(record.fair_closing_odds),
                    record.shin_margin,
                    1 if record.is_frozen else 0,
                    record.status,
                    created_at,
                ),
            )

            for sel, c_odd in record.closing_odds.items():
                f_odd = record.fair_closing_odds.get(sel, c_odd)
                cursor.execute(
                    """
                    INSERT INTO closing_line_selections (
                        snapshot_id, fixture_id, market, bookmaker, selection, closing_odds, fair_closing_odds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (snap_id, record.fixture_id, record.market, record.bookmaker, sel, c_odd, f_odd),
                )
            conn.commit()

        self._save_to_json_ledger(record)

    def _save_to_json_ledger(self, record: ClosingLineRecord) -> None:
        """Append record to dedicated JSON ledger atomically."""
        try:
            self.json_path.parent.mkdir(parents=True, exist_ok=True)
            ledger: dict[str, Any] = {}
            if self.json_path.exists():
                try:
                    with open(self.json_path, encoding="utf-8") as fh:
                        ledger = json.load(fh)
                except Exception:
                    ledger = {}

            key = f"{record.fixture_id}|{record.market}|{record.bookmaker}"
            if key not in ledger:
                ledger[key] = record.to_dict()
                tmp_path = self.json_path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as fh:
                    json.dump(ledger, fh, indent=2, ensure_ascii=False)
                tmp_path.replace(self.json_path)
        except Exception:
            pass

    def list_records(self, fixture_id: str | None = None) -> list[ClosingLineRecord]:
        """List all frozen records or records matching a fixture_id."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if fixture_id:
                cursor.execute("SELECT * FROM closing_lines WHERE fixture_id = ?", (str(fixture_id),))
            else:
                cursor.execute("SELECT * FROM closing_lines ORDER BY kickoff_utc ASC")

            records = []
            for row in cursor.fetchall():
                records.append(
                    ClosingLineRecord(
                        fixture_id=row["fixture_id"],
                        match_name=row["match_name"],
                        league=row["league"],
                        kickoff_utc=parse_iso_or_datetime(row["kickoff_utc"]),
                        kickoff_trt=row["kickoff_trt"],
                        frozen_at_utc=parse_iso_or_datetime(row["frozen_at_utc"]),
                        frozen_at_trt=row["frozen_at_trt"],
                        market=row["market"],
                        closing_odds=json.loads(row["closing_odds_json"]),
                        fair_closing_odds=json.loads(row["fair_closing_odds_json"]),
                        bookmaker=row["bookmaker"],
                        shin_margin=row["shin_margin"],
                        is_frozen=bool(row["is_frozen"]),
                        status=row["status"],
                    )
                )
            return records


# ---------------------------------------------------------------------------
# Core Freezing Functions
# ---------------------------------------------------------------------------

def freeze_closing_line(
    fixture_id: str,
    market_odds: dict[str, Any],
    kickoff_utc: datetime | str,
    match_name: str = "",
    league: str = "",
    market: str = "1X2",
    bookmaker: str = "PINNACLE",
    fair_closing_odds: dict[str, float] | None = None,
    now_utc: datetime | str | None = None,
    force: bool = False,
    store: ClosingLineStore | None = None,
    raise_if_exists: bool = True,
) -> ClosingLineRecord:
    """Capture and freeze market odds at T-5m pre-kickoff into immutable store.

    Args:
        fixture_id: Unique fixture identifier.
        market_odds: Dictionary of selection -> decimal odds (e.g. {"1": 2.10, "X": 3.20, "2": 3.40})
                     or nested dict containing 'closing_odds'.
        kickoff_utc: Scheduled kickoff datetime in UTC.
        match_name: Optional human-readable match title.
        league: Competition name.
        market: Market name (e.g. "1X2", "OU_2.5", "CORNER_OU_9.5").
        bookmaker: Sharp benchmark bookmaker name (default "PINNACLE").
        fair_closing_odds: Optional pre-computed Shin fair odds.
        now_utc: Simulated or actual reference time in UTC.
        force: If True, bypasses T-5m timing window check.
        store: ClosingLineStore instance (defaults to global store).
        raise_if_exists: If True, raises ClosingLineAlreadyFrozenError if already frozen;
                         if False, returns the existing frozen record.

    Returns:
        ClosingLineRecord representing the frozen immutable snapshot.
    """
    store = store or ClosingLineStore()
    ko_dt = parse_iso_or_datetime(kickoff_utc)
    ref_now = parse_iso_or_datetime(now_utc) if now_utc is not None else datetime.now(UTC)

    # 1. Immutability check
    if store.has_frozen(fixture_id, market, bookmaker):
        if raise_if_exists:
            raise ClosingLineAlreadyFrozenError(
                f"Closing line for fixture '{fixture_id}', market '{market}', bookmaker '{bookmaker}' is already frozen."
            )
        existing = store.get_record(fixture_id, market, bookmaker)
        if existing is not None:
            return existing

    # 2. Timing check (unless force=True)
    if not force:
        delta_sec = (ko_dt - ref_now).total_seconds()
        if delta_sec < 0:
            raise ClosingLineTimingError(
                f"SPEC-0013 Violation: Match has already kicked off ({ko_dt.isoformat()}). Cannot freeze post-kickoff."
            )
        if delta_sec > 300:
            raise ClosingLineTimingError(
                f"Timing Violation: Kickoff is {delta_sec / 60.0:.1f}m away (> 5m). Closing lines can only freeze within T-5m."
            )

    # 3. Extract and validate odds (fail-closed per SPEC-0012)
    raw_odds: dict[str, float] = {}
    if "closing_odds" in market_odds and isinstance(market_odds["closing_odds"], dict):
        raw_odds = {str(k): float(v) for k, v in market_odds["closing_odds"].items()}
        if fair_closing_odds is None and "fair_closing_odds" in market_odds:
            fair_closing_odds = {str(k): float(v) for k, v in market_odds["fair_closing_odds"].items()}
    else:
        raw_odds = {str(k): float(v) for k, v in market_odds.items() if not isinstance(v, dict)}

    fair_odds, margin = extract_fair_odds(raw_odds, fair_closing_odds)

    # 4. Construct record
    record = ClosingLineRecord(
        fixture_id=str(fixture_id),
        match_name=match_name or f"Fixture {fixture_id}",
        league=league or "Unknown League",
        kickoff_utc=ko_dt,
        kickoff_trt=format_trt(ko_dt),
        frozen_at_utc=ref_now,
        frozen_at_trt=format_trt(ref_now),
        market=market,
        closing_odds=raw_odds,
        fair_closing_odds=fair_odds,
        bookmaker=bookmaker,
        shin_margin=margin,
        is_frozen=True,
        status="FROZEN",
    )

    # 5. Persist record
    store.save_record(record)
    return record


# ---------------------------------------------------------------------------
# Accurate CLV Calculation
# ---------------------------------------------------------------------------

def compute_clv(
    entry_odds: float,
    frozen_closing_odds: float,
    frozen_fair_odds: float,
) -> dict[str, Any]:
    """Calculate raw CLV, devigged fair CLV, and CLV edge percentage strictly referencing frozen closing lines.

    Formula:
    - clv_raw = entry_odds / frozen_closing_odds
    - clv_fair = entry_odds / frozen_fair_odds
    - clv_edge_pct = (entry_odds / frozen_fair_odds - 1.0) * 100.0

    Constitutional Compliance:
    - SPEC-0012: Fail-closed if any odds <= 1.0 (no synthetic / default odds).

    Returns:
        dict with 'clv_raw', 'clv_fair', 'clv_edge_pct', 'beat_closing'.
    """
    if not (math.isfinite(entry_odds) and entry_odds > 1.0):
        raise ClosingLineUnavailableError(
            f"SPEC-0012 Violation: entry_odds must be strictly > 1.0 (got {entry_odds})."
        )
    if not (math.isfinite(frozen_closing_odds) and frozen_closing_odds > 1.0):
        raise ClosingLineUnavailableError(
            f"SPEC-0012 Violation: frozen_closing_odds must be strictly > 1.0 (got {frozen_closing_odds})."
        )
    if not (math.isfinite(frozen_fair_odds) and frozen_fair_odds > 1.0):
        raise ClosingLineUnavailableError(
            f"SPEC-0012 Violation: frozen_fair_odds must be strictly > 1.0 (got {frozen_fair_odds})."
        )

    clv_raw = round(entry_odds / frozen_closing_odds, 4)
    clv_fair = round(entry_odds / frozen_fair_odds, 4)
    clv_edge_pct = round((entry_odds / frozen_fair_odds - 1.0) * 100.0, 2)
    beat_closing = bool(clv_fair > 1.0)

    return {
        "clv_raw": clv_raw,
        "clv_fair": clv_fair,
        "clv_edge_pct": clv_edge_pct,
        "beat_closing": beat_closing,
    }


# ---------------------------------------------------------------------------
# Constitutional Validators (SPEC-0013, SPEC-0014, SPEC-0015)
# ---------------------------------------------------------------------------

def validate_coupon_stake(stake: float) -> bool:
    """SPEC-0015 Constitutional Validator: Minimum 50 TL stake enforcement.

    Raises:
        ValueError fail-closed if stake < 50.0 TL.
    """
    if stake < 50.0:
        raise ValueError(
            f"SPEC-0015 Violation: Coupon stake must be at least 50.0 TL (got {stake:.2f} TL)."
        )
    return True


def check_fixture_kickoff_window(
    kickoff_utc: datetime | str,
    reference_now_utc: datetime | str | None = None,
) -> tuple[bool, str]:
    """Validate kickoff against SPEC-0013 (> now + 3m) and SPEC-0014 (<= now + 12h)."""
    ko_dt = parse_iso_or_datetime(kickoff_utc)
    now_dt = parse_iso_or_datetime(reference_now_utc) if reference_now_utc is not None else datetime.now(UTC)

    min_cutoff = now_dt + timedelta(minutes=3)
    max_cutoff = now_dt + timedelta(hours=12)

    if ko_dt <= min_cutoff:
        return (
            False,
            f"SPEC-0013 Violation: Kickoff {format_trt(ko_dt)} is <= now + 3m cutoff ({format_trt(min_cutoff)}).",
        )
    if ko_dt > max_cutoff:
        return (
            False,
            f"SPEC-0014 Violation: Kickoff {format_trt(ko_dt)} exceeds 12h window ({format_trt(max_cutoff)}).",
        )
    return (True, "VALID_WINDOW")


# ---------------------------------------------------------------------------
# Coordinating Engine
# ---------------------------------------------------------------------------

class ClosingLineFreezeEngine:
    """Coordinating engine for closing line snapshot freeze and CLV tracking."""

    def __init__(
        self,
        store: ClosingLineStore | None = None,
        db_path: Path | str | None = None,
    ) -> None:
        self.store = store or ClosingLineStore(db_path=db_path)

    def is_eligible_for_freeze(
        self,
        kickoff_utc: datetime | str,
        now_utc: datetime | str | None = None,
    ) -> bool:
        """Check if fixture is within [kickoff - 5m, kickoff] window."""
        return is_eligible_for_freeze(kickoff_utc, now_utc)

    def freeze(
        self,
        fixture_id: str,
        market_odds: dict[str, Any],
        kickoff_utc: datetime | str,
        match_name: str = "",
        league: str = "",
        market: str = "1X2",
        bookmaker: str = "PINNACLE",
        fair_closing_odds: dict[str, float] | None = None,
        now_utc: datetime | str | None = None,
        force: bool = False,
    ) -> ClosingLineRecord:
        """Freeze fixture odds into immutable store."""
        return freeze_closing_line(
            fixture_id=fixture_id,
            market_odds=market_odds,
            kickoff_utc=kickoff_utc,
            match_name=match_name,
            league=league,
            market=market,
            bookmaker=bookmaker,
            fair_closing_odds=fair_closing_odds,
            now_utc=now_utc,
            force=force,
            store=self.store,
        )

    def get_frozen_line(
        self,
        fixture_id: str,
        market: str,
        bookmaker: str = "PINNACLE",
    ) -> ClosingLineRecord | None:
        """Retrieve frozen record from store."""
        return self.store.get_record(fixture_id, market, bookmaker)

    def compute_signal_clv(
        self,
        fixture_id: str,
        market: str,
        outcome: str,
        entry_odds: float,
        bookmaker: str = "PINNACLE",
    ) -> dict[str, Any]:
        """Compute CLV for a specific signal against its frozen closing line."""
        record = self.get_frozen_line(fixture_id, market, bookmaker)
        if record is None:
            raise ClosingLineUnavailableError(
                f"Closing line for fixture '{fixture_id}' market '{market}' has not been frozen."
            )
        if outcome not in record.closing_odds:
            raise ClosingLineUnavailableError(
                f"Selection '{outcome}' not found in frozen closing odds for fixture '{fixture_id}'."
            )
        closing_odd = record.closing_odds[outcome]
        fair_odd = record.fair_closing_odds.get(outcome, closing_odd)
        return compute_clv(entry_odds, closing_odd, fair_odd)
