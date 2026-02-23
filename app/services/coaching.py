"""Claude coaching service.

Stockfish evaluates. Claude teaches. We never ask Claude to calculate —
we provide Stockfish output and ask Claude to EXPLAIN.
"""

import logging
from typing import Optional

import anthropic
from sqlalchemy.orm import Session

from app.models.models import (
    Game, MoveAnalysis, GameSummary, CoachingSession, SessionType,
    MoveClassification, PlayerColor
)
from app.config import settings

logger = logging.getLogger(__name__)

SONNET_MODEL = "claude-sonnet-4-20250514"
OPUS_MODEL = "claude-opus-4-20250514"


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def explain_move(db: Session, game: Game, ply: int) -> dict:
    """Generate Claude coaching explanation for a single move."""
    analysis = db.query(MoveAnalysis).filter(
        MoveAnalysis.game_id == game.id,
        MoveAnalysis.ply == ply,
    ).first()

    if not analysis:
        return {"error": f"No analysis found for game {game.id}, ply {ply}"}

    # Build PGN up to this point
    import chess.pgn, io
    pgn_game = chess.pgn.read_game(io.StringIO(game.pgn))
    moves_so_far = []
    if pgn_game:
        for i, move in enumerate(pgn_game.mainline_moves()):
            if i + 1 > ply:
                break
            moves_so_far.append(move)

    board = pgn_game.board() if pgn_game else None
    pgn_text = ""
    if board:
        temp = board.copy()
        san_moves = []
        for m in moves_so_far:
            san_moves.append(temp.san(m))
            temp.push(m)
        # Format as move pairs
        formatted = []
        for i in range(0, len(san_moves), 2):
            mn = (i // 2) + 1
            if i + 1 < len(san_moves):
                formatted.append(f"{mn}. {san_moves[i]} {san_moves[i+1]}")
            else:
                formatted.append(f"{mn}. {san_moves[i]}")
        pgn_text = " ".join(formatted)

    prompt = f"""You are a chess coach explaining a move to an intermediate player (800-1200 rated).

POSITION (FEN): {analysis.fen_before}
GAME CONTEXT: {pgn_text}
OPENING: {game.opening_name or 'Unknown'} ({game.eco or '?'})
GAME PHASE: {analysis.game_phase.value if analysis.game_phase else 'unknown'}

THE PLAYER PLAYED: {analysis.move_played_san}
THE CORRECT MOVE WAS: {analysis.best_move_san or 'N/A'}
EVALUATION SWING: {analysis.eval_before:.0f} → {analysis.eval_after:.0f} ({analysis.classification.value if analysis.classification else 'unknown'})

Explain:
1. What the player's move does and why it seems reasonable (validate their thinking)
2. What it actually gives up or fails to accomplish
3. Why the correct move is better — what STRATEGIC GOAL does it serve?
4. The underlying chess PRINCIPLE this illustrates (e.g., "don't move the same piece twice in the opening", "control the center before attacking on the wing", "in endgames, activate your king")
5. A one-sentence rule of thumb the player can remember and apply in future games

Be conversational, direct, and concrete. Reference specific squares and pieces. No generic advice. Teach the WHY, not just the WHAT."""

    client = _get_client()
    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )

    coaching_text = response.content[0].text

    session = CoachingSession(
        game_id=game.id,
        session_type=SessionType.game_review,
        prompt_sent=prompt,
        response=coaching_text,
        model_used=SONNET_MODEL,
    )
    db.add(session)
    db.commit()

    return {
        "ply": ply,
        "move_played": analysis.move_played_san,
        "best_move": analysis.best_move_san,
        "classification": analysis.classification.value if analysis.classification else None,
        "eval_before": analysis.eval_before,
        "eval_after": analysis.eval_after,
        "coaching": coaching_text,
    }


