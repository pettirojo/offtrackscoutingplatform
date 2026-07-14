# data_processor.py
"""
Processes a competition/season entirely from local CSV files.
No internet, no StatsBomb API.

It looks for CSVs in these locations (in order):
  1. ./user_data/matches/<competition_id>/<season_id>.csv
  2. ./matches_<competition_id>_<season_id>.csv (if in current dir)
  3. ./<season_id>.csv (if only one season per competition)

Events are looked for in:
  1. ./user_data/events/<match_id>.csv
  2. ./events_<match_id>.csv
  3. ./<match_id>.csv (if in current dir)

The processor will create the necessary folders if they don't exist.
"""
import json
import os
import sys
import time
import warnings
import pandas as pd
import shutil

from config import COMPETITIONS, MIN_GOALS_FOR_SCATTER, ENABLE_HOLD_UP, USER_DATA_DIR
from models import get_db_connection, init_db
from hold_up import compute_hold_up_stats
from clutch import compute_opponent_difficulty, compute_clutch_stats_for_match
from usage import compute_usage_and_sca, build_team_structure, classify_leap
from minutes import compute_minutes_played

warnings.filterwarnings("ignore", message="credentials were not supplied")

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable

# ------------------------------------------------------------
# Flexible CSV loaders
# ------------------------------------------------------------

def find_file(paths):
    """Return the first existing file path from a list."""
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def load_user_matches(competition_id, season_id):
    """Load match list from CSV, trying multiple possible locations."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Possible file locations
    possible = [
        os.path.join(USER_DATA_DIR, "matches", str(competition_id), f"{season_id}.csv"),
        os.path.join(base_dir, f"matches_{competition_id}_{season_id}.csv"),
        os.path.join(base_dir, f"{season_id}.csv"),
    ]
    # Also try direct in user_data root
    possible.append(os.path.join(USER_DATA_DIR, f"matches_{competition_id}_{season_id}.csv"))
    
    path = find_file(possible)
    if not path:
        # Create the default folder and show error
        default_path = possible[0]
        os.makedirs(os.path.dirname(default_path), exist_ok=True)
        raise FileNotFoundError(
            f"Match CSV not found. Please place your match CSV at:\n"
            f"  {default_path}\n"
            f"or rename it to 'matches_{competition_id}_{season_id}.csv' and place it in the current directory.\n"
            f"Tried: {possible}"
        )
    
    df = pd.read_csv(path)
    required = ["match_id", "home_team", "away_team", "match_date"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column '{col}' in match CSV")
    df["match_date"] = pd.to_datetime(df["match_date"])
    return df

def load_user_events(match_id):
    """Load events from CSV, trying multiple locations."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    possible = [
        os.path.join(USER_DATA_DIR, "events", f"{match_id}.csv"),
        os.path.join(base_dir, f"events_{match_id}.csv"),
        os.path.join(base_dir, f"{match_id}.csv"),
    ]
    path = find_file(possible)
    if not path:
        # Create the default folder and show error
        default_path = possible[0]
        os.makedirs(os.path.dirname(default_path), exist_ok=True)
        raise FileNotFoundError(
            f"Events CSV for match {match_id} not found. Please place it at:\n"
            f"  {default_path}\n"
            f"or rename it to 'events_{match_id}.csv' and place it in the current directory.\n"
            f"Tried: {possible}"
        )

    df = pd.read_csv(path)

    # Build 'location' as a list [x, y]
    if "location_x" in df.columns and "location_y" in df.columns:
        df["location"] = df.apply(
            lambda r: [r["location_x"], r["location_y"]] 
            if pd.notna(r["location_x"]) and pd.notna(r["location_y"]) 
            else None,
            axis=1
        )

    # Build 'pass_end_location' as a list [x, y]
    if "pass_end_x" in df.columns and "pass_end_y" in df.columns:
        df["pass_end_location"] = df.apply(
            lambda r: [r["pass_end_x"], r["pass_end_y"]] 
            if pd.notna(r["pass_end_x"]) and pd.notna(r["pass_end_y"]) 
            else None,
            axis=1
        )

    # Convert boolean columns from 0/1 to True/False
    for col in ["pass_cross", "pass_shot_assist", "pass_goal_assist"]:
        if col in df.columns:
            df[col] = df[col].astype(float).map({1.0: True, 0.0: False})

    # Build 'tactics' for Starting XI events (used by minutes.py)
    if "starting_xi_json" in df.columns:
        df["tactics"] = None
        mask = df["type"] == "Starting XI"
        df.loc[mask, "tactics"] = df.loc[mask, "starting_xi_json"].apply(
            lambda x: {"lineup": json.loads(x)} if pd.notna(x) else None
        )

    return df


