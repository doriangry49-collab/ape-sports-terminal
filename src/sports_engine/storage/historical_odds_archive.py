"""
TASK-018: Historical Odds Archive — Data Layer
==============================================
Provides:
  - HistoricalOddsRecord (canonical schema)
  - HistoricalOddsArchive (immutable storage + duplicate protection)
  - OddsHistoryQuery (data contract for UI)
  - MovementCalculator (first/last/min/max/changes per bookmaker/selection)
  - ProvenanceType enum (PROVIDER_HISTORICAL | SELF_CAPTURED)
"""

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class ProvenanceType(str, Enum):
    PROVIDER_HISTORICAL = "PROVIDER_HISTORICAL"
    SELF_CAPTURED = "SELF_CAPTURED"


class SnapshotLabel(str, Enum):
    FIRST_AVAILABLE = "FIRST_AVAILABLE_SNAPSHOT"
    LAST_PREMATCH = "LAST_PREMATCH_SNAPSHOT"
    CLOSING_ODDS = "CLOSING_ODDS"
    REGULAR = "REGULAR"


class OddsMovementDirection(str, Enum):
    SHORTENED = "SHORTENED"
    DRIFTED = "DRIFTED"
    STABLE = "STABLE"
    SIGNIFICANT_MOVE = "SIGNIFICANT_MOVE"


MOVEMENT_THRESHOLD_PCT = 1.0
SIGNIFICANT_THRESHOLD_PCT = 5.0


@dataclass
class HistoricalOddsRecord:
    historical_snapshot_id: str
    provider: str
    source_type: ProvenanceType
    provider_event_id: str
    event_id: str
    sport: str
    competition: str
    competition_id: Optional[str]
    event_start_time: str
    home_team: str
    away_team: str
    bookmaker: str
    market: str
    selection: str
    odds_decimal: float
    odds_raw: float
    odds_format_raw: str
    actual_snapshot_timestamp: str
    retrieved_at: str
    source_timestamp: Optional[str] = None
    previous_snapshot_timestamp: Optional[str] = None
    next_snapshot_timestamp: Optional[str] = None
    requested_timestamp: Optional[str] = None
    snapshot_label: SnapshotLabel = SnapshotLabel.REGULAR
    provider_snapshot_id: Optional[str] = None
    import_batch_id: Optional[str] = None


def make_snapshot_id(
    provider: str,
    provider_event_id: str,
    bookmaker: str,
    market: str,
    selection: str,
    actual_snapshot_timestamp: str,
) -> str:
    raw = f"{provider}|{provider_event_id}|{bookmaker}|{market}|{selection}|{actual_snapshot_timestamp}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


@dataclass
class OddsMovementPoint:
    timestamp: str
    odds: float
    implied_prob: float
    direction: OddsMovementDirection
    pct_change: float
    is_significant: bool


@dataclass
class SelectionOddsHistory:
    provider: str
    event_id: str
    bookmaker: str
    market: str
    selection: str
    snapshots: list = field(default_factory=list)
    first_available_odds: Optional[float] = None
    last_prematch_odds: Optional[float] = None
    closing_odds: Optional[float] = None
    minimum_odds: Optional[float] = None
    maximum_odds: Optional[float] = None
    absolute_change: Optional[float] = None
    percentage_change: Optional[float] = None
    implied_prob_change: Optional[float] = None
    number_of_snapshots: int = 0
    number_of_changes: int = 0
    movements: list = field(default_factory=list)
    has_confirmed_closing: bool = False
    closing_label: str = "LAST_PREMATCH_SNAPSHOT"


def calculate_movement(
    snapshots: list,
    kickoff_iso: str,
    prematch_window_seconds: int = 7200,
) -> "Optional":
    if not snapshots:
        return None
    sorted_snaps = sorted(snapshots, key=lambda x: x["actual_snapshot_timestamp"])
    kickoff = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
    odds_values = [s["odds_decimal"] for s in sorted_snaps]

    last_prematch = None
    for snap in reversed(sorted_snaps):
        ts = datetime.fromisoformat(snap["actual_snapshot_timestamp"].replace("Z", "+00:00"))
        delta = (kickoff - ts).total_seconds()
        if 0 <= delta <= prematch_window_seconds:
            last_prematch = snap
            break

    movements = []
    for i in range(1, len(sorted_snaps)):
        prev = sorted_snaps[i - 1]
        curr = sorted_snaps[i]
        delta = curr["odds_decimal"] - prev["odds_decimal"]
        pct = (delta / prev["odds_decimal"]) * 100 if prev["odds_decimal"] else 0.0
        imp = 1.0 / curr["odds_decimal"] if curr["odds_decimal"] else 0.0
        if abs(pct) >= SIGNIFICANT_THRESHOLD_PCT:
            direction = OddsMovementDirection.SIGNIFICANT_MOVE
        elif pct < -MOVEMENT_THRESHOLD_PCT:
            direction = OddsMovementDirection.SHORTENED
        elif pct > MOVEMENT_THRESHOLD_PCT:
            direction = OddsMovementDirection.DRIFTED
        else:
            direction = OddsMovementDirection.STABLE
        movements.append(OddsMovementPoint(
            timestamp=curr["actual_snapshot_timestamp"],
            odds=curr["odds_decimal"],
            implied_prob=round(imp, 6),
            direction=direction,
            pct_change=round(pct, 4),
            is_significant=abs(pct) >= SIGNIFICANT_THRESHOLD_PCT,
        ))

    first_odds = odds_values[0]
    last_odds = odds_values[-1]
    abs_change = round(last_odds - first_odds, 4)
    pct_change = round((abs_change / first_odds) * 100, 4) if first_odds else 0.0
    imp_change = round((1 / last_odds - 1 / first_odds), 6) if first_odds and last_odds else 0.0
    s0 = sorted_snaps[0]
    return SelectionOddsHistory(
        provider=s0.get("provider", ""),
        event_id=s0.get("event_id", ""),
        bookmaker=s0.get("bookmaker", ""),
        market=s0.get("market", ""),
        selection=s0.get("selection", ""),
        snapshots=sorted_snaps,
        first_available_odds=first_odds,
        last_prematch_odds=last_prematch["odds_decimal"] if last_prematch else last_odds,
        minimum_odds=min(odds_values),
        maximum_odds=max(odds_values),
        absolute_change=abs_change,
        percentage_change=pct_change,
        implied_prob_change=imp_change,
        number_of_snapshots=len(sorted_snaps),
        number_of_changes=sum(1 for m in movements if m.direction != OddsMovementDirection.STABLE),
        movements=movements,
        has_confirmed_closing=False,
        closing_label="LAST_PREMATCH_SNAPSHOT",
    )


