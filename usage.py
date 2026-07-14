# usage.py
"""
Engine C: Usage & System Structure.

Usage events = shots, carries, crosses, and progressive passes (forward
passes that meaningfully advance the ball - see geometry.is_progressive_pass).
Back/sideways passes are deliberately excluded so "usage" reflects
ball-dominant, attacking involvement rather than raw touches.
"""
import pandas as pd

from geometry import attacking_goal_x, is_progressive_pass


def _is_usage_event(row, home_team):
    etype = row["type"]
    if etype in ("Shot", "Carry"):
        return True
    if etype == "Pass":
        if row.get("pass_cross") is True:
            return True
        loc = row.get("location")
        end_loc = row.get("pass_end_location")
        if not isinstance(loc, (list, tuple)) or not isinstance(end_loc, (list, tuple)):
            return False
        team = row["team"]
        period = row.get("period", 1)
        goal_x = attacking_goal_x(team, home_team, period)
        return is_progressive_pass(loc[0], loc[1], end_loc[0], end_loc[1], goal_x)
    return False


def _is_sca_event(row):
    """Shot-creating action: a pass/carry/dribble whose immediate follow-up
    (same possession, next event by a teammate) is a shot. We approximate
    this with StatsBomb's own shot-assist flags where present, and fall back
    to key-pass detection via pass_shot_assist / pass_goal_assist."""
    if row["type"] != "Pass":
        return False
    # NB: use `is True` rather than bool(x) - StatsBomb boolean columns come
    # back as NaN for "not set", and bool(float('nan')) is True in Python,
    # which would silently mark every pass as a shot-creating action.
    return row.get("pass_shot_assist") is True or row.get("pass_goal_assist") is True


def compute_usage_and_sca(match_id, home_team, away_team, events):
    """
    Returns {player: {"team": team_name, "usage_count": int, "sca_count": int}}
    for a single match. Rates (percent of team total) are computed by the
    caller once all matches are aggregated, since usage rate is meant to be
    relative to a team's full-season attacking output, not one match.
    """
    out = {}
    for _, row in events.iterrows():
        player = row.get("player")
        if pd.isna(player):
            continue
        team = row["team"]
        d = out.setdefault(player, {"team": team, "usage_count": 0, "sca_count": 0})

        if _is_usage_event(row, home_team):
            d["usage_count"] += 1
        if _is_sca_event(row):
            d["sca_count"] += 1

    return out


def build_team_structure(team_name, player_rows):
    """
    player_rows: list of {"player": name, "usage_rate": float, "sca_per90": float}
    for players on this team across the season.
    Returns the team_structure dict, or None if fewer than 2 players qualify.
    """
    if len(player_rows) < 2:
        return None

    by_usage = sorted(player_rows, key=lambda r: r["usage_rate"], reverse=True)
    top = by_usage[0]
    second = by_usage[1]
    heliocentricity = top["usage_rate"] - second["usage_rate"]

    by_sca = sorted(player_rows, key=lambda r: r["sca_per90"], reverse=True)
    top_creator = by_sca[0]
    creativity_gap = top_creator["sca_per90"] - top["sca_per90"]

    return {
        "team": team_name,
        "top_usage_player": top["player"],
        "top_usage_rate": top["usage_rate"],
        "second_usage_player": second["player"],
        "second_usage_rate": second["usage_rate"],
        "heliocentricity": heliocentricity,
        "top_creator": top_creator["player"],
        "top_sca": top_creator["sca_per90"],
        "top_usage_sca": top["sca_per90"],
        "creativity_gap": creativity_gap,
    }


def classify_leap(delta_usage, delta_sca):
    """The 'Leap' quadrant framework from the design doc."""
    if delta_usage >= 2 and delta_sca >= 1:
        return "Big Leap"
    if delta_usage <= 0 and delta_sca > 0:
        return "Efficient Improvement"
    if delta_usage > 2 and delta_sca <= 0:
        return "Volume Increase"
    return "Stable"
