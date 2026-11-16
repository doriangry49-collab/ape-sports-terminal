"""
TASK-018: Tests for HistoricalOddsArchive.
"""
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SPORTS_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    'sports_engine.storage.historical_odds_archive',
    str(_SPORTS_ROOT / 'src/sports_engine/storage/historical_odds_archive.py')
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules['sports_engine.storage.historical_odds_archive'] = _mod
_spec.loader.exec_module(_mod)

HistoricalOddsArchive = _mod.HistoricalOddsArchive
HistoricalOddsRecord = _mod.HistoricalOddsRecord
ProvenanceType = _mod.ProvenanceType
SnapshotLabel = _mod.SnapshotLabel
OddsMovementDirection = _mod.OddsMovementDirection
make_snapshot_id = _mod.make_snapshot_id
calculate_movement = _mod.calculate_movement


def _rec(bookmaker='pinnacle', market='1X2', selection='Leeds', odds=8.25,
         ts='2026-10-09T10:00:00+00:00', prov=None, lbl=None):
    eid = 'propline_epl_20261010_arsenal_vs_leeds'
    sid = make_snapshot_id('propline', eid, bookmaker, market, selection, ts)
    return HistoricalOddsRecord(
        historical_snapshot_id=sid, provider='propline',
        source_type=prov or ProvenanceType.SELF_CAPTURED,
        provider_event_id=eid, event_id=eid, sport='soccer',
        competition='Premier League', competition_id=None,
        event_start_time='2026-10-10T11:30:00+00:00',
        home_team='Arsenal', away_team='Leeds',
        bookmaker=bookmaker, market=market, selection=selection,
        odds_decimal=odds, odds_raw=odds, odds_format_raw='decimal',
        actual_snapshot_timestamp=ts, retrieved_at=datetime.now(UTC).isoformat(),
        snapshot_label=lbl or SnapshotLabel.REGULAR,
    )


@pytest.fixture
def arch(tmp_path):
    return HistoricalOddsArchive(tmp_path / 'hist')


# 1. Snapshot ID deterministik
def test_1_snapshot_id_deterministic():
    a = make_snapshot_id('p', 'e1', 'bm', 'mkt', 'sel', '2026-01-01T00:00:00+00:00')
    b = make_snapshot_id('p', 'e1', 'bm', 'mkt', 'sel', '2026-01-01T00:00:00+00:00')
    assert a == b and len(a) == 24

# 2. Farklı girdiler farklı ID
def test_2_different_ids():
    a = make_snapshot_id('p', 'e1', 'bm_a', 'mkt', 'sel', '2026-01-01T00:00:00+00:00')
    b = make_snapshot_id('p', 'e1', 'bm_b', 'mkt', 'sel', '2026-01-01T00:00:00+00:00')
    c = make_snapshot_id('p', 'e1', 'bm_a', 'mkt', 'sel', '2026-01-02T00:00:00+00:00')
    assert a != b and a != c

# 3. Immutable storage - no overwrite
def test_3_save_no_overwrite(arch):
    r = _rec()
    ok, reason = arch.save_record(r)
    assert ok is True and reason == 'SAVED'
    ok2, reason2 = arch.save_record(r)
    assert ok2 is False and reason2 == 'DUPLICATE'

# 4. Batch duplicate protection
def test_4_batch_duplicate(arch):
    r = _rec()
    counts = arch.import_batch([r, r])
    assert counts['saved'] == 1 and counts['duplicate'] == 1 and counts['error'] == 0

# 5. Provenance types stored correctly
def test_5_provenance_types(arch):
    r_ph = _rec(ts='2026-10-09T08:00:00+00:00', prov=ProvenanceType.PROVIDER_HISTORICAL)
    r_sc = _rec(ts='2026-10-09T09:00:00+00:00', prov=ProvenanceType.SELF_CAPTURED)
    arch.import_batch([r_ph, r_sc])
    history = arch.get_event_history('propline_epl_20261010_arsenal_vs_leeds')
    assert len(history) == 2
    types = {r.source_type for r in history}
    assert ProvenanceType.PROVIDER_HISTORICAL in types
    assert ProvenanceType.SELF_CAPTURED in types

