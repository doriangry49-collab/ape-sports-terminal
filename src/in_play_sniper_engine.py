"""In-Play Continuous Hazard & Sniper Engine (v1.0).

Continuously monitors active soccer matches in real-time via ESPN scoreboard & boxscore feeds,
tracks elapsed minutes, current goal state, shot pressure, and cumulative corner counts.
Applies Empirical Bayes time-decay hazard models to identify bookmaker panic over-corrections
(e.g., high pre-match corner expectation matches experiencing early-minute corner drought,
causing live lines to over-decay while remaining-time hazard rate remains elevated).

Fully integrated with APE Syndicate Committee (P0 Risk Actuary, P2 Props Hunter).
Enforces fail-closed safety (SPEC-0012) and minimum stake constraints (SPEC-0015).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from advanced_corner_model import AdvancedCornerEngine, neg_binomial_cdf
except ImportError:
    from src.advanced_corner_model import AdvancedCornerEngine, neg_binomial_cdf

try:
    from atomic_io import atomic_write_json
except ImportError:
    from src.atomic_io import atomic_write_json

try:
    from telegram_notifier import (
        format_in_play_sniper_alert,
        send_telegram_message,
    )
except ImportError:
    try:
        from src.telegram_notifier import (
            format_in_play_sniper_alert,
            send_telegram_message,
        )
    except ImportError:
        def send_telegram_message(*args, **kwargs):
            return False
        format_in_play_sniper_alert = None

try:
    from goal_anomaly_engine import (
        AnomalySignalTier,
        GoalAnomalyEngine,
        format_in_play_goal_anomaly_alert,
    )
    from goal_timing_engine import GoalTimingEngine
except ImportError:
    try:
        from src.goal_anomaly_engine import (
            AnomalySignalTier,
            GoalAnomalyEngine,
            format_in_play_goal_anomaly_alert,
        )
        from src.goal_timing_engine import GoalTimingEngine
    except ImportError:
        GoalAnomalyEngine = None
        GoalTimingEngine = None
        AnomalySignalTier = None
        format_in_play_goal_anomaly_alert = None

try:
    from live_momentum_engine import LiveMomentumEngine, LiveMomentumEvaluation, MomentumState
except ImportError:
    try:
        from src.live_momentum_engine import (
            LiveMomentumEngine,
            LiveMomentumEvaluation,
            MomentumState,
        )
    except ImportError:
        try:
            from sports_engine.models.live_momentum_engine import (
                LiveMomentumEngine,
                LiveMomentumEvaluation,
                MomentumState,
            )
        except ImportError:
            LiveMomentumEngine = None
            LiveMomentumEvaluation = None
            MomentumState = None

try:
    from live_inplay_ledger import LiveInPlayLedger
except ImportError:
    try:
        from src.live_inplay_ledger import LiveInPlayLedger
    except ImportError:
        LiveInPlayLedger = None

try:
    from live_stale_line_adapter import fetch_nesine_live_bulletin
except ImportError:
    try:
        from src.live_stale_line_adapter import fetch_nesine_live_bulletin
    except ImportError:
        fetch_nesine_live_bulletin = None

try:
    from team_normalizer import TeamNormalizer
except ImportError:
    try:
        from src.team_normalizer import TeamNormalizer
    except ImportError:
        TeamNormalizer = None

logger = logging.getLogger("InPlaySniperEngine")

ROOT_DIR = Path(__file__).resolve().parent.parent
SEEN_IN_PLAY_FILE = ROOT_DIR / "output" / "seen_in_play_alerts.json"
NESINE_BRIDGE_CACHE_FILE = ROOT_DIR / "output" / "nesine_inplay_bridge_cache.json"
ACTIVE_INPLAY_ALERTS_FILE = ROOT_DIR / "output" / "live_inplay_active_alerts.json"

DEFAULT_CORNER_BASELINE = 9.85
KAPPA_DEFAULT = 0.14
PRIOR_HALF_LIFE_MINUTES = 30.0  # Empirical Bayes half-life weighting parameter


def american_to_decimal(val: Any) -> float | None:
    """Convert American odds string/number (e.g. '+119', '-171') to decimal odds."""
    if val is None:
        return None
    s = str(val).strip().upper()
    if not s or s in {"OFF", "NL", "EVEN", "EV"}:
        return 2.0 if s in {"EVEN", "EV"} else None
    try:
        num = float(s)
    except ValueError:
        return None
    if num == 0:
        return None
    dec = 1.0 + (num / 100.0) if num > 0 else 1.0 + (100.0 / abs(num))
    return round(dec, 3) if dec > 1.01 else None


def _parse_total_line(line_str: Any) -> float | None:
    if not line_str:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", str(line_str))
    return float(m.group(1)) if m else None


def parse_espn_live_odds(comp: dict[str, Any]) -> dict[str, Any]:
    """Extract live & opening DraftKings/ESPN bookmaker odds from an ESPN competition node."""
    odds_list = comp.get("odds") or []
    if not isinstance(odds_list, list) or not odds_list:
        return {}

    node = odds_list[0] or {}
    provider_name = str((node.get("provider") or {}).get("name") or "ESPN").strip()
    out: dict[str, Any] = {"odds_provider": provider_name}

    total = node.get("total") or {}
    over_cur = (total.get("over") or {}).get("current") or {}
    under_cur = (total.get("under") or {}).get("current") or {}
    cur_line = _parse_total_line(over_cur.get("line")) or _parse_total_line(under_cur.get("line"))
    over_dec = american_to_decimal(over_cur.get("odds"))
    under_dec = american_to_decimal(under_cur.get("odds"))
    if cur_line is not None and over_dec:
        out["live_total_line"] = cur_line
        out["live_total_over_odds"] = over_dec
        if under_dec:
            out["live_total_under_odds"] = under_dec

    over_open = (total.get("over") or {}).get("open") or (total.get("over") or {}).get("close") or {}
    open_line = _parse_total_line(over_open.get("line"))
    open_over_dec = american_to_decimal(over_open.get("odds"))
    if open_line == 2.5 and open_over_dec:
        out["open_o25"] = open_over_dec

    ml = node.get("moneyline") or {}
    h_cur = american_to_decimal(((ml.get("home") or {}).get("current") or {}).get("odds"))
    d_cur = american_to_decimal(((ml.get("draw") or {}).get("current") or {}).get("odds"))
    a_cur = american_to_decimal(((ml.get("away") or {}).get("current") or {}).get("odds"))
    if h_cur and d_cur and a_cur:
        out["live_1x2"] = (h_cur, d_cur, a_cur)

    h_open = american_to_decimal(((ml.get("home") or {}).get("open") or {}).get("odds"))
    a_open = american_to_decimal(((ml.get("away") or {}).get("open") or {}).get("odds"))
    if h_open:
        out["open_1"] = h_open
    if a_open:
        out["open_2"] = a_open

    return out


def parse_display_clock(clock_str: str | None) -> int | None:
    """Safely extract integer elapsed minutes from ESPN display clock string (e.g. 35', 45'+2')."""
    if not clock_str:
        return None
    # Match patterns like 35', 45'+2', 90'+4'
    match = re.match(r"^(\d+)", str(clock_str).strip())
    if match:
        try:
            return int(match.group(1))
        except (ValueError, TypeError):
            return None
    return None


class InPlaySniperEngine:
    """Real-Time In-Play Hazard & Mispricing Sniper Engine."""

    def __init__(
        self,
        corner_engine: AdvancedCornerEngine | None = None,
        goal_anomaly_engine: Any | None = None,
        momentum_engine: Any | None = None,
        nesine_pre_provider: Callable[[], list[dict[str, Any]]] | None = None,
        nesine_live_provider: Callable[[], list[dict[str, Any]]] | None = None,
        bridge_cache_path: Path | None = None,
        ledger: Any | None = None,
        active_alerts_path: Path | None = None,
    ) -> None:
        self.corner_engine = corner_engine or AdvancedCornerEngine()
        if goal_anomaly_engine is not None:
            self.goal_anomaly_engine = goal_anomaly_engine
        elif GoalAnomalyEngine is not None:
            self.goal_anomaly_engine = GoalAnomalyEngine()
        else:
            self.goal_anomaly_engine = None

        if momentum_engine is not None:
            self.momentum_engine = momentum_engine
        elif LiveMomentumEngine is not None:
            self.momentum_engine = LiveMomentumEngine()
        else:
            self.momentum_engine = None

        self.normalizer = TeamNormalizer() if TeamNormalizer is not None else None
        self.nesine_pre_provider = nesine_pre_provider
        self.nesine_live_provider = nesine_live_provider
        self.bridge_cache_path = bridge_cache_path or NESINE_BRIDGE_CACHE_FILE
        self.active_alerts_path = active_alerts_path or ACTIVE_INPLAY_ALERTS_FILE
        self._nesine_bridge_records: list[dict[str, Any]] = self._load_nesine_bridge_cache()
        self._nesine_live_records: list[dict[str, Any]] = []
        self._last_nesine_refresh_utc: datetime | None = None

        self.ledger = ledger if ledger is not None else (LiveInPlayLedger() if LiveInPlayLedger is not None else None)
        self.seen_alerts: set[str] = self._load_seen_alerts()

    def _persist_active_alert(self, sig_payload: dict[str, Any]) -> None:
        """Persist verified non-synthetic live alerts (max 2h TTL) for UI terminal snapshot."""
        if sig_payload.get("is_synthetic_odds", True):
            return
        try:
            cutoff = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
            existing: list[dict[str, Any]] = []
            if self.active_alerts_path.exists():
                raw = json.loads(self.active_alerts_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    existing = [
                        r for r in raw
                        if isinstance(r, dict)
                        and not r.get("is_synthetic_odds", True)
                        and str(r.get("timestamp_utc", "")) >= cutoff
                        and str(r.get("id", "")) != str(sig_payload.get("id", ""))
                    ]
            serializable = {
                k: v for k, v in sig_payload.items()
                if k not in ("anomaly_result", "momentum_eval", "committee_review")
            }
            existing.append(serializable)
            atomic_write_json(self.active_alerts_path, existing[-20:])
        except Exception as e:
            logger.debug(f"Could not persist active in-play alerts: {e}")

    def _load_nesine_bridge_cache(self) -> list[dict[str, Any]]:
        """Load persisted pre-kickoff Nesine odds cache so matches stay linked after kickoff."""
        if not self.bridge_cache_path.exists():
            return []
        try:
            raw = json.loads(self.bridge_cache_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return []
            cutoff = (datetime.now(UTC) - timedelta(hours=18)).isoformat()
            return [r for r in raw if isinstance(r, dict) and str(r.get("cached_at_utc", "")) >= cutoff]
        except Exception as e:
            logger.debug(f"Could not load {self.bridge_cache_path}: {e}")
            return []

    def _save_nesine_bridge_cache(self) -> None:
        try:
            atomic_write_json(self.bridge_cache_path, self._nesine_bridge_records)
        except Exception as e:
            logger.debug(f"Could not save {self.bridge_cache_path}: {e}")

    def _load_external_nesine_live_feed(self) -> list[dict[str, Any]]:
        """Load optional real-time Nesine live feed from injected callable or configured local JSON."""
        if self.nesine_live_provider is not None:
            try:
                rows = self.nesine_live_provider() or []
                return [r for r in rows if isinstance(r, dict)]
            except Exception as e:
                logger.debug(f"nesine_live_provider error: {e}")
                return []

        feed_path_str = os.environ.get("NESINE_LIVE_FEED_JSON_PATH", "").strip()
        if feed_path_str:
            p = Path(feed_path_str)
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        return [r for r in data if isinstance(r, dict)]
                except Exception as e:
                    logger.debug(f"Failed reading NESINE_LIVE_FEED_JSON_PATH {p}: {e}")
        return []

    def refresh_nesine_bridge(self, force: bool = False) -> dict[str, int]:
        """Refresh pre-match Nesine closing cache (getprebultenfull) and optional live Nesine feed."""
        now = datetime.now(UTC)
        if (
            not force
            and self._last_nesine_refresh_utc is not None
            and (now - self._last_nesine_refresh_utc).total_seconds() < 120.0
        ):
            return {
                "pre_cached_count": len(self._nesine_bridge_records),
                "live_feed_count": len(self._nesine_live_records),
            }

        pre_provider = self.nesine_pre_provider or fetch_nesine_live_bulletin
        if pre_provider is not None:
            try:
                bulletin = pre_provider() or []
                by_key: dict[str, dict[str, Any]] = {}
                cutoff = (now - timedelta(hours=18)).isoformat()
                for rec in self._nesine_bridge_records:
                    key = str(rec.get("nesine_code") or f"{rec.get('home','')}_{rec.get('away','')}")
                    if str(rec.get("cached_at_utc", "")) >= cutoff:
                        by_key[key] = rec

                for item in bulletin:
                    if not isinstance(item, dict) or not item.get("home") or not item.get("away"):
                        continue
                    key = str(item.get("nesine_code") or f"{item.get('home','')}_{item.get('away','')}")
                    by_key[key] = {
                        "nesine_code": item.get("nesine_code"),
                        "home": item.get("home"),
                        "away": item.get("away"),
                        "date_str": item.get("date_str"),
                        "time_str": item.get("time_str"),
                        "nesine_1x2": item.get("nesine_1x2"),
                        "nesine_ou25": item.get("nesine_ou25"),
                        "nesine_dc": item.get("nesine_dc"),
                        "nesine_corners": item.get("nesine_corners"),
                        "cached_at_utc": now.isoformat(),
                    }

                self._nesine_bridge_records = list(by_key.values())
                self._save_nesine_bridge_cache()
            except Exception as e:
                logger.debug(f"Nesine pre-match bridge refresh skipped: {e}")

        self._nesine_live_records = self._load_external_nesine_live_feed()
        self._last_nesine_refresh_utc = now
        return {
            "pre_cached_count": len(self._nesine_bridge_records),
            "live_feed_count": len(self._nesine_live_records),
        }

    def match_nesine_context(self, home: str, away: str) -> dict[str, Any]:
        """Match an in-play match against Nesine live feed (if present) and pre-match closing cache."""
        if not home or not away:
            return {}

        def _find_best(records: list[dict[str, Any]]) -> dict[str, Any] | None:
            if not records:
                return None
            if self.normalizer is not None:
                return self.normalizer.match_fixture(home, away, records, threshold=0.65)
            h_low, a_low = home.strip().lower(), away.strip().lower()
            for r in records:
                if str(r.get("home", "")).strip().lower() == h_low and str(r.get("away", "")).strip().lower() == a_low:
                    return r
            return None

        live_hit = _find_best(self._nesine_live_records)
        pre_hit = _find_best(self._nesine_bridge_records)

        ctx: dict[str, Any] = {}
        if pre_hit:
            ctx["nesine_code"] = pre_hit.get("nesine_code")
            ctx["nesine_pre_match"] = {
                "nesine_1x2": pre_hit.get("nesine_1x2"),
                "nesine_ou25": pre_hit.get("nesine_ou25"),
                "nesine_corners": pre_hit.get("nesine_corners"),
                "nesine_dc": pre_hit.get("nesine_dc"),
            }
        if live_hit:
            ctx["nesine_code"] = live_hit.get("nesine_code") or ctx.get("nesine_code")
            ctx["nesine_live"] = live_hit
        return ctx

    def _load_seen_alerts(self) -> set[str]:
        """Load previously alerted in-play event IDs to prevent duplicate alerts."""
        if SEEN_IN_PLAY_FILE.exists():
            try:
                data = json.loads(SEEN_IN_PLAY_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return set(data)
            except Exception as e:
                logger.debug(f"Could not load {SEEN_IN_PLAY_FILE}: {e}")
        return set()

    def _save_seen_alerts(self) -> None:
        """Atomically persist seen alert IDs to disk."""
        try:
            atomic_write_json(SEEN_IN_PLAY_FILE, list(self.seen_alerts))
        except Exception as e:
            logger.warning(f"Could not save {SEEN_IN_PLAY_FILE}: {e}")

    def fetch_live_in_play_matches(
        self,
        min_minute: int = 10,
        max_minute: int = 80,
    ) -> list[dict[str, Any]]:
        """Query ESPN live scoreboard + real-time DraftKings/Nesine odds bridge."""
        self.refresh_nesine_bridge()
        url = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        matches: list[dict[str, Any]] = []

        try:
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for ev in data.get("events", []):
                    status_obj = ev.get("status", {})
                    state = status_obj.get("type", {}).get("state")
                    if state != "in":
                        continue  # Only target active in-play matches

                    clock_display = status_obj.get("displayClock", "")
                    elapsed_min = parse_display_clock(clock_display)
                    if elapsed_min is None:
                        continue

                    # Filter within target sniper window (e.g. 10' to 80')
                    if elapsed_min < min_minute or elapsed_min > max_minute:
                        continue

                    ev_id = str(ev.get("id", ""))
                    name = ev.get("name", "")

                    comp = (ev.get("competitions") or [{}])[0]
                    comps = comp.get("competitors", [])
                    if len(comps) != 2:
                        continue

                    teams = {c.get("homeAway"): c for c in comps}
                    home_comp = teams.get("home", comps[0])
                    away_comp = teams.get("away", comps[1])

                    home_name = (
                        home_comp.get("team", {}).get("name")
                        or home_comp.get("team", {}).get("displayName")
                        or ""
                    )
                    away_name = (
                        away_comp.get("team", {}).get("name")
                        or away_comp.get("team", {}).get("displayName")
                        or ""
                    )

                    try:
                        hg = int(home_comp.get("score", 0) or 0)
                        ag = int(away_comp.get("score", 0) or 0)
                    except (ValueError, TypeError):
                        hg, ag = 0, 0

                    # Extract league slug from links
                    league_code = "all"
                    for link in ev.get("links", []):
                        m_slug = re.search(r"/league/([a-zA-Z0-9\.]+)", link.get("href", ""))
                        if m_slug:
                            league_code = m_slug.group(1).lower()
                            break

                    espn_odds = parse_espn_live_odds(comp)
                    nesine_ctx = self.match_nesine_context(home_name, away_name)
                    nesine_pre = nesine_ctx.get("nesine_pre_match") or {}
                    nesine_live = nesine_ctx.get("nesine_live") or {}

                    pre_1x2 = nesine_pre.get("nesine_1x2")
                    pre_ou25 = nesine_pre.get("nesine_ou25")
                    open_o25 = (pre_ou25[0] if pre_ou25 and len(pre_ou25) == 2 else None) or espn_odds.get("open_o25")
                    open_1 = (pre_1x2[0] if pre_1x2 and len(pre_1x2) == 3 else None) or espn_odds.get("open_1")
                    open_2 = (pre_1x2[2] if pre_1x2 and len(pre_1x2) == 3 else None) or espn_odds.get("open_2")

                    live_total_line = nesine_live.get("live_total_line") or espn_odds.get("live_total_line")
                    live_total_over_odds = nesine_live.get("live_total_over_odds") or espn_odds.get("live_total_over_odds")
                    live_total_under_odds = nesine_live.get("live_total_under_odds") or espn_odds.get("live_total_under_odds")
                    live_1x2 = nesine_live.get("live_1x2") or espn_odds.get("live_1x2")
                    live_corners = nesine_live.get("live_corners")

                    has_real_live_total = bool(live_total_line is not None and live_total_over_odds)
                    has_real_live_corners = bool(isinstance(live_corners, dict) and live_corners)
                    if nesine_live and (nesine_live.get("live_total_over_odds") or has_real_live_corners):
                        odds_source = "nesine_live"
                    elif has_real_live_total or live_1x2:
                        odds_source = f"espn_{espn_odds.get('odds_provider', 'live').lower().replace(' ', '_')}_live"
                    else:
                        odds_source = "none"

                    matches.append({
                        "event_id": ev_id,
                        "name": name,
                        "home": home_name,
                        "away": away_name,
                        "hg": hg,
                        "ag": ag,
                        "elapsed_min": elapsed_min,
                        "clock_display": clock_display,
                        "period": status_obj.get("period", 1),
                        "league_code": league_code,
                        "nesine_code": nesine_ctx.get("nesine_code"),
                        "nesine_pre_match": nesine_pre or None,
                        "open_o25": open_o25,
                        "open_1": open_1,
                        "open_2": open_2,
                        "live_total_line": live_total_line,
                        "live_total_over_odds": live_total_over_odds,
                        "live_total_under_odds": live_total_under_odds,
                        "live_1x2": live_1x2,
                        "live_corners": live_corners,
                        "has_real_live_odds": bool(has_real_live_total or has_real_live_corners or live_1x2),
                        "has_real_live_corners": has_real_live_corners,
                        "odds_source": odds_source,
                    })
        except Exception as e:
            logger.debug(f"Failed to fetch live in-play scoreboard: {e}")

        return matches

    def fetch_live_match_stats(self, event_id: str, league_code: str) -> dict[str, Any] | None:
        """Fetch real-time corner counts, shots, and possession from ESPN event summary."""
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_code}/summary?event={event_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

        stats: dict[str, Any] = {
            "home_corners": 0,
            "away_corners": 0,
            "total_corners": 0,
            "home_shots": 0,
            "away_shots": 0,
            "total_shots": 0,
            "home_sot": 0,
            "away_sot": 0,
            "total_sot": 0,
            "home_possession": 50.0,
            "away_possession": 50.0,
            "has_corners": False,
        }

        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                box = data.get("boxscore", {})
                teams = box.get("teams", [])
                if len(teams) < 2:
                    return None

                for idx, t in enumerate(teams):
                    is_home = (idx == 0)
                    for s in t.get("statistics", []):
                        name = s.get("name")
                        val = s.get("displayValue")
                        if val is None:
                            continue

                        if name == "wonCorners":
                            try:
                                c = int(float(val))
                                if is_home:
                                    stats["home_corners"] = c
                                else:
                                    stats["away_corners"] = c
                                stats["has_corners"] = True
                            except (ValueError, TypeError):
                                pass
                        elif name == "totalShots":
                            try:
                                sh = int(float(val))
                                if is_home:
                                    stats["home_shots"] = sh
                                else:
                                    stats["away_shots"] = sh
                            except (ValueError, TypeError):
                                pass
                        elif name == "shotsOnTarget":
                            try:
                                sot = int(float(val))
                                if is_home:
                                    stats["home_sot"] = sot
                                else:
                                    stats["away_sot"] = sot
                            except (ValueError, TypeError):
                                pass
                        elif name == "possessionPct":
                            try:
                                p = float(val)
                                if is_home:
                                    stats["home_possession"] = p
                                else:
                                    stats["away_possession"] = p
                            except (ValueError, TypeError):
                                pass

                stats["total_corners"] = stats["home_corners"] + stats["away_corners"]
                stats["total_shots"] = stats["home_shots"] + stats["away_shots"]
                stats["total_sot"] = stats["home_sot"] + stats["away_sot"]

                # Extract Halftime Linescores (Period 1 scores)
                ht_home, ht_away = 0, 0
                has_ht_score = False
                header = data.get("header", {})
                comps = header.get("competitions", [{}])[0].get("competitors", [])
                if len(comps) >= 2:
                    for c_idx, c in enumerate(comps):
                        ls = c.get("linescores", [])
                        if ls:
                            try:
                                v = int(float(ls[0].get("displayValue", 0)))
                                if c_idx == 0:
                                    ht_home = v
                                else:
                                    ht_away = v
                                has_ht_score = True
                            except (ValueError, TypeError):
                                pass

                stats["ht_home"] = ht_home
                stats["ht_away"] = ht_away
                stats["ht_goals"] = ht_home + ht_away
                stats["has_ht_score"] = has_ht_score
                stats["key_events"] = data.get("keyEvents", [])

                return stats
        except Exception as e:
            logger.debug(f"Failed to fetch live stats for event {event_id}: {e}")
            return None

    def evaluate_in_play_hazard(
        self,
        home: str,
        away: str,
        elapsed_min: int,
        current_corners: int,
        current_goals_home: int,
        current_goals_away: int,
        total_shots: int = 0,
        pre_match_mu: float | None = None,
        league_key: str = "",
        live_corner_odds_by_line: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        """Compute Bayesian continuous hazard projection and evaluate live corner mispricings."""
        # 1. Pre-Match Prior
        if pre_match_mu is None:
            try:
                pre_match_mu, _ = self.corner_engine.estimate_corner_mu(
                    home_team=home,
                    away_team=away,
                    league_key=league_key,
                )
            except Exception:
                pre_match_mu = DEFAULT_CORNER_BASELINE

        pre_match_mu = max(6.5, min(14.0, float(pre_match_mu)))

        # 2. Time Horizon & Empirical Bayes Shrinkage
        elapsed = max(1, min(89, elapsed_min))
        time_rem = 90.0 - elapsed

        # Weighting: early minutes prioritize pre-match prior; late minutes prioritize empirical live pace
        w_prior = PRIOR_HALF_LIFE_MINUTES / (PRIOR_HALF_LIFE_MINUTES + elapsed)
        w_live = 1.0 - w_prior

        lambda_prior_per_min = pre_match_mu / 90.0
        lambda_live_per_min = current_corners / elapsed

        # Blended base hazard rate per minute
        lambda_blended = (w_prior * lambda_prior_per_min) + (w_live * lambda_live_per_min)

        # 3. Game-State Dynamic Multipliers
        # Siege effect: If home team or heavy favorite is trailing by 1 goal, attack intensity spikes
        siege_multiplier = 1.0
        score_diff = current_goals_home - current_goals_away
        if score_diff == -1:  # Home team trailing by 1
            siege_multiplier = 1.15
        elif score_diff == 1:  # Away team trailing by 1
            siege_multiplier = 1.10
        elif score_diff == 0 and elapsed >= 60:  # Late deadlock
            siege_multiplier = 1.08
        elif abs(score_diff) >= 3:  # Blowout lead decay
            siege_multiplier = 0.85

        # High Shot Tempo Lift: If teams are firing shots (>1 shot every 3 minutes)
        shot_rate = total_shots / elapsed if elapsed > 0 else 0.0
        if shot_rate >= 0.35:
            siege_multiplier *= 1.08

        effective_lambda_per_min = lambda_blended * siege_multiplier

        # 4. Projected Remaining & Total Corners
        mu_remaining = effective_lambda_per_min * time_rem
        projected_total = current_corners + mu_remaining

        # 5. Probability Pricing for Live Lines (e.g. current_corners + 2.5, 3.5 or standard lines)
        target_lines = [
            float(current_corners + 1.5),
            float(current_corners + 2.5),
            float(current_corners + 3.5),
            8.5,
            9.5,
            10.5,
        ]
        if isinstance(live_corner_odds_by_line, dict):
            for raw_k in live_corner_odds_by_line:
                try:
                    target_lines.append(float(raw_k))
                except (TypeError, ValueError):
                    pass
        # Deduplicate and sort
        unique_lines = sorted({round(line, 1) for line in target_lines if line > current_corners})

        line_evaluations: list[dict[str, Any]] = []
        for line in unique_lines:
            needed = int(line + 0.5) - current_corners
            if needed <= 0:
                p_over = 1.0
            else:
                p_under = neg_binomial_cdf(needed - 1, mu_remaining, kappa=KAPPA_DEFAULT)
                p_over = max(0.01, min(0.99, 1.0 - p_under))

            # Fair odds before bookmaker overround
            fair_odds = round(1.0 / p_over, 2) if p_over > 0.01 else 99.0

            # SPEC-0012 Fail-Closed: Only compute market EV when real live corner odds exist (no fake 1.85 fallback)
            real_quote = None
            if isinstance(live_corner_odds_by_line, dict):
                line_node = live_corner_odds_by_line.get(f"{line:.1f}") or live_corner_odds_by_line.get(str(line))
                if isinstance(line_node, dict):
                    cand_odd = line_node.get("over")
                    if cand_odd is not None and float(cand_odd) > 1.01:
                        real_quote = round(float(cand_odd), 3)

            is_synthetic = real_quote is None
            market_odds = real_quote
            edge_pct = round((p_over * real_quote - 1.0) * 100.0, 2) if real_quote is not None else None

            line_evaluations.append({
                "line": line,
                "needed_corners": needed,
                "p_over": round(p_over, 4),
                "fair_odds": fair_odds,
                "market_odds": market_odds,
                "is_synthetic_odds": is_synthetic,
                "edge_pct": edge_pct,
            })

        # Detect Panic Mispricing ONLY against verified real live bookmaker odds (fail-closed)
        is_panic_mispricing = False
        best_opportunity = None

        if pre_match_mu >= 9.5 and elapsed <= 55:
            real_evals = [
                le for le in line_evaluations
                if not le["is_synthetic_odds"] and le["market_odds"] is not None and le["edge_pct"] is not None
            ]
            for le in real_evals:
                in_playable_band = 1.45 <= float(le["market_odds"]) <= 6.50
                if le["edge_pct"] >= 5.0 and le["p_over"] >= 0.55 and in_playable_band:
                    is_panic_mispricing = True
                    if best_opportunity is None or le["edge_pct"] > best_opportunity["edge_pct"]:
                        best_opportunity = le

        return {
            "home": home,
            "away": away,
            "elapsed_min": elapsed,
            "current_corners": current_corners,
            "pre_match_mu": round(pre_match_mu, 2),
            "projected_remaining": round(mu_remaining, 2),
            "projected_total": round(projected_total, 2),
            "lambda_prior_per_min": round(lambda_prior_per_min, 4),
            "lambda_live_per_min": round(lambda_live_per_min, 4),
            "effective_lambda_per_min": round(effective_lambda_per_min, 4),
            "siege_multiplier": round(siege_multiplier, 2),
            "is_panic_mispricing": is_panic_mispricing,
            "best_opportunity": best_opportunity,
            "lines": line_evaluations,
        }

    def scan_in_play_opportunities(
        self,
        committee: Any | None = None,
        dispatch_telegram: bool = True,
    ) -> list[dict[str, Any]]:
        """Autonomous live scan pass: fetches in-play matches, calculates hazard, and dispatches alerts."""
        live_matches = self.fetch_live_in_play_matches()
        if not live_matches:
            logger.info("No active in-play soccer matches found in target sniper window.")
            return []

        opportunities: list[dict[str, Any]] = []

        for m in live_matches:
            ev_id = m["event_id"]
            stats = self.fetch_live_match_stats(ev_id, m["league_code"])
            if not stats or not stats.get("has_corners"):
                continue

            current_corners = stats["total_corners"]
            hazard = self.evaluate_in_play_hazard(
                home=m["home"],
                away=m["away"],
                elapsed_min=m["elapsed_min"],
                current_corners=current_corners,
                current_goals_home=m["hg"],
                current_goals_away=m["ag"],
                total_shots=stats["total_shots"],
                league_key=m["league_code"],
                live_corner_odds_by_line=m.get("live_corners"),
            )

            if not hazard.get("is_panic_mispricing") or not hazard.get("best_opportunity"):
                continue

            # Momentum Filter for Corner Sniper: veto if corner velocity is dead
            if self.momentum_engine and stats:
                diff = abs(m["hg"] - m["ag"])
                c_mom = self.momentum_engine.evaluate_momentum(
                    elapsed_min=m["elapsed_min"],
                    total_shots=stats.get("total_shots", 0),
                    shots_on_target=stats.get("total_sot", 0),
                    total_corners=current_corners,
                    home_shots=stats.get("home_shots"),
                    away_shots=stats.get("away_shots"),
                    home_possession=stats.get("home_possession", 50.0),
                    away_possession=stats.get("away_possession", 50.0),
                    current_score_diff=diff,
                    key_events=stats.get("key_events", []),
                )
                if not c_mom.is_corner_qualified:
                    logger.info(
                        f"[MOMENTUM VETO] Corner Sniper for {m['name']} vetoed by momentum: {', '.join(c_mom.veto_reasons)}"
                    )
                    continue

            best = hazard["best_opportunity"]
            real_odd = best.get("market_odds")
            if best.get("is_synthetic_odds", True) or real_odd is None or float(real_odd) <= 1.01:
                continue
            line = best["line"]
            alert_key = f"{ev_id}_{line}_OVER"

            if alert_key in self.seen_alerts:
                continue

            odds_source = str(m.get("corner_odds_source") or "nesine_live")

            # Standardized Syndicate Signal Payload (SPEC-0015 Stake Compliant)
            sig_payload = {
                "id": alert_key,
                "event_id": ev_id,
                "league": m["league_code"],
                "home": m["home"],
                "away": m["away"],
                "elapsed_min": m["elapsed_min"],
                "score": f"{m['hg']}-{m['ag']}",
                "current_corners": current_corners,
                "market": "CANLI KORNER",
                "selection": f"{line} ÜST",
                "outcome": f"{line} ÜST",
                "line": line,
                "prob": best["p_over"],
                "fair_odd": best.get("fair_odds"),
                "book_odd": float(real_odd),
                "soft_odds": float(real_odd),
                "edge_pct": best["edge_pct"],
                "ev_pct": best["edge_pct"],
                "stake": 50.0,
                "pre_match_mu": hazard["pre_match_mu"],
                "projected_total": hazard["projected_total"],
                "is_synthetic_odds": False,
                "odds_source": odds_source,
                "nesine_code": m.get("nesine_code"),
                "nesine_pre_match": m.get("nesine_pre_match"),
                "momentum_eval": c_mom if (self.momentum_engine and stats) else None,
                "timestamp_utc": datetime.now(UTC).isoformat(),
            }

            # Filter through Syndicate Committee if provided
            approved = True
            review_meta = {}
            if committee is not None:
                try:
                    review = committee.review_signal(sig_payload)
                    approved = bool(review.get("approved", True))
                    review_meta = review
                except Exception as ce:
                    logger.debug(f"Syndicate review error for {m['name']}: {ce}")

            if not approved:
                logger.info(f"[SYNDICATE VETO] In-Play Sniper for {m['name']} vetoed: {review_meta.get('veto_reason')}")
                continue

            # Mark as alerted
            self.seen_alerts.add(alert_key)
            self._save_seen_alerts()

            # Record to Paper Trading Ledger
            if self.ledger is not None:
                try:
                    self.ledger.record_in_play_bet(sig_payload)
                except Exception as le:
                    logger.debug(f"Could not record corner sniper to ledger: {le}")

            self._persist_active_alert(sig_payload)
            sig_payload["committee_review"] = review_meta
            opportunities.append(sig_payload)

            # Telegram Notification (SPEC-0012 Fail-Closed: verified real live odds only)
            if dispatch_telegram:
                try:
                    if format_in_play_sniper_alert is not None:
                        msg = format_in_play_sniper_alert(sig_payload)
                    else:
                        msg = (
                            f"⚡ *[APE IN-PLAY SNIPER — CANLI PUSU]*\n"
                            f"⚽ *{m['home']} vs {m['away']}* (Dk {m['elapsed_min']}')\n"
                            f"🎯 Toplam Korner {line} ÜST @ {float(real_odd):.2f} [{odds_source}]"
                        )
                    send_telegram_message(msg)
                    logger.info(f"Dispatched In-Play Sniper Telegram alert for {m['home']} vs {m['away']}")
                except Exception as te:
                    logger.warning(f"Telegram dispatch failed: {te}")

        return opportunities

    def scan_in_play_goal_anomalies(
        self,
        committee: Any | None = None,
        dispatch_telegram: bool = True,
        min_minute: int = 15,
        max_minute: int = 85,
    ) -> list[dict[str, Any]]:
        """Scan active in-play matches for high-tempo goal anomalies and timing window eruptions."""
        if not self.goal_anomaly_engine:
            return []

        live_matches = self.fetch_live_in_play_matches(min_minute=min_minute, max_minute=max_minute)
        if not live_matches:
            return []

        opportunities: list[dict[str, Any]] = []

        for m in live_matches:
            ev_id = m["event_id"]
            stats = self.fetch_live_match_stats(ev_id, m["league_code"])

            # Halftime and current goals
            current_goals = m["hg"] + m["ag"]
            ht_goals = stats.get("ht_goals", 0) if stats else 0
            if m["elapsed_min"] < 45 and not (stats and stats.get("has_ht_score", False)):
                ht_goals = current_goals

            fixture = {
                "event_id": ev_id,
                "home_team": m["home"],
                "away_team": m["away"],
                "league": m["league_code"],
                "open_o25": float(m["open_o25"]) if m.get("open_o25") else None,
                "open_1": float(m["open_1"]) if m.get("open_1") else None,
                "open_2": float(m["open_2"]) if m.get("open_2") else None,
            }

            key_events = stats.get("key_events", []) if stats else []
            shot_rate = (stats["total_shots"] / m["elapsed_min"]) if stats and m["elapsed_min"] > 0 else 0.0

            res = self.goal_anomaly_engine.evaluate_live_fixture(
                fixture=fixture,
                minute=m["elapsed_min"],
                ht_goals=ht_goals,
                score_home=m["hg"],
                score_away=m["ag"],
                total_shots_rate=shot_rate,
                key_events=key_events,
            )

            # Qualification check:
            # If 45'+: must pass the 88.8% HT rule (ht_goals >= 2) -> res.is_live_qualified == True
            # If <45': current_goals >= 2 (early explosion) or high pressure timing window with GASI >= 60
            qualifies = False
            if m["elapsed_min"] >= 45:
                is_gold_or_silver = (
                    hasattr(res.tier, "value") and res.tier.value in ("GOLD_TIER", "SILVER_TIER")
                ) or str(res.tier) in ("GOLD_TIER", "SILVER_TIER")
                qualifies = bool(res.is_live_qualified and is_gold_or_silver)
            else:
                qualifies = bool(current_goals >= 2 and res.gasi_score >= 60.0)

            if not qualifies:
                continue

            # Fail-Closed Live Momentum Filter:
            # Vetoes if shot velocity < 0.20, danger index < 45, rolling 15m stalled, or wall match grind
            momentum_eval = None
            if self.momentum_engine and stats:
                diff = abs(m["hg"] - m["ag"])
                momentum_eval = self.momentum_engine.evaluate_momentum(
                    elapsed_min=m["elapsed_min"],
                    total_shots=stats.get("total_shots", 0),
                    shots_on_target=stats.get("total_sot", 0),
                    total_corners=stats.get("total_corners", 0),
                    home_shots=stats.get("home_shots"),
                    away_shots=stats.get("away_shots"),
                    home_possession=stats.get("home_possession", 50.0),
                    away_possession=stats.get("away_possession", 50.0),
                    current_score_diff=diff,
                    key_events=stats.get("key_events", []),
                )
                if not momentum_eval.is_ambush_qualified:
                    logger.info(
                        f"[MOMENTUM VETO] Match {m['name']} vetoed by momentum: {', '.join(momentum_eval.veto_reasons)}"
                    )
                    continue

            live_line = m.get("live_total_line")
            live_over_odd = m.get("live_total_over_odds")
            has_real_live_total = (
                live_line is not None
                and live_over_odd is not None
                and float(live_line) > current_goals
                and float(live_over_odd) > 1.01
            )

            if not has_real_live_total:
                logger.debug(
                    f"[SPEC-0012 SKIP] {m['name']} has no real live total odds (no synthetic 1.85 fallback)."
                )
                continue

            live_line_f = round(float(live_line), 1)
            book_odd = round(float(live_over_odd), 3)
            rem_frac = max(0.05, (90.0 - min(87, int(m["elapsed_min"]))) / 90.0)
            tempo_mult = 1.12 if (res.timing_evaluation and res.timing_evaluation.is_high_pressure_window) else 1.0
            mu_rem_goals = max(0.20, float(res.implied_total_xg) * rem_frac * tempo_mult)
            needed_goals = max(1, int(live_line_f + 0.5) - current_goals)
            p_signal = max(
                0.02,
                min(0.95, 1.0 - neg_binomial_cdf(needed_goals - 1, mu_rem_goals, kappa=KAPPA_DEFAULT)),
            )
            edge_pct = round((p_signal * book_odd - 1.0) * 100.0, 2)
            if book_odd < 1.45 or book_odd > 6.50 or edge_pct < 4.0:
                logger.info(
                    f"[LIVE EV VETO] Goal Anomaly {m['name']} Over {live_line_f} @ {book_odd:.2f} "
                    f"(p={p_signal:.2%}, edge={edge_pct:+.1f}%) vetoed"
                )
                continue
            target_line = f"{live_line_f:.1f} ÜST"
            is_synthetic_odds = False
            odds_source = str(m.get("odds_source") or "espn_draftkings_live")

            alert_key = f"{ev_id}_GOAL_ANOMALY_{current_goals}_{target_line}"
            legacy_alert_key = f"{ev_id}_GOAL_ANOMALY_{current_goals}"
            if alert_key in self.seen_alerts or legacy_alert_key in self.seen_alerts:
                continue

            sig_payload = {
                "id": alert_key,
                "event_id": ev_id,
                "league": m["league_code"],
                "home": m["home"],
                "away": m["away"],
                "elapsed_min": m["elapsed_min"],
                "score": f"{m['hg']}-{m['ag']}",
                "ht_score": f"{stats.get('ht_home', 0)}-{stats.get('ht_away', 0)}" if stats and stats.get("has_ht_score") else "",
                "ht_goals": ht_goals,
                "market": "CANLI GOL ANOMALİSİ",
                "selection": target_line,
                "outcome": target_line,
                "prob": round(float(p_signal), 4),
                "fair_odd": round(1.0 / max(0.01, float(p_signal)), 2),
                "book_odd": book_odd,
                "soft_odds": book_odd,
                "edge_pct": edge_pct,
                "ev_pct": edge_pct,
                "stake": 50.0,  # SPEC-0015 Minimum Stake Rule
                "gasi_score": res.gasi_score,
                "tier": res.tier.value if hasattr(res.tier, "value") else str(res.tier),
                "is_synthetic_odds": is_synthetic_odds,
                "odds_source": odds_source,
                "nesine_code": m.get("nesine_code"),
                "nesine_pre_match": m.get("nesine_pre_match"),
                "anomaly_result": res,
                "momentum_eval": momentum_eval,
                "timestamp_utc": datetime.now(UTC).isoformat(),
            }

            # Filter through Syndicate Committee if provided
            approved = True
            review_meta = {}
            if committee is not None:
                try:
                    review = committee.review_signal(sig_payload)
                    approved = bool(review.get("approved", True))
                    review_meta = review
                except Exception as ce:
                    logger.debug(f"Syndicate review error for goal anomaly {m['name']}: {ce}")

            if not approved:
                logger.info(f"[SYNDICATE VETO] In-Play Goal Anomaly for {m['name']} vetoed: {review_meta.get('veto_reason')}")
                continue

            self.seen_alerts.add(alert_key)
            self._save_seen_alerts()

            # Record to Paper Trading Ledger
            if self.ledger is not None:
                try:
                    self.ledger.record_in_play_bet(sig_payload)
                except Exception as le:
                    logger.debug(f"Could not record goal anomaly to ledger: {le}")

            self._persist_active_alert(sig_payload)
            sig_payload["committee_review"] = review_meta
            opportunities.append(sig_payload)

            # Telegram Notification (SPEC-0012 Fail-Closed: verified real live odds only)
            if dispatch_telegram and not sig_payload["is_synthetic_odds"]:
                try:
                    if format_in_play_goal_anomaly_alert is not None:
                        msg = format_in_play_goal_anomaly_alert(
                            result=res,
                            minute=m["elapsed_min"],
                            current_score=f"{m['hg']}-{m['ag']}",
                            ht_score=sig_payload["ht_score"],
                            recommended_line=target_line,
                            market_odds=book_odd,
                        )
                    else:
                        msg = (
                            f"⚡ *[APE CANLI GOL ANOMALİSİ]*\n"
                            f"⚽ *{m['home']} vs {m['away']}* (Dk {m['elapsed_min']}')\n"
                            f"🎯 Canlı {target_line} @ {book_odd:.2f} [{odds_source}]"
                        )
                    send_telegram_message(msg)
                    logger.info(f"Dispatched In-Play Goal Anomaly Telegram alert for {m['home']} vs {m['away']}")
                except Exception as te:
                    logger.warning(f"Telegram dispatch failed: {te}")

        return opportunities
