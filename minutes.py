# minutes.py
"""
Engine-support module: minutes played per player per match.

Per-90 metrics (SCA/90, goals/90, wall actions/90) need actual time on the
pitch, not appearances - a substitute who plays 10 minutes across 10
matches has 10 "matches_played" but only ~100 minutes on the clock, and
per-match rates badly understate that player's output. StatsBomb doesn't
expose "minutes played" as a column directly, so this derives it from data
already present in every events pull (no extra API calls, no extra
network round-trips per match):

  - "Starting XI" events give each team's starting lineup (kickoff, minute 0).
  - "Substitution" events give sub-off / sub-on minutes.
  - The match's last event minute approximates full-time (including
    stoppage time), separately for however many periods were played.

Known limitation: a player sent off (red card) isn't detected as an "off"
event here, so their minutes will be slightly overstated. That's a rare
edge case relative to the substitute-undercounting problem this fixes, and
StatsBomb's own model output doesn't include a clean red-card-exit column
either, so treat this as a good approximation rather than an exact figure.
"""
import pandas as pd


def compute_minutes_played(events, home_team=None, away_team=None):
    """
    events: the full events DataFrame for one match (same one already
    fetched for usage/clutch).
    Returns {player_name: minutes_played} for that match. Players who
    never appear in a Starting XI or Substitution record are skipped
    rather than guessed at.
    """
    if events is None or events.empty or "minute" not in events.columns:
        return {}

    total_match_minutes = events["minute"].max()
    if pd.isna(total_match_minutes):
        return {}

    starters = set()
    starting_xi = events[events["type"] == "Starting XI"]
    for _, row in starting_xi.iterrows():
        tactics = row.get("tactics")
        if not isinstance(tactics, dict):
            continue
        for entry in tactics.get("lineup", []) or []:
            player = entry.get("player")
            name = player.get("name") if isinstance(player, dict) else None
            if name:
                starters.add(name)

    sub_off_minute = {}
    sub_on_minute = {}
    subs = events[events["type"] == "Substitution"]
    for _, row in subs.iterrows():
        off_player = row.get("player")
        on_player = row.get("substitution_replacement")
        minute = row.get("minute", 0)
        minute = 0 if pd.isna(minute) else minute
        if pd.notna(off_player):
            sub_off_minute[off_player] = minute
        if pd.notna(on_player):
            sub_on_minute[on_player] = minute

    all_players = set(events["player"].dropna().unique()) | starters | set(sub_on_minute)

    minutes = {}
    for player in all_players:
        if player in starters:
            start = 0
        elif player in sub_on_minute:
            start = sub_on_minute[player]
        else:
            # Has events but no Starting XI / Substitution record - rare
            # data gap. Skip rather than fabricate a minutes count.
            continue
        end = sub_off_minute.get(player, total_match_minutes)
        played = max(0.0, end - start)
        if played > 0:
            minutes[player] = played

    return minutes