# 6. Bookmaker separation
def test_6_bookmaker_separation(arch):
    r1 = _rec(bookmaker='pinnacle', ts='2026-10-09T10:00:00+00:00')
    r2 = _rec(bookmaker='bovada', ts='2026-10-09T10:00:00+00:00')
    arch.import_batch([r1, r2])
    history = arch.get_event_history('propline_epl_20261010_arsenal_vs_leeds')
    assert {r.bookmaker for r in history} == {'pinnacle', 'bovada'}

# 7. Timestamp preserved
def test_7_timestamp_preserved(arch):
    ts = '2026-10-09T14:35:22+00:00'
    arch.save_record(_rec(ts=ts))
    history = arch.get_event_history('propline_epl_20261010_arsenal_vs_leeds')
    assert history[0].actual_snapshot_timestamp == ts

# 8. Movement: SHORTENED / DRIFTED / SIGNIFICANT
def test_8_movement_calc():
    snaps = [
        {'actual_snapshot_timestamp': '2026-10-09T08:00:00+00:00', 'odds_decimal': 8.0,
         'bookmaker': 'p', 'market': '1X2', 'selection': 'Leeds',
         'event_id': 'e1', 'provider': 'x', 'source_type': ProvenanceType.SELF_CAPTURED},
        {'actual_snapshot_timestamp': '2026-10-09T10:00:00+00:00', 'odds_decimal': 7.5,
         'bookmaker': 'p', 'market': '1X2', 'selection': 'Leeds',
         'event_id': 'e1', 'provider': 'x', 'source_type': ProvenanceType.SELF_CAPTURED},
        {'actual_snapshot_timestamp': '2026-10-09T12:00:00+00:00', 'odds_decimal': 9.0,
         'bookmaker': 'p', 'market': '1X2', 'selection': 'Leeds',
         'event_id': 'e1', 'provider': 'x', 'source_type': ProvenanceType.SELF_CAPTURED},
    ]
    h = calculate_movement(snaps, '2026-10-10T11:30:00Z')
    assert h.number_of_snapshots == 3
    assert h.minimum_odds == 7.5
    assert h.maximum_odds == 9.0
    assert h.number_of_changes == 2
    assert h.movements[0].direction == OddsMovementDirection.SIGNIFICANT_MOVE

# 9. STABLE movement
def test_9_stable():
    snaps = [
        {'actual_snapshot_timestamp': '2026-10-09T08:00:00+00:00', 'odds_decimal': 8.0,
         'bookmaker': 'p', 'market': '1X2', 'selection': 'Leeds',
         'event_id': 'e1', 'provider': 'x', 'source_type': ProvenanceType.SELF_CAPTURED},
        {'actual_snapshot_timestamp': '2026-10-09T10:00:00+00:00', 'odds_decimal': 8.02,
         'bookmaker': 'p', 'market': '1X2', 'selection': 'Leeds',
         'event_id': 'e1', 'provider': 'x', 'source_type': ProvenanceType.SELF_CAPTURED},
    ]
    h = calculate_movement(snaps, '2026-10-10T11:30:00Z')
    assert h.movements[0].direction == OddsMovementDirection.STABLE
    assert h.number_of_changes == 0

# 10. Last prematch detection
def test_10_last_prematch():
    snaps = [
        {'actual_snapshot_timestamp': '2026-10-09T08:00:00+00:00', 'odds_decimal': 8.25,
         'bookmaker': 'p', 'market': '1X2', 'selection': 'Leeds',
         'event_id': 'e1', 'provider': 'x', 'source_type': ProvenanceType.SELF_CAPTURED},
        {'actual_snapshot_timestamp': '2026-10-10T10:30:00+00:00', 'odds_decimal': 8.50,
         'bookmaker': 'p', 'market': '1X2', 'selection': 'Leeds',
         'event_id': 'e1', 'provider': 'x', 'source_type': ProvenanceType.SELF_CAPTURED},
    ]
    h = calculate_movement(snaps, '2026-10-10T11:30:00Z')
    assert h.last_prematch_odds == 8.50

