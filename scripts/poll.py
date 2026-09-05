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


def compute_projected_total(starters, players_points, projections_by_player, scoring):
    """
    Live-projected final total for one roster:
      actual points so far, PLUS each starter's pre-game projection for any
      starter who hasn't put a point on the board yet.

    Known simplification: a starter's projection drops to zero the moment
    they register ANY stat, even a single yard early in their game — so a
    slow-starting player who explodes late will make the "projected" number
    look a little conservative mid-game. Doing this precisely would mean
    knowing each player's actual kickoff time, which the public API doesn't
    expose directly. This is the honest, buildable v1; a schedule-aware
    version is a reasonable follow-up if the gap bothers you in practice.
    """
    actual_total = 0.0
    remaining_total = 0.0
    for pid in starters:
        if pid == "0":  # empty slot
            continue
        pts = players_points.get(pid, 0.0) or 0.0
        actual_total += pts
        if pts == 0.0:
            stats = projections_by_player.get(pid)
            if stats:
                remaining_total += common.score_stats(stats, scoring)
    return round(actual_total, 2), round(actual_total + remaining_total, 2)


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

    rosters_out = {}
    for m in matchups:
        roster_id = str(m["roster_id"])
        starters = m.get("starters") or []
        players_points = m.get("players_points") or {}
        actual, projected = compute_projected_total(
            starters, players_points, projections_by_player, scoring
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
