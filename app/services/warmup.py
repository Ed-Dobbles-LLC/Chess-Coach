"""Pre-session warm-up generator.

Creates a personalized 5-drill warm-up set based on recent weaknesses.
"""

import logging
from datetime import date, timedelta
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import (
    Game, GameSummary, MoveAnalysis, DrillPosition,
    MoveClassification, GamePhase, GameResult,
)

logger = logging.getLogger(__name__)


def get_warmup(db: Session) -> dict:
    """Generate a personalized warm-up drill set based on recent weaknesses."""

    # Step 1: Look at the last 20 analyzed games
    recent_summaries = db.query(GameSummary).join(
        Game, Game.id == GameSummary.game_id
    ).filter(
        Game.time_class == "blitz",
    ).order_by(Game.end_time.desc()).limit(20).all()

    if not recent_summaries:
        return _fallback_warmup(db)

    # Step 2: Identify top 3 weakness areas
    weaknesses = _identify_weaknesses(db, recent_summaries)

    # Step 3: Pull drills targeting those weaknesses
    drills = _select_drills(db, weaknesses)

    # Step 4: Supplement with replay positions if needed
    if len(drills) < 5:
        drills = _supplement_with_replay(db, drills, 5 - len(drills))

    # Build focus description
    focus_parts = []
    for w in weaknesses[:3]:
        focus_parts.append(w["description"])
    focus_text = (
        f"Your last 20 games show {focus_parts[0]} is your biggest leak. "
        + (f"{len(drills)} drills target your weaknesses." if drills else "")
    ) if focus_parts else "General warm-up positions."

    return {
        "warmup_focus": focus_text,
        "estimated_time": "5 minutes",
        "weakness_areas": weaknesses[:3],
        "drills": [
            {
                "id": d.id,
                "fen": d.fen,
                "type": "tactical_drill",
                "theme": d.tactical_theme,
                "game_phase": d.game_phase.value if d.game_phase else None,
                "difficulty": d.difficulty_rating,
                "your_accuracy": f"{d.times_correct}/{d.times_shown}" if d.times_shown > 0 else "new",
                "opening_eco": d.opening_eco,
            }
            for d in drills
        ],
    }


def _identify_weaknesses(db: Session, summaries: list[GameSummary]) -> list[dict]:
    """Identify top weakness areas from recent games."""
    weaknesses = []

    # Weakness 1: Highest CPL phase
    phase_cpls = {
        "opening": [],
        "middlegame": [],
        "endgame": [],
    }
    for s in summaries:
        if s.opening_accuracy is not None:
            phase_cpls["opening"].append(s.opening_accuracy)
        if s.middlegame_accuracy is not None:
            phase_cpls["middlegame"].append(s.middlegame_accuracy)
        if s.endgame_accuracy is not None:
            phase_cpls["endgame"].append(s.endgame_accuracy)

    phase_avgs = {}
    for phase, cpls in phase_cpls.items():
        if cpls:
            phase_avgs[phase] = sum(cpls) / len(cpls)

    if phase_avgs:
        worst_phase = max(phase_avgs, key=phase_avgs.get)
        weaknesses.append({
            "type": "phase",
            "phase": worst_phase,
            "value": round(phase_avgs[worst_phase], 1),
            "description": f"{worst_phase} play (avg CPL: {phase_avgs[worst_phase]:.0f})",
        })

    # Weakness 2: Most frequent blunder classification
    game_ids = [s.game_id for s in summaries]
    blunder_moves = db.query(MoveAnalysis).filter(
        MoveAnalysis.game_id.in_(game_ids),
        MoveAnalysis.is_player_move == True,
        MoveAnalysis.classification.in_(["mistake", "blunder"]),
    ).all()

    phase_blunders = defaultdict(int)
    for m in blunder_moves:
        phase = m.game_phase.value if m.game_phase else "unknown"
        phase_blunders[phase] += 1

    if phase_blunders:
        worst_blunder_phase = max(phase_blunders, key=phase_blunders.get)
        weaknesses.append({
            "type": "blunder_phase",
            "phase": worst_blunder_phase,
            "value": phase_blunders[worst_blunder_phase],
            "description": f"{worst_blunder_phase} blunders ({phase_blunders[worst_blunder_phase]} in last 20 games)",
        })

    # Weakness 3: Most problematic opening
    games = db.query(Game).filter(Game.id.in_(game_ids)).all()
    opening_stats = defaultdict(lambda: {"games": 0, "losses": 0, "eco": None})
    for g in games:
        if g.opening_name:
            opening_stats[g.opening_name]["games"] += 1
            opening_stats[g.opening_name]["eco"] = g.eco
            if g.result == GameResult.loss:
                opening_stats[g.opening_name]["losses"] += 1

    # Find opening with worst loss rate (min 3 games)
    worst_opening = None
    worst_loss_rate = 0
    for name, stats in opening_stats.items():
        if stats["games"] >= 3:
            loss_rate = stats["losses"] / stats["games"]
            if loss_rate > worst_loss_rate:
                worst_loss_rate = loss_rate
                worst_opening = (name, stats)

    if worst_opening:
        name, stats = worst_opening
        weaknesses.append({
            "type": "opening",
            "opening": name,
            "eco": stats["eco"],
            "value": round(worst_loss_rate * 100, 1),
            "description": f"{name} ({stats['losses']}/{stats['games']} losses)",
        })

    return weaknesses


