#!/usr/bin/env python3
"""
generate_synthetic_events.py

Generates a per-match events CSV (matching the schema data_processor.py
expects — same columns as user_data/events/1001.csv) for every match in
your match-list CSV that doesn't already have an events file.

Why this exists: your matches CSV (user_data/matches/999/1.csv) already
lists ~500+ fixtures across ~30 clubs, but only match 1001 has an events
file, so data_processor.py silently skips everything else. This script
fills in the rest with a believable — clearly synthetic — season of event
data so usage rate, clutch, xG/finishing, and team-structure all have a
real sample size to work with.

Design choices that matter for the downstream engines:
  - Each club gets ONE persistent roster (11 starters + subs) reused
    across every match it plays. Random rosters per match would wreck
    usage_rate/team_structure, which are meant to track the same players
    across a season.
  - "My Home Team" and "My Away Team" reuse the exact roster already
    established in 1001.csv, since those two clubs recur later in the
    fixture list — you don't want two different "James Whitfield"s.
  - Shot outcomes are generated so goals-per-team sum to the real
    score in your matches CSV (data_processor.py doesn't cross-check
    this, but it keeps the numbers coherent to look at).
  - home_score/away_score on Shot rows reflect the score BEFORE that
    shot (what clutch.py's importance model expects); Pass/Carry rows
    just carry the current running score.

Usage:
    python generate_synthetic_events.py
    python generate_synthetic_events.py --limit 50        # only fill in 50 matches
    python generate_synthetic_events.py --seed 7           # different random season
    python generate_synthetic_events.py --matches-csv path/to/1.csv --events-dir path/to/events
"""
import argparse
import json
import os
import random

import pandas as pd

# ------------------------------------------------------------------
# Known rosters (reused as-is so recurring clubs stay consistent with
# the match-1001 events file you already have).
# ------------------------------------------------------------------
KNOWN_ROSTERS = {
    "My Home Team": {
        "starters": [
            ("James Whitfield", "Goalkeeper"), ("Daniel Cross", "Right Back"),
            ("Marcus Reed", "Center Back"), ("Oliver Hunt", "Center Back"),
            ("Ethan Bell", "Left Back"), ("Lucas Grant", "Defensive Midfield"),
            ("Noah Fisher", "Center Midfield"), ("Henry Palmer", "Center Midfield"),
            ("William Shaw", "Right Wing"), ("Benjamin Cole", "Striker"),
            ("Samuel Blake", "Left Wing"),
        ],
        "subs": [
            ("Leo Marsh", "Center Midfield"), ("Charlie Doyle", "Right Back"),
            ("Jack Turner", "Striker"), ("George Hale", "Center Back"),
        ],
    },
    "My Away Team": {
        "starters": [
            ("Diego Marin", "Goalkeeper"), ("Carlos Vega", "Right Back"),
            ("Mateo Silva", "Center Back"), ("Luca Romano", "Center Back"),
            ("Andres Torres", "Left Back"), ("Pablo Nunez", "Defensive Midfield"),
            ("Rafael Costa", "Center Midfield"), ("Bruno Ferreira", "Center Midfield"),
            ("Hugo Alves", "Right Wing"), ("Enzo Rossi", "Striker"),
            ("Marco Bianchi", "Left Wing"),
        ],
        "subs": [
            ("Tiago Duarte", "Center Midfield"), ("Nico Fabri", "Left Back"),
            ("Sergio Nieto", "Striker"), ("Ivan Cabral", "Center Back"),
        ],
    },
}

POSITIONS = [
    "Goalkeeper", "Right Back", "Center Back", "Center Back", "Left Back",
    "Defensive Midfield", "Center Midfield", "Center Midfield",
    "Right Wing", "Striker", "Left Wing",
]
SUB_POSITIONS = ["Center Midfield", "Striker", "Right Back", "Center Back", "Left Wing"]

