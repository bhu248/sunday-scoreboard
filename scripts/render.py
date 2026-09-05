#!/usr/bin/env python3
"""
Turn data/week<N>.jsonl into docs/week<N>.html — the same time-lapse race
visual as the feasibility demo, but driven by real snapshots instead of a
scripted example. Also regenerates docs/index.html so there's one link that
always points at whatever weeks have been played.

Runs after every poll (cheap — it's just re-templating a small JSON blob),
so the page updates live through the day, not just once Monday night ends.
GitHub Pages serves whatever's in docs/ on main, so no separate deploy step
is needed beyond committing the file.
"""

import json
import os
import re
import sys

import common

LEAGUE_ID = os.environ.get("LEAGUE_ID", "1393377829990727680")
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

# The 8-hue validated categorical palette from the design system this project
# started from. With 14 teams we cycle it — every bar is already directly
# labeled with its team name, so a repeated hue is a cosmetic overlap, never
# an identity ambiguity.
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]


def build_frames(snapshots, roster_ids):
    frames = []
    prev_points = {rid: {} for rid in roster_ids}
    for snap in snapshots:
        rosters = snap.get("rosters", {})
        teams_frame = []
        flashes = []
        for rid in roster_ids:
            r = rosters.get(rid, {"actual": 0, "projected": 0, "players_points": {}})
            teams_frame.append({"id": rid, "actual": r["actual"], "projected": r["projected"]})

            cur_pp = r.get("players_points", {})
            for pid, pts in cur_pp.items():
                delta = pts - prev_points[rid].get(pid, 0.0)
                if delta > 0.05:
                    flashes.append({"id": rid, "pid": pid, "delta": round(delta, 2)})
            prev_points[rid] = cur_pp

        frames.append({"ts": snap["ts"], "teams": teams_frame, "flashes": flashes})
    return frames


def render_week(week):
    snapshots = common.load_snapshots(week)
    names = common.team_names(LEAGUE_ID)
    roster_ids = list(names.keys())
    # keep a stable order (by roster_id) so a team's row identity is consistent frame to frame
    roster_ids.sort(key=lambda x: int(x))

    if not snapshots:
        print(f"No snapshots yet for week {week}; nothing to render.")
        return None

    players = common.load_players_cache()
    frames = build_frames(snapshots, roster_ids)

    # resolve player labels for flashes actually used, so the page payload stays small
    used_pids = {f["pid"] for fr in frames for f in fr["flashes"]}
    player_labels = {pid: players.get(pid, pid) for pid in used_pids}

    payload = {
        "week": week,
        "teamNames": [names[rid] for rid in roster_ids],
        "rosterIds": roster_ids,
        "frames": frames,
        "playerLabels": player_labels,
    }

    html = TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":")))
    html = html.replace("__WEEK__", str(week))
    html = html.replace("__SERIES_LIGHT__", json.dumps(SERIES_LIGHT))
    html = html.replace("__SERIES_DARK__", json.dumps(SERIES_DARK))
    html = html.replace("__LAST_UPDATED__", snapshots[-1]["ts"])
    html = html.replace("__LEAGUE_ID__", LEAGUE_ID)

    os.makedirs(DOCS_DIR, exist_ok=True)
    out_path = os.path.join(DOCS_DIR, f"week{week}.html")
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Rendered {out_path} from {len(snapshots)} snapshots.")
    return out_path


def render_index():
    os.makedirs(DOCS_DIR, exist_ok=True)
    weeks = []
    for fname in os.listdir(DOCS_DIR):
        m = re.match(r"week(\d+)\.html$", fname)
        if m:
            weeks.append(int(m.group(1)))
    weeks.sort(reverse=True)

    items = "\n".join(f'<li><a href="week{w}.html">Week {w}</a></li>' for w in weeks) or "<li>No weeks played yet.</li>"
    html = INDEX_TEMPLATE.replace("__ITEMS__", items)
    with open(os.path.join(DOCS_DIR, "index.html"), "w") as f:
        f.write(html)