def _select_drills(db: Session, weaknesses: list[dict]) -> list[DrillPosition]:
    """Select drills targeting identified weaknesses."""
    today = date.today()
    selected = []
    seen_ids = set()

    for weakness in weaknesses:
        query = db.query(DrillPosition).filter(
            DrillPosition.next_review_date <= today,
        )

        if weakness["type"] == "phase" or weakness["type"] == "blunder_phase":
            query = query.filter(DrillPosition.game_phase == weakness["phase"])
        elif weakness["type"] == "opening" and weakness.get("eco"):
            query = query.filter(DrillPosition.opening_eco == weakness["eco"])

        # Prioritize drills the player gets wrong (accuracy < 50%)
        drills = query.order_by(
            DrillPosition.difficulty_rating.desc(),
            DrillPosition.next_review_date.asc(),
        ).limit(5).all()

        # Sort by accuracy (worst first)
        drills.sort(key=lambda d: (
            d.times_correct / d.times_shown if d.times_shown > 0 else 0.5
        ))

        for d in drills:
            if d.id not in seen_ids and len(selected) < 5:
                selected.append(d)
                seen_ids.add(d.id)

    return selected[:5]


def _supplement_with_replay(db: Session, existing: list[DrillPosition], needed: int) -> list[DrillPosition]:
    """Add positions from recent games to fill the warmup set."""
    existing_ids = {d.id for d in existing}

    # Get drills due today that aren't already selected
    today = date.today()
    extra = db.query(DrillPosition).filter(
        DrillPosition.next_review_date <= today,
        ~DrillPosition.id.in_(existing_ids) if existing_ids else True,
    ).order_by(
        DrillPosition.difficulty_rating.desc(),
    ).limit(needed).all()

    return existing + extra


def _fallback_warmup(db: Session) -> dict:
    """Fallback when no analyzed games are available."""
    today = date.today()
    drills = db.query(DrillPosition).filter(
        DrillPosition.next_review_date <= today,
    ).order_by(
        DrillPosition.difficulty_rating.desc(),
    ).limit(5).all()

    return {
        "warmup_focus": "General warm-up — analyze more games for personalized recommendations.",
        "estimated_time": "5 minutes",
        "weakness_areas": [],
        "drills": [
            {
                "id": d.id,
                "fen": d.fen,
                "type": "tactical_drill",
                "theme": d.tactical_theme,
                "game_phase": d.game_phase.value if d.game_phase else None,
                "difficulty": d.difficulty_rating,
                "your_accuracy": f"{d.times_correct}/{d.times_shown}" if d.times_shown > 0 else "new",
                "opening_eco": d.opening_eco,
            }
            for d in drills
        ],
    }
