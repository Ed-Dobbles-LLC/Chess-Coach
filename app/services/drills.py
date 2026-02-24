"""Drill trainer service with spaced repetition.

Extracts blunder/mistake positions from analyzed games and serves them
as training drills with SM-2 based spaced repetition scheduling.
"""

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import (
    DrillPosition, MoveAnalysis, Game, GameSummary,
    MoveClassification, GamePhase
)
from app.services.tactics import classify_drill_themes

logger = logging.getLogger(__name__)

# SM-2 inspired intervals (days) based on consecutive correct answers
INTERVALS = [1, 3, 7, 14, 30, 60]


def extract_drill_positions(db: Session, game_id: Optional[int] = None,
                            min_classification: str = "mistake") -> dict:
    """
    Extract positions where the player made mistakes/blunders and create drill entries.

    Args:
        game_id: If provided, only extract from this game. Otherwise, all analyzed games.
        min_classification: Minimum severity to extract ('inaccuracy', 'mistake', 'blunder')
    """
    threshold_map = {
        "inaccuracy": [MoveClassification.inaccuracy, MoveClassification.mistake, MoveClassification.blunder],
        "mistake": [MoveClassification.mistake, MoveClassification.blunder],
        "blunder": [MoveClassification.blunder],
    }
    classifications = threshold_map.get(min_classification, [MoveClassification.mistake, MoveClassification.blunder])

    query = db.query(MoveAnalysis).filter(
        MoveAnalysis.is_player_move == True,
        MoveAnalysis.classification.in_(classifications),
        MoveAnalysis.best_move_san.isnot(None),
    )

    if game_id:
        query = query.filter(MoveAnalysis.game_id == game_id)

    analyses = query.all()

    created = 0
    skipped = 0

    for analysis in analyses:
        # Check if drill already exists
        existing = db.query(DrillPosition).filter(
            DrillPosition.game_id == analysis.game_id,
            DrillPosition.ply == analysis.ply,
        ).first()

        if existing:
            skipped += 1
            continue

        game = db.query(Game).filter(Game.id == analysis.game_id).first()

        # Detect tactical themes
        themes = classify_drill_themes(
            fen=analysis.fen_before,
            best_move_san=analysis.best_move_san,
            player_move_san=analysis.move_played_san,
            eval_delta=analysis.eval_delta or 0,
            game_phase=analysis.game_phase.value if analysis.game_phase else "middlegame",
        )

        drill = DrillPosition(
            game_id=analysis.game_id,
            ply=analysis.ply,
            fen=analysis.fen_before,
            correct_move_san=analysis.best_move_san,
            player_move_san=analysis.move_played_san,
            eval_delta=analysis.eval_delta,
            tactical_theme=themes if themes else None,
            game_phase=analysis.game_phase,
            opening_eco=game.eco if game else None,
            next_review_date=date.today(),
            difficulty_rating=min(abs(analysis.eval_delta or 0) / 100.0, 5.0),
        )
        db.add(drill)
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped}


def get_next_drills(db: Session, count: int = 10,
                    game_phase: Optional[str] = None,
                    opening_eco: Optional[str] = None) -> list[dict]:
    """
    Get the next drill positions for review, respecting spaced repetition schedule.
    Prioritizes overdue drills, then new drills, then upcoming drills.
    """
    today = date.today()

    query = db.query(DrillPosition).filter(
        DrillPosition.next_review_date <= today
    )

    if game_phase:
        query = query.filter(DrillPosition.game_phase == game_phase)
    if opening_eco:
        query = query.filter(DrillPosition.opening_eco == opening_eco)

    # Order: most overdue first, then by difficulty (harder first)
    drills = query.order_by(
        DrillPosition.next_review_date.asc(),
        DrillPosition.difficulty_rating.desc(),
    ).limit(count).all()

    results = []
    for d in drills:
        game = db.query(Game).filter(Game.id == d.game_id).first()
        results.append({
            "id": d.id,
            "fen": d.fen,
            "game_phase": d.game_phase.value if d.game_phase else None,
            "opening_eco": d.opening_eco,
            "tactical_theme": d.tactical_theme,
            "difficulty": d.difficulty_rating,
            "times_shown": d.times_shown,
            "times_correct": d.times_correct,
            "accuracy": round(d.times_correct / d.times_shown * 100, 1) if d.times_shown > 0 else None,
            "game_id": d.game_id,
            "opening_name": game.opening_name if game else None,
            "player_color": game.player_color.value if game else None,
        })

    return results


