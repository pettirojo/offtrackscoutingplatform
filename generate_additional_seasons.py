#!/usr/bin/env python3
"""
generate_additional_seasons.py

Adds season_id=2 and season_id=3 (same competition_id=999) on top of the
season 1 data from generate_synthetic_events.py, so the Player Leap tab
has something to diff.

What makes this "leap-friendly" rather than just more random data:
  - Rosters are identical across all three seasons (same build_rosters()
    call, same seed) so player_leap's season-over-season join actually
    finds common players.
  - Each player gets a per-season "trend" — a deliberate bump or drop in
    how often they're involved in usage events (passes/carries/crosses)
    and shot-creating actions, relative to their season 1 baseline. The
    trend categories are chosen so classify_leap() in usage.py produces
    a real mix: some "Big Leap", some "Efficient Improvement", some
    "Volume Increase", most "Stable" — instead of pure noise.
  - Fixtures for the new seasons are freshly generated round-ish-robin
    schedules among the same 30 clubs (new match_id ranges so they don't
    collide with season 1's 1001-1520ish IDs: season 2 uses 2001+,
    season 3 uses 3001+).

Run this AFTER generate_synthetic_events.py has produced season 1's
user_data/events/*.csv (or at least have user_data/matches/999/1.csv in
place, since team names are read from there).

Usage:
    python generate_additional_seasons.py
    python generate_additional_seasons.py --matches-per-season 250
"""
import argparse
import os
import random

import numpy as np
import pandas as pd

from generate_synthetic_events import (
    build_rosters, starting_xi_json, rand_loc, POSITIONS, SUB_POSITIONS,
    COLUMNS, TYPE_STARTING_XI, TYPE_PASS, TYPE_CARRY, TYPE_SHOT, TYPE_SUB,
)

TREND_CATEGORIES = [
    # (label, usage_multiplier, sca_multiplier, weight)
    ("big_leap", 1.7, 2.4, 0.12),
    ("efficient_improvement", 0.95, 1.6, 0.15),
    ("volume_increase", 1.6, 0.95, 0.15),
    ("decline", 0.6, 0.6, 0.10),
    ("stable", 1.0, 1.0, 0.48),
]


def build_player_trends(rosters, season_id, base_seed):
    """
    {player_name: {"usage_mult": float, "sca_mult": float}} for this season,
    relative to the season-1 baseline (season 1 itself always gets 1.0/1.0).
    """
    trends = {}
    all_players = []
    for roster in rosters.values():
        all_players.extend(n for n, _ in roster["starters"] + roster["subs"])

    if season_id == 1:
        return {p: {"usage_mult": 1.0, "sca_mult": 1.0} for p in all_players}

    labels, u_mults, s_mults, weights = zip(*TREND_CATEGORIES)
    for player in all_players:
        rng = random.Random(f"{base_seed}-trend-{season_id}-{player}")
        idx = rng.choices(range(len(labels)), weights=weights, k=1)[0]
        # small jitter so it's not identical for every player in a category
        jitter = lambda: rng.uniform(0.9, 1.1)
        trends[player] = {
            "usage_mult": round(u_mults[idx] * jitter(), 3),
            "sca_mult": round(s_mults[idx] * jitter(), 3),
        }
    return trends


def generate_fixtures(teams, season_id, match_id_start, num_matches, seed, start_date):
    rng = random.Random(f"{seed}-fixtures-{season_id}")
    np_rng = np.random.default_rng(seed + season_id)
    rows = []
    date = pd.Timestamp(start_date)
    match_id = match_id_start
    for _ in range(num_matches):
        home, away = rng.sample(teams, 2)
        home_goals = int(np_rng.poisson(1.45))
        away_goals = int(np_rng.poisson(1.15))
        rows.append({
            "match_id": match_id, "home_team": home, "away_team": away,
            "home_score": home_goals, "away_score": away_goals,
            "match_date": date.strftime("%Y-%m-%d"),
        })
        match_id += 1
        date += pd.Timedelta(days=rng.choice([2, 3, 3, 4]))
    return pd.DataFrame(rows)