FIRST_NAMES = [
    "Alex", "Ryan", "Owen", "Liam", "Dylan", "Max", "Finn", "Toby", "Aaron", "Callum",
    "Josh", "Nathan", "Adam", "Kai", "Leon", "Miles", "Elliot", "Reece", "Jamie", "Connor",
    "Theo", "Harvey", "Louis", "Zack", "Fraser", "Isaac", "Joel", "Ollie", "Ezra", "Miguel",
    "Andre", "Nico", "Felix", "Tom", "Jonah", "Ravi", "Amir", "Kofi", "Sami", "Bilal",
    "Mikael", "Erik", "Anders", "Jonas", "Stefan", "Dario", "Emil", "Viktor", "Mateus", "Tariq",
]
LAST_NAMES = [
    "Harding", "Kellow", "Ashby", "Merrick", "Fenwick", "Osei", "Delacroix", "Brandt",
    "Sorensen", "Okafor", "Pryce", "Hollis", "Vance", "Whittaker", "Sadler", "Larkin",
    "Marsh", "Quill", "Radcliffe", "Stannard", "Uzoma", "Voss", "Wexford", "Yardley",
    "Zeller", "Barrington", "Cavanagh", "Dunmore", "Ellery", "Farrow", "Gillan", "Hexham",
    "Ibrahimi", "Jelic", "Kessler", "Lindqvist", "Mbeki", "Novak", "Oduya", "Petronio",
    "Quintero", "Roswell", "Sabatini", "Thorne", "Ulster", "Verhoeven", "Winslow", "Xander",
    "Yeboah", "Zamora",
]

TYPE_STARTING_XI = "Starting XI"
TYPE_PASS = "Pass"
TYPE_CARRY = "Carry"
TYPE_SHOT = "Shot"
TYPE_SUB = "Substitution"

COLUMNS = [
    "match_id", "player", "team", "type", "minute", "period",
    "location_x", "location_y", "shot_outcome", "shot_statsbomb_xg",
    "pass_end_x", "pass_end_y", "pass_shot_assist", "pass_goal_assist",
    "pass_cross", "substitution_replacement", "starting_xi_json",
    "home_score", "away_score",
]


def build_name_pool(n, rng, used):
    names = []
    attempts = 0
    while len(names) < n and attempts < n * 50:
        attempts += 1
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        if name not in used:
            used.add(name)
            names.append(name)
    return names


def build_rosters(teams, seed):
    """One persistent 11-starter + 4-sub roster per club."""
    used_names = set()
    for r in KNOWN_ROSTERS.values():
        for name, _ in r["starters"] + r["subs"]:
            used_names.add(name)

    rosters = {}
    for team in teams:
        if team in KNOWN_ROSTERS:
            rosters[team] = KNOWN_ROSTERS[team]
            continue
        rng = random.Random(f"{seed}-{team}")
        names = build_name_pool(15, rng, used_names)
        starters = list(zip(names[:11], POSITIONS))
        subs = list(zip(names[11:15], SUB_POSITIONS))
        rosters[team] = {"starters": starters, "subs": subs}
    return rosters


def starting_xi_json(starters):
    lineup = []
    for i, (name, pos) in enumerate(starters, start=1):
        lineup.append({
            "player": {"id": i, "name": name},
            "position": {"id": i, "name": pos},
            "jersey_number": i,
        })
    return json.dumps(lineup)


def rand_loc(rng, attacking=False):
    x = rng.uniform(0, 120)
    y = rng.uniform(0, 80)
    if attacking:
        x = rng.uniform(70, 120)
    return round(x, 1), round(y, 1)


