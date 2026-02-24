"""Stockfish analysis pipeline.

Analyzes games move-by-move using python-chess engine interface.
Classifies moves, detects game phases, and generates game summaries.
"""

import logging
import io
from typing import Optional

import chess
import chess.pgn
import chess.engine
from sqlalchemy.orm import Session

from app.models.models import (
    Game, MoveAnalysis, GameSummary, MoveClassification, GamePhase, PlayerColor
)
from app.config import settings

logger = logging.getLogger(__name__)


def classify_move(cp_loss: float) -> MoveClassification:
    """Classify a move based on centipawn loss."""
    abs_loss = abs(cp_loss)
    if abs_loss <= settings.threshold_best:
        return MoveClassification.best
    elif abs_loss <= settings.threshold_excellent:
        return MoveClassification.excellent
    elif abs_loss <= settings.threshold_good:
        return MoveClassification.good
    elif abs_loss <= settings.threshold_inaccuracy:
        return MoveClassification.inaccuracy
    elif abs_loss <= settings.threshold_mistake:
        return MoveClassification.mistake
    else:
        return MoveClassification.blunder


def detect_game_phase(board: chess.Board, ply: int) -> GamePhase:
    """
    Detect game phase using piece count heuristic from PROJECT.md:
    - Opening: moves 1-15 AND fewer than 3 pieces captured
    - Middlegame: not opening AND total piece count > 10 (excl pawns and kings)
    - Endgame: total piece count <= 10 (excl pawns and kings), OR queens traded and pieces <= 14
    """
    move_number = (ply + 1) // 2

    # Count non-pawn, non-king pieces
    piece_count = 0
    queens_on_board = 0
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece and piece.piece_type not in (chess.PAWN, chess.KING):
            piece_count += 1
            if piece.piece_type == chess.QUEEN:
                queens_on_board += 1

    # Count captured pieces (start with 14 non-pawn non-king pieces)
    pieces_captured = 14 - piece_count

    if piece_count <= 10:
        return GamePhase.endgame
    if queens_on_board == 0 and piece_count <= 14:
        return GamePhase.endgame
    if move_number <= 15 and pieces_captured < 3:
        return GamePhase.opening
    return GamePhase.middlegame


def eval_to_cp(info: chess.engine.InfoDict, perspective_white: bool) -> Optional[float]:
    """Extract centipawn value from engine info, from white's perspective."""
    score = info.get("score")
    if score is None:
        return None
    pov = score.white()
    mate_in = pov.mate()
    if mate_in is not None:
        return 10000.0 if mate_in > 0 else -10000.0
    cp = pov.score()
    return float(cp) if cp is not None else None


