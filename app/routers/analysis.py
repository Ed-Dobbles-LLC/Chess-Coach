"""Stockfish analysis endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Game, MoveAnalysis, GameSummary, User
from app.services.stockfish import analyze_game, batch_analyze
from app.services.auth import get_current_user

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class BatchRequest(BaseModel):
    game_ids: list[int] | None = None
    limit: int = 200
    time_class: str = "blitz"
    depth: int | None = None


@router.post("/batch")
def trigger_batch_analysis(req: BatchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Trigger Stockfish batch analysis on games."""
    result = batch_analyze(
        db,
        game_ids=req.game_ids,
        limit=req.limit,
        time_class_filter=req.time_class,
        depth=req.depth,
    )
    return result


@router.get("/status")
def analysis_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Check how many games have been analyzed vs total."""
    total_games = db.query(Game).count()
    analyzed = db.query(GameSummary).count()
    return {
        "total_games": total_games,
        "analyzed": analyzed,
        "remaining": total_games - analyzed,
        "percent_complete": round(analyzed / total_games * 100, 1) if total_games > 0 else 0,
    }


@router.get("/game/{game_id}")
def get_game_analysis(
    game_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    player_only: bool = Query(False, description="Only return player's moves"),
):
    """Get move-by-move analysis for a game."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    query = db.query(MoveAnalysis).filter(MoveAnalysis.game_id == game_id)
    if player_only:
        query = query.filter(MoveAnalysis.is_player_move == True)

    moves = query.order_by(MoveAnalysis.ply).all()

    if not moves:
        raise HTTPException(status_code=404, detail="No analysis found for this game")

    return {
        "game_id": game_id,
        "player_color": game.player_color.value,
        "total_moves": len(moves),
        "moves": [
            {
                "ply": m.ply,
                "move_number": m.move_number,
                "color": m.color.value,
                "is_player_move": m.is_player_move,
                "fen_before": m.fen_before,
                "move_played": m.move_played,
                "move_played_san": m.move_played_san,
                "best_move": m.best_move,
                "best_move_san": m.best_move_san,
                "eval_before": m.eval_before,
                "eval_after": m.eval_after,
                "eval_delta": m.eval_delta,
                "classification": m.classification.value if m.classification else None,
                "game_phase": m.game_phase.value if m.game_phase else None,
                "top_3_lines": m.top_3_lines,
            }
            for m in moves
        ],
    }
