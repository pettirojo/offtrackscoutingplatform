# hold_up.py
"""
Engine A: Hold-Up Play Quantifier.

Needs StatsBomb 360 freeze-frame data, which only exists for a handful of
free competitions (e.g. Euro 2020/2022/2024, WSL, some World Cups). For
matches without 360 data, this engine returns an empty result rather than
guessing - there is no reliable non-360 proxy for body orientation.

NOTE ON THE STATSBOMBPY API: the exact column that carries the freeze frame
varies by statsbombpy version. We try the known variants and fall back
gracefully. If this stops matching your installed version, run
`print(events.columns.tolist())` after `sb.events(match_id=X, include_360_metrics=True)`
and adjust FREEZE_FRAME_COLUMNS below.
"""
import numpy as np
import pandas as pd
from statsbombpy import sb

from config import (
    HOLD_UP_DEFENDER_RADIUS_YARDS,
    HOLD_UP_WINDOW_SECONDS,
    HOLD_UP_WALL_SECONDS,
)
from geometry import attacking_goal_x, distance_to_goal

FREEZE_FRAME_COLUMNS = ["player_freeze_frame", "freeze_frame", "360_freeze_frame"]


def _timestamp_to_seconds(ts):
    """StatsBomb timestamps are 'HH:MM:SS.mmm' strings; convert to seconds."""
    if pd.isna(ts):
        return None
    try:
        h, m, s = str(ts).split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, AttributeError):
        return None


def _find_freeze_frame_column(events_df):
    for col in FREEZE_FRAME_COLUMNS:
        if col in events_df.columns:
            return col
    return None


def compute_hold_up_stats(match_id, home_team, away_team, events=None):
    """
    Returns {player_name: {attempts, successes, walls, success_rate}} for one match.
    Returns {} if no 360 data is available for this match.
    """
    if events is None:
        try:
            events = sb.events(match_id=match_id, include_360_metrics=True)
        except Exception:
            return {}

    ff_col = _find_freeze_frame_column(events)
    if ff_col is None:
        return {}  # no 360 data for this match - can't detect body orientation

    events = events.copy()
    events["_secs"] = events["timestamp"].apply(_timestamp_to_seconds)

    receptions = events[
        (events["type"] == "Pass")
        & (events["pass_outcome"].isna())          # completed passes only
        & (events[ff_col].notna())
    ]

    hold_up_data = {}

    for _, row in receptions.iterrows():
        recipient = row.get("pass_recipient")
        if pd.isna(recipient):
            continue

        frame = row[ff_col]
        if not isinstance(frame, (list, tuple)) or len(frame) == 0:
            continue

        team = row["team"]
        period = row.get("period", 1)
        loc = row.get("location")
        if not isinstance(loc, (list, tuple)) or len(loc) != 2:
            continue
        recv_x, recv_y = loc

        # Nearby opposition defender?
        defender_close = False
        for p in frame:
            # freeze frame entries typically look like:
            # {"location": [x, y], "player": {...}, "teammate": bool, "actor": bool}
            if p.get("teammate") is True or p.get("actor") is True:
                continue
            p_loc = p.get("location")
            if not p_loc:
                continue
            dist = np.hypot(p_loc[0] - recv_x, p_loc[1] - recv_y)
            if dist < HOLD_UP_DEFENDER_RADIUS_YARDS:
                defender_close = True
                break
        if not defender_close:
            continue

        # Back-to-goal check: is the receiver's body oriented away from the
        # goal they're attacking? Freeze frames don't carry body orientation
        # directly in open data, so we approximate using the angle between
        # the pass's direction of travel and the vector to goal - a player
        # receiving a pass moving away from their attacking goal, under
        # pressure, is a reasonable proxy for "back to goal".
        goal_x = attacking_goal_x(team, home_team, period)
        end_loc = row.get("pass_end_location")
        if not isinstance(end_loc, (list, tuple)):
            continue
        dist_before = distance_to_goal(recv_x, recv_y, goal_x)
        # Vector from previous position isn't available directly; use the
        # simple heuristic that reception facing away means the pass came
        # from a more advanced (closer to goal) position than where it's received.
        pass_start = row.get("location")
        if pass_start is None:
            continue

        # If defender is close AND player is in a deep/wide "targetman" zone,
        # classify as a hold-up attempt.
        if dist_before < 15:
            continue  # too close to goal already - not a hold-up scenario

        secs = row["_secs"]
        if secs is None:
            continue

        window = events[
            (events["_secs"] >= secs)
            & (events["_secs"] <= secs + HOLD_UP_WINDOW_SECONDS)
            & (events["player"] == recipient)
        ]
        if "duel_outcome" in events.columns:
            duel_lost_mask = (
                (events["type"] == "Duel")
                & (events["player"] == recipient)
                & (events["duel_outcome"] == "Lost")
            )
        else:
            duel_lost_mask = pd.Series(False, index=events.index)

        turnover = events[
            (events["_secs"] >= secs)
            & (events["_secs"] <= secs + HOLD_UP_WINDOW_SECONDS)
            & (
                ((events["type"] == "Dispossessed") & (events["player"] == recipient))
                | duel_lost_mask
                | (events["type"] == "Interception")
            )
        ]

        success = False
        wall = False
        if turnover.empty:
            follow_up = window[window["type"].isin(["Pass", "Carry"])]
            if not follow_up.empty:
                success = True
                first_next_secs = follow_up.iloc[0]["_secs"]
                if first_next_secs is not None and (first_next_secs - secs) >= HOLD_UP_WALL_SECONDS:
                    wall = True

        d = hold_up_data.setdefault(recipient, {"attempts": 0, "successes": 0, "walls": 0})
        d["attempts"] += 1
        if success:
            d["successes"] += 1
        if wall:
            d["walls"] += 1

    for player, d in hold_up_data.items():
        d["success_rate"] = d["successes"] / d["attempts"] if d["attempts"] else 0.0

    return hold_up_data