TEMPLATE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>Week __WEEK__ — Sunday Scoreboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@700;800&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  :root{
    color-scheme: light;
    --surface:#f6f5f0; --surface-raised:#ffffff; --surface-sunken:#ebe9e1;
    --ink:#17181a; --ink-secondary:#54544c; --ink-muted:#8b897e;
    --border:rgba(23,24,26,0.11); --accent:#1f6b3d; --accent-ink:#ffffff;
    --live:#c96a12; --live-surface:#f7ead6;
  }
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      color-scheme: dark;
      --surface:#131311; --surface-raised:#1c1c19; --surface-sunken:#0f0f0d;
      --ink:#f1efe6; --ink-secondary:#c4c2b6; --ink-muted:#8b897e;
      --border:rgba(241,239,230,0.12); --accent:#4fae74; --accent-ink:#0d140f;
      --live:#f0ac3f; --live-surface:#362a15;
    }
  }
  :root[data-theme="dark"]{
    color-scheme: dark;
    --surface:#131311; --surface-raised:#1c1c19; --surface-sunken:#0f0f0d;
    --ink:#f1efe6; --ink-secondary:#c4c2b6; --ink-muted:#8b897e;
    --border:rgba(241,239,230,0.12); --accent:#4fae74; --accent-ink:#0d140f;
    --live:#f0ac3f; --live-surface:#362a15;
  }
  *{box-sizing:border-box;}
  body{ margin:0; background:var(--surface); color:var(--ink); font-family:"Public Sans",system-ui,sans-serif; -webkit-font-smoothing:antialiased; }
  .wrap{ max-width:860px; margin:0 auto; padding:2.5rem 1.25rem 4rem; }
  .display{ font-family:"Big Shoulders Display",sans-serif; font-weight:800; }
  .mono{ font-family:"IBM Plex Mono",ui-monospace,monospace; font-variant-numeric:tabular-nums; }
  a{ color:var(--accent); }
  .eyebrow{ font-size:0.76rem; font-weight:700; letter-spacing:0.1em; text-transform:uppercase; color:var(--accent); margin-bottom:0.6rem; }
  h1{ font-size:clamp(2rem,5vw,3rem); line-height:0.98; margin:0 0 1.6rem; }
  .race-card{ background:var(--surface-raised); border:1px solid var(--border); border-radius:12px; padding:1.4rem; }
  .race-head{ display:flex; justify-content:space-between; align-items:center; gap:1rem; margin-bottom:1rem; flex-wrap:wrap; }
  .live-badge{ display:inline-flex; align-items:center; gap:0.4em; background:var(--live-surface); color:var(--live); font-size:0.72rem; font-weight:700; letter-spacing:0.05em; text-transform:uppercase; padding:0.3em 0.65em; border-radius:100px; }
  .live-badge .dot{ width:6px; height:6px; border-radius:50%; background:var(--live); }
  .race-track{ position:relative; }
  .race-row{ position:absolute; left:0; right:0; height:34px; transition: top 450ms cubic-bezier(.4,0,.2,1); display:flex; align-items:center; gap:0.6rem; }
  .race-name{ width:150px; flex:0 0 auto; font-size:0.78rem; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; text-align:right; }
  .race-bar-track{ flex:1 1 auto; position:relative; height:20px; }
  .race-bar-proj{ position:absolute; left:0; top:0; height:100%; border-radius:3px; opacity:0.3; transition: width 450ms cubic-bezier(.4,0,.2,1); }
  .race-bar{ position:absolute; left:0; top:0; height:100%; border-radius:3px; min-width:3px; transition: width 450ms cubic-bezier(.4,0,.2,1); }
  .race-score{ position:absolute; top:50%; transform:translateY(-50%); font-size:0.76rem; font-weight:600; white-space:nowrap; transition: left 450ms; }
  .race-flash{ position:absolute; top:-1.05rem; font-size:0.68rem; font-weight:600; color:var(--live); opacity:0; white-space:nowrap; transition:opacity 350ms ease; }
  .race-flash.show{ opacity:1; }
  .race-legend{ display:flex; gap:1.2rem; font-size:0.76rem; color:var(--ink-secondary); margin-top:1rem; flex-wrap:wrap; }
  .race-legend .item{ display:flex; align-items:center; gap:0.4em; }
  .race-legend .swatch{ width:13px; height:9px; border-radius:2px; background:var(--ink-muted); }
  .race-legend .swatch.proj{ opacity:0.32; }
  .meta{ font-size:0.8rem; color:var(--ink-muted); margin-top:1rem; line-height:1.6; }
  footer{ margin-top:2.5rem; font-size:0.8rem; color:var(--ink-muted); }

  .race-controls{ display:flex; align-items:center; gap:0.8rem; margin-top:1.1rem; padding-top:1rem; border-top:1px solid var(--border); }
  .play-btn{ width:32px; height:32px; border-radius:50%; border:1px solid var(--border); background:var(--surface-sunken); color:var(--ink); cursor:pointer; display:flex; align-items:center; justify-content:center; flex:0 0 auto; }
  .play-btn:hover{ background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }
  .scrub{ flex:1 1 auto; appearance:none; height:4px; border-radius:2px; background:var(--surface-sunken); outline:none; cursor:pointer; }
  .scrub::-webkit-slider-thumb{ appearance:none; width:13px; height:13px; border-radius:50%; background:var(--accent); cursor:pointer; border:2px solid var(--surface-raised); }
  .scrub::-moz-range-thumb{ width:13px; height:13px; border-radius:50%; background:var(--accent); cursor:pointer; border:2px solid var(--surface-raised); }
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">Week __WEEK__ &middot; <a href="index.html">all weeks</a></div>
  <h1 class="display">Sunday Scoreboard</h1>
  <div class="race-card">
    <div class="race-head">
      <span class="mono" id="clockLabel" style="font-size:0.9rem;font-weight:600;"></span>
      <span class="live-badge"><span class="dot"></span>Updated __LAST_UPDATED__ UTC</span>
    </div>
    <div class="race-track" id="raceTrack"></div>
    <div class="race-controls">
      <button class="play-btn" id="playBtn" aria-label="Play">
        <svg id="playIcon" width="12" height="12" viewBox="0 0 14 14" fill="currentColor"><path d="M2 1.5 12 7 2 12.5Z"/></svg>
        <svg id="pauseIcon" width="12" height="12" viewBox="0 0 14 14" fill="currentColor" style="display:none"><path d="M2.5 1.5h3v11h-3ZM8.5 1.5h3v11h-3Z"/></svg>
      </button>
      <input type="range" class="scrub" id="scrub" min="0" max="0" value="0" step="1">
    </div>
    <div class="race-legend">
      <span class="item"><span class="swatch"></span>Actual points</span>
      <span class="item"><span class="swatch proj"></span>Live-projected final</span>
    </div>
  </div>
  <p class="meta">Teams are ranked by live-projected final (the pale bar), not actual points banked so far — a team with a big head start from players already done can still sit below one with more real upside left on the field. Rebuilt automatically from Sleeper API snapshots polled every few minutes during game windows. Opens showing the latest snapshot — drag the scrubber back to replay how the day got there. Reload for the newest data; this page doesn't auto-refresh itself.</p>
  <footer>Sunday Scoreboard &middot; league <span class="mono">__LEAGUE_ID__</span></footer>
