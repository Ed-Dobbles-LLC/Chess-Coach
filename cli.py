"""CLI tools for Chess Coach batch operations.

Usage:
    python cli.py sync               — Sync games from Chess.com
    python cli.py analyze [--limit N] — Batch analyze unanalyzed blitz games
    python cli.py extract-drills      — Extract drill positions from analyzed games
    python cli.py tag-themes          — Retroactively tag tactical themes on existing drills
    python cli.py build-sessions      — Build play session records from game history
    python cli.py status              — Show database status
"""

import sys
import logging
import argparse
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def cmd_sync(args):
    from app.database import SessionLocal
    from app.services.chess_com import sync_games
    from sqlalchemy import func
    from app.models.models import Game

    db = SessionLocal()
    latest = db.query(func.max(Game.end_time)).scalar()
    since = int(latest.timestamp()) if latest else None

    logger.info(f"Syncing games (incremental since {latest})...")
    result = sync_games(db, since_timestamp=since)
    logger.info(f"Sync complete: {result['new_games']} new, {result['skipped']} skipped, {result['errors']} errors")
    db.close()


def cmd_analyze(args):
    from app.database import SessionLocal
    from app.models.models import Game, GameSummary, TimeClass
    from app.services.stockfish import analyze_game

    db = SessionLocal()

    # Find unanalyzed blitz games
    analyzed_ids = db.query(GameSummary.game_id).all()
    analyzed_set = {r[0] for r in analyzed_ids}

    games = db.query(Game).filter(
        Game.time_class == TimeClass.blitz,
    ).order_by(Game.end_time.desc()).all()

    unanalyzed = [g for g in games if g.id not in analyzed_set]
    if args.limit:
        unanalyzed = unanalyzed[:args.limit]

    total = len(unanalyzed)
    logger.info(f"Found {total} unanalyzed blitz games to process")

    completed = 0
    errors = 0
    start_time = time.time()

    for i, game in enumerate(unanalyzed):
        elapsed = time.time() - start_time
        rate = (i / elapsed * 60) if elapsed > 0 and i > 0 else 0
        eta = ((total - i) / rate) if rate > 0 else 0

        logger.info(
            f"[{i+1}/{total}] Game {game.id} | "
            f"{game.opening_name or '?'} | "
            f"{rate:.1f} games/min | "
            f"ETA: {eta:.0f} min"
        )

        try:
            result = analyze_game(db, game, depth=args.depth)
            if "error" in result:
                logger.warning(f"  Error: {result['error']}")
                errors += 1
            else:
                completed += 1
                logger.info(
                    f"  CPL: {result['avg_cpl']} | "
                    f"Blunders: {result['blunders']} | "
                    f"Mistakes: {result['mistakes']}"
                )
        except Exception as e:
            logger.error(f"  Failed: {e}")
            errors += 1

    total_time = time.time() - start_time
    logger.info(f"\nDone. {completed} completed, {errors} errors in {total_time/60:.1f} minutes")
    db.close()


def cmd_extract_drills(args):
    from app.database import SessionLocal
    from app.services.drills import extract_drill_positions

    db = SessionLocal()
    logger.info("Extracting drill positions from analyzed games...")
    result = extract_drill_positions(db, min_classification="mistake")
    logger.info(f"Created {result['created']} drills, {result['skipped']} already existed")
    db.close()


def cmd_tag_themes(args):
    from app.database import SessionLocal
    from app.models.models import DrillPosition
    from app.services.tactics import classify_drill_themes

    db = SessionLocal()

    if args.force:
        drills = db.query(DrillPosition).all()
    else:
        drills = db.query(DrillPosition).filter(
            DrillPosition.tactical_theme.is_(None)
        ).all()

    logger.info(f"Tagging themes on {len(drills)} drill positions...")
    tagged = 0

    for drill in drills:
        themes = classify_drill_themes(
            fen=drill.fen,
            best_move_san=drill.correct_move_san,
            player_move_san=drill.player_move_san,
            eval_delta=drill.eval_delta or 0,
            game_phase=drill.game_phase.value if drill.game_phase else "middlegame",
        )
        if themes:
            drill.tactical_theme = themes
            tagged += 1

    db.commit()
    logger.info(f"Tagged {tagged} drills with tactical themes")
    db.close()


def cmd_build_sessions(args):
    from app.database import SessionLocal, engine, Base
    # Import models to ensure PlaySession is registered before create_all
    from app.models import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    from app.services.sessions import build_play_sessions

    db = SessionLocal()
    logger.info("Building play session records from game history...")
    result = build_play_sessions(db)
    logger.info(f"Created {result['created']} sessions covering {result.get('total_games_grouped', 0)} games")
    db.close()


def cmd_status(args):
    from app.database import SessionLocal
    from app.models.models import Game, GameSummary, MoveAnalysis, DrillPosition, CoachingSession, PlaySession
    from sqlalchemy import func

    db = SessionLocal()

    total_games = db.query(Game).count()
    analyzed = db.query(GameSummary).count()
    total_moves = db.query(MoveAnalysis).count()
    drills = db.query(DrillPosition).count()
    drills_with_themes = db.query(DrillPosition).filter(DrillPosition.tactical_theme.isnot(None)).count()
    coaching = db.query(CoachingSession).count()
    try:
        play_sessions = db.query(PlaySession).count()
    except Exception:
        play_sessions = 0

    print(f"\n{'='*40}")
    print(f"  CHESS COACH DATABASE STATUS")
    print(f"{'='*40}")
    print(f"  Games:          {total_games:,}")
    print(f"  Analyzed:       {analyzed:,} ({analyzed/total_games*100:.1f}%)" if total_games else "  Analyzed: 0")
    print(f"  Move analyses:  {total_moves:,}")
    print(f"  Drill positions:{drills:,}")
    print(f"  Drills w/themes:{drills_with_themes:,}")
    print(f"  Coach sessions: {coaching:,}")
    print(f"  Play sessions:  {play_sessions:,}")
    print(f"{'='*40}\n")

    db.close()


def main():
    parser = argparse.ArgumentParser(description="Chess Coach CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("sync", help="Sync games from Chess.com")

    analyze_p = sub.add_parser("analyze", help="Batch Stockfish analysis")
    analyze_p.add_argument("--limit", type=int, default=None, help="Max games to analyze")
    analyze_p.add_argument("--depth", type=int, default=18, help="Stockfish depth")

    sub.add_parser("extract-drills", help="Extract drill positions")

    tag_p = sub.add_parser("tag-themes", help="Tag tactical themes on drills")
    tag_p.add_argument("--force", action="store_true", help="Re-tag all drills, not just untagged")

    sub.add_parser("build-sessions", help="Build play session records")

    sub.add_parser("status", help="Show database status")

    args = parser.parse_args()

    if args.command == "sync":
        cmd_sync(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "extract-drills":
        cmd_extract_drills(args)
    elif args.command == "tag-themes":
        cmd_tag_themes(args)
    elif args.command == "build-sessions":
        cmd_build_sessions(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
