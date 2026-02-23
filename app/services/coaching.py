"""Claude coaching service.

Stockfish evaluates. Claude teaches. We never ask Claude to calculate —
we provide Stockfish output and ask Claude to EXPLAIN.
"""

import io
import logging
import re
from typing import Optional

import chess.pgn
import anthropic
from sqlalchemy.orm import Session

from app.models.models import (
    Game, MoveAnalysis, GameSummary, CoachingSession, SessionType,
    MoveClassification, PlayerColor, GamePhase
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


def _build_pgn_up_to(game: Game, target_ply: int) -> str:
    """Build formatted PGN text up to a given ply."""
    pgn_game = chess.pgn.read_game(io.StringIO(game.pgn))
    if not pgn_game:
        return ""
    board = pgn_game.board()
    san_moves = []
    for i, move in enumerate(pgn_game.mainline_moves()):
        if i + 1 > target_ply:
            break
        san_moves.append(board.san(move))
        board.push(move)
    formatted = []
    for i in range(0, len(san_moves), 2):
        mn = (i // 2) + 1
        if i + 1 < len(san_moves):
            formatted.append(f"{mn}. {san_moves[i]} {san_moves[i+1]}")
        else:
            formatted.append(f"{mn}. {san_moves[i]}")
    return " ".join(formatted)


def _get_next_moves_text(all_analyses: list[MoveAnalysis], current_ply: int, count: int = 4) -> str:
    """Get the next N moves after the current ply as text."""
    subsequent = [a for a in all_analyses if a.ply > current_ply and a.ply <= current_ply + count]
    if not subsequent:
        return "Game ended here."
    parts = []
    for a in subsequent:
        parts.append(f"{a.move_number}{'.' if a.color.value == 'white' else '...'}{a.move_played_san}")
    return " ".join(parts)


def generate_walkthrough(db: Session, game: Game) -> dict:
    """Generate a move-by-move guided walkthrough with commentary at inflection points only."""
    summary = db.query(GameSummary).filter(GameSummary.game_id == game.id).first()
    if not summary:
        return {"error": "Game has not been analyzed yet. Run Stockfish analysis first."}

    all_analyses = db.query(MoveAnalysis).filter(
        MoveAnalysis.game_id == game.id,
    ).order_by(MoveAnalysis.ply).all()

    if not all_analyses:
        return {"error": "No move analysis found. Run Stockfish analysis first."}

    # Build lookup by ply
    by_ply = {a.ply: a for a in all_analyses}
    max_ply = max(a.ply for a in all_analyses)
    critical_moments = set(summary.critical_moments or [])

    # Identify commentary points
    commentary_plies = set()
    prev_phase = None
    for a in all_analyses:
        # Mistake or blunder on player's move
        if a.is_player_move and a.classification in (MoveClassification.mistake, MoveClassification.blunder):
            commentary_plies.add(a.ply)
        # Significant eval swing on player's move
        if a.is_player_move and a.eval_delta is not None and abs(a.eval_delta) > 50:
            commentary_plies.add(a.ply)
        # Critical moment from GameSummary
        if a.ply in critical_moments:
            commentary_plies.add(a.ply)
        # Phase transition (first move of new phase)
        if a.game_phase and prev_phase and a.game_phase != prev_phase:
            commentary_plies.add(a.ply)
        prev_phase = a.game_phase
    # Last move of the game
    commentary_plies.add(max_ply)

    commentary_plies = sorted(commentary_plies)

    # Build per-moment context for the prompt
    moments_prompt_sections = []
    for idx, ply in enumerate(commentary_plies, 1):
        a = by_ply[ply]
        pgn_text = _build_pgn_up_to(game, ply)
        next_moves = _get_next_moves_text(all_analyses, ply)

        # Determine commentary type
        if ply == max_ply:
            moment_type = "game_end"
        elif a.classification in (MoveClassification.blunder,):
            moment_type = "blunder"
        elif a.classification in (MoveClassification.mistake,):
            moment_type = "mistake"
        elif a.is_player_move and a.eval_delta is not None and abs(a.eval_delta) > 50:
            moment_type = "significant_swing"
        elif ply in critical_moments:
            moment_type = "critical_moment"
        else:
            moment_type = "phase_transition"

        section = f"""<moment id="{idx}" ply="{ply}">
<move_number>{a.move_number}</move_number>
<color>{a.color.value}</color>
<fen>{a.fen_before}</fen>
<pgn_to_here>{pgn_text}</pgn_to_here>
<move_played>{a.move_played_san}</move_played>
<best_move>{a.best_move_san or a.move_played_san}</best_move>
<eval_before>{a.eval_before:.0f}</eval_before>
<eval_after>{a.eval_after:.0f}</eval_after>
<eval_delta>{f'{a.eval_delta:.0f}' if a.eval_delta is not None else 'N/A'}</eval_delta>
<classification>{a.classification.value if a.classification else 'unknown'}</classification>
<game_phase>{a.game_phase.value if a.game_phase else 'unknown'}</game_phase>
<next_moves>{next_moves}</next_moves>
<is_player_move>{a.is_player_move}</is_player_move>
<moment_type>{moment_type}</moment_type>
</moment>"""
        moments_prompt_sections.append(section)

    moments_xml = "\n\n".join(moments_prompt_sections)

    prompt = f"""You are a chess coach providing a guided walkthrough of a complete game for an intermediate player (800-1200 rated).

GAME CONTEXT:
- Opening: {game.opening_name or 'Unknown'} ({game.eco or '?'})
- Player color: {game.player_color.value}
- Result: {game.result.value} ({game.result_type})
- Player rating: {game.player_rating} | Opponent rating: {game.opponent_rating}
- Full PGN: {game.pgn[:3000]}

Below are {len(commentary_plies)} key moments from this game. For each moment, provide 2-3 sentences of coaching commentary. Be specific — reference actual squares, pieces, and tactical motifs. No generic advice.

For mistakes/blunders: explain what the player was probably thinking, why it fails, and what the correct move accomplishes.
For phase transitions: note the shift in priorities (e.g., development → piece activity → king safety).
For the game end: explain the final position and what sealed the outcome.

{moments_xml}

Respond in EXACTLY this format — one section per moment, using XML tags:

<walkthrough>
<moment id="1" ply="[ply_number]">
[Your 2-3 sentence coaching commentary for this moment]
</moment>
<moment id="2" ply="[ply_number]">
[Your 2-3 sentence coaching commentary for this moment]
</moment>
...continue for all {len(commentary_plies)} moments...
</walkthrough>

<narrative>
[2-3 sentence story arc of the entire game: how it opened, where it turned, how it ended]
</narrative>"""

    client = _get_client()
    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_response = response.content[0].text

    # Parse the response
    commentary_points = []
    moment_pattern = re.compile(
        r'<moment\s+id="(\d+)"\s+ply="(\d+)">\s*(.*?)\s*</moment>',
        re.DOTALL,
    )
    for match in moment_pattern.finditer(raw_response):
        parsed_ply = int(match.group(2))
        commentary_text = match.group(3).strip()
        a = by_ply.get(parsed_ply)
        if not a:
            continue

        # Determine type
        if parsed_ply == max_ply:
            point_type = "game_end"
        elif a.classification == MoveClassification.blunder:
            point_type = "blunder"
        elif a.classification == MoveClassification.mistake:
            point_type = "mistake"
        elif a.is_player_move and a.eval_delta is not None and abs(a.eval_delta) > 50:
            point_type = "significant_swing"
        elif parsed_ply in critical_moments:
            point_type = "critical_moment"
        else:
            point_type = "phase_transition"

        commentary_points.append({
            "ply": parsed_ply,
            "move_number": a.move_number,
            "color": a.color.value,
            "fen": a.fen_before,
            "move_played": a.move_played_san,
            "best_move": a.best_move_san or a.move_played_san,
            "classification": a.classification.value if a.classification else None,
            "eval_before": a.eval_before,
            "eval_after": a.eval_after,
            "game_phase": a.game_phase.value if a.game_phase else None,
            "commentary": commentary_text,
            "type": point_type,
        })

    # If XML parsing missed some moments, fall back to matching by ply from our known list
    parsed_plies = {cp["ply"] for cp in commentary_points}
    if len(parsed_plies) < len(commentary_plies):
        logger.warning(
            f"Walkthrough parsing: got {len(parsed_plies)}/{len(commentary_plies)} moments from XML. "
            f"Missing plies: {set(commentary_plies) - parsed_plies}"
        )

    # Parse narrative summary
    narrative_match = re.search(r'<narrative>\s*(.*?)\s*</narrative>', raw_response, re.DOTALL)
    narrative_summary = narrative_match.group(1).strip() if narrative_match else ""

    # Store in coaching_sessions
    import json
    session = CoachingSession(
        game_id=game.id,
        session_type=SessionType.game_review,
        prompt_sent=prompt,
        response=json.dumps({
            "commentary_points": commentary_points,
            "narrative_summary": narrative_summary,
        }),
        model_used=SONNET_MODEL,
    )
    db.add(session)
    db.commit()

    return {
        "game_id": game.id,
        "total_moves": game.total_moves,
        "commentary_points": commentary_points,
        "narrative_summary": narrative_summary,
    }


def generate_behavioral_narrative(db: Session, patterns: list[dict]) -> dict:
    """Send behavioral pattern data to Claude Opus for narrative diagnosis."""
    import json

    # Build pattern summary for the prompt
    pattern_sections = []
    for p in patterns:
        if p.get("frequency", 0) == 0 and "Insufficient" in p.get("frequency_label", ""):
            continue
        section = f"""PATTERN: {p['pattern_name']}
Description: {p.get('description', '')}
Frequency: {p.get('frequency_label', '')}
Impact: {p.get('impact_label', '')}
Severity: {p.get('severity', 'low')}
Details: {json.dumps(p.get('detail', {}), indent=2)}
Example game IDs: {p.get('example_game_ids', [])}"""
        pattern_sections.append(section)

    if not pattern_sections:
        return {
            "patterns": patterns,
            "narrative": "Insufficient data for behavioral analysis. Analyze more games first.",
        }

    patterns_text = "\n\n".join(pattern_sections)

    prompt = f"""You are a chess coach providing a behavioral analysis for eddobbles2021 (800-1200 rated blitz player, 5,000+ games on Chess.com).

Below are BEHAVIORAL PATTERNS mined from their complete game history. These are not per-game stats — they are cross-game tendencies detected by analyzing thousands of games.

{patterns_text}

Provide a narrative behavioral diagnosis:

1. RANKING — Rank the patterns by impact on rating. Which habit costs the most Elo?
2. CONNECTIONS — How do these patterns relate to each other? (e.g., time trouble → more blunders → tilt → losing streaks)
3. SPECIFIC GAME REFERENCES — Reference the example game IDs where patterns are most visible
4. ROOT CAUSES — What underlying chess understanding gaps produce these patterns?
5. PRIORITIZED IMPROVEMENT PLAN — A concrete 3-step plan, ordered by expected Elo gain:
   - Step 1: The single behavior change that would gain the most rating points
   - Step 2: The second-highest impact change
   - Step 3: A practice routine to reinforce both

Be direct. Reference the actual numbers. This player is an executive — no fluff, no generic advice. Write as if you're sitting across the table from them with a laptop open to their game history."""

    client = _get_client()
    response = client.messages.create(
        model=OPUS_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    narrative_text = response.content[0].text

    # Store in coaching_sessions
    session = CoachingSession(
        game_id=None,
        session_type=SessionType.behavioral_analysis,
        prompt_sent=prompt,
        response=narrative_text,
        model_used=OPUS_MODEL,
    )
    db.add(session)
    db.commit()

    return {
        "patterns": patterns,
        "narrative": narrative_text,
        "session_id": session.id,
    }
