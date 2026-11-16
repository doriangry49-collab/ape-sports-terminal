"""Unit tests for Dual-Feed Sharp Odds Redundancy Manager."""
from espn_odds_adapter import american_to_decimal
from sharp_feed_manager import DualFeedSharpManager


def test_american_to_decimal_conversions():
    assert american_to_decimal("+100") == 2.0
    assert american_to_decimal("+150") == 2.5
    assert american_to_decimal("-200") == 1.5
    assert american_to_decimal("-160") == 1.625
    assert american_to_decimal("0") is None
    assert american_to_decimal(None) is None


def test_dual_feed_manager_transitions():
    mgr = DualFeedSharpManager()
    assert mgr.propline_active is True
    assert mgr.consecutive_propline_errors == 0

    # First error -> still active
    mgr.report_propline_failure()
    assert mgr.propline_active is True
    assert mgr.consecutive_propline_errors == 1

    # Second consecutive error -> trips circuit breaker to secondary feed
    mgr.report_propline_failure()
    assert mgr.propline_active is False
    assert mgr.consecutive_propline_errors == 2

    # Success restores primary
    mgr.report_propline_success()
    assert mgr.propline_active is True
    assert mgr.consecutive_propline_errors == 0

    # Immediate circuit-breaker engagement
    mgr.engage_fallback()
    assert mgr.propline_active is False
    assert mgr.consecutive_propline_errors >= 2


def test_national_team_turkish_english_matching():
    """Verify international break national team names match across Turkish Nesine & English ESPN."""
    from live_stale_line_adapter import match_nesine_fixture

    bulletin = [
        {"nesine_code": "10", "home": "Sırbistan", "away": "Almanya"},
        {"nesine_code": "11", "home": "Moldova", "away": "Kazakistan"},
        {"nesine_code": "12", "home": "Lihtenştayn", "away": "Azerbaycan"},
    ]
    assert match_nesine_fixture("Serbia", "Germany", bulletin)["nesine_code"] == "10"
    assert match_nesine_fixture("Moldova", "Kazakhstan", bulletin)["nesine_code"] == "11"
    assert match_nesine_fixture("Liechtenstein", "Azerbaijan", bulletin)["nesine_code"] == "12"


def test_bzzoiro_global_odds_and_fallback_cache(monkeypatch):
    """Verify Bzzoiro global adapter parses valid 1X2 / O/U 2.5 odds and fails closed without a key."""
    import io
    import json as json_mod

    import bzzoiro_odds_adapter

    # 1. Fail-closed when API key is missing
    monkeypatch.setattr(bzzoiro_odds_adapter, "_resolve_bzzoiro_key", lambda: "")
    assert bzzoiro_odds_adapter.fetch_bzzoiro_global_odds() == []

    # 2. Parse valid 1X2 & O/U 2.5 events and drop invalid odds
    payload = {
        "next": None,
        "results": [
            {
                "id": 901,
                "home_team": "Brazil",
                "away_team": "Argentina",
                "event_date": "2026-11-14T20:00:00Z",
                "league": {"name": "Int. Friendly Games", "country": "World"},
                "odds_home": 2.15,
                "odds_draw": 3.30,
                "odds_away": 3.40,
                "odds_over_25": 1.95,
                "odds_under_25": 1.85,
            },
            {
                "id": 902,
                "home_team": "Invalid",
                "away_team": "Match",
                "odds_home": 1.0,
                "odds_draw": None,
                "odds_away": 2.50,
            },
        ],
    }

    class _FakeResp:
        def __init__(self, body: bytes):
            self._buf = io.BytesIO(body)
        def read(self):
            return self._buf.read()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    monkeypatch.setattr(bzzoiro_odds_adapter, "_resolve_bzzoiro_key", lambda: "test_token")
    monkeypatch.setattr(
        bzzoiro_odds_adapter.urllib.request,
        "urlopen",
        lambda req, timeout=8.0: _FakeResp(json_mod.dumps(payload).encode("utf-8")),
    )

    events = bzzoiro_odds_adapter.fetch_bzzoiro_global_odds(date_from="2026-11-14", date_to="2026-11-15")
    assert len(events) == 1
    assert events[0]["event_id"] == "bzz_901"
    assert events[0]["provider"] == "Bzzoiro_Consensus"
    assert events[0]["current_1x2"] == (2.15, 3.30, 3.40)
    assert events[0]["current_ou25"] == (1.95, 1.85)

    # 3. DualFeedSharpManager caches Bzzoiro results across repeated calls
    call_count = {"n": 0}
    import sharp_feed_manager

    def _mock_fetch():
        call_count["n"] += 1
        return events

    monkeypatch.setattr(sharp_feed_manager, "fetch_bzzoiro_global_odds", _mock_fetch)
    mgr = DualFeedSharpManager()
    assert mgr.get_bzzoiro_fallback_odds() == events
    assert mgr.get_bzzoiro_fallback_odds() == events
    assert call_count["n"] == 1


