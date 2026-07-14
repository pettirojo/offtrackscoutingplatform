# clutch.py
"""
Engine B: Clutch Evaluator.

Difficulty and importance are computed by the batch processor (which has
access to the full, chronologically-ordered season) and passed in here -
that keeps this module a pure function of its inputs, which makes it
testable and avoids the placeholder-value bug in the original draft.
"""
import pandas as pd

from config import CLUTCH_BIG_CHANCE_XG


def compute_opponent_difficulty(team_form):
    """
    team_form: dict with keys wins, draws, losses, goals_for, goals_against,
    points over their last <=7 matches (built by the batch processor's
    running standings table).
    Returns a 1-7 difficulty score.
    """
    played = team_form.get("played", 0)
    if played == 0:
        return 4.0  # neutral default for a team's very first matches

    win_rate = team_form["wins"] / played
    gd_per_game = (team_form["goals_for"] - team_form["goals_against"]) / played
    ppg = team_form["points"] / played

    # Combine three signals (0-1 win rate, roughly -3..3 GD/game, 0-3 ppg)
    # into a single score, then squash into 1-7.
    raw = (win_rate * 0.5) + (max(min(gd_per_game, 3), -3) / 6 * 0.3) + (ppg / 3 * 0.2)
    # raw is roughly in [-0.05, 1.0]; map to [1, 7]
    score = 1 + max(0, min(1, raw)) * 6
    return round(score, 2)


def _win_draw_prob(goal_diff, remaining_frac):
    """Simple empirical-ish curve for P(win)/P(draw) given goal difference
    and fraction of match time remaining. Not a substitute for a fitted
    model, but monotonic and bounded, which is what the importance metric needs."""
    if goal_diff == 0:
        win_p, draw_p = 0.34, 0.38
    elif goal_diff == 1:
        win_p, draw_p = 0.55, 0.28
    elif goal_diff == -1:
        win_p, draw_p = 0.15, 0.28
    elif goal_diff >= 2:
        win_p, draw_p = min(0.70 + 0.08 * (goal_diff - 2), 0.95), 0.08
    else:  # <= -2
        win_p, draw_p = max(0.03 - 0.02 * (abs(goal_diff) - 2), 0.01), 0.10

    # Time remaining amplifies uncertainty: leads are less safe early,
    # deficits are less hopeless early.
    if goal_diff > 0:
        win_p = win_p * (1 - 0.15 * remaining_frac)
    elif goal_diff < 0:
        win_p = win_p * (1 + 0.10 * remaining_frac)

    win_p = max(0.0, min(1.0, win_p))
    draw_p = max(0.0, min(1.0 - win_p, draw_p))
    return win_p, draw_p


def compute_moment_importance(home_goals_before, away_goals_before, minute, is_home_shot):
    """Expected-points swing if this specific shot becomes a goal."""
    remaining_frac = max(0.0, (90 - minute) / 90)
    gd_shooter_perspective = (home_goals_before - away_goals_before) * (1 if is_home_shot else -1)

    win_p, draw_p = _win_draw_prob(gd_shooter_perspective, remaining_frac)
    current_pts = win_p * 3 + draw_p * 1

    new_gd = gd_shooter_perspective + 1
    new_win_p, new_draw_p = _win_draw_prob(new_gd, remaining_frac)
    new_pts = new_win_p * 3 + new_draw_p * 1

    return round(abs(new_pts - current_pts), 3)


def compute_clutch_stats_for_match(events, home_team, away_team, difficulty_lookup, importance_fn=None):
    """
    difficulty_lookup: {team_name: difficulty_score} for THIS match (i.e. the
    difficulty of the opponent, keyed by the shooting team).
    Returns {player: {goals, weighted_goals, misses, weighted_misses,
                       difficulties: [...], importances: [...],
                       total_xg, total_shots}}

    total_xg/total_shots are accumulated for EVERY shot the player takes,
    not just goals and "big chance" misses - the clutch weighting below
    stays scoped to high-leverage moments, but finishing efficiency
    (goals - xG) needs the full shot log to mean anything.
    """
    importance_fn = importance_fn or compute_moment_importance
    shots = events[events["type"] == "Shot"]

    out = {}
    for _, shot in shots.iterrows():
        player = shot.get("player")
        if pd.isna(player):
            continue

        is_goal = shot.get("shot_outcome") == "Goal"
        xg = shot.get("shot_statsbomb_xg", 0) or 0

        d = out.setdefault(player, {
            "goals": 0, "weighted_goals": 0.0,
            "misses": 0, "weighted_misses": 0.0,
            "difficulties": [], "importances": [],
            "total_xg": 0.0, "total_shots": 0,
        })
        d["total_xg"] += xg
        d["total_shots"] += 1

        if not is_goal and xg < CLUTCH_BIG_CHANCE_XG:
            continue  # only weigh goals and "big chance" misses for the clutch score

        team = shot["team"]
        minute = shot.get("minute", 0)
        home_goals_before = shot.get("home_score", shot.get("home_goals_before", 0)) or 0
        away_goals_before = shot.get("away_score", shot.get("away_goals_before", 0)) or 0
        is_home_shot = (team == home_team)

        difficulty = difficulty_lookup.get(team, 4.0)
        importance = importance_fn(home_goals_before, away_goals_before, minute, is_home_shot)
        weight = difficulty * importance

        d["difficulties"].append(difficulty)
        d["importances"].append(importance)
        if is_goal:
            d["goals"] += 1
            d["weighted_goals"] += weight
        else:
            d["misses"] += 1
            d["weighted_misses"] += weight

    for player, d in out.items():
        d["net_clutch"] = d["weighted_goals"] - d["weighted_misses"]
        d["avg_difficulty"] = sum(d["difficulties"]) / len(d["difficulties"]) if d["difficulties"] else 0
        d["avg_importance"] = sum(d["importances"]) / len(d["importances"]) if d["importances"] else 0

    return out