def simulate_match(match_id, home_team, away_team, home_score, away_score,
                    home_roster, away_roster, rng):
    rows = []
    home_starters = [n for n, _ in home_roster["starters"]]
    away_starters = [n for n, _ in away_roster["starters"]]
    home_subs = [n for n, _ in home_roster["subs"]]
    away_subs = [n for n, _ in away_roster["subs"]]

    # Starting XI rows
    rows.append(dict(match_id=match_id, player=None, team=home_team, type=TYPE_STARTING_XI,
                      minute=0, period=1, starting_xi_json=starting_xi_json(home_roster["starters"]),
                      home_score=0, away_score=0))
    rows.append(dict(match_id=match_id, player=None, team=away_team, type=TYPE_STARTING_XI,
                      minute=0, period=1, starting_xi_json=starting_xi_json(away_roster["starters"]),
                      home_score=0, away_score=0))

    on_pitch = {home_team: list(home_starters), away_team: list(away_starters)}
    bench = {home_team: list(home_subs), away_team: list(away_subs)}

    # Attacking-weighted player pool per team (wingers/strikers get more shots)
    def weight(pos_list, names):
        w = []
        for n in names:
            pos = dict(pos_list).get(n, "Center Midfield")
            if pos in ("Striker",):
                w.append((n, 5))
            elif pos in ("Right Wing", "Left Wing"):
                w.append((n, 3))
            elif "Midfield" in pos:
                w.append((n, 2))
            else:
                w.append((n, 1))
        return w

    home_weights = weight(home_roster["starters"], home_starters)
    away_weights = weight(away_roster["starters"], away_starters)

    def weighted_choice(weights):
        names, w = zip(*weights)
        return rng.choices(names, weights=w, k=1)[0]

    # Build a shot schedule: goals for each side placed at random minutes,
    # plus some extra non-goal shots (some "big chances" for clutch scoring).
    total_minutes = 90
    shot_events = []
    for _ in range(home_score):
        shot_events.append(("home", rng.randint(1, 90), True))
    for _ in range(away_score):
        shot_events.append(("away", rng.randint(1, 90), True))
    extra_shots = rng.randint(6, 14)
    for _ in range(extra_shots):
        side = rng.choice(["home", "away"])
        shot_events.append((side, rng.randint(1, 90), False))
    shot_events.sort(key=lambda e: e[1])

    running_home, running_away = 0, 0
    sub_minutes_home = sorted(rng.sample(range(55, 88), k=min(2, len(home_subs))))
    sub_minutes_away = sorted(rng.sample(range(55, 88), k=min(2, len(away_subs))))
    sub_idx_home, sub_idx_away = 0, 0

    shot_ptr = 0
    for minute in range(1, total_minutes + 1):
        period = 1 if minute <= 45 else 2

        # substitutions
        if sub_idx_home < len(sub_minutes_home) and minute == sub_minutes_home[sub_idx_home] and home_subs and on_pitch[home_team]:
            off_player = rng.choice(on_pitch[home_team][1:])  # avoid subbing keeper
            on_player = bench[home_team].pop(0)
            on_pitch[home_team] = [on_player if p == off_player else p for p in on_pitch[home_team]]
            rows.append(dict(match_id=match_id, player=off_player, team=home_team, type=TYPE_SUB,
                              minute=minute, period=period, substitution_replacement=on_player,
                              home_score=running_home, away_score=running_away))
            sub_idx_home += 1
        if sub_idx_away < len(sub_minutes_away) and minute == sub_minutes_away[sub_idx_away] and away_subs and on_pitch[away_team]:
            off_player = rng.choice(on_pitch[away_team][1:])
            on_player = bench[away_team].pop(0)
            on_pitch[away_team] = [on_player if p == off_player else p for p in on_pitch[away_team]]
            rows.append(dict(match_id=match_id, player=off_player, team=away_team, type=TYPE_SUB,
                              minute=minute, period=period, substitution_replacement=on_player,
                              home_score=running_home, away_score=running_away))
            sub_idx_away += 1

        # a couple of pass/carry events per minute to build minutes/usage/SCA
        for _ in range(rng.randint(2, 4)):
            side_team, other_team = (home_team, away_team) if rng.random() < 0.5 else (away_team, home_team)
            names = on_pitch[side_team]
            if not names:
                continue
            player = rng.choice(names)
            etype = TYPE_CARRY if rng.random() < 0.25 else TYPE_PASS
            x, y = rand_loc(rng)
            if etype == TYPE_CARRY:
                rows.append(dict(match_id=match_id, player=player, team=side_team, type=TYPE_CARRY,
                                  minute=minute, period=period, location_x=x, location_y=y,
                                  home_score=running_home, away_score=running_away))
            else:
                ex, ey = rand_loc(rng)
                is_cross = 1 if rng.random() < 0.08 else 0
                rows.append(dict(match_id=match_id, player=player, team=side_team, type=TYPE_PASS,
                                  minute=minute, period=period, location_x=x, location_y=y,
                                  pass_end_x=ex, pass_end_y=ey, pass_shot_assist=0,
                                  pass_goal_assist=0, pass_cross=is_cross,
                                  home_score=running_home, away_score=running_away))

        # shots scheduled for this minute
        while shot_ptr < len(shot_events) and shot_events[shot_ptr][1] == minute:
            side, _, is_goal = shot_events[shot_ptr]
            shot_ptr += 1
            team = home_team if side == "home" else away_team
            names = on_pitch[team]
            if not names:
                continue
            weights = home_weights if side == "home" else away_weights
            weights = [(n, w) for n, w in weights if n in names] or [(n, 1) for n in names]
            player = weighted_choice(weights)
            x, y = rand_loc(rng, attacking=True)
            xg = round(rng.uniform(0.35, 0.75), 3) if is_goal else round(rng.uniform(0.03, 0.55), 3)
            before_home, before_away = running_home, running_away
            if is_goal:
                outcome = "Goal"
                if side == "home":
                    running_home += 1
                else:
                    running_away += 1
            else:
                outcome = rng.choice(["Blocked", "Off T", "Saved", "Wayward"])

            # occasionally credit an assist on the preceding pass
            if rng.random() < 0.55 and names:
                assister_pool = [p for p in names if p != player]
                if assister_pool:
                    assister = rng.choice(assister_pool)
                    ax, ay = rand_loc(rng, attacking=True)
                    rows.append(dict(match_id=match_id, player=assister, team=team, type=TYPE_PASS,
                                      minute=minute, period=period, location_x=ax, location_y=ay,
                                      pass_end_x=x, pass_end_y=y,
                                      pass_shot_assist=1, pass_goal_assist=1 if is_goal else 0,
                                      pass_cross=0, home_score=before_home, away_score=before_away))

            rows.append(dict(match_id=match_id, player=player, team=team, type=TYPE_SHOT,
                              minute=minute, period=period, location_x=x, location_y=y,
                              shot_outcome=outcome, shot_statsbomb_xg=xg,
                              home_score=before_home, away_score=before_away))

    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches-csv", default="user_data/matches/999/1.csv")
    ap.add_argument("--events-dir", default="user_data/events")
    ap.add_argument("--limit", type=int, default=None, help="Only generate this many missing matches")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    os.makedirs(args.events_dir, exist_ok=True)
    matches = pd.read_csv(args.matches_csv)

    teams = sorted(set(matches["home_team"]) | set(matches["away_team"]))
    rosters = build_rosters(teams, args.seed)

    generated, skipped_existing = 0, 0
    for _, m in matches.iterrows():
        match_id = int(m["match_id"])
        out_path = os.path.join(args.events_dir, f"{match_id}.csv")
        if os.path.exists(out_path):
            skipped_existing += 1
            continue
        if args.limit is not None and generated >= args.limit:
            continue

        rng = random.Random(f"{args.seed}-{match_id}")
        rows = simulate_match(
            match_id, m["home_team"], m["away_team"],
            int(m["home_score"]), int(m["away_score"]),
            rosters[m["home_team"]], rosters[m["away_team"]], rng,
        )
        df = pd.DataFrame(rows)
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = None
        df = df[COLUMNS]
        df.to_csv(out_path, index=False)
        generated += 1

    print(f"Generated {generated} new match event files in {args.events_dir}/")
    print(f"Skipped {skipped_existing} matches that already had an events CSV.")


if __name__ == "__main__":
    main()
