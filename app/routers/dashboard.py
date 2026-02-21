"""Dashboard and aggregate stats endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, case, extract

from app.database import get_db
from app.models.models import Game, GameSummary, MoveAnalysis, GameResult, PlayerColor

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    """Aggregated stats for dashboard view."""
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

    return {
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