def simulate_match_weighted(match_id, home_team, away_team, home_score, away_score,
                             home_roster, away_roster, trends, rng):
    rows = []
    home_starters = [n for n, _ in home_roster["starters"]]
    away_starters = [n for n, _ in away_roster["starters"]]
    home_subs = [n for n, _ in home_roster["subs"]]
    away_subs = [n for n, _ in away_roster["subs"]]

    rows.append(dict(match_id=match_id, player=None, team=home_team, type=TYPE_STARTING_XI,
                      minute=0, period=1, starting_xi_json=starting_xi_json(home_roster["starters"]),
                      home_score=0, away_score=0))
    rows.append(dict(match_id=match_id, player=None, team=away_team, type=TYPE_STARTING_XI,
                      minute=0, period=1, starting_xi_json=starting_xi_json(away_roster["starters"]),
                      home_score=0, away_score=0))

    on_pitch = {home_team: list(home_starters), away_team: list(away_starters)}
    bench = {home_team: list(home_subs), away_team: list(away_subs)}

    def usage_weight(name, pos_list):
        pos = dict(pos_list).get(name, "Center Midfield")
        base = {"Striker": 5, "Right Wing": 3, "Left Wing": 3}.get(pos, 2 if "Midfield" in pos else 1)
        return base * trends.get(name, {"usage_mult": 1.0})["usage_mult"]

    def sca_weight(name):
        return trends.get(name, {"sca_mult": 1.0})["sca_mult"]

    home_weights = {n: usage_weight(n, home_roster["starters"]) for n in home_starters}
    away_weights = {n: usage_weight(n, away_roster["starters"]) for n in away_starters}

    def weighted_pick(names, weight_map):
        names = list(names)
        w = [weight_map.get(n, 1.0) for n in names]
        return rng.choices(names, weights=w, k=1)[0]

    total_minutes = 90
    shot_events = []
    for _ in range(home_score):
        shot_events.append(("home", rng.randint(1, 90), True))
    for _ in range(away_score):
        shot_events.append(("away", rng.randint(1, 90), True))
    for _ in range(rng.randint(6, 14)):
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

        if sub_idx_home < len(sub_minutes_home) and minute == sub_minutes_home[sub_idx_home] and home_subs and on_pitch[home_team]:
            off_player = rng.choice(on_pitch[home_team][1:])
            on_player = bench[home_team].pop(0)
            on_pitch[home_team] = [on_player if p == off_player else p for p in on_pitch[home_team]]
            home_weights[on_player] = usage_weight(on_player, home_roster["subs"])
            rows.append(dict(match_id=match_id, player=off_player, team=home_team, type=TYPE_SUB,
                              minute=minute, period=period, substitution_replacement=on_player,
                              home_score=running_home, away_score=running_away))
            sub_idx_home += 1
        if sub_idx_away < len(sub_minutes_away) and minute == sub_minutes_away[sub_idx_away] and away_subs and on_pitch[away_team]:
            off_player = rng.choice(on_pitch[away_team][1:])
            on_player = bench[away_team].pop(0)
            on_pitch[away_team] = [on_player if p == off_player else p for p in on_pitch[away_team]]
            away_weights[on_player] = usage_weight(on_player, away_roster["subs"])
            rows.append(dict(match_id=match_id, player=off_player, team=away_team, type=TYPE_SUB,
                              minute=minute, period=period, substitution_replacement=on_player,
                              home_score=running_home, away_score=running_away))
            sub_idx_away += 1

        for _ in range(rng.randint(2, 4)):
            side_team = home_team if rng.random() < 0.5 else away_team
            names = on_pitch[side_team]
            weight_map = home_weights if side_team == home_team else away_weights
            if not names:
                continue
            player = weighted_pick(names, weight_map)
            etype = TYPE_CARRY if rng.random() < 0.25 else TYPE_PASS
            x, y = rand_loc(rng)
            if etype == TYPE_CARRY:
                rows.append(dict(match_id=match_id, player=player, team=side_team, type=TYPE_CARRY,
                                  minute=minute, period=period, location_x=x, location_y=y,
                                  home_score=running_home, away_score=running_away))
            else:
                ex, ey = rand_loc(rng)
                is_cross = 1 if rng.random() < 0.08 else 0
                # sca_mult biases how often this pass ends up flagged as a
                # shot-creating action later (see assist logic below), so
                # here we just record it as a normal pass.
                rows.append(dict(match_id=match_id, player=player, team=side_team, type=TYPE_PASS,
                                  minute=minute, period=period, location_x=x, location_y=y,
                                  pass_end_x=ex, pass_end_y=ey, pass_shot_assist=0,
                                  pass_goal_assist=0, pass_cross=is_cross,
                                  home_score=running_home, away_score=running_away))

        while shot_ptr < len(shot_events) and shot_events[shot_ptr][1] == minute:
            side, _, is_goal = shot_events[shot_ptr]
            shot_ptr += 1
            team = home_team if side == "home" else away_team
            names = on_pitch[team]
            weight_map = home_weights if side == "home" else away_weights
            if not names:
                continue
            player = weighted_pick(names, weight_map)
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

            assister_pool = [p for p in names if p != player]
            if assister_pool:
                # sca_mult raises/lowers the odds this player's pass gets
                # counted as a shot-creating action, which is what drives
                # the SCA-per-90 delta the leap tab actually reads.
                assist_weights = [sca_weight(p) for p in assister_pool]
                assister = rng.choices(assister_pool, weights=assist_weights, k=1)[0]
                if rng.random() < 0.55:
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

    # SCA-per-90 moves on a much smaller scale than usage_rate (a handful
    # of key passes per match vs. dozens of touches), so the multiplicative
    # reweighting above isn't enough on its own to clear classify_leap's
    # delta_sca>=1 threshold for "Big Leap" players. Top up directly here,
    # scaled by how far above baseline this player's sca_mult trend is.
    for team_name, starters in ((home_team, home_starters), (away_team, away_starters)):
        weight_map = home_weights if team_name == home_team else away_weights
        for player in starters:
            mult = sca_weight(player)
            if mult <= 1.3:
                continue
            extra = int(round((mult - 1.0) * rng.uniform(0.8, 1.3)))
            for _ in range(extra):
                minute = rng.randint(1, 90)
                period = 1 if minute <= 45 else 2
                ax, ay = rand_loc(rng, attacking=True)
                ex, ey = rand_loc(rng, attacking=True)
                rows.append(dict(match_id=match_id, player=player, team=team_name, type=TYPE_PASS,
                                  minute=minute, period=period, location_x=ax, location_y=ay,
                                  pass_end_x=ex, pass_end_y=ey, pass_shot_assist=1,
                                  pass_goal_assist=0, pass_cross=0,
                                  home_score=running_home, away_score=running_away))

    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches-csv", default="user_data/matches/999/1.csv",
                     help="Season 1 match CSV, used only to read the team list")
    ap.add_argument("--matches-dir", default="user_data/matches/999")
    ap.add_argument("--events-dir", default="user_data/events")
    ap.add_argument("--matches-per-season", type=int, default=250)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    os.makedirs(args.matches_dir, exist_ok=True)
    os.makedirs(args.events_dir, exist_ok=True)

    season1 = pd.read_csv(args.matches_csv)
    teams = sorted(set(season1["home_team"]) | set(season1["away_team"]))
    rosters = build_rosters(teams, args.seed)

    season_defs = [
        (2, 2001, "2025-08-01"),
        (3, 3001, "2026-08-01"),
    ]

    for season_id, match_id_start, start_date in season_defs:
        trends = build_player_trends(rosters, season_id, args.seed)

        fixtures = generate_fixtures(
            teams, season_id, match_id_start, args.matches_per_season, args.seed, start_date
        )
        matches_path = os.path.join(args.matches_dir, f"{season_id}.csv")
        fixtures.to_csv(matches_path, index=False)

        for _, m in fixtures.iterrows():
            match_id = int(m["match_id"])
            rng = random.Random(f"{args.seed}-{season_id}-{match_id}")
            rows = simulate_match_weighted(
                match_id, m["home_team"], m["away_team"],
                int(m["home_score"]), int(m["away_score"]),
                rosters[m["home_team"]], rosters[m["away_team"]], trends, rng,
            )
            df = pd.DataFrame(rows)
            for col in COLUMNS:
                if col not in df.columns:
                    df[col] = None
            df = df[COLUMNS]
            df.to_csv(os.path.join(args.events_dir, f"{match_id}.csv"), index=False)

        print(f"Season {season_id}: {len(fixtures)} matches written to {matches_path} "
              f"and {args.events_dir}/")

    print("\nDon't forget to add these to config.py:")
    print('    "My Custom League 2025": {"competition_id": 999, "season_id": 2},')
    print('    "My Custom League 2026": {"competition_id": 999, "season_id": 3},')


if __name__ == "__main__":
    main()