# ------------------------------------------------------------
# RunningStandings (unchanged)
# ------------------------------------------------------------

class RunningStandings:
    """Tracks each team's last-7-match form as the season is processed in date order."""
    def __init__(self):
        self.history = {}  # team -> list of {"win": bool, "draw": bool, "gf": int, "ga": int, "pts": int}

    def difficulty_for(self, team):
        recent = self.history.get(team, [])[-7:]
        if not recent:
            return compute_opponent_difficulty({"played": 0})
        form = {
            "played": len(recent),
            "wins": sum(1 for m in recent if m["win"]),
            "goals_for": sum(m["gf"] for m in recent),
            "goals_against": sum(m["ga"] for m in recent),
            "points": sum(m["pts"] for m in recent),
        }
        return compute_opponent_difficulty(form)

    def record_result(self, home_team, away_team, home_score, away_score):
        for team, gf, ga in ((home_team, home_score, away_score), (away_team, away_score, home_score)):
            win = gf > ga
            draw = gf == ga
            pts = 3 if win else (1 if draw else 0)
            self.history.setdefault(team, []).append(
                {"win": win, "draw": draw, "gf": gf, "ga": ga, "pts": pts}
            )


# ------------------------------------------------------------
# Main processing function (with better error handling)
# ------------------------------------------------------------

