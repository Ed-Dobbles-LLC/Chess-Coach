"""Dashboard and aggregate stats endpoints."""

import io
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, extract

import chess.pgn

from app.database import get_db
from app.models.models import Game, GameSummary, MoveAnalysis, GameResult, PlayerColor, DrillPosition

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Simple in-memory cache for expensive dashboard queries
_cache = {}
_cache_ttl = 300  # 5 minutes

def _cached(key, ttl=_cache_ttl):
    """Decorator-less cache check. Returns (hit, value)."""
    import time
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < ttl:
        return True, entry[1]
    return False, None

def _set_cache(key, value):
    import time
    _cache[key] = (time.time(), value)


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    """Aggregated stats for dashboard view."""
    hit, cached = _cached("dashboard_summary")
    if hit:
        return cached

    total_games = db.query(Game).count()
    analyzed_games = db.query(GameSummary).count()

    wins = db.query(Game).filter(Game.result == GameResult.win).count()
    losses = db.query(Game).filter(Game.result == GameResult.loss).count()
    draws = db.query(Game).filter(Game.result == GameResult.draw).count()

    # Rating trend (last 90 days of blitz)
    from datetime import datetime, timedelta, timezone
    ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)
    recent_games = db.query(
        Game.end_time, Game.player_rating, Game.result
    ).filter(
        Game.time_class == "blitz",
        Game.end_time >= ninety_days_ago,
    ).order_by(Game.end_time).all()

    rating_trend = [
        {
            "date": g.end_time.isoformat() if g.end_time else None,
            "rating": g.player_rating,
            "result": g.result.value,
        }
        for g in recent_games
    ]

    # Avg CPL from analyzed games
    avg_cpl = db.query(func.avg(GameSummary.avg_centipawn_loss)).scalar()
    avg_blunders = db.query(func.avg(GameSummary.blunder_count)).scalar()

    # Time class breakdown
    time_class_stats = db.query(
        Game.time_class,
        func.count(Game.id),
        func.avg(case((Game.result == "win", 1.0), else_=0.0)),
    ).group_by(Game.time_class).all()

    result = {
        "total_games": total_games,
        "analyzed_games": analyzed_games,
        "record": {"wins": wins, "losses": losses, "draws": draws},
        "win_rate": round(wins / total_games * 100, 1) if total_games > 0 else 0,
        "avg_cpl": round(avg_cpl, 1) if avg_cpl else None,
        "avg_blunders_per_game": round(avg_blunders, 2) if avg_blunders else None,
        "rating_trend": rating_trend,
        "by_time_class": [
            {
                "time_class": tc.value if tc else "unknown",
                "games": count,
                "win_rate": round(wr * 100, 1) if wr else 0,
            }
            for tc, count, wr in time_class_stats
        ],
    }
    _set_cache("dashboard_summary", result)
    return result


@router.get("/openings")
def opening_stats(db: Session = Depends(get_db)):
    """Opening repertoire stats."""
    stats = db.query(
        Game.opening_name,
        Game.eco,
        func.count(Game.id).label("games"),
        func.avg(case((Game.result == "win", 1.0), else_=0.0)).label("win_rate"),
        func.avg(case(
            (Game.player_color == "white", 1.0),
            else_=0.0
        )).label("pct_white"),
    ).filter(
        Game.opening_name.isnot(None),
    ).group_by(
        Game.opening_name, Game.eco
    ).having(
        func.count(Game.id) >= 3
    ).order_by(func.count(Game.id).desc()).limit(30).all()

    results = []
    for s in stats:
        # Get avg CPL for games with this opening that have been analyzed
        avg_cpl = db.query(func.avg(GameSummary.avg_centipawn_loss)).join(
            Game, Game.id == GameSummary.game_id
        ).filter(
            Game.opening_name == s.opening_name
        ).scalar()

        results.append({
            "opening_name": s.opening_name,
            "eco": s.eco,
            "games": s.games,
            "win_rate": round(s.win_rate * 100, 1),
            "pct_white": round(s.pct_white * 100, 1),
            "avg_cpl": round(avg_cpl, 1) if avg_cpl else None,
        })

    return {"openings": results}


@router.get("/patterns")
def pattern_stats(db: Session = Depends(get_db)):
    """Weakness/strength pattern data."""
    # Phase performance
    phase_stats = {}
    for phase in ["opening", "middlegame", "endgame"]:
        avg = db.query(func.avg(
            getattr(GameSummary, f"{phase}_accuracy")
        )).scalar()
        phase_stats[phase] = round(avg, 1) if avg else None

    # Color performance
    color_stats = {}
    for color in [PlayerColor.white, PlayerColor.black]:
        games = db.query(Game).filter(Game.player_color == color)
        total = games.count()
        wins = games.filter(Game.result == GameResult.win).count()
        avg_cpl = db.query(func.avg(GameSummary.avg_centipawn_loss)).join(
            Game, Game.id == GameSummary.game_id
        ).filter(Game.player_color == color).scalar()

        color_stats[color.value] = {
            "games": total,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "avg_cpl": round(avg_cpl, 1) if avg_cpl else None,
        }

    # Common blunder classifications by game phase
    blunder_by_phase = db.query(
        MoveAnalysis.game_phase,
        func.count(MoveAnalysis.id),
    ).filter(
        MoveAnalysis.is_player_move == True,
        MoveAnalysis.classification.in_(["mistake", "blunder"]),
    ).group_by(MoveAnalysis.game_phase).all()

    return {
        "phase_performance": phase_stats,
        "color_performance": color_stats,
        "mistakes_by_phase": {
            p.value if p else "unknown": c for p, c in blunder_by_phase
        },
    }


