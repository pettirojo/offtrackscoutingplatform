# config.py
"""
Central configuration for the scouting platform.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------
# Where your custom CSV files live.
# Create this folder and place your matches/ and events/ subfolders.
# ------------------------------------------------------------
USER_DATA_DIR = os.path.join(BASE_DIR, "user_data")

# List your custom competitions here.
# You can invent any competition_id / season_id (e.g., 999, 1).
# The engine will look for matches/{competition_id}/{season_id}.csv
# inside USER_DATA_DIR.
COMPETITIONS = {
    "My Custom League 2024": {"competition_id": 999, "season_id": 1},
    "My Custom League 2025": {"competition_id": 999, "season_id": 2},
    "My Custom League 2026": {"competition_id": 999, "season_id": 3},
    # Add more as you have match CSVs.
}

DATABASE_PATH = os.path.join(BASE_DIR, "scouting.db")

# Analytical thresholds – tweak to taste
HOLD_UP_DEFENDER_RADIUS_YARDS = 3.0
HOLD_UP_WINDOW_SECONDS = 3.0
HOLD_UP_WALL_SECONDS = 2.0
CLUTCH_BIG_CHANCE_XG = 0.28

# 🔥 FIXED: Lowered threshold so players with even 1 goal appear in scatter
MIN_GOALS_FOR_SCATTER = 1   # was 3 – now your single-match scorers will show

# Hold-up detection requires 360 freeze‑frame data (not available in CSV).
# Leave this False to get all other metrics without errors.
ENABLE_HOLD_UP = False

# Flask
DEBUG = True
PORT = 5000