def analyze_game(db: Session, game: Game, depth: int | None = None) -> dict:
    """
    Run Stockfish analysis on every move of a game.

    Returns dict with analysis stats.
    """
    depth = depth or settings.stockfish_depth
    # Safety timeout: 30 seconds per move position prevents engine hangs
    move_limit = chess.engine.Limit(depth=depth, time=30.0)

    try:
        pgn_game = chess.pgn.read_game(io.StringIO(game.pgn))
    except Exception as e:
        logger.error(f"Failed to parse PGN for game {game.id}: {e}")
        return {"error": str(e)}

    if pgn_game is None:
        return {"error": "Could not parse PGN"}

    board = pgn_game.board()
    player_is_white = game.player_color == PlayerColor.white

    moves = list(pgn_game.mainline_moves())
    if not moves:
        return {"error": "No moves in game"}

    # Clear existing analysis for this game
    db.query(MoveAnalysis).filter(MoveAnalysis.game_id == game.id).delete()
    db.query(GameSummary).filter(GameSummary.game_id == game.id).delete()

    analyses = []
    player_cp_losses = []
    phase_cp_losses = {"opening": [], "middlegame": [], "endgame": []}
    critical_moments = []

    try:
        engine = chess.engine.SimpleEngine.popen_uci(settings.stockfish_path)
        engine.configure({"Threads": settings.stockfish_threads, "Hash": settings.stockfish_hash_mb})
    except Exception as e:
        logger.error(f"Failed to start Stockfish: {e}")
        return {"error": f"Stockfish startup failed: {e}"}

    try:
        prev_eval_white = None

        for ply_idx, move in enumerate(moves):
            ply = ply_idx + 1
            move_number = (ply + 1) // 2
            is_white_move = (ply % 2 == 1)
            color = PlayerColor.white if is_white_move else PlayerColor.black
            is_player_move = (is_white_move == player_is_white)

            fen_before = board.fen()
            game_phase = detect_game_phase(board, ply)

            move_pushed = False
            try:
                # Get engine evaluation of current position
                info_before = engine.analyse(board, move_limit)
                eval_before_white = eval_to_cp(info_before, True)

                # Get the best move
                best_move_result = engine.play(board, move_limit)
                best_move = best_move_result.move

                best_move_san = board.san(best_move) if best_move else None
                best_move_uci = best_move.uci() if best_move else None

                # Get top 3 lines
                multi_info = engine.analyse(board, move_limit, multipv=3)
                top_3 = []
                if isinstance(multi_info, list):
                    for line_info in multi_info:
                        pv = line_info.get("pv", [])
                        score = line_info.get("score")
                        if pv and score:
                            pv_san = []
                            temp_board = board.copy()
                            for m in pv[:5]:
                                pv_san.append(temp_board.san(m))
                                temp_board.push(m)
                            s = score.white()
                            mate = s.mate()
                            cp = (10000 if mate > 0 else -10000) if mate is not None else (s.score() or 0)
                            top_3.append({"moves": pv_san, "eval": cp})

                move_played_san = board.san(move)
                move_played_uci = move.uci()

                # Make the move and evaluate the resulting position
                board.push(move)
                move_pushed = True
                info_after = engine.analyse(board, move_limit)
                eval_after_white = eval_to_cp(info_after, True)

                # Calculate eval delta from player's perspective
                if eval_before_white is not None and eval_after_white is not None:
                    if is_white_move:
                        # White moved: positive delta = good for white
                        eval_delta = eval_after_white - eval_before_white
                        eval_before_player = eval_before_white if player_is_white else -eval_before_white
                        eval_after_player = eval_after_white if player_is_white else -eval_after_white
                    else:
                        # Black moved: flip perspective
                        eval_delta = -(eval_after_white - eval_before_white)
                        eval_before_player = -eval_before_white if player_is_white else eval_before_white
                        eval_after_player = -eval_after_white if player_is_white else eval_after_white

                    # cp_loss is how much the move cost (positive = lost advantage)
                    # For the moving side: compare best eval to actual eval
                    cp_loss = -eval_delta  # positive means the move was worse than best
                    classification = classify_move(cp_loss) if is_player_move else classify_move(cp_loss)
                else:
                    eval_delta = None
                    eval_before_player = None
                    eval_after_player = None
                    cp_loss = 0
                    classification = MoveClassification.good

                analysis = MoveAnalysis(
                    game_id=game.id,
                    move_number=move_number,
                    ply=ply,
                    color=color,
                    is_player_move=is_player_move,
                    fen_before=fen_before,
                    move_played=move_played_uci,
                    move_played_san=move_played_san,
                    best_move=best_move_uci,
                    best_move_san=best_move_san,
                    eval_before=eval_before_player,
                    eval_after=eval_after_player,
                    eval_delta=eval_delta if is_player_move else None,
                    classification=classification,
                    depth=depth,
                    game_phase=game_phase,
                    top_3_lines=top_3 if top_3 else None,
                )
                analyses.append(analysis)
                db.add(analysis)

                if is_player_move and eval_delta is not None:
                    player_cp_losses.append(abs(cp_loss) if cp_loss > 0 else 0)
                    phase_cp_losses[game_phase.value].append(abs(cp_loss) if cp_loss > 0 else 0)

                    # Detect critical moments (eval swing > 100cp on player's move)
                    if abs(cp_loss) > 100:
                        critical_moments.append(ply)

                prev_eval_white = eval_after_white

            except chess.engine.EngineTerminatedError:
                logger.error(f"Engine terminated at ply {ply} of game {game.id}")
                if not move_pushed:
                    board.push(move)
                break
            except Exception as e:
                logger.warning(f"Engine error at ply {ply} of game {game.id}: {e}")
                if not move_pushed:
                    board.push(move)
                continue

    finally:
        engine.quit()

    # Build game summary
    avg_cpl = sum(player_cp_losses) / len(player_cp_losses) if player_cp_losses else 0
    blunders = sum(1 for a in analyses if a.is_player_move and a.classification == MoveClassification.blunder)
    mistakes = sum(1 for a in analyses if a.is_player_move and a.classification == MoveClassification.mistake)
    inaccuracies = sum(1 for a in analyses if a.is_player_move and a.classification == MoveClassification.inaccuracy)

    def phase_avg(phase_list):
        return sum(phase_list) / len(phase_list) if phase_list else None

    summary = GameSummary(
        game_id=game.id,
        avg_centipawn_loss=round(avg_cpl, 1),
        blunder_count=blunders,
        mistake_count=mistakes,
        inaccuracy_count=inaccuracies,
        opening_accuracy=round(phase_avg(phase_cp_losses["opening"]) or 0, 1),
        middlegame_accuracy=round(phase_avg(phase_cp_losses["middlegame"]) or 0, 1),
        endgame_accuracy=round(phase_avg(phase_cp_losses["endgame"]) or 0, 1),
        critical_moments=critical_moments,
    )
    db.add(summary)
    db.commit()

    return {
        "game_id": game.id,
        "moves_analyzed": len(analyses),
        "avg_cpl": round(avg_cpl, 1),
        "blunders": blunders,
        "mistakes": mistakes,
        "inaccuracies": inaccuracies,
        "critical_moments": len(critical_moments),
    }


def batch_analyze(db: Session, game_ids: list[int] | None = None,
                  limit: int = 200, time_class_filter: str = "blitz",
                  depth: int | None = None) -> dict:
    """
    Batch analyze multiple games. If game_ids not provided, picks the most recent
    unanalyzed games matching the time_class filter.
    """
    if game_ids:
        games = db.query(Game).filter(Game.id.in_(game_ids)).all()
    else:
        # Find games without analysis
        analyzed_ids = db.query(GameSummary.game_id).subquery()
        query = db.query(Game).filter(
            ~Game.id.in_(db.query(analyzed_ids.c.game_id))
        )
        if time_class_filter:
            query = query.filter(Game.time_class == time_class_filter)
        games = query.order_by(Game.end_time.desc()).limit(limit).all()

    results = {"total": len(games), "completed": 0, "errors": 0, "details": []}

    for game in games:
        logger.info(f"Analyzing game {game.id} ({results['completed'] + 1}/{len(games)})")
        try:
            result = analyze_game(db, game, depth=depth)
            if "error" in result:
                results["errors"] += 1
            else:
                results["completed"] += 1
            results["details"].append(result)
        except Exception as e:
            logger.error(f"Failed to analyze game {game.id}: {e}")
            results["errors"] += 1
            results["details"].append({"game_id": game.id, "error": str(e)})

    return results