</div>
<script>
(function(){
  "use strict";
  var DATA = __PAYLOAD__;
  var SERIES_LIGHT = __SERIES_LIGHT__;
  var SERIES_DARK = __SERIES_DARK__;
  var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  var SERIES = dark ? SERIES_DARK : SERIES_LIGHT;

  var N = DATA.rosterIds.length;
  var frames = DATA.frames;
  if (!frames.length){ document.getElementById("raceTrack").textContent = "No data yet."; return; }

  var maxScore = 0;
  frames.forEach(function(fr){ fr.teams.forEach(function(t){ if (t.projected > maxScore) maxScore = t.projected; }); });
  maxScore = Math.max(maxScore * 1.1, 10);

  var track = document.getElementById("raceTrack");
  var rowH = 34 + 6;
  track.style.height = (N * rowH - 6) + "px";

  var rows = DATA.rosterIds.map(function(rid, i){
    var row = document.createElement("div");
    row.className = "race-row";
    var color = SERIES[i % SERIES.length];
    row.innerHTML =
      '<div class="race-name">' + DATA.teamNames[i] + '</div>' +
      '<div class="race-bar-track">' +
        '<div class="race-bar-proj" style="background:' + color + '"></div>' +
        '<div class="race-bar" style="background:' + color + '"></div>' +
        '<div class="race-flash"></div>' +
        '<div class="race-score mono"></div>' +
      '</div>';
    track.appendChild(row);
    return {
      id: rid,
      el: row,
      barProj: row.querySelector(".race-bar-proj"),
      bar: row.querySelector(".race-bar"),
      score: row.querySelector(".race-score"),
      flash: row.querySelector(".race-flash")
    };
  });

  function render(idx){
    var f = frames[idx];
    var byId = {};
    f.teams.forEach(function(t){ byId[t.id] = t; });

    // Ranked by live-projected final, not actual-so-far — a team that's
    // banked a big score from players who are already done can still sit
    // below a team with less banked but more real upside left on the field.
    var order = f.teams.slice().sort(function(a,b){ return b.projected - a.projected; }).map(function(t){ return t.id; });
    var rank = {};
    order.forEach(function(id,pos){ rank[id] = pos; });

    rows.forEach(function(r){
      var t = byId[r.id];
      var pos = rank[r.id];
      r.el.style.top = (pos * rowH) + "px";
      var pct = Math.max(1.5, (t.actual / maxScore) * 100);
      var pctProj = Math.max(pct, (t.projected / maxScore) * 100);
      r.bar.style.width = pct + "%";
      r.barProj.style.width = pctProj + "%";
      r.score.textContent = t.actual.toFixed(1);
      r.score.style.left = "calc(" + pct + "% + 8px)";

      var fl = f.flashes.find(function(x){ return x.id === r.id; });
      if (fl){
        var label = DATA.playerLabels[fl.pid] || fl.pid;
        r.flash.textContent = "+" + fl.delta.toFixed(1) + " · " + label;
        r.flash.classList.add("show");
      } else {
        r.flash.classList.remove("show");
      }
    });

    var d = new Date(f.ts);
    document.getElementById("clockLabel").textContent = d.toLocaleString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", month: "short", day: "numeric" }) + " ET";
  }

  var scrub = document.getElementById("scrub");
  scrub.max = frames.length - 1;

  var current = frames.length - 1;
  var playing = false;
  var timer = null;

  function setPlaying(p){
    playing = p;
    document.getElementById("playIcon").style.display = p ? "none" : "";
    document.getElementById("pauseIcon").style.display = p ? "" : "none";
  }

  function tick(){
    if (!playing) return;
    current++;
    if (current >= frames.length){ current = frames.length - 1; setPlaying(false); clearInterval(timer); }
    scrub.value = current;
    render(current);
  }

  document.getElementById("playBtn").addEventListener("click", function(){
    if (current >= frames.length - 1){ current = 0; scrub.value = 0; render(0); }
    setPlaying(!playing);
    clearInterval(timer);
    if (playing) timer = setInterval(tick, 200);
  });

  scrub.addEventListener("input", function(){
    setPlaying(false);
    clearInterval(timer);
    current = parseInt(scrub.value, 10);
    render(current);
  });

  scrub.value = current;
  render(current); // show the latest snapshot by default; drag the scrubber to replay the day
})();
</script>
</body>
</html>
"""

INDEX_TEMPLATE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>Sunday Scoreboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  body{ font-family: system-ui, sans-serif; background:#f6f5f0; color:#17181a; max-width:640px; margin:3rem auto; padding:0 1.25rem; }
  h1{ font-size:1.8rem; }
  ul{ padding-left: 1.2rem; line-height: 2; }
  a{ color:#1f6b3d; font-weight:600; }
  .quiz-link{ margin-top:2rem; padding-top:1.25rem; border-top:1px solid #ddd9cc; }
</style>
</head>
<body>
  <h1>Sunday Scoreboard</h1>
  <ul>
__ITEMS__
  </ul>
  <p class="quiz-link">🏈 <a href="quiz.html">Guess the Drafter</a> &mdash; guess which manager drafted each player from this year's real draft.</p>
</body>
</html>
"""

if __name__ == "__main__":
    # Optional explicit week, e.g. `python scripts/render.py 0` to render the
    # dummy-data test week regardless of what's actually live right now.
    if len(sys.argv) > 1:
        week = int(sys.argv[1])
    else:
        state = common.get_state()
        week = state.get("display_week") or state["week"]
    render_week(week)
    render_index()
