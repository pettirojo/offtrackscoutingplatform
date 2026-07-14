# models.py
import sqlite3
from config import DATABASE_PATH


def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_columns(cur, table, columns):
    """
    Adds any of `columns` (name -> SQL type/default) that don't already
    exist on `table`. Lets older scouting.db files (created before per-90
    and xG metrics existed) pick up the new columns via ALTER TABLE instead
    of forcing a full --refresh rebuild.
    """
    cur.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    for col, decl in columns.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS player_aggregates (
            player_name TEXT NOT NULL,
            team_name TEXT,
            competition_id INTEGER NOT NULL,
            season_id INTEGER NOT NULL,
            matches_played INTEGER DEFAULT 0,
            usage_rate REAL DEFAULT 0,
            hold_up_attempts INTEGER DEFAULT 0,
            hold_up_successes INTEGER DEFAULT 0,
            hold_up_success_rate REAL DEFAULT 0,
            wall_count REAL DEFAULT 0,
            net_clutch_score REAL DEFAULT 0,
            avg_goal_difficulty REAL DEFAULT 0,
            avg_goal_importance REAL DEFAULT 0,
            weighted_goals REAL DEFAULT 0,
            weighted_misses REAL DEFAULT 0,
            shot_creating_actions REAL DEFAULT 0,
            goals INTEGER DEFAULT 0,
            PRIMARY KEY (player_name, competition_id, season_id)
        )
    ''')

    # Per-90 minutes and finishing-efficiency metrics.
    # NOTE: as of this update, `wall_count` and `shot_creating_actions` are
    # computed on a per-90-minutes basis rather than per-match - rows written
    # by an older version of data_processor.py hold per-match values until
    # you re-run `python run.py --refresh` (or --competition ... --refresh).
    _ensure_columns(cur, "player_aggregates", {
        "minutes_played": "REAL DEFAULT 0",
        "goals_per90": "REAL DEFAULT 0",
        "xg": "REAL DEFAULT 0",
        "finishing_efficiency": "REAL DEFAULT 0",
    })

    cur.execute('''
        CREATE TABLE IF NOT EXISTS team_structure (
            team_name TEXT NOT NULL,
            competition_id INTEGER NOT NULL,
            season_id INTEGER NOT NULL,
            top_usage_player TEXT,
            top_usage_rate REAL,
            second_usage_player TEXT,
            second_usage_rate REAL,
            heliocentricity REAL,
            top_creator TEXT,
            top_sca REAL,
            top_usage_sca REAL,
            creativity_gap REAL,
            PRIMARY KEY (team_name, competition_id, season_id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS player_leap (
            player_name TEXT NOT NULL,
            competition_id INTEGER NOT NULL,
            season1_id INTEGER NOT NULL,
            season2_id INTEGER NOT NULL,
            usage_1 REAL,
            usage_2 REAL,
            sca_1 REAL,
            sca_2 REAL,
            delta_usage REAL,
            delta_sca REAL,
            leap_category TEXT,
            PRIMARY KEY (player_name, competition_id, season1_id, season2_id)
        )
    ''')

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DATABASE_PATH}")
