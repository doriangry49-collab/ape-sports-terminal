"""Unit tests for live_stale_line_adapter resilience and SPEC-0012 compliance."""

from __future__ import annotations

import json
import urllib.error

import pytest

from live_stale_line_adapter import (
    AdapterHTTPError,
    AdapterTimeoutError,
    _get_json,
    fetch_nesine_live_bulletin,
)


def _create_mock_nesine_payload() -> dict:
    return {
        "sg": {
            "EA": [
                {
                    "TYPE": 1,
                    "C": 101,
                    "HN": "Galatasaray",
                    "AN": "Fenerbahce",
                    "D": "2026-11-02",
                    "T": "20:00",
                    "EMBS": 1,
                    "MA": [
                        {
                            "MTID": 1,
                            "MBS": 1,
                            "OCA": [
                                {"N": 1, "O": "2.10"},
                                {"N": 2, "O": "3.20"},
                                {"N": 3, "O": "2.90"},
                            ],
                        },
                        {
                            "MTID": 12,
                            "SOV": 2.5,
                            "OCA": [
                                {"N": 1, "O": "1.85"},
                                {"N": 2, "O": "1.75"},
                            ],
                        },
                    ],
                }
            ]
        }
    }


def test_fetch_nesine_live_bulletin_retry_on_network_glitch(monkeypatch):
    """Verify that transient network errors trigger retry with exponential backoff and recover."""
    attempts = 0
    mock_payload = _create_mock_nesine_payload()

    class MockResp:
        def __init__(self, data: dict):
            self.status = 200
            self._data = json.dumps(data).encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def mock_urlopen(req, timeout=10.0):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.URLError("Temporary CDN Connection Refused")
        return MockResp(mock_payload)

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)

    results = fetch_nesine_live_bulletin(timeout=10.0, max_retries=3, backoff_factor=0.01)

    assert attempts == 2
    assert len(results) == 1
    match = results[0]
    assert match["home"] == "Galatasaray"
    assert match["away"] == "Fenerbahce"
    assert match["nesine_1x2"] == (2.10, 3.20, 2.90)
    assert match["nesine_ou25"] == (1.75, 1.85)


def test_fetch_nesine_live_bulletin_timeout_value(monkeypatch):
    """Verify that urlopen is called with the specified 10.0s timeout."""
    observed_timeout = None
    mock_payload = _create_mock_nesine_payload()

    class MockResp:
        def __init__(self):
            self.status = 200

        def read(self):
            return json.dumps(mock_payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def mock_urlopen(req, timeout=10.0):
        nonlocal observed_timeout
        observed_timeout = timeout
        return MockResp()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    fetch_nesine_live_bulletin(timeout=10.0)
    assert observed_timeout == 10.0


def test_fetch_nesine_live_bulletin_spec0012_error_diagnostics(monkeypatch):
    """Verify SPEC-0012 diagnostic error handling and raise_on_error flag."""
    def mock_urlopen_503(req, timeout=10.0):
        raise urllib.error.HTTPError("https://cdnbulten.nesine.com", 503, "Service Unavailable", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_503)
    monkeypatch.setattr("time.sleep", lambda s: None)

    # 1. Default mode: fail-closed empty list
    res_default = fetch_nesine_live_bulletin(max_retries=2, backoff_factor=0.01, raise_on_error=False)
    assert res_default == []

    # 2. Strict mode: raises AdapterHTTPError
    with pytest.raises(AdapterHTTPError) as exc_info:
        fetch_nesine_live_bulletin(max_retries=2, backoff_factor=0.01, raise_on_error=True)
    assert exc_info.value.status_code == 503
    assert "Service Unavailable" in str(exc_info.value)


def test_fetch_nesine_live_bulletin_timeout_exception(monkeypatch):
    """Verify that socket timeouts raise AdapterTimeoutError when raise_on_error=True."""
    def mock_urlopen_timeout(req, timeout=10.0):
        raise TimeoutError("Socket timed out after 10.0s")

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_timeout)
    monkeypatch.setattr("time.sleep", lambda s: None)

    with pytest.raises(AdapterTimeoutError):
        fetch_nesine_live_bulletin(max_retries=2, backoff_factor=0.01, raise_on_error=True)


def test_get_json_retry_and_timeout(monkeypatch):
    """Verify _get_json retries on transient errors and returns parsed dict."""
    attempts = 0

    class MockResp:
        def __init__(self):
            self.status = 200

        def read(self):
            return json.dumps({"events": [{"id": 1, "name": "Event 1"}]}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def mock_urlopen(req, timeout=10.0):
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise urllib.error.URLError("Network reset")
        return MockResp()

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)

    payload = _get_json("https://api.prop-line.com/v1/odds", {}, {}, timeout=10.0, max_retries=3, backoff_factor=0.01)
    assert attempts == 2
    assert payload == {"events": [{"id": 1, "name": "Event 1"}]}


def test_fetch_nesine_live_bulletin_parses_real_double_chance_mtid3(monkeypatch):
    """Verify MTID=3 real Çifte Şans odds (1X/12/X2) are parsed while <= 1.01 values are omitted."""
    payload = {
        "sg": {
            "LA": [{"LID": 10, "N": "Süper Lig", "CC": "TUR"}],
            "EA": [
                {
                    "TYPE": 1,
                    "C": 9999,
                    "HN": "EvTakim",
                    "AN": "DepTakim",
                    "D": "14.11.2026",
                    "T": "22:00",
                    "EMBS": 1,
                    "LC": 10,
                    "MA": [
                        {"MTID": 1, "MBS": 1, "OCA": [{"N": 1, "O": 1.50}, {"N": 2, "O": 3.60}, {"N": 3, "O": 5.00}]},
                        {"MTID": 3, "MBS": 1, "OCA": [{"N": 1, "O": 1.00}, {"N": 2, "O": 1.12}, {"N": 3, "O": 1.78}]},
                    ],
                }
            ],
        }
    }

    class MockResp:
        status = 200

        def read(self):
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=10.0: MockResp())
    matches = fetch_nesine_live_bulletin(max_retries=1)
    assert len(matches) == 1
    assert matches[0]["nesine_dc"] == {"12": 1.12, "X2": 1.78}
