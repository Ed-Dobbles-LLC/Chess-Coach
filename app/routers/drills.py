"""Drill trainer endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.drills import (
    get_next_drills, submit_drill_attempt, get_drill_stats, extract_drill_positions
)
from app.services.coaching import explain_move
from app.models.models import Game

router = APIRouter(prefix="/api/drills", tags=["drills"])


class DrillAttemptRequest(BaseModel):
    move_san: str


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
