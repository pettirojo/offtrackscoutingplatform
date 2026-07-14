# app.py
import os
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from config import COMPETITIONS, MIN_GOALS_FOR_SCATTER
from models import get_db_connection, init_db

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Only these files are ever served over HTTP - the rest of the folder
# (source code, the SQLite database) stays off-limits even though
# everything lives in one directory for convenience.
FRONTEND_FILES = {"index.html", "style.css", "script.js"}

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    return send_from_directory(APP_DIR, "index.html")


@app.route("/<path:filename>")
def frontend_file(filename):
    if filename not in FRONTEND_FILES:
        return jsonify({"error": "not found"}), 404
    return send_from_directory(APP_DIR, filename)


@app.route("/api/competitions", methods=["GET"])
def competitions():
    """So the frontend doesn't need to hardcode competition/season IDs."""
    return jsonify([
        {"label": label, **ids} for label, ids in COMPETITIONS.items()
    ])


@app.route("/api/player/<player_name>", methods=["GET"])
def player_profile(player_name):
    competition_id = request.args.get("competition_id", type=int)
    season_id = request.args.get("season_id", type=int)

    conn = get_db_connection()
    cur = conn.cursor()

    query = "SELECT * FROM player_aggregates WHERE player_name LIKE ?"
    params = [f"%{player_name}%"]
    if competition_id and season_id:
        query += " AND competition_id = ? AND season_id = ?"
        params.extend([competition_id, season_id])
    query += " LIMIT 1"

    cur.execute(query, params)
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": f"No player matching '{player_name}' found. "
                                  f"Have you run data_processor.py yet?"}), 404
    return jsonify(dict(row))


@app.route("/api/players", methods=["GET"])
def players():
    """Return all players for a competition/season with all aggregate stats."""
    competition_id = request.args.get("competition_id", type=int)
    season_id = request.args.get("season_id", type=int)
    if not competition_id or not season_id:
        return jsonify({"error": "competition_id and season_id are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT player_name, team_name, matches_played, minutes_played, goals,
               goals_per90, xg, finishing_efficiency,
               usage_rate, hold_up_success_rate, net_clutch_score,
               shot_creating_actions, avg_goal_difficulty, avg_goal_importance,
               weighted_goals, weighted_misses, wall_count
        FROM player_aggregates
        WHERE competition_id = ? AND season_id = ?
        ORDER BY player_name
    ''', (competition_id, season_id))
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/league_scatter", methods=["GET"])
def league_scatter():
    competition_id = request.args.get("competition_id", type=int)
    season_id = request.args.get("season_id", type=int)
    if not competition_id or not season_id:
        return jsonify({"error": "competition_id and season_id are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT player_name, team_name, avg_goal_difficulty, avg_goal_importance,
               net_clutch_score, usage_rate, goals, xg, finishing_efficiency
        FROM player_aggregates
        WHERE competition_id = ? AND season_id = ? AND goals >= ?
        ORDER BY net_clutch_score DESC
    ''', (competition_id, season_id, MIN_GOALS_FOR_SCATTER))
    rows = cur.fetchall()
    conn.close()

    return jsonify([{
        "player": r["player_name"], "team": r["team_name"],
        "avg_difficulty": r["avg_goal_difficulty"], "avg_importance": r["avg_goal_importance"],
        "net_clutch": r["net_clutch_score"], "usage_rate": r["usage_rate"], "goals": r["goals"],
        "xg": r["xg"], "finishing_efficiency": r["finishing_efficiency"],
    } for r in rows])


@app.route("/api/team_structure", methods=["GET"])
def team_structure():
    team_name = request.args.get("team")
    competition_id = request.args.get("competition_id", type=int)
    season_id = request.args.get("season_id", type=int)
    if not competition_id or not season_id:
        return jsonify({"error": "competition_id and season_id are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    query = "SELECT * FROM team_structure WHERE competition_id = ? AND season_id = ?"
    params = [competition_id, season_id]
    if team_name:
        query += " AND team_name = ?"
        params.append(team_name)
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/player_leap", methods=["GET"])
def player_leap():
    competition_id = request.args.get("competition_id", type=int)
    season1 = request.args.get("season1", type=int)
    season2 = request.args.get("season2", type=int)
    if not all([competition_id, season1, season2]):
        return jsonify({"error": "competition_id, season1 and season2 are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT * FROM player_leap
        WHERE competition_id = ? AND season1_id = ? AND season2_id = ?
    ''', (competition_id, season1, season2))
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", debug=False, port=port)
