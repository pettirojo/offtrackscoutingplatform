# geometry.py
"""
Shared helpers for working with StatsBomb's pitch coordinate system.

StatsBomb's pitch is 120 (x) by 80 (y) units, both goals centered on y=40.
Attacking direction flips at half-time, so rather than guessing "home vs away"
from event ordering (fragile), we require the caller to pass in the actual
home_team name (from sb.matches()) and infer direction from period + team.
"""
import numpy as np


def attacking_goal_x(team, home_team, period):
    """
    Returns the x-coordinate of the goal this team is attacking, given the
    match period (1 = first half, 2 = second half, extra time periods mirror
    the previous period's second half).
    """
    is_home = (team == home_team)
    # Home attacks x=120 in period 1, x=0 in period 2 (standard flip).
    # Odd periods behave like period 1, even periods like period 2.
    first_half_like = (period % 2 == 1)
    if is_home:
        return 120.0 if first_half_like else 0.0
    else:
        return 0.0 if first_half_like else 120.0


def distance_to_goal(x, y, goal_x, goal_y=40.0):
    return float(np.hypot(goal_x - x, goal_y - y))


def is_progressive_pass(start_x, start_y, end_x, end_y, goal_x, goal_y=40.0):
    """
    Standard-ish progressive pass definition (distance-to-goal reduction
    thresholds that scale with pitch zone):
      - own half: needs >=30 yards of progress
      - opposition half: needs >=15 yards
      - final third: needs >=10 yards
    """
    d_before = distance_to_goal(start_x, start_y, goal_x, goal_y)
    d_after = distance_to_goal(end_x, end_y, goal_x, goal_y)
    progress = d_before - d_after
    if progress <= 0:
        return False

    if d_before > 60:       # own half
        return progress >= 30
    elif d_before > 20:     # opposition half, outside final third
        return progress >= 15
    else:                  # final third
        return progress >= 10
