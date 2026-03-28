"""Claude coaching endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Game, CoachingSession
from app.services.coaching import explain_move, review_game, generate_pattern_diagnosis, generate_walkthrough
from app.services.behavior import detect_all_patterns

router = APIRouter(prefix="/api/coach", tags=["coaching"])


class MoveExplainRequest(BaseModel):
    game_id: int
    ply: int


@router.post("/game-review/{game_id}")
def coach_game_review(game_id: int, db: Session = Depends(get_db)):
    """Generate Claude coaching review for a game."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    result = review_game(db, game)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/move-explain")
def coach_move_explain(req: MoveExplainRequest, db: Session = Depends(get_db)):
    """Explain a single move with Claude coaching."""
    game = db.query(Game).filter(Game.id == req.game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    result = explain_move(db, game, req.ply)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/walkthrough/{game_id}")
def coach_walkthrough(game_id: int, db: Session = Depends(get_db)):
    """Generate an interactive game walkthrough with commentary at inflection points."""
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    result = generate_walkthrough(db, game)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/behavioral-analysis")
def coach_behavioral_analysis(db: Session = Depends(get_db)):
    """Run all behavioral pattern detectors and generate Claude narrative."""
    from app.services.coaching import generate_behavioral_narrative
    patterns = detect_all_patterns(db)
    result = generate_behavioral_narrative(db, patterns)
    return result


@router.post("/diagnose")
def coach_diagnose(db: Session = Depends(get_db)):
    """Generate full pattern diagnosis using Claude Opus."""
    result = generate_pattern_diagnosis(db)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/monthly-report")
def coach_monthly_report(db: Session = Depends(get_db)):
    """Generate narrative monthly progress report using Claude Opus."""
    from app.services.progress import get_progress
    from app.services.coaching import generate_monthly_report
    progress = get_progress(db, weeks=8)
    if "error" in progress:
        raise HTTPException(status_code=400, detail=progress["error"])

    result = generate_monthly_report(db, progress)
    return result


@router.get("/sessions")
def list_coaching_sessions(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    session_type: str | None = None,
):
    """List past coaching sessions."""
    query = db.query(CoachingSession)

    if session_type:
        query = query.filter(CoachingSession.session_type == session_type)

    total = query.count()
    sessions = query.order_by(CoachingSession.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "sessions": [
            {
                "id": s.id,
                "game_id": s.game_id,
                "session_type": s.session_type.value,
                "response": s.response,
                "model_used": s.model_used,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sessions
        ],
    }
