#!/usr/bin/env python3
"""
One poll: fetch this week's live matchup scores + pre-game projections for
league LEAGUE_ID, and append one timestamped snapshot to data/week<N>.jsonl.

Meant to be run every few minutes by the GitHub Actions workflow during game
windows. Safe to run any time — outside the season it just prints a message
and exits without writing anything.
"""

import os
import sys

import common

LEAGUE_ID = os.environ.get("LEAGUE_ID", "1393377829990727680")


def compute_projected_total(starters, players_points, projections_by_player, scoring, players_team, team_progress):
    """
    Live-projected final total for one roster: for each starter, their
    actual points so far PLUS whatever's left of their pre-game projection
    above that, decayed by how far their own NFL game has progressed — so
    the "upside" on top of actual fades out smoothly and lands on exactly
    their actual total once their game ends, instead of staying pinned at
    a ceiling or cratering the instant they score.

        remaining = max(pregame_projection - actual, 0) * (1 - elapsed)
        contribution = actual + remaining

    where `elapsed` (0.0-1.0) comes from common.team_game_progress, which
    reads ESPN's public scoreboard for that player's team's game clock.

    FIXED 2026-09-10: replaced the previous max(actual, pregame_projection)
    approximation. That version kept a player pinned at their full
    pre-game projection for their ENTIRE game and only let the number move
    once actual overtook it — which was a real improvement over the
    original kickoff-cliff bug, but still wasn't a "live" projection, it
    was just a flatter static one. Sleeper's public API has no live,
    per-player projection feed at all (confirmed: the projections endpoint
    returns one unchanging pre-game number for the whole week — verified
    against this project's own real Week 1 data, where a roster with zero
    players who'd recorded any stat held an exactly unchanged projected
    total for over an hour of live play). This function is what actually
    makes the number live: it fakes the decay ourselves using each game's
    real clock instead of Sleeper's scoring data.

    If a player's team's game progress can't be determined (ESPN fetch
    failed, bye week, not yet posted), `team_progress.get(...)` returns
    None and we fall back to elapsed=0 — i.e. still show their full
    pre-game upside rather than silently re-creating the original
    kickoff-cliff bug by assuming their game is over.
    """
    actual_total = 0.0
    projected_total = 0.0
    for pid in starters:
        if pid == "0":  # empty slot
            continue
        pts = players_points.get(pid, 0.0) or 0.0
        actual_total += pts
        stats = projections_by_player.get(pid)
        pregame_projection = common.score_stats(stats, scoring) if stats else 0.0

        # A team defense/special-teams slot is keyed by the team's own
        # abbreviation (e.g. "SEA") rather than a normal player id.
        team = players_team.get(pid, pid)
        elapsed = team_progress.get(team)
        if elapsed is None:
            elapsed = 0.0
        elapsed = max(0.0, min(1.0, elapsed))

        remaining = max(pregame_projection - pts, 0.0) * (1.0 - elapsed)
        projected_total += pts + remaining
    return round(actual_total, 2), round(projected_total, 2)


def main():
    state = common.get_state()
    season = state["season"]
    week = state.get("display_week") or state["week"]
    season_type = state["season_type"]

    if season_type not in ("regular", "post"):
        print(f"season_type={season_type!r}, not in-season — skipping poll.")
        return

    league = common.get_league(LEAGUE_ID)
    scoring = league.get("scoring_settings", {})

    matchups = common.get_matchups(LEAGUE_ID, week)
    projections_by_player = common.get_projections(season, week, season_type)
    players_team = common.load_player_teams()
    team_progress = common.team_game_progress(season, week, season_type)

    rosters_out = {}
    for m in matchups:
        roster_id = str(m["roster_id"])
        starters = m.get("starters") or []
        players_points = m.get("players_points") or {}
        actual, projected = compute_projected_total(
            starters, players_points, projections_by_player, scoring, players_team, team_progress
        )
        rosters_out[roster_id] = {
            "actual": actual,
            "projected": projected,
            "players_points": {pid: players_points.get(pid, 0.0) for pid in starters if pid != "0"},
        }

    snapshot = {"ts": common.now_iso(), "week": week, "rosters": rosters_out}
    common.append_snapshot(week, snapshot)
    print(f"[{snapshot['ts']}] week {week}: logged {len(rosters_out)} rosters.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - a bad poll should not fail the workflow run
        print(f"poll.py error (non-fatal, will retry next scheduled run): {exc}", file=sys.stderr)
        sys.exit(0)
