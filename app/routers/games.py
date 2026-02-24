"""Game management endpoints."""

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.models import Game, GameSummary, TimeClass
from app.services.chess_com import sync_games

router = APIRouter(prefix="/api/games", tags=["games"])


@router.get("")
def list_games(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    time_class: str | None = None,
    result: str | None = None,
    opening: str | None = None,
    analyzed: bool | None = None,
):
    """List games with pagination and filters."""
    query = db.query(Game)

    if time_class:
        query = query.filter(Game.time_class == time_class)
    if result:
        query = query.filter(Game.result == result)
    if opening:
        query = query.filter(Game.opening_name.ilike(f"%{opening}%"))
    if analyzed is not None:
        analyzed_ids = db.query(GameSummary.game_id)
        if analyzed:
            query = query.filter(Game.id.in_(analyzed_ids))
        else:
            query = query.filter(~Game.id.in_(analyzed_ids))

    total = query.count()
    games = query.order_by(Game.end_time.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    # Batch-fetch analyzed game IDs to avoid N+1 queries
    game_ids = [g.id for g in games]
    analyzed_game_ids = set()
    if game_ids:
        analyzed_game_ids = {
            row[0] for row in db.query(GameSummary.game_id).filter(
                GameSummary.game_id.in_(game_ids)
            ).all()
        }

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "games": [
            {
                "id": g.id,
                "chess_com_id": g.chess_com_id,
                "player_color": g.player_color.value,
                "result": g.result.value,
                "result_type": g.result_type,
                "time_class": g.time_class.value if g.time_class else None,
                "opening_name": g.opening_name,
                "eco": g.eco,
                "player_rating": g.player_rating,
                "opponent_rating": g.opponent_rating,
                "total_moves": g.total_moves,
                "end_time": g.end_time.isoformat() if g.end_time else None,
                "has_analysis": g.id in analyzed_game_ids,
            }
            for g in games
        ],
    }


@router.get("/{game_id}")
def get_game(game_id: int, db: Session = Depends(get_db)):
    """Get a single game with full details and analysis."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    summary = db.query(GameSummary).filter(GameSummary.game_id == game_id).first()

    return {
        "id": game.id,
        "chess_com_id": game.chess_com_id,
        "pgn": game.pgn,
        "white_username": game.white_username,
        "black_username": game.black_username,
        "player_color": game.player_color.value,
        "result": game.result.value,
        "result_type": game.result_type,
        "time_control": game.time_control,
        "time_class": game.time_class.value if game.time_class else None,
        "rated": game.rated,
        "eco": game.eco,
        "opening_name": game.opening_name,
        "end_time": game.end_time.isoformat() if game.end_time else None,
        "white_rating": game.white_rating,
        "black_rating": game.black_rating,
        "player_rating": game.player_rating,
        "opponent_rating": game.opponent_rating,
        "total_moves": game.total_moves,
        "summary": {
            "avg_centipawn_loss": summary.avg_centipawn_loss,
            "blunder_count": summary.blunder_count,
            "mistake_count": summary.mistake_count,
            "inaccuracy_count": summary.inaccuracy_count,
            "opening_accuracy": summary.opening_accuracy,
            "middlegame_accuracy": summary.middlegame_accuracy,
            "endgame_accuracy": summary.endgame_accuracy,
            "critical_moments": summary.critical_moments,
            "coaching_notes": summary.coaching_notes,
        } if summary else None,
    }


@router.post("/sync")
def trigger_sync(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Trigger Chess.com game import (incremental)."""
    # Get the most recent game timestamp for incremental sync
    latest = db.query(func.max(Game.end_time)).scalar()
    since = int(latest.timestamp()) if latest else None

    result = sync_games(db, since_timestamp=since)
    return result