def test_expanded_turkish_national_and_club_matching():
    """Verify expanded CONMEBOL/CONCACAF/AFC/UEFA multi-word national & B. Münih club aliases."""
    import inspect

    import bzzoiro_odds_adapter
    from live_stale_line_adapter import match_nesine_fixture

    bulletin = [
        {"nesine_code": "201", "home": "Kolombiya", "away": "Şili"},
        {"nesine_code": "202", "home": "Kosta Rika", "away": "Bosna Hersek"},
        {"nesine_code": "203", "home": "Faroe Adaları", "away": "Karadağ"},
        {"nesine_code": "204", "home": "Avustralya", "away": "Yeni Zelanda"},
        {"nesine_code": "205", "home": "B. Münih (K)", "away": "Wolfsburg (K)"},
    ]
    assert match_nesine_fixture("Colombia", "Chile", bulletin)["nesine_code"] == "201"
    assert match_nesine_fixture("Costa Rica", "Bosnia and Herzegovina", bulletin)["nesine_code"] == "202"
    assert match_nesine_fixture("Faroe Islands", "Montenegro", bulletin)["nesine_code"] == "203"
    assert match_nesine_fixture("Australia", "New Zealand", bulletin)["nesine_code"] == "204"
    assert match_nesine_fixture("Bayern Munich (W)", "VfL Wolfsburg (W)", bulletin)["nesine_code"] == "205"
    assert inspect.signature(bzzoiro_odds_adapter.fetch_bzzoiro_global_odds).parameters["max_pages"].default == 15


def test_espn_totals_strictly_requires_25_line(monkeypatch):
    """Ensure ESPN alternate lines (e.g., 1.5 or 3.5) never masquerade as 2.5 O/U odds."""
    import io
    import json

    import espn_odds_adapter

    payload = {
        "events": [
            {
                "id": "101",
                "date": "2026-11-14T19:45Z",
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Northern Ireland"}},
                            {"homeAway": "away", "team": {"displayName": "Ukraine"}},
                        ],
                        "odds": [
                            {
                                "provider": {"displayName": "DraftKings"},
                                "overUnder": 1.5,
                                "total": {
                                    "over": {"open": {"line": "o2.5", "odds": "+120"}, "close": {"line": "o1.5", "odds": "-165"}},
                                    "under": {"open": {"line": "u2.5", "odds": "-170"}, "close": {"line": "u1.5", "odds": "+130"}},
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "id": "102",
                "date": "2026-11-14T19:45Z",
                "competitions": [
                    {
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Poland"}},
                            {"homeAway": "away", "team": {"displayName": "Romania"}},
                        ],
                        "odds": [
                            {
                                "provider": {"displayName": "DraftKings"},
                                "overUnder": 2.5,
                                "total": {
                                    "over": {"close": {"line": "o2.5", "odds": "-155"}},
                                    "under": {"close": {"line": "u2.5", "odds": "+120"}},
                                },
                            }
                        ],
                    }
                ],
            },
        ]
    }

    class _FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        espn_odds_adapter.urllib.request,
        "urlopen",
        lambda req, timeout=6.0: _FakeResp(json.dumps(payload).encode("utf-8")),
    )
    rows = espn_odds_adapter.fetch_espn_sharp_odds_for_league("uefa.nations")
    assert len(rows) == 2
    assert rows[0]["current_ou25"] is None
    assert rows[0]["open_ou25"] == (2.2, 1.588)
    assert rows[1]["current_ou25"] == (1.645, 2.2)