def process_league(competition_id, season_id, label=""):
    print(f"\n=== Processing {label or competition_id} (season {season_id}) ===")

    try:
        matches = load_user_matches(competition_id, season_id)
    except FileNotFoundError as e:
        print(f"  {e}")
        return

    if matches.empty:
        print("  No matches found in your CSV.")
        return

    matches = matches.sort_values("match_date")
    standings = RunningStandings()

    player_agg = {}
    holdup_available_matches = 0

    if ENABLE_HOLD_UP:
        print("  Hold-up detection enabled – requires 360 data (not available in CSV).")
    else:
        print("  Hold-up detection disabled (config.ENABLE_HOLD_UP = False).")

    for _, match in tqdm(list(matches.iterrows()), total=len(matches)):
        match_id = match["match_id"]
        home_team = match["home_team"]
        away_team = match["away_team"]
        home_score = match.get("home_score", 0)
        away_score = match.get("away_score", 0)

        try:
            events = load_user_events(match_id)
        except FileNotFoundError as e:
            print(f"  Skipping match {match_id}: {e}")
            continue

        # Compute opponent difficulty using form up to (but not including) this match
        difficulty_lookup = {
            home_team: standings.difficulty_for(away_team),
            away_team: standings.difficulty_for(home_team),
        }

        # Hold-up (always empty if ENABLE_HOLD_UP is False)
        if ENABLE_HOLD_UP:
            hold_up_data = compute_hold_up_stats(match_id, home_team, away_team, events=events)
        else:
            hold_up_data = {}
        if hold_up_data:
            holdup_available_matches += 1

        # Clutch, Usage, and Minutes engines – they work on DataFrames
        clutch_data = compute_clutch_stats_for_match(events, home_team, away_team, difficulty_lookup)
        usage_data = compute_usage_and_sca(match_id, home_team, away_team, events)
        minutes_data = compute_minutes_played(events, home_team, away_team)

        # Aggregate per player
        all_players = set(hold_up_data) | set(clutch_data) | set(usage_data) | set(minutes_data)
        for player in all_players:
            d = player_agg.setdefault(player, {
                "team": None, "matches": 0, "minutes": 0.0,
                "usage_sum": 0, "sca_sum": 0,
                "hold_up_attempts": 0, "hold_up_successes": 0, "hold_up_walls": 0,
                "weighted_goals": 0.0, "weighted_misses": 0.0, "goals": 0,
                "difficulties": [], "importances": [], "total_xg": 0.0,
            })
            if player in usage_data:
                d["team"] = usage_data[player]["team"]
                d["usage_sum"] += usage_data[player]["usage_count"]
                d["sca_sum"] += usage_data[player]["sca_count"]
            d["matches"] += 1
            d["minutes"] += minutes_data.get(player, 0.0)

            if player in hold_up_data:
                hd = hold_up_data[player]
                d["hold_up_attempts"] += hd["attempts"]
                d["hold_up_successes"] += hd["successes"]
                d["hold_up_walls"] += hd["walls"]

            if player in clutch_data:
                cd = clutch_data[player]
                d["weighted_goals"] += cd["weighted_goals"]
                d["weighted_misses"] += cd["weighted_misses"]
                d["goals"] += cd["goals"]
                d["difficulties"].extend(cd["difficulties"])
                d["importances"].extend(cd["importances"])
                d["total_xg"] += cd.get("total_xg", 0.0)

        standings.record_result(home_team, away_team, home_score, away_score)

    if ENABLE_HOLD_UP and holdup_available_matches == 0:
        print("  Note: no 360 freeze-frame data found (CSV doesn't support it).")

    # Team-level totals for usage rate
    team_totals = {}
    for player, d in player_agg.items():
        if not d["team"]:
            continue
        t = team_totals.setdefault(d["team"], {"usage": 0, "sca": 0})
        t["usage"] += d["usage_sum"]
        t["sca"] += d["sca_sum"]

    conn = get_db_connection()
    cur = conn.cursor()

    team_player_rows = {}

    for player, d in player_agg.items():
        matches_played = d["matches"]
        if matches_played == 0 or not d["team"]:
            continue

        minutes_played = d["minutes"]
        team_total_usage = team_totals.get(d["team"], {}).get("usage", 0)
        usage_rate = (d["usage_sum"] / team_total_usage * 100) if team_total_usage else 0

        if minutes_played > 0:
            sca_per90 = d["sca_sum"] / minutes_played * 90
            wall_per90 = d["hold_up_walls"] / minutes_played * 90
            goals_per90 = d["goals"] / minutes_played * 90
        else:
            sca_per90 = 0
            wall_per90 = 0
            goals_per90 = 0

        hu_attempts = d["hold_up_attempts"]
        hu_success_rate = d["hold_up_successes"] / hu_attempts if hu_attempts else 0

        net_clutch = d["weighted_goals"] - d["weighted_misses"]
        avg_difficulty = sum(d["difficulties"]) / len(d["difficulties"]) if d["difficulties"] else 0
        avg_importance = sum(d["importances"]) / len(d["importances"]) if d["importances"] else 0

        xg = d.get("total_xg", 0.0)
        finishing_efficiency = d["goals"] - xg

        cur.execute('''
            INSERT OR REPLACE INTO player_aggregates
            (player_name, team_name, competition_id, season_id, matches_played,
             minutes_played, usage_rate, hold_up_attempts, hold_up_successes,
             hold_up_success_rate, wall_count, net_clutch_score, avg_goal_difficulty,
             avg_goal_importance, weighted_goals, weighted_misses,
             shot_creating_actions, goals, goals_per90, xg, finishing_efficiency)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            player, d["team"], competition_id, season_id, matches_played,
            minutes_played, usage_rate, hu_attempts, d["hold_up_successes"],
            hu_success_rate, wall_per90, net_clutch, avg_difficulty,
            avg_importance, d["weighted_goals"], d["weighted_misses"],
            sca_per90, d["goals"], goals_per90, xg, finishing_efficiency,
        ))

        team_player_rows.setdefault(d["team"], []).append({
            "player": player, "usage_rate": usage_rate, "sca_per90": sca_per90,
        })

    for team_name, rows in team_player_rows.items():
        structure = build_team_structure(team_name, rows)
        if not structure:
            continue
        cur.execute('''
            INSERT OR REPLACE INTO team_structure
            (team_name, competition_id, season_id, top_usage_player, top_usage_rate,
             second_usage_player, second_usage_rate, heliocentricity,
             top_creator, top_sca, top_usage_sca, creativity_gap)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            team_name, competition_id, season_id,
            structure["top_usage_player"], structure["top_usage_rate"],
            structure["second_usage_player"], structure["second_usage_rate"],
            structure["heliocentricity"], structure["top_creator"],
            structure["top_sca"], structure["top_usage_sca"], structure["creativity_gap"],
        ))

    conn.commit()
    conn.close()
    print(f"  Done. {len(player_agg)} players, {len(team_player_rows)} teams written.")


