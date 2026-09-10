# Sunday Scoreboard — project notes for Claude Code

This file exists to hand off context from an earlier Claude session (Cowork)
to Claude Code. Read this before making changes — several bugs have already
been found and fixed here, and it's easy to accidentally re-introduce one of
them if you reason about the scoring model from scratch.

## What this is

A zero-secrets GitHub Actions + GitHub Pages system. Every few minutes during
NFL game windows, `scripts/poll.py` hits Sleeper's public, unauthenticated API
for league `1393377829990727680`, appends one timestamped snapshot to
`data/week<N>.jsonl`, and `scripts/render.py` rebuilds `docs/week<N>.html` — a
live dual-bar (actual + live-projected) time-lapse race chart — from the full
snapshot history. GitHub Pages serves `docs/`. No API keys, no secrets, no
auth anywhere in this project — keep it that way.

## File layout

- `scripts/common.py` — all Sleeper API calls, plus `team_game_progress()`
  (the one non-Sleeper external call, to ESPN's public scoreboard — see
  below), `score_stats()` (generic dot-product scorer using the league's own
  `scoring_settings`), and the players cache (`load_players_cache()` for
  display labels, `load_player_teams()` for each player's current team).
- `scripts/poll.py` — one poll → one snapshot. `compute_projected_total()` is
  the scoring model; read its docstring in full before touching it.
- `scripts/render.py` — rebuilds the HTML chart from the full `.jsonl`
  history: time-lapse bars, the 5 biggest plays, the week-winning-play
  marker, chronological slate labels ("Thursday Night Football" etc.),
  click-to-jump on markers/legend.
- `scripts/seed_dummy_data.py` — generates fake week-0 demo data with fake
  player-id labels like `"WR1 — deep TD catch"`. Dummy-data-only; if you ever
  see a garbled name like that in real output, it means dummy data leaked in,
  not a labeling bug.
- `.github/workflows/scoreboard.yml` — the cron schedule. Every line fires at
  minute `2-57/5`, not `*/5` — GitHub Actions scheduled runs get delayed
  worst right at round 5-minute marks (documented GitHub behavior, confirmed
  in production during this project's Week 1 opener). The 2026-specific
  Friday/Saturday date block (Black Friday, Christmas, Week 15-18 Saturdays)
  has no year field in cron, so it will fire again on the same calendar
  dates in 2027 with the wrong games — review/remove that block before the
  2027 season.
- `selftest.py` (repo root) — **not committed to the repo**, dev-only. Mocks
  every Sleeper call and runs `poll.py` + `render.py` against fake data,
  asserting exact expected numbers. Run this before shipping any change to
  `compute_projected_total` or the render logic. It has caught every
  regression described below.

## The scoring model — read this before touching `compute_projected_total`

Three different bugs have been found and fixed here, each one a plausible-
looking mistake:

1. **The kickoff-cliff bug (original).** A player contributed their full
   pre-game projection only while their actual points were exactly `0.0`;
   the instant they recorded ANY stat, their contribution dropped to just
   their actual, zeroing the rest of their projection. This made every
   team's "projected" total crater toward "actual" right at kickoff —
   backwards, since a player who just scored is usually still early in their
   game.

2. **The uniform wall-clock-decay bug.** While investigating a later issue,
   a retroactive "fix" decayed every roster's projection using a single
   assumed kickoff-time + fixed game-duration, applied to ALL rosters
   uniformly — including rosters whose players had recorded zero actual
   points. Result: scoreless teams' projections cratered too, just because
   time had passed, with no in-game justification. **Fix:** decay must be
   gated on `actual > 0` — see the gate in `compute_projected_total` (the
   `if pts > 0.0: ... else: elapsed = 0.0` block). A player who hasn't
   scored yet keeps their full, undecayed projection no matter how much
   wall-clock time passes; "hasn't scored" isn't evidence their opportunity
   is used up, it's just as likely their game hasn't gotten to them yet.

3. **The two-formulas-in-one-timeline bug.** The retroactive backfill from
   bug #2 used a fabricated wall-clock timer; live polls use a DIFFERENT
   formula based on `common.team_game_progress()` (ESPN's real scoreboard
   clock). These disagreed more and more as time passed, so the chart showed
   values sliding down through the middle of a game and then snapping back
   up near pregame levels the moment a fresh live poll landed — a visible
   "dip in the middle of the time-lapse." **Fix:** there must be exactly ONE
   formula for "projected," ever: `max(actual, pregame_projection)` per
   player when `team_game_progress` returns no real clock data (elapsed=0),
   decaying smoothly toward actual as elapsed approaches 1.0 when it does.
   Never retroactively rewrite history with a different formula than the one
   live polls are currently using — reconstruct historical "projected"
   values using the SAME formula live polls use, with real per-player
   pre-game projections (fetch each one individually from
   `https://api.sleeper.app/projections/nfl/player/<id>?season=...&week=...`
   — the bulk `/v1/projections/nfl/...` endpoint is too large for reliable
   single-key lookups by an LLM; the per-player endpoint is small and exact).

## ESPN dependency — currently dormant, not broken

`common.team_game_progress()` reads ESPN's public, unauthenticated scoreboard
(`site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard`) to get each
game's live quarter/clock, because **Sleeper's own projections endpoint is
confirmed static** — it returns one unchanging pre-game number for the whole
week, verified by both the lack of any live-projection endpoint in Sleeper's
docs and by this project's own production data (a roster with zero scoring
players held an exactly unchanged projected total for over an hour of live
play). ESPN's clock is how "live" decay actually happens.

As of this hand-off, ESPN has **never once** reported the league's real Week
1 game (NE @ SEA, 2026-09-09) as anything but `STATUS_SCHEDULED`, checked
repeatedly over several hours including well after its actual kickoff time.
This means `team_game_progress()` has been returning empty/zero progress for
this entire game, so the decay feature has been sitting dormant — every
player's projection just holds at `max(actual, pregame_projection)` with no
time-decay, which is correct, safe, degraded behavior, not a bug. Don't
"fix" this without first re-checking ESPN's live status — the code is
working as designed for a game ESPN hasn't started reporting on.

## Other known behaviors (not bugs)

- **Sleeper's pregame projections can drift slightly over time**, even
  before a player takes the field — a player's own projection number was
  observed shifting by a couple of points between polls taken hours apart,
  presumably from upstream injury/inactive-list updates. This is legitimate
  and expected; don't assume a small shift on a scoreless player's number is
  a sign of a decay bug resurfacing — check whether it's actually the
  player's source projection that moved.
- **Scheduled (`schedule:`) GitHub Actions triggers have not been confirmed
  to fire reliably.** Manual `workflow_dispatch` runs work fine; scheduled
  runs were observed going missing for 15-20+ minutes or more at a time
  during the Week 1 opener, with nothing diagnosable from outside GitHub
  (workflow isn't disabled, default branch is correct, no GitHub status
  incident, YAML/cron is valid). This was never root-caused. Claude Code has
  something the Cowork session didn't: real `gh` CLI access to this repo's
  Actions run history (`gh run list`, `gh api .../actions/workflows`) — worth
  using that to actually dig into run timestamps vs. cron schedule if this
  keeps happening.
- **`docs/week<N>.html` only reflects what's in `data/week<N>.jsonl` as of
  the last render.** After any direct edit to the `.jsonl` history, you must
  run `python scripts/render.py` (or trigger the workflow) to regenerate the
  HTML — the committed data and the committed page can drift out of sync
  otherwise.
- **Multiple fantasy rosters can share the same real NFL game.** Don't
  assume different roster IDs means different real games — in this league's
  Week 1 data, six different fantasy rosters all had a player in the same
  single NE@SEA game.

## Workflow for any change to the scoring/render logic

1. Make the change.
2. Run `python3 selftest.py` from the repo root — it must print
   `ALL SELFTESTS PASSED`. Extend its fake-data scenarios to cover whatever
   you just changed before considering it verified (see the scoreless-roster
   test case already in there as a template).
3. Only then commit/push.