@router.get("/time-analysis")
def time_analysis(db: Session = Depends(get_db)):
    """Time-of-day and day-of-week performance breakdown."""
    # Hour of day
    hourly = db.query(
        extract("hour", Game.end_time).label("hour"),
        func.count(Game.id),
        func.avg(case((Game.result == "win", 1.0), else_=0.0)),
    ).filter(
        Game.time_class == "blitz",
    ).group_by("hour").order_by("hour").all()

    # Day of week (0=Sunday in extract, but varies by DB)
    daily = db.query(
        extract("dow", Game.end_time).label("dow"),
        func.count(Game.id),
        func.avg(case((Game.result == "win", 1.0), else_=0.0)),
    ).filter(
        Game.time_class == "blitz",
    ).group_by("dow").order_by("dow").all()

    day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    return {
        "by_hour": [
            {"hour": int(h), "games": c, "win_rate": round(wr * 100, 1)}
            for h, c, wr in hourly
        ],
        "by_day": [
            {
                "day": day_names[int(d)] if d is not None and int(d) < 7 else "Unknown",
                "games": c,
                "win_rate": round(wr * 100, 1),
            }
            for d, c, wr in daily
        ],
    }


@router.get("/opening-book/{eco}")
def opening_book(eco: str, db: Session = Depends(get_db)):
    """Opening book view: theory, your stats, and your deviations for a specific opening."""
    hit, cached = _cached(f"opening_book_{eco}")
    if hit:
        return cached

    # Get all games with this ECO code
    games = db.query(Game).filter(Game.eco == eco).order_by(Game.end_time.desc()).all()
    if not games:
        return {"error": "No games found with this ECO code"}

    opening_name = games[0].opening_name
    total = len(games)
    wins = sum(1 for g in games if g.result == GameResult.win)
    losses = sum(1 for g in games if g.result == GameResult.loss)
    draws = total - wins - losses

    # Parse mainline moves from all games to find the "book" (most common moves)
    move_trees = {}  # {move_number: {san_move: count}}
    for game in games:
        try:
            pgn_game = chess.pgn.read_game(io.StringIO(game.pgn))
            if not pgn_game:
                continue
            board = pgn_game.board()
            for i, move in enumerate(pgn_game.mainline_moves()):
                if i >= 20:  # First 10 full moves
                    break
                san = board.san(move)
                ply = i + 1
                if ply not in move_trees:
                    move_trees[ply] = {}
                move_trees[ply][san] = move_trees[ply].get(san, 0) + 1
                board.push(move)
        except Exception:
            continue

    # Build the "book" — most common move at each ply
    book_moves = []
    for ply in sorted(move_trees.keys()):
        moves = move_trees[ply]
        sorted_moves = sorted(moves.items(), key=lambda x: -x[1])
        main_move = sorted_moves[0]
        alternatives = sorted_moves[1:4]  # Top 3 alternatives
        book_moves.append({
            "ply": ply,
            "move_number": (ply + 1) // 2,
            "color": "white" if ply % 2 == 1 else "black",
            "main_move": main_move[0],
            "main_count": main_move[1],
            "main_pct": round(main_move[1] / total * 100, 1),
            "alternatives": [
                {"move": m, "count": c, "pct": round(c / total * 100, 1)}
                for m, c in alternatives
            ],
        })

    # Get analyzed game stats
    avg_cpl = db.query(func.avg(GameSummary.avg_centipawn_loss)).join(
        Game, Game.id == GameSummary.game_id
    ).filter(Game.eco == eco).scalar()

    # Color breakdown
    as_white = sum(1 for g in games if g.player_color.value == "white")
    white_wins = sum(1 for g in games if g.player_color.value == "white" and g.result == GameResult.win)
    as_black = total - as_white
    black_wins = sum(1 for g in games if g.player_color.value == "black" and g.result == GameResult.win)

    # Drill count for this opening
    drill_count = db.query(DrillPosition).filter(DrillPosition.opening_eco == eco).count()

    result = {
        "eco": eco,
        "opening_name": opening_name,
        "total_games": total,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
        "avg_cpl": round(avg_cpl, 1) if avg_cpl else None,
        "as_white": {"games": as_white, "win_rate": round(white_wins / as_white * 100, 1) if as_white > 0 else 0},
        "as_black": {"games": as_black, "win_rate": round(black_wins / as_black * 100, 1) if as_black > 0 else 0},
        "book_moves": book_moves,
        "drill_count": drill_count,
    }
    _set_cache(f"opening_book_{eco}", result)
    return result


@router.get("/time-management")
def time_management(db: Session = Depends(get_db)):
    """Time management analytics — time-vs-accuracy stats from clock data."""
    from app.services.time_management import get_time_management_stats
    return get_time_management_stats(db)


@router.get("/progress")
def progress_report(weeks: int = Query(default=12, ge=1, le=52), db: Session = Depends(get_db)):
    """Weekly progress snapshots and trend analysis."""
    from app.services.progress import get_progress
    return get_progress(db, weeks)


@router.get("/sessions")
def sessions_summary(db: Session = Depends(get_db)):
    """Playing session analysis with tilt detection."""
    hit, cached = _cached("sessions_summary")
    if hit:
        return cached

    from app.services.sessions import get_sessions_summary
    result = get_sessions_summary(db)
    if "error" not in result:
        _set_cache("sessions_summary", result)
    return result


@router.get("/sessions/{date}")
def session_detail(date: str, db: Session = Depends(get_db)):
    """Detailed game-by-game data for a session on a specific date."""
    from app.services.sessions import get_session_detail
    return get_session_detail(db, date)
