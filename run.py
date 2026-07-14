#!/usr/bin/env python3
"""
Single-command launcher for the scouting platform.

    python run.py                          # build data (first run only) + serve
    python run.py --refresh                # re-pull and rebuild all data, then serve
    python run.py --competition "My Custom League 2024"   # only process one competition
    python run.py --serve-only             # skip data building entirely
    python run.py --leap                   # (re)populate player_leap and exit
"""
import argparse
import os
import sys
import webbrowser
from threading import Timer

from config import COMPETITIONS, DATABASE_PATH, PORT
from models import init_db
from data_processor import process_league, populate_all_leaps


def build_data(competition_label=None):
    init_db()
    if competition_label:
        if competition_label not in COMPETITIONS:
            print(f"Unknown competition '{competition_label}'. Options: {list(COMPETITIONS.keys())}")
            sys.exit(1)
        cfg = COMPETITIONS[competition_label]
        process_league(cfg["competition_id"], cfg["season_id"], label=competition_label)
    else:
        for label, cfg in COMPETITIONS.items():
            process_league(cfg["competition_id"], cfg["season_id"], label=label)
        # Only meaningful once 2+ seasons of the same competition are configured.
        populate_all_leaps()


def main():
    parser = argparse.ArgumentParser(description="Build data (if needed) and run the scouting platform.")
    parser.add_argument("--refresh", action="store_true", help="Re-download and rebuild all data even if scouting.db already exists.")
    parser.add_argument("--competition", type=str, default=None, help="Only process this competition (see config.py for labels).")
    parser.add_argument("--serve-only", action="store_true", help="Skip data building, just start the server.")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab.")
    parser.add_argument("--leap", action="store_true",
                         help="(Re)populate player_leap from whatever seasons are already in "
                              "scouting.db, then exit without starting the server.")
    args = parser.parse_args()

    db_exists = os.path.exists(DATABASE_PATH)

    if args.leap:
        if not db_exists:
            print("No scouting.db found yet - run `python run.py` first to build some data.")
            sys.exit(1)
        init_db()
        populate_all_leaps()
        return

    if args.serve_only:
        if not db_exists:
            print("No scouting.db found yet - the dashboard will be empty until you run "
                  "`python run.py` without --serve-only at least once.")
    elif args.refresh or not db_exists:
        if not db_exists:
            print("No database found - building it now. This will read your CSV files.\n")
        build_data(args.competition)
    else:
        print(f"Using existing {DATABASE_PATH}. Pass --refresh to rebuild, "
              f"or --competition <name> to add another competition.\n")

    # Ensure schema is up-to-date (adds missing columns)
    #init_db()

    # Import app AFTER data building so a slow first-run doesn't hold a port open pointlessly.
    from app import app

    url = f"http://localhost:{PORT}"
    if not args.no_browser:
        Timer(1.2, lambda: webbrowser.open(url)).start()

    print(f"\nServing Dossier at {url}  (Ctrl+C to stop)\n")
    app.run(debug=False, port=PORT, use_reloader=False)


if __name__ == "__main__":
    main()
