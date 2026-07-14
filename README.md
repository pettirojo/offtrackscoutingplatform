# Dossier — Football Scouting Intelligence Platform

A free, local scouting tool built on StatsBomb open data. It runs three
analytical engines and serves them through a small Flask app that also
hosts the dashboard, so the whole thing runs as one process:

- **Hold-Up Play** — detects back-to-goal possession retention under
  pressure using StatsBomb's 360 freeze-frame data (only available for a
  handful of competitions — see note below).
- **Clutch Evaluator** — weights goals and big-chance misses by opponent
  difficulty and match-moment importance (an expected-points swing model).
- **Usage & System Structure** — usage rate, heliocentricity, and
  creativity gap, to judge how much a player's output depends on their
  team's system.

All rate stats (SCA, goals, wall actions) are computed **per 90 minutes
played**, not per match — a substitute who plays 10 minutes across 10
matches is scored on those ~100 minutes, not as if they'd started 10 full
games. Minutes are derived from each match's Starting XI and Substitution
events (already part of every events pull, so this adds no extra API
calls) — see `minutes.py` for the approach and its one known gap (an early
red card isn't detected, so that player's minutes are slightly
overstated).

Every player with shots also gets **xG and finishing efficiency**
(`goals - xG`) on their profile and in the league scatter data — a quick
way to separate "was actually clinical" from "got hot for a season."

Everything lives in one folder. No separate frontend server, no
backend/frontend split to juggle.

## Setup (one-time)

```bash
pip install -r requirements.txt
```

Python 3.9+ recommended.

## Run it

```bash
python run.py
```

That's the whole thing. On first run this will:

1. Create `scouting.db` (SQLite) if it doesn't exist.
2. Download and process every competition listed in `config.py` (needs
   internet — this project doesn't ship any football data itself). This
   is the slow part; a progress bar shows per-competition status.
3. Start the server and open your browser to `http://localhost:5000`.

On every run after that, `python run.py` just starts the server instantly
using whatever's already in `scouting.db` — no re-downloading.

### Other ways to run it

```bash
python run.py --refresh                        # rebuild all data from scratch
python run.py --competition "UEFA Euro 2024"    # only (re)process one competition
python run.py --serve-only                      # skip data building, just serve
python run.py --no-browser                      # don't auto-open a browser tab
python run.py --leap                            # (re)populate player_leap and exit
```

### Player Leap (season-over-season deltas)

The `player_leap` table compares a player's `usage_rate` and
`shot_creating_actions` (per-90) between two seasons of the **same**
competition, and tags them with `classify_leap()`: `Big Leap`, `Efficient
Improvement`, `Volume Increase`, or `Stable`.

To use it:

1. Add a second season of a league you already have to `COMPETITIONS` in
   `config.py`. To find its `competition_id`/`season_id`, run:
   ```bash
   python -c "from statsbombpy import sb; print(sb.competitions())"
   ```
   and filter to the competition you want.
2. Process it: `python run.py --competition "<new season label>" --refresh`
3. `player_leap` is populated automatically the next time `python run.py`
   does a full (no `--competition` filter) data build, or run
   `python run.py --leap` to populate it immediately from whatever seasons
   are already in `scouting.db`.

Season pairs are matched by ascending `season_id` within a
`competition_id` as a chronological proxy — spot-check the result for a
competition you know well before trusting it on a new one.

### About hold-up metrics

StatsBomb's 360 data (needed for hold-up detection) only exists for select
competitions — Euro 2020/2022/2024 and a few World Cups are good bets.
`config.py` defaults to a small known-good sample. If you process a
competition without 360 data, hold-up numbers just come back as zero;
clutch and usage metrics don't need 360 data and populate regardless.

## Files

```
scouting-platform/
├── run.py             ← the one command you run
├── app.py             ← Flask API + serves the dashboard
├── config.py           competitions, thresholds
├── models.py            SQLite schema
├── data_processor.py    batch orchestrator across all 3 engines
├── geometry.py          shared pitch-coordinate helpers
├── minutes.py            minutes-played derivation (for per-90 stats)
├── hold_up.py           Engine A
├── clutch.py            Engine B (also tracks xG for finishing efficiency)
├── usage.py             Engine C
├── requirements.txt
├── index.html
├── style.css
└── script.js
```

`app.py` only ever serves `index.html`, `style.css`, and `script.js` over
HTTP — the Python source and the SQLite database stay off-limits even
though they sit in the same folder.

## API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/competitions` | Lists competitions configured in `config.py` |
| `GET /api/player/<name>` | Unified player profile (fuzzy name match) |
| `GET /api/league_scatter?competition_id=&season_id=` | Data for the two scatter matrices |
| `GET /api/team_structure?competition_id=&season_id=` | Heliocentricity / creativity gap per team |
| `GET /api/player_leap?competition_id=&season1=&season2=` | Season-over-season leap data (table + `classify_leap()` helper exist; a populating script isn't wired in yet — see Notes) |

## Notes on what's simplified

This is a solid working foundation, not a finished commercial product:

- **Progressive pass** and **shot-creating action** definitions are
  reasonable approximations, not official StatsBomb labels (open data
  doesn't include those flags directly).
- **Opponent difficulty** is a heuristic built from each team's rolling
  7-match form (win rate, goal difference, points) — treat the 1–7 score
  as directional, not a calibrated rating system.
- **`player_leap`** is populated automatically once two seasons of the
  same competition are in `scouting.db` (see "Player Leap" above) — season
  order is inferred from `season_id`, which is usually but not always
  chronological, so double-check it for competitions you know well.
- **Minutes played** are inferred from Starting XI / Substitution events,
  not a dedicated StatsBomb field, so an early red card will slightly
  overstate that player's minutes for that match (see `minutes.py`).
- All thresholds (defender radius, big-chance xG cutoff, etc.) live in
  `config.py`.

## License

MIT