class HistoricalOddsArchive:
    def __init__(self, base_dir: "Any"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.base_dir / "index.json"
        self._index: dict = self._load_index()

    def _load_index(self) -> dict:
        if self._index_path.exists():
            with open(self._index_path, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_index(self) -> None:
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2)

    def _provider_dir(self, provider: str) -> Path:
        d = self.base_dir / provider
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_record(self, record: "HistoricalOddsRecord", commit_index: bool = True) -> tuple:
        sid = record.historical_snapshot_id
        if sid in self._index:
            return False, "DUPLICATE"
        provider_dir = self._provider_dir(record.provider)
        event_dir = provider_dir / record.event_id
        event_dir.mkdir(parents=True, exist_ok=True)
        record_path = event_dir / f"{sid}.json"
        if record_path.exists():
            self._index[sid] = str(record_path)
            if commit_index:
                self._save_index()
            return False, "ALREADY_EXISTS_ON_DISK"
        data = asdict(record)
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._index[sid] = str(record_path)
        if commit_index:
            self._save_index()
        return True, "SAVED"

    def import_batch(self, records: list["HistoricalOddsRecord"]) -> dict:
        counts: dict = {"saved": 0, "duplicate": 0, "error": 0}
        any_modified = False
        for rec in records:
            try:
                saved, reason = self.save_record(rec, commit_index=False)
                if saved:
                    counts["saved"] += 1
                    any_modified = True
                elif reason in ("DUPLICATE", "ALREADY_EXISTS_ON_DISK"):
                    counts["duplicate"] += 1
                    if reason == "ALREADY_EXISTS_ON_DISK":
                        any_modified = True
            except Exception:
                counts["error"] += 1
        if any_modified:
            self._save_index()
        return counts

    def get_event_history(
        self, event_id: str, provider: Optional[str] = None
    ) -> list["HistoricalOddsRecord"]:
        records: list = []
        search_dirs = []
        if provider:
            event_dir = self.base_dir / provider / event_id
            if event_dir.exists():
                search_dirs.append(event_dir)
        else:
            for p_dir in self.base_dir.iterdir():
                if p_dir.is_dir():
                    event_dir = p_dir / event_id
                    if event_dir.exists():
                        search_dirs.append(event_dir)
        for event_dir in search_dirs:
            for f in event_dir.glob("*.json"):
                with open(f, encoding="utf-8") as fp:
                    d = json.load(fp)
                d["source_type"] = ProvenanceType(d["source_type"])
                d["snapshot_label"] = SnapshotLabel(d.get("snapshot_label", "REGULAR"))
                records.append(HistoricalOddsRecord(**d))
        return sorted(records, key=lambda r: r.actual_snapshot_timestamp)

    def coverage_report(self) -> dict:
        total = 0
        providers: set = set()
        events: set = set()
        bookmakers: set = set()
        markets: set = set()
        selections: set = set()
        competitions: set = set()
        source_types: dict = {}
        earliest: Optional[str] = None
        latest: Optional[str] = None
        for sid, path_str in self._index.items():
            path = Path(path_str)
            if not path.exists():
                continue
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            total += 1
            providers.add(d.get("provider", ""))
            events.add(d.get("event_id", ""))
            bookmakers.add(d.get("bookmaker", ""))
            markets.add(d.get("market", ""))
            selections.add(d.get("selection", ""))
            competitions.add(d.get("competition", ""))
            st = d.get("source_type", "UNKNOWN")
            source_types[st] = source_types.get(st, 0) + 1
            ts = d.get("actual_snapshot_timestamp", "")
            if ts:
                if earliest is None or ts < earliest:
                    earliest = ts
                if latest is None or ts > latest:
                    latest = ts
        return {
            "total_records": total,
            "unique_events": len(events),
            "unique_providers": len(providers),
            "unique_bookmakers": len(bookmakers),
            "unique_markets": len(markets),
            "unique_selections": len(selections),
            "unique_competitions": len(competitions),
            "source_type_breakdown": source_types,
            "earliest_snapshot": earliest,
            "latest_snapshot": latest,
            "avg_records_per_event": round(total / max(1, len(events)), 1),
            "providers": sorted(providers),
            "markets": sorted(markets),
        }


@dataclass
class OddsHistoryQueryRequest:
    event_id: str
    market: Optional[str] = None
    selection: Optional[str] = None
    bookmaker: Optional[str] = None
    source_type: Optional[ProvenanceType] = None


@dataclass
class OddsHistoryResponse:
    event: dict
    market: str
    selection: str
    bookmakers: list[str]
    snapshots: list
    by_bookmaker: dict
    movement_summary: dict
    provenance: dict
    query_timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
