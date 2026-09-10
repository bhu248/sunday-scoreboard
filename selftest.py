"""
Local dry run with mocked network calls, to sanity check poll.py / render.py
logic before shipping. Not part of the delivered repo.
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))

import common  # noqa: E402

TEST_LEAGUE = "test123"

FAKE_STATE = {"season": "2026", "week": 1, "display_week": 1, "season_type": "regular"}

FAKE_LEAGUE = {
    "scoring_settings": {
        "pass_yd": 0.04, "pass_td": 4.0, "pass_int": -1.0,
        "rush_yd": 0.1, "rush_td": 6.0,
        "rec": 0.5, "rec_yd": 0.1, "rec_td": 6.0,
        "fum_lost": -0.5, "fgm": 3.0, "fgmiss": -1.0, "xpm": 1.0, "xpmiss": -1.0,
    }
}

FAKE_USERS = [
    {"user_id": "u1", "display_name": "alice", "metadata": {"team_name": "Alpha Team"}},
    {"user_id": "u2", "display_name": "bob", "metadata": {}},
]
FAKE_ROSTERS = [
    {"roster_id": 1, "owner_id": "u1"},
    {"roster_id": 2, "owner_id": "u2"},
]

# poll #1: player p1 hasn't scored yet (0 actual -> use projection), p2 has 6 actual pts already
FAKE_MATCHUPS_1 = [
    {"roster_id": 1, "points": 6.0, "starters": ["p1", "p2"], "players_points": {"p1": 0.0, "p2": 6.0}},
    {"roster_id": 2, "points": 0.0, "starters": ["p3"], "players_points": {"p3": 0.0}},
]
# poll #2: p1 finally scores (a TD), p2 stays flat, p3 still scoreless
FAKE_MATCHUPS_2 = [
    {"roster_id": 1, "points": 12.6, "starters": ["p1", "p2"], "players_points": {"p1": 6.6, "p2": 6.0}},
    {"roster_id": 2, "points": 0.0, "starters": ["p3"], "players_points": {"p3": 0.0}},
]

FAKE_PROJECTIONS = {
    "p1": {"rush_yd": 40.0, "rush_td": 0.5},   # 40*0.1 + 0.5*6 = 7.0 projected
    "p2": {"rec": 4.0, "rec_yd": 50.0},         # 4*0.5 + 50*0.1 = 7.0 projected
    "p3": {"pass_yd": 250.0, "pass_td": 1.5},   # 10 + 6 = 16.0 projected
}

FAKE_PLAYERS_CACHE = {"p1": "Fake Runner (RB)", "p2": "Fake Catcher (WR)", "p3": "Fake Thrower (QB)"}
FAKE_PLAYER_TEAMS = {"p1": "AAA", "p2": "BBB", "p3": "CCC"}

# poll #1: no ESPN game-clock data yet (simulates pregame, or an ESPN
# hiccup) -> every team falls back to elapsed=0, so this should reduce to
# exactly the old max(actual, pregame_projection) behavior.
FAKE_PROGRESS_1 = {}
# poll #2: p1's team (AAA) is at halftime, p2's team (BBB) has finished —
# each player's "upside" above their actual should decay accordingly. p3's
# team (CCC) is ALSO well into its game (0.9) even though p3 personally is
# still scoreless -- this is the case that must NOT decay: a quiet player
# isn't evidence their opportunity is gone, just that it hasn't arrived yet.
FAKE_PROGRESS_2 = {"AAA": 0.5, "BBB": 1.0, "CCC": 0.9}


def install_mocks():
    common.get_state = lambda: FAKE_STATE
    common.get_league = lambda league_id: FAKE_LEAGUE
    common.get_users = lambda league_id: FAKE_USERS
    common.get_rosters = lambda league_id: FAKE_ROSTERS
    common.get_projections = lambda season, week, season_type="regular": FAKE_PROJECTIONS
    common.load_players_cache = lambda: FAKE_PLAYERS_CACHE
    common.load_player_teams = lambda: FAKE_PLAYER_TEAMS
    common._matchup_seq = iter([FAKE_MATCHUPS_1, FAKE_MATCHUPS_2])
    common.get_matchups = lambda league_id, week: next(common._matchup_seq)
    common._progress_seq = iter([FAKE_PROGRESS_1, FAKE_PROGRESS_2])
    common.team_game_progress = lambda season, week, season_type="regular": next(common._progress_seq)


def main():
    # Run entirely inside a throwaway temp directory — this must NEVER touch
    # the real data/ and docs/ folders in a cloned repo, since those hold
    # real season snapshots and the published pages once the season starts.
    sandbox = tempfile.mkdtemp(prefix="scoreboard-selftest-")
    data_dir = os.path.join(sandbox, "data")
    docs_dir = os.path.join(sandbox, "docs")
    os.makedirs(data_dir)
    os.makedirs(docs_dir)

    install_mocks()
    common.DATA_DIR = data_dir
    common.PLAYERS_CACHE = os.path.join(data_dir, "players_cache.json")
    os.environ["LEAGUE_ID"] = TEST_LEAGUE

    import poll
    poll.LEAGUE_ID = TEST_LEAGUE
    poll.main()
    poll.main()  # second poll -> second snapshot

    snaps = common.load_snapshots(1)
    assert len(snaps) == 2, f"expected 2 snapshots, got {len(snaps)}"
    r1 = snaps[0]["rosters"]["1"]
    assert r1["actual"] == 6.0, r1
    # no ESPN game-clock data yet -> elapsed=0 for every team -> reduces to
    # the old max(actual, pregame_projection): max(0,7)=7 for p1, max(6,7)=7 for p2
    assert r1["projected"] == 14.0, r1
    r2 = snaps[1]["rosters"]["1"]
    assert r2["actual"] == 12.6, r2
    # p1 (team AAA, at halftime/elapsed=0.5): actual 6.6 + (7-6.6)*0.5 = 6.8
    # p2 (team BBB, game over/elapsed=1.0):   actual 6.0 + (7-6.0)*0.0 = 6.0
    # 6.8 + 6.0 = 12.8 -- the live decay actually moves the number now,
    # instead of staying frozen at 14.0 all game like the old pinned model.
    assert r2["projected"] == 12.8, r2

    # p3 (roster 2) never scores in either poll, even though by poll #2
    # their team's game is 90% elapsed -- projected must stay pinned at the
    # full 16.0 pre-game projection both times, NOT decay toward 0 just
    # because time passed. This is the exact bug just fixed: every roster's
    # projected total was cratering together regardless of whether that
    # roster had scored anything.
    p3_poll1 = snaps[0]["rosters"]["2"]
    p3_poll2 = snaps[1]["rosters"]["2"]
    assert p3_poll1["actual"] == 0.0 and p3_poll1["projected"] == 16.0, p3_poll1
    assert p3_poll2["actual"] == 0.0 and p3_poll2["projected"] == 16.0, p3_poll2

    print("poll.py logic: PASS")
    print("  snapshot 1, roster 1:", r1)
    print("  snapshot 2, roster 1:", r2)
    print("  snapshot 2, roster 2 (scoreless all game):", p3_poll2)

    import render
    render.LEAGUE_ID = TEST_LEAGUE
    render.DOCS_DIR = docs_dir
    out = render.render_week(1)
    assert out and os.path.exists(out)
    with open(out) as f:
        html = f.read()
    assert "Alpha Team" in html
    assert "Fake Runner (RB)" in html  # flash label for p1's jump between poll 1 and poll 2
    print("render.py logic: PASS —", out, f"({len(html)} bytes)")

    render.render_index()
    idx = os.path.join(docs_dir, "index.html")
    assert os.path.exists(idx)
    with open(idx) as f:
        assert "week1.html" in f.read()
    print("index render: PASS")

    shutil.rmtree(sandbox)
    print("\nALL SELFTESTS PASSED (ran entirely in a throwaway temp dir — your real data/ and docs/ were untouched)")


if __name__ == "__main__":
    main()
