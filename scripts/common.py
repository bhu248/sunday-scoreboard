"""
Shared helpers for talking to Sleeper's public API.

Everything here is a plain read-only GET — Sleeper's API needs no auth key.
Rate-limit guidance from https://docs.sleeper.com/ is "stay under 1000 calls/minute";
a single poll of one league uses ~4 calls, so we are nowhere near that.

The one endpoint Sleeper asks callers to go easy on is /players/nfl (a ~5MB
dump of every player). We cache it to disk and only re-fetch if the cache is
missing or more than 20 hours old.
"""

import json
import os
import time
from datetime import datetime, timezone

import requests

BASE = "https://api.sleeper.app/v1"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PLAYERS_CACHE = os.path.join(DATA_DIR, "players_cache.json")
PLAYERS_CACHE_MAX_AGE_SEC = 20 * 60 * 60  # 20 hours

_session = requests.Session()
_session.headers.update({"User-Agent": "sunday-scoreboard/1.0 (+github actions)"})


def _get(url, params=None):
    resp = _session.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_state():
    """Current NFL season/week, so the poller never needs a week hardcoded."""
    return _get(f"{BASE}/state/nfl")


def get_league(league_id):
    return _get(f"{BASE}/league/{league_id}")


def get_rosters(league_id):
    return _get(f"{BASE}/league/{league_id}/rosters")


def get_users(league_id):
    return _get(f"{BASE}/league/{league_id}/users")


def get_matchups(league_id, week):
    return _get(f"{BASE}/league/{league_id}/matchups/{week}")


def get_projections(season, week, season_type="regular"):
    """
    Bulk pre-game projections for every skill-position player in a given week.
    Undocumented endpoint, confirmed working as of 2026-08-28. Returns a dict
    of player_id -> raw stat-category projections (yards, TDs, receptions...),
    NOT a single point total — we score it ourselves with the league's own
    scoring_settings, since Sleeper's built-in pts_ppr/pts_half_ppr totals
    assume stock scoring and this league runs custom settings.
    """
    positions = ["QB", "RB", "WR", "TE", "K", "DEF"]
    params = [("season_type", season_type)] + [("position[]", p) for p in positions]
    rows = _get(f"{BASE}/projections/nfl/{season}/{week}", params=params)
    by_player = {}
    for row in rows:
        pid = row.get("player_id")
        stats = row.get("stats") or {}
        if pid:
            by_player[pid] = stats
    return by_player


def score_stats(stats, scoring_settings):
    """
    Generic dot product: sum(stat_value * points_per_stat) over whatever
    categories are present in both. This is exactly how Sleeper itself scores
    a boxscore, so it works for any league's custom settings without us
    having to hardcode which categories matter.
    """
    total = 0.0
    for key, value in stats.items():
        weight = scoring_settings.get(key)
        if weight:
            total += value * weight
    return round(total, 2)


def team_names(league_id):
    """roster_id (str) -> display team name, falling back to the manager's username."""
    users_by_id = {u["user_id"]: u for u in get_users(league_id)}
    names = {}
    for roster in get_rosters(league_id):
        owner_id = roster.get("owner_id")
        user = users_by_id.get(owner_id, {})
        meta = user.get("metadata") or {}
        name = meta.get("team_name") or user.get("display_name") or f"Roster {roster['roster_id']}"
        names[str(roster["roster_id"])] = name
    return names


def load_players_cache():
    """
    player_id -> "First Last (POS)", refreshed at most once a day per
    Sleeper's own guidance for this endpoint. Used only to label flashes
    ("+9.6 — J. Smith (RB)") — never called on the hot polling path.

    The staleness check is based on a timestamp stored *inside* the cache
    file, not the file's mtime — this cache gets committed to the repo, and
    `git checkout` stamps every file with the current time regardless of
    when it was actually written, so an mtime check would never see it as
    stale once it's under version control.
    """
    if os.path.exists(PLAYERS_CACHE):
        with open(PLAYERS_CACHE, "r") as f:
            cached = json.load(f)
        fetched_at = cached.get("fetched_at", 0)
        if time.time() - fetched_at < PLAYERS_CACHE_MAX_AGE_SEC:
            return cached["players"]

    raw = _get(f"{BASE}/players/nfl")
    slim = {}
    for pid, p in raw.items():
        if not isinstance(p, dict):
            continue
        first = p.get("first_name") or ""
        last = p.get("last_name") or ""
        pos = p.get("position") or ""
        team = p.get("team") or ""
        label = (f"{first} {last}".strip() or pid)
        if pos:
            label += f" ({pos})"
        elif team:
            label += f" ({team})"
        slim[pid] = label
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PLAYERS_CACHE, "w") as f:
        json.dump({"fetched_at": time.time(), "players": slim}, f)
    return slim


def week_data_path(week):
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, f"week{week}.jsonl")


def append_snapshot(week, snapshot):
    path = week_data_path(week)
    with open(path, "a") as f:
        f.write(json.dumps(snapshot, separators=(",", ":")) + "\n")


def load_snapshots(week):
    path = week_data_path(week)
    if not os.path.exists(path):
        return []
    snaps = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                snaps.append(json.loads(line))
    return snaps
