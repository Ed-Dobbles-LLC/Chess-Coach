"""Drill trainer endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sqlalchemy import func

from app.database import get_db
from app.services.drills import (
    get_next_drills, submit_drill_attempt, get_drill_stats, extract_drill_positions
)
from app.services.coaching import explain_move
from app.models.models import Game, MoveAnalysis, MoveClassification

router = APIRouter(prefix="/api/drills", tags=["drills"])


class DrillAttemptRequest(BaseModel):
    move_san: str


class ReplayRevealRequest(BaseModel):
    user_guess: str


@router.get("")
def get_drills(
    db: Session = Depends(get_db),
    count: int = Query(10, ge=1, le=50),
    game_phase: str | None = None,
    opening_eco: str | None = None,
):
    """Get next drill positions respecting spaced repetition schedule."""
    drills = get_next_drills(db, count=count, game_phase=game_phase, opening_eco=opening_eco)
    return {"drills": drills, "count": len(drills)}


@router.post("/{drill_id}/attempt")
def attempt_drill(drill_id: int, req: DrillAttemptRequest, db: Session = Depends(get_db)):
    """Submit a drill answer and get feedback."""
    result = submit_drill_attempt(db, drill_id, req.move_san)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    # If wrong, get Claude coaching explanation
    if not result["correct"] and result.get("game_id") and result.get("ply"):
        game = db.query(Game).filter(Game.id == result["game_id"]).first()
        if game:
            coaching = explain_move(db, game, result["ply"])
            result["coaching"] = coaching.get("coaching")

    return result


@router.get("/stats")
def drill_statistics(db: Session = Depends(get_db)):
    """Get drill performance statistics."""
    return get_drill_stats(db)


@router.post("/extract")
def extract_drills(
    db: Session = Depends(get_db),
    game_id: int | None = None,
    min_severity: str = Query("mistake", pattern="^(inaccuracy|mistake|blunder)$"),
):
    """Extract drill positions from analyzed games."""
    result = extract_drill_positions(db, game_id=game_id, min_classification=min_severity)
    return result


@router.get("/replay-positions")
def get_replay_positions(
    db: Session = Depends(get_db),
    count: int = Query(10, ge=1, le=50),
    phase: str | None = None,
    min_eval_delta: int = Query(50, ge=0),
):
    """Get positions from player's own games for 'What Would You Play?' mode.

    Returns positions where the player's move was suboptimal (mistake/blunder)
    or had significant eval delta. Does NOT include the answer — use the
    reveal endpoint for that.
    """
    query = db.query(MoveAnalysis).join(Game, Game.id == MoveAnalysis.game_id).filter(
        MoveAnalysis.is_player_move == True,
        MoveAnalysis.best_move_san.isnot(None),
        MoveAnalysis.fen_before.isnot(None),
    )

    # Filter by eval delta or classification
    query = query.filter(
        (MoveAnalysis.classification.in_(["mistake", "blunder"])) |
        (MoveAnalysis.eval_delta.isnot(None) & (func.abs(MoveAnalysis.eval_delta) > min_eval_delta))
    )

    if phase:
        query = query.filter(MoveAnalysis.game_phase == phase)

    # Order by most recent games first, then by eval delta magnitude
    from sqlalchemy import func
    positions = query.order_by(Game.end_time.desc()).limit(count * 3).all()

    # Shuffle and take 'count' positions
    import random
    random.shuffle(positions)
    selected = positions[:count]

    results = []
    for m in selected:
        game = db.query(Game).filter(Game.id == m.game_id).first()
        move_number = (m.ply + 1) // 2
        color = "white" if m.ply % 2 == 1 else "black"

        results.append({
            "position_id": f"game_{m.game_id}_ply_{m.ply}",
            "fen": m.fen_before,
            "game_id": m.game_id,
            "ply": m.ply,
            "move_number": move_number,
            "game_phase": m.game_phase.value if m.game_phase else None,
            "player_color": game.player_color.value if game else color,
            "classification": m.classification.value if m.classification else None,
            "eval_before": m.eval_before,
            "context": f"{game.opening_name or 'Unknown'}, move {move_number}, {'you' if game else 'player'} as {color}",
        })

    return {"positions": results, "count": len(results)}


@router.post("/replay-positions/{position_id}/reveal")
def reveal_replay_position(
    position_id: str,
    req: ReplayRevealRequest,
    db: Session = Depends(get_db),
):
    """Reveal the answer for a 'What Would You Play?' position.

    Compares the user's guess against the engine's best move and returns
    feedback including what the player actually played in the game.
    """
    # Parse position_id: "game_{game_id}_ply_{ply}"
    parts = position_id.split("_")
    if len(parts) < 4:
        raise HTTPException(status_code=400, detail="Invalid position_id format")

    try:
        game_id = int(parts[1])
        ply = int(parts[3])
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid position_id format")

    move = db.query(MoveAnalysis).filter(
        MoveAnalysis.game_id == game_id,
        MoveAnalysis.ply == ply,
    ).first()

    if not move:
        raise HTTPException(status_code=404, detail="Position not found")

    # Normalize move comparison (strip + and # for comparison)
    user_clean = req.user_guess.strip().rstrip("+#")
    best_clean = (move.best_move_san or "").strip().rstrip("+#")
    was_correct = user_clean == best_clean

    result = {
        "position_id": position_id,
        "correct_move": move.best_move_san,
        "was_correct": was_correct,
        "user_guess": req.user_guess,
        "what_player_played": move.move_played_san,
        "eval_before": move.eval_before,
        "eval_after": move.eval_after,
        "eval_delta": move.eval_delta,
        "classification": move.classification.value if move.classification else None,
    }

    # Get Claude coaching explanation for the correct move
    game = db.query(Game).filter(Game.id == game_id).first()
    if game:
        try:
            coaching = explain_move(db, game, ply)
            result["coaching"] = coaching.get("coaching")
        except Exception:
            result["coaching"] = None

    return result


@router.get("/warmup")
def get_warmup(db: Session = Depends(get_db)):
    """Generate a personalized pre-session warm-up drill set."""
    from app.services.warmup import get_warmup as _get_warmup
    return _get_warmup(db)
