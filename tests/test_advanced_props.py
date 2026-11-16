"""Unit tests for Advanced Props (Corners, Combos, Scorers) and MBS 1 filtering."""

from __future__ import annotations

from unittest.mock import patch

from src.live_stale_line_adapter import fetch_nesine_live_bulletin


def test_fetch_nesine_live_bulletin_parses_corners_combos_scorers() -> None:
    mock_payload = {
        "sg": {
            "EA": [
                {
                    "C": "12345",
                    "TYPE": 1,
                    "HN": "Real Madrid",
                    "AN": "Barcelona",
                    "D": "2026-11-01T20:00:00Z",
                    "EMBS": 1,
                    "MA": [
                        {
                            "MTID": 1,
                            "OCA": [
                                {"N": 1, "O": 2.10},
                                {"N": 2, "O": 3.40},
                                {"N": 3, "O": 3.10},
                            ],
                        },
                        {
                            "MTID": 12,
                            "SOV": 2.5,
                            "OCA": [
                                {"N": 1, "O": 2.05},
                                {"N": 2, "O": 1.70},
                            ],
                        },
                        {
                            "MTID": 216,
                            "SOV": 9.5,
                            "OCA": [
                                {"N": 1, "O": 1.85},
                                {"N": 2, "O": 1.80},
                            ],
                        },
                        {
                            "MTID": 701,
                            "OCA": [
                                {"ON": "Vinicius Jr", "O": 2.20},
                                {"ON": "Kylian Mbappe", "O": 1.95},
                            ],
                        },
                        {
                            "MTID": 885,
                            "OCA": [
                                {"ON": "Real Madrid 1+ Gol & 5+ Korner", "O": 1.75},
                            ],
                        },
                        {
                            "MTID": 5,
                            "OCA": [
                                {"N": 1, "O": 3.20},
                                {"N": 4, "O": 4.80},
                            ],
                        },
                        {
                            "MTID": 43,
                            "OCA": [
                                {"N": 1, "O": 3.10},
                                {"N": 4, "O": 14.50},
                            ],
                        },
                        {
                            "MTID": 225,
                            "OCA": [
                                {"N": 1, "O": 3.60},
                                {"N": 2, "O": 1.18},
                            ],
                        },
                        {
                            "MTID": 777,
                            "OCA": [
                                {"ON": "2:1", "O": 7.50},
                            ],
                        },
                    ],
                }
            ]
        }
    }

    with patch("urllib.request.urlopen") as mock_url:
        import io
        import json

        mock_resp = io.BytesIO(json.dumps(mock_payload).encode("utf-8"))
        mock_resp.status = 200  # type: ignore[attr-defined]
        mock_url.return_value.__enter__.return_value = mock_resp

        results = fetch_nesine_live_bulletin()

    assert len(results) == 1
    item = results[0]
    assert item["nesine_code"] == "12345"
    assert item["mbs"] == 1
    assert item["nesine_1x2"] == (2.10, 3.40, 3.10)
    assert item["nesine_ou25"] == (1.70, 2.05)  # (Over, Under)
    assert item["nesine_corners"] == {"9.5": {"under": 1.85, "over": 1.80}}
    assert item["nesine_scorers"] == [
        {"player": "Kylian Mbappe", "odd": 1.95},
        {"player": "Vinicius Jr", "odd": 2.20},
    ]
    assert item["nesine_combos"] == [
        {"name": "Real Madrid 1+ Gol & 5+ Korner", "odd": 1.75}
    ]
    assert item["nesine_htft"]["X/1"] == 4.80
    assert item["nesine_tg6"] == 14.50
    assert item["nesine_iy_kg_var"] == 3.60
    assert item["nesine_scores"] == [{"score": "2:1", "odd": 7.50}]

