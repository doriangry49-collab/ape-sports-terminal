"""Historical Odds Archive & Movement Intelligence Engine (TASK-017).

Provides:
- Immutable snapshot persistence (never overwrites).
- Canonical record schema with provenance, kickoff time, and last_prematch flag.
- Inter-snapshot line movement calculations (delta, % change, implied prob change, direction).
- CLV data structure foundation.
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import get_settings
from sports_engine.adapters.schema import NormalizedOddsRecord

DEFAULT_ARCHIVE_DIR = get_settings().project_root / "artifacts" / "odds" / "TASK-017-odds-history"


@dataclass(frozen=True)
class HistoricalOddsEntry:
    """Canonical immutable historical odds record."""
    snapshot_id: str
    captured_at: str
    event_id: str
    provider: str
    bookmaker: str
    competition: str
    market: str
    selection: str
    odds_raw: str
    odds_decimal: float
    event_start_time: str | None
    home_team: str
    away_team: str
    is_last_prematch: bool = False
    source_market_id: str = ""
    source_selection_id: str = ""


class OddsArchiveManager:
    """Manages immutable persistence and retrieval of historical odds snapshots."""

    def __init__(self, archive_dir: Path | str | None = None):
        self.archive_dir = Path(archive_dir) if archive_dir else DEFAULT_ARCHIVE_DIR
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot_records(
        self,
        records: list[NormalizedOddsRecord],
        snapshot_id: str,
        captured_at: datetime | None = None,
    ) -> list[HistoricalOddsEntry]:
        """Convert NormalizedOddsRecords into immutable HistoricalOddsEntry objects."""
        now_dt = captured_at or datetime.now(UTC)
        cap_iso = now_dt.isoformat()

        entries: list[HistoricalOddsEntry] = []
        for r in records:
            # Check if within 2 hours of kickoff (preliminary last_prematch flag)
            is_last = False
            if r.kickoff:
                try:
                    ko_dt = datetime.fromisoformat(r.kickoff.replace("Z", "+00:00"))
                    if ko_dt.tzinfo is None:
                        ko_dt = ko_dt.replace(tzinfo=UTC)
                    time_to_ko = (ko_dt - now_dt).total_seconds()
                    # If kickoff is within 2 hours and hasn't started yet
                    if 0 <= time_to_ko <= 7200:
                        is_last = True
                except Exception:
                    pass

            entry = HistoricalOddsEntry(
                snapshot_id=snapshot_id,
                captured_at=cap_iso,
                event_id=r.event_id,
                provider=r.provider,
                bookmaker=r.bookmaker,
                competition=r.competition,
                market=r.market,
                selection=r.selection,
                odds_raw=r.odds_raw,
                odds_decimal=r.odds_decimal,
                event_start_time=r.kickoff,
                home_team=r.home_team,
                away_team=r.away_team,
                is_last_prematch=is_last,
                source_market_id=r.source_market_id,
                source_selection_id=r.source_selection_id,
            )
            entries.append(entry)
        return entries

    def save_immutable_snapshot(
        self,
        snapshot_id: str,
        entries: list[HistoricalOddsEntry],
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Persist snapshot. Strictly enforces immutability (fails if file exists)."""
        target_path = self.archive_dir / f"{snapshot_id}.json"
        if target_path.exists():
            raise FileExistsError(
                f"Immutable violation: snapshot file '{target_path.name}' already exists and cannot be overwritten."
            )

        payload = {
            "snapshot_id": snapshot_id,
            "saved_at": datetime.now(UTC).isoformat(),
            "total_records": len(entries),
            "metadata": metadata or {},
            "records": [asdict(e) for e in entries],
        }

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        return target_path

    def load_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        """Load an archived snapshot by ID or filename."""
        filename = snapshot_id if snapshot_id.endswith(".json") else f"{snapshot_id}.json"
        path = self.archive_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Snapshot '{filename}' not found in archive.")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def list_archived_snapshots(self) -> list[str]:
        """List all archived snapshot IDs in chronological order."""
        files = sorted(self.archive_dir.glob("*.json"))
        return [f.stem for f in files]

    @staticmethod
    def calculate_line_movement(
        older_entries: list[dict[str, Any]],
        newer_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Calculate line movements between two snapshots."""
        # Key: (event_id, provider, bookmaker, market, selection)
        def make_key(e: dict[str, Any]) -> tuple:
            return (
                e.get("event_id"),
                e.get("provider"),
                e.get("bookmaker"),
                e.get("market"),
                e.get("selection"),
            )

        old_map = {make_key(e): e for e in older_entries}
        movements: list[dict[str, Any]] = []

        for new_e in newer_entries:
            k = make_key(new_e)
            old_e = old_map.get(k)
            if not old_e:
                continue

            o_old = float(old_e.get("odds_decimal", 0.0))
            o_new = float(new_e.get("odds_decimal", 0.0))
            if o_old <= 1.0 or o_new <= 1.0:
                continue

            delta = round(o_new - o_old, 4)
            pct = round((delta / o_old) * 100.0, 2)
            p_imp_old = round(1.0 / o_old, 4)
            p_imp_new = round(1.0 / o_new, 4)
            p_delta = round(p_imp_new - p_imp_old, 4)

            direction = "STABLE"
            if abs(pct) >= 1.0:
                direction = "SHORTENED" if delta < 0 else "DRIFTED"

            movements.append({
                "event_id": new_e.get("event_id"),
                "fixture": f"{new_e.get('home_team')} vs {new_e.get('away_team')}",
                "provider": new_e.get("provider"),
                "bookmaker": new_e.get("bookmaker"),
                "market": new_e.get("market"),
                "selection": new_e.get("selection"),
                "initial_odds": o_old,
                "latest_odds": o_new,
                "delta_odds": delta,
                "pct_change": pct,
                "initial_implied_prob": p_imp_old,
                "latest_implied_prob": p_imp_new,
                "delta_implied_prob": p_delta,
                "direction": direction,
                "initial_timestamp": old_e.get("captured_at"),
                "latest_timestamp": new_e.get("captured_at"),
            })

        return movements