def submit_drill_attempt(db: Session, drill_id: int, move_san: str) -> dict:
    """
    Process a drill attempt. Returns whether correct and schedules next review.
    """
    drill = db.query(DrillPosition).filter(DrillPosition.id == drill_id).first()
    if not drill:
        return {"error": "Drill not found"}

    drill.times_shown += 1
    is_correct = move_san.strip() == drill.correct_move_san.strip()

    if is_correct:
        drill.times_correct += 1
        # SM-2 inspired scheduling: use accuracy AND total correct count together.
        # High accuracy + many correct = long interval. Low accuracy = short interval.
        accuracy = drill.times_correct / drill.times_shown
        if accuracy >= 0.8 and drill.times_correct >= 3:
            # Mastery track: advance through full interval schedule
            interval_idx = min(drill.times_correct - 1, len(INTERVALS) - 1)
        elif accuracy >= 0.6:
            # Partial mastery: cap at 7-day intervals
            interval_idx = min(drill.times_correct - 1, 2)  # Max: INTERVALS[2] = 7 days
        else:
            # Low accuracy despite some correct answers: keep reviewing frequently
            interval_idx = 0  # 1 day
        drill.next_review_date = date.today() + timedelta(days=INTERVALS[interval_idx])
    else:
        # Wrong answer: reset to review tomorrow
        drill.next_review_date = date.today() + timedelta(days=1)

    db.commit()

    return {
        "correct": is_correct,
        "your_move": move_san,
        "correct_move": drill.correct_move_san,
        "player_move_in_game": drill.player_move_san,
        "eval_delta": drill.eval_delta,
        "next_review": str(drill.next_review_date),
        "drill_accuracy": round(drill.times_correct / drill.times_shown * 100, 1) if drill.times_shown > 0 else 0,
        "fen": drill.fen,
        "game_id": drill.game_id,
        "ply": drill.ply,
    }


def get_drill_stats(db: Session) -> dict:
    """Get aggregate drill performance stats."""
    total = db.query(DrillPosition).count()
    if total == 0:
        return {"total_drills": 0}

    attempted = db.query(DrillPosition).filter(DrillPosition.times_shown > 0).count()
    total_shown = db.query(func.sum(DrillPosition.times_shown)).scalar() or 0
    total_correct = db.query(func.sum(DrillPosition.times_correct)).scalar() or 0

    mastered = db.query(DrillPosition).filter(
        DrillPosition.times_correct >= 3,
        DrillPosition.times_shown > 0,
    ).count()

    due_today = db.query(DrillPosition).filter(
        DrillPosition.next_review_date <= date.today()
    ).count()

    # Breakdown by game phase
    phase_stats = {}
    for phase in ["opening", "middlegame", "endgame"]:
        phase_drills = db.query(DrillPosition).filter(DrillPosition.game_phase == phase)
        phase_total = phase_drills.count()
        phase_correct = db.query(func.sum(DrillPosition.times_correct)).filter(
            DrillPosition.game_phase == phase
        ).scalar() or 0
        phase_shown = db.query(func.sum(DrillPosition.times_shown)).filter(
            DrillPosition.game_phase == phase
        ).scalar() or 0
        phase_stats[phase] = {
            "total": phase_total,
            "accuracy": round(phase_correct / phase_shown * 100, 1) if phase_shown > 0 else None,
        }

    return {
        "total_drills": total,
        "attempted": attempted,
        "mastered": mastered,
        "due_today": due_today,
        "overall_accuracy": round(total_correct / total_shown * 100, 1) if total_shown > 0 else None,
        "total_attempts": total_shown,
        "by_phase": phase_stats,
    }
