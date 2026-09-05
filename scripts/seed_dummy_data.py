#!/usr/bin/env python3
"""
Write a fabricated "week 0" of scoring snapshots, using your league's real
14 team names, so you can see the actual time-lapse render end to end before
Week 1 is real. Safe to run anytime, including in the off-season — it never
touches data/week1.jsonl or later, since real weeks are always >= 1.

Usage: python scripts/seed_dummy_data.py
Then:  python scripts/render.py 0

Re-running this overwrites data/week0.jsonl from scratch each time, so it's
safe to run again after tweaking anything.
"""

import random

import common

LEAGUE_ID = "1393377829990727680"
TEST_WEEK = 0

# Since the draft hasn't happened yet, no roster has real players on it, so
# there's nothing real to attribute a score jump to — these labels stand in
# for "some starter on this roster did something," the same way the very
# first feasibility demo used generic roster-slot labels instead of real
# player names.
EVENT_LABELS = [
    "RB1 — rushing TD", "WR2 — 21-yd catch", "QB — TD pass", "K — 42-yd FG",
    "FLEX — short gain", "TE — red zone TD", "DEF — sack + stop",
    "WR1 — deep TD catch", "RB2 — goal-line TD", "QB — rushing TD",
    "WR1 — 2 first downs", "K — 51-yd FG", "FLEX — screen pass",
]


def make_events(rng, total_minutes):
    """A handful of scoring bumps spread across the fake day for one team."""
    n_events = rng.randint(3, 6)
    times = sorted(rng.sample(range(10, total_minutes), n_events))
    events = []
    for t in times:
        delta = round(rng.uniform(2.0, 13.0), 1)
        label = rng.choice(EVENT_LABELS)
        events.append((t, delta, label))
    return events


def main():
    rng = random.Random(42)  # fixed seed: reproducible, so re-runs are comparable
    names = common.team_names(LEAGUE_ID)
    roster_ids = sorted(names.keys(), key=int)

    total_minutes = 240
    step = 3
    fake_pid_counter = [0]

    per_team_events = {}
    per_team_projection = {}
    for rid in roster_ids:
        events = make_events(rng, total_minutes)
        per_team_events[rid] = events
        final_actual = sum(e[1] for e in events)
        # a pre-game projection that's sometimes an over-, sometimes an
        # under-estimate of how the fake day actually goes — real variance,
        # not just the team's own final score played back at itself
        per_team_projection[rid] = round(final_actual * rng.uniform(0.75, 1.3), 1)

    # clear any previous seed run
    path = common.week_data_path(TEST_WEEK)
    open(path, "w").close()

    running = {rid: 0.0 for rid in roster_ids}
    event_idx = {rid: 0 for rid in roster_ids}

    for t in range(0, total_minutes + 1, step):
        rosters_out = {}
        for rid in roster_ids:
            events = per_team_events[rid]
            players_points = {}
            while event_idx[rid] < len(events) and events[event_idx[rid]][0] <= t:
                _, delta, label = events[event_idx[rid]]
                running[rid] += delta
                fake_pid_counter[0] += 1
                # the fake player_id IS the human-readable label: render.py
                # falls back to displaying the id verbatim when it's not in
                # Sleeper's real player-name cache, which is exactly what we
                # want for a synthetic demo player
                players_points[f"{label} #{fake_pid_counter[0]}"] = delta
                event_idx[rid] += 1

            remaining = per_team_projection[rid] * max(0.0, 1 - t / total_minutes)
            rosters_out[rid] = {
                "actual": round(running[rid], 2),
                "projected": round(running[rid] + remaining, 2),
                "players_points": players_points,
            }

        snapshot = {"ts": common.now_iso(), "week": TEST_WEEK, "rosters": rosters_out}
        common.append_snapshot(TEST_WEEK, snapshot)

    print(f"Seeded {total_minutes // step + 1} fake snapshots for week {TEST_WEEK} "
          f"across {len(roster_ids)} real teams from league {LEAGUE_ID}.")
    print("Next: python scripts/render.py 0")


if __name__ == "__main__":
    main()