# 11. No synthetic odds
def test_11_no_synthetic(arch):
    arch.save_record(_rec(odds=8.25, ts='2026-10-09T10:00:00+00:00'))
    history = arch.get_event_history('propline_epl_20261010_arsenal_vs_leeds')
    assert len(history) == 1 and history[0].odds_decimal == 8.25

# 12. Market separation
def test_12_market_separation(arch):
    r1 = _rec(market='1X2', selection='Leeds', ts='2026-10-09T10:00:00+00:00')
    r2 = _rec(market='TOTALS', selection='Over 2.5', ts='2026-10-09T10:00:00+00:00')
    arch.import_batch([r1, r2])
    history = arch.get_event_history('propline_epl_20261010_arsenal_vs_leeds')
    assert {r.market for r in history} == {'1X2', 'TOTALS'}

# 13. Coverage report
def test_13_coverage(arch):
    arch.import_batch([
        _rec(bookmaker='pinnacle', ts='2026-10-09T08:00:00+00:00'),
        _rec(bookmaker='bovada', ts='2026-10-09T08:00:00+00:00'),
        _rec(bookmaker='pinnacle', ts='2026-10-09T10:00:00+00:00'),
    ])
    r = arch.coverage_report()
    assert r['total_records'] == 3
    assert r['unique_bookmakers'] == 2
    assert 'SELF_CAPTURED' in r['source_type_breakdown']

# 14. Provenance in coverage
def test_14_provenance_coverage(arch):
    arch.import_batch([
        _rec(prov=ProvenanceType.PROVIDER_HISTORICAL, ts='2026-10-08T12:00:00+00:00'),
        _rec(prov=ProvenanceType.SELF_CAPTURED, ts='2026-10-09T10:00:00+00:00'),
    ])
    r = arch.coverage_report()
    assert r['source_type_breakdown'].get('PROVIDER_HISTORICAL', 0) == 1
    assert r['source_type_breakdown'].get('SELF_CAPTURED', 0) == 1

# 15. Point-in-time integrity
def test_15_point_in_time():
    timestamps = ['2026-10-08T20:00:00+00:00', '2026-10-09T12:00:00+00:00', '2026-10-10T09:00:00+00:00']
    snaps = [
        {'actual_snapshot_timestamp': ts, 'odds_decimal': o,
         'bookmaker': 'p', 'market': '1X2', 'selection': 'Leeds',
         'event_id': 'e1', 'provider': 'x', 'source_type': ProvenanceType.SELF_CAPTURED}
        for ts, o in zip(timestamps, [8.0, 8.25, 7.80], strict=True)
    ]
    h = calculate_movement(snaps, '2026-10-10T11:30:00Z')
    assert h.number_of_snapshots == 3
    assert len(h.movements) == 2
    mv_ts = {m.timestamp for m in h.movements}
    assert '2026-10-09T12:00:00+00:00' in mv_ts
    assert '2026-10-10T09:00:00+00:00' in mv_ts

# 16. TASK-017 snapshots importable
def test_16_task017_snapshots():
    d = _SPORTS_ROOT / 'artifacts/odds/TASK-017-odds-history'
    files = list(d.glob('odds_snapshot_*.json'))
    assert len(files) >= 1, 'At least 1 TASK-017 snapshot must exist'
    for sf in files[:2]:
        data = json.loads(sf.read_text(encoding='utf-8'))
        records = data.get('records', data) if isinstance(data, dict) else data
        assert len(records) > 0

# 17. No opening/closing label fabrication
def test_17_no_fabricated_opening_closing():
    r = _rec(lbl=SnapshotLabel.REGULAR)
    assert r.snapshot_label == SnapshotLabel.REGULAR
    assert r.snapshot_label != SnapshotLabel.CLOSING_ODDS
    assert r.snapshot_label != SnapshotLabel.FIRST_AVAILABLE

# 18. Archive historical dir exists after import
def test_18_historical_dir_structure():
    base = _SPORTS_ROOT / 'artifacts/odds/historical'
    assert base.exists(), 'Historical archive directory must exist'
    assert (base / 'index.json').exists(), 'index.json must exist'