# ------------------------------------------------------------
# Player Leap (unchanged)
# ------------------------------------------------------------

def populate_player_leap(competition_id, season1_id, season2_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        SELECT player_name, usage_rate, shot_creating_actions
        FROM player_aggregates WHERE competition_id = ? AND season_id = ?
    ''', (competition_id, season1_id))
    season1 = {r["player_name"]: r for r in cur.fetchall()}

    cur.execute('''
        SELECT player_name, usage_rate, shot_creating_actions
        FROM player_aggregates WHERE competition_id = ? AND season_id = ?
    ''', (competition_id, season2_id))
    season2 = {r["player_name"]: r for r in cur.fetchall()}

    common_players = set(season1) & set(season2)
    for player in common_players:
        u1, u2 = season1[player]["usage_rate"], season2[player]["usage_rate"]
        sca1, sca2 = season1[player]["shot_creating_actions"], season2[player]["shot_creating_actions"]
        delta_usage = u2 - u1
        delta_sca = sca2 - sca1
        category = classify_leap(delta_usage, delta_sca)

        cur.execute('''
            INSERT OR REPLACE INTO player_leap
            (player_name, competition_id, season1_id, season2_id,
             usage_1, usage_2, sca_1, sca_2, delta_usage, delta_sca, leap_category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (player, competition_id, season1_id, season2_id,
              u1, u2, sca1, sca2, delta_usage, delta_sca, category))

    conn.commit()
    conn.close()
    return len(common_players)


def populate_all_leaps():
    by_competition = {}
    for cfg in COMPETITIONS.values():
        by_competition.setdefault(cfg["competition_id"], set()).add(cfg["season_id"])

    total_pairs = 0
    for competition_id, season_ids in by_competition.items():
        season_ids = sorted(season_ids)
        if len(season_ids) < 2:
            continue
        for season1_id, season2_id in zip(season_ids, season_ids[1:]):
            n = populate_player_leap(competition_id, season1_id, season2_id)
            if n:
                print(f"  Player leap: competition {competition_id}, "
                      f"season {season1_id} -> {season2_id}: {n} players")
                total_pairs += 1
    if total_pairs == 0:
        print("  No season pairs found within the same competition_id in "
              "config.py – add a second season of a league to use player_leap.")
    return total_pairs


# ------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    target = sys.argv[1] if len(sys.argv) > 1 else None

    start = time.time()
    if target:
        if target not in COMPETITIONS:
            print(f"Unknown competition '{target}'. Options: {list(COMPETITIONS.keys())}")
            sys.exit(1)
        cfg = COMPETITIONS[target]
        process_league(cfg["competition_id"], cfg["season_id"], label=target)
    else:
        for label, cfg in COMPETITIONS.items():
            process_league(cfg["competition_id"], cfg["season_id"], label=label)
        populate_all_leaps()

    print(f"\nTotal time: {time.time() - start:.1f}s")