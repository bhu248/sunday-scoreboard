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


def install_mocks():
    common.get_state = lambda: FAKE_STATE
    common.get_league = lambda league_id: FAKE_LEAGUE
    common.get_users = lambda league_id: FAKE_USERS
    common.get_rosters = lambda league_id: FAKE_ROSTERS
    common.get_projections = lambda season, week, season_type="regular": FAKE_PROJECTIONS
    common.load_players_cache = lambda: FAKE_PLAYERS_CACHE
    common._matchup_seq = iter([FAKE_MATCHUPS_1, FAKE_MATCHUPS_2])
    common.get_matchups = lambda league_id, week: next(common._matchup_seq)


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
    assert r1["projected"] == 13.0, r1   # 6.0 actual + p1's 7.0 projection (p1 hadn't scored yet)
    r2 = snaps[1]["rosters"]["1"]
    assert r2["actual"] == 12.6, r2
    assert r2["projected"] == 12.6, r2   # p1 has now scored -> its projection drops out, matches actual
    print("poll.py logic: PASS")
    print("  snapshot 1, roster 1:", r1)
    print("  snapshot 2, roster 1:", r2)

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