def review_game(db: Session, game: Game) -> dict:
    """Generate a full game review using Claude."""
    summary = db.query(GameSummary).filter(GameSummary.game_id == game.id).first()
    if not summary:
        return {"error": "Game has not been analyzed yet. Run Stockfish analysis first."}

    # Get critical moment details
    critical_analyses = db.query(MoveAnalysis).filter(
        MoveAnalysis.game_id == game.id,
        MoveAnalysis.is_player_move == True,
        MoveAnalysis.ply.in_(summary.critical_moments or []),
    ).order_by(MoveAnalysis.ply).all()

    critical_text = ""
    for ca in critical_analyses:
        critical_text += (
            f"  Move {ca.move_number}: Played {ca.move_played_san}, "
            f"Best was {ca.best_move_san}\n"
            f"  Eval: {ca.eval_before:.0f} → {ca.eval_after:.0f} | "
            f"Classification: {ca.classification.value if ca.classification else '?'}\n"
            f"  FEN: {ca.fen_before}\n\n"
        )

    if not critical_text:
        critical_text = "  No major critical moments detected."

    prompt = f"""You are a chess coach reviewing a complete game for an intermediate player (800-1200 rated).

GAME PGN: {game.pgn[:3000]}
OPENING: {game.opening_name or 'Unknown'} ({game.eco or '?'})
RESULT: {game.result.value} ({game.result_type})
PLAYER COLOR: {game.player_color.value}
PLAYER RATING: {game.player_rating} | OPPONENT RATING: {game.opponent_rating}

CRITICAL MOMENTS (positions where eval swung > 100cp on player's move):
{critical_text}

GAME STATISTICS:
- Average centipawn loss: {summary.avg_centipawn_loss}
- Opening accuracy (moves 1-15): {summary.opening_accuracy} CPL
- Middlegame accuracy: {summary.middlegame_accuracy} CPL
- Endgame accuracy: {summary.endgame_accuracy} CPL
- Blunders: {summary.blunder_count} | Mistakes: {summary.mistake_count} | Inaccuracies: {summary.inaccuracy_count}

Provide a coaching review structured as:
1. ONE SENTENCE game summary — what happened and why
2. THE TURNING POINT — the single most important moment, explained in depth (why the position demanded a specific plan, what the correct plan was, and why the player's choice went wrong)
3. PATTERN ALERT — if any of the mistakes match recurring themes (premature attacks, neglected development, king safety, endgame technique), name the pattern
4. ONE THING TO PRACTICE — the single most impactful improvement area from this game, stated as a concrete drill or study topic

Keep it under 500 words. Direct, no fluff. This player is an executive — respect their time."""

    client = _get_client()
    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    coaching_text = response.content[0].text

    # Store in coaching_sessions
    session = CoachingSession(
        game_id=game.id,
        session_type=SessionType.game_review,
        prompt_sent=prompt,
        response=coaching_text,
        model_used=SONNET_MODEL,
    )
    db.add(session)

    # Update game summary with coaching notes
    summary.coaching_notes = coaching_text
    db.commit()

    return {
        "game_id": game.id,
        "review": coaching_text,
        "stats": {
            "avg_cpl": summary.avg_centipawn_loss,
            "blunders": summary.blunder_count,
            "mistakes": summary.mistake_count,
            "inaccuracies": summary.inaccuracy_count,
        },
    }


def generate_pattern_diagnosis(db: Session) -> dict:
    """Generate aggregate pattern analysis using Claude Opus."""
    from sqlalchemy import func, case

    username = settings.chess_com_username.lower()

    # Opening performance
    opening_stats = db.query(
        Game.opening_name,
        func.count(Game.id).label("games_played"),
        func.avg(case((Game.result == "win", 1), else_=0)).label("win_rate"),
    ).filter(
        Game.opening_name.isnot(None),
        Game.time_class == "blitz",
    ).group_by(Game.opening_name).having(
        func.count(Game.id) >= 5
    ).order_by(func.count(Game.id).desc()).limit(15).all()

    opening_table = "Opening | Games | Win Rate\n"
    for o in opening_stats:
        opening_table += f"{o.opening_name} | {o.games_played} | {o.win_rate * 100:.0f}%\n"

    # Phase performance
    phase_stats = {}
    for phase in ["opening", "middlegame", "endgame"]:
        avg = db.query(func.avg(
            getattr(GameSummary, f"{phase}_accuracy")
        )).scalar()
        phase_stats[phase] = round(avg, 1) if avg else 0

    # Color performance
    color_stats = {}
    for color in ["white", "black"]:
        games = db.query(Game).filter(Game.player_color == color, Game.time_class == "blitz")
        total = games.count()
        wins = games.filter(Game.result == "win").count()
        color_stats[color] = {
            "total": total,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
        }

    # Total analyzed games count
    analyzed_count = db.query(GameSummary).count()

    prompt = f"""You are a chess coach analyzing aggregate performance data for an intermediate player.

PLAYER: eddobbles2021 | PRIMARY TIME CONTROL: 5|5

OPENING PERFORMANCE (from {analyzed_count} analyzed games):
{opening_table}

PHASE PERFORMANCE:
- Opening avg CPL: {phase_stats['opening']} (moves 1-15)
- Middlegame avg CPL: {phase_stats['middlegame']}
- Endgame avg CPL: {phase_stats['endgame']}

COLOR PERFORMANCE:
- As White: {color_stats['white']['win_rate']}% win rate ({color_stats['white']['total']} games)
- As Black: {color_stats['black']['win_rate']}% win rate ({color_stats['black']['total']} games)

Provide:
1. TOP 3 WEAKNESSES — ranked by impact on rating, with specific evidence from the data
2. TOP 2 STRENGTHS — what the player does well (they need to know this too)
3. RECOMMENDED STUDY PLAN — a prioritized 4-week plan: what to study each week, estimated time per day (15-30 min), and specific resources or exercises
4. OPENING REPERTOIRE ADVICE — based on their results, should they narrow their repertoire? Switch openings? Double down on what's working?

Be data-driven. Reference the actual numbers. No generic advice."""

    client = _get_client()
    response = client.messages.create(
        model=OPUS_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    diagnosis_text = response.content[0].text

    session = CoachingSession(
        game_id=None,
        session_type=SessionType.pattern_diagnosis,
        prompt_sent=prompt,
        response=diagnosis_text,
        model_used=OPUS_MODEL,
    )
    db.add(session)
    db.commit()

    return {
        "diagnosis": diagnosis_text,
        "analyzed_games": analyzed_count,
        "session_id": session.id,
    }
