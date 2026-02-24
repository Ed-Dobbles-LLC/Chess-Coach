"""Behavioral pattern mining engine.

Identifies RECURRING tendencies across all analyzed games — not per-game stats,
but cross-game behavioral patterns that reveal habits, blind spots, and tilt.
"""

import io
import re
import logging
from collections import defaultdict
from datetime import timedelta

import chess
import chess.pgn
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.models.models import (
    Game, MoveAnalysis, GameSummary, GameResult, PlayerColor,
    MoveClassification, GamePhase,
)

logger = logging.getLogger(__name__)


# ── Clock Parsing ──

def parse_clocks_from_pgn(pgn_text: str) -> list[float]:
    """Extract clock times (in seconds) from PGN %clk annotations.

    Chess.com PGNs include {[%clk H:MM:SS.s]} after each move.
    Returns a list of remaining-time-in-seconds, one per ply, in move order.
    """
    pattern = re.compile(r'\[%clk (\d+):(\d+):(\d+(?:\.\d+)?)\]')
    clocks = []
    for m in pattern.finditer(pgn_text):
        hours = int(m.group(1))
        minutes = int(m.group(2))
        seconds = float(m.group(3))
        clocks.append(hours * 3600 + minutes * 60 + seconds)
    return clocks


def _parse_pgn_moves(pgn_text: str):
    """Parse PGN and return (chess.pgn.Game, list of san moves, list of boards after each move)."""
    pgn_game = chess.pgn.read_game(io.StringIO(pgn_text))
    if not pgn_game:
        return None, [], []
    board = pgn_game.board()
    sans = []
    boards = [board.copy()]
    for move in pgn_game.mainline_moves():
        sans.append(board.san(move))
        board.push(move)
        boards.append(board.copy())
    return pgn_game, sans, boards


# ── Pattern Detectors ──

def detect_early_queen_trades(db: Session) -> dict:
    """How often does the player trade queens before move 20?
    Win rate when they do vs don't?"""
    games = db.query(Game).filter(Game.time_class == "blitz").all()
    if not games:
        return _empty_pattern("early_queen_trades")

    traded_early = []
    not_traded_early = []

    for game in games:
        try:
            _, sans, boards = _parse_pgn_moves(game.pgn)
            if not sans:
                continue

            queen_traded_before_20 = False
            for ply_idx in range(min(40, len(sans))):  # first 20 full moves = 40 plies
                board_before = boards[ply_idx]
                board_after = boards[ply_idx + 1]

                # Count queens before and after
                queens_before = len(board_before.pieces(chess.QUEEN, chess.WHITE)) + \
                                len(board_before.pieces(chess.QUEEN, chess.BLACK))
                queens_after = len(board_after.pieces(chess.QUEEN, chess.WHITE)) + \
                               len(board_after.pieces(chess.QUEEN, chess.BLACK))

                if queens_before == 2 and queens_after < 2:
                    queen_traded_before_20 = True
                    break

            if queen_traded_before_20:
                traded_early.append(game)
            else:
                not_traded_early.append(game)
        except Exception:
            continue

    total = len(traded_early) + len(not_traded_early)
    if total == 0:
        return _empty_pattern("early_queen_trades")

    freq = len(traded_early) / total
    wr_traded = _win_rate(traded_early)
    wr_not_traded = _win_rate(not_traded_early)
    impact = wr_traded - wr_not_traded

    # Find most pronounced examples (biggest deviation from average)
    example_ids = [g.id for g in traded_early[:5]]

    return {
        "pattern_name": "early_queen_trades",
        "description": "Trading queens before move 20 — avoiding complex middlegames",
        "frequency": round(freq * 100, 1),
        "frequency_label": f"{len(traded_early)} of {total} games ({freq * 100:.1f}%)",
        "impact": round(impact, 1),
        "impact_label": f"Win rate {wr_traded:.1f}% with early trade vs {wr_not_traded:.1f}% without",
        "detail": {
            "games_with_trade": len(traded_early),
            "games_without_trade": len(not_traded_early),
            "win_rate_with_trade": round(wr_traded, 1),
            "win_rate_without_trade": round(wr_not_traded, 1),
        },
        "example_game_ids": example_ids,
        "severity": _severity(abs(impact)),
    }


def detect_piece_retreats(db: Session) -> dict:
    """When eval drops, how often does the player's next move retreat a piece?"""
    analyzed_game_ids = [r[0] for r in db.query(GameSummary.game_id).all()]
    if not analyzed_game_ids:
        return _empty_pattern("piece_retreats_under_pressure")

    retreat_count = 0
    non_retreat_count = 0
    retreat_eval_deltas = []
    non_retreat_eval_deltas = []
    retreat_game_ids = defaultdict(int)

    for game_id in analyzed_game_ids:
        moves = db.query(MoveAnalysis).filter(
            MoveAnalysis.game_id == game_id,
        ).order_by(MoveAnalysis.ply).all()

        for i, move in enumerate(moves):
            if not move.is_player_move:
                continue
            # Look for opponent's previous move causing eval drop for player
            if i == 0:
                continue
            prev = moves[i - 1]
            if prev.is_player_move:
                continue
            if prev.eval_after is None or prev.eval_before is None:
                continue
            # Did the opponent's move hurt the player? (eval_after from player perspective drops)
            if move.eval_before is not None and prev.eval_before is not None:
                pressure = prev.eval_before - move.eval_before
                if pressure < -30:  # Opponent gained > 30cp advantage
                    # Check if player's response is a retreat (piece moves backward)
                    is_retreat = _is_retreat_move(move, moves, i)
                    if is_retreat:
                        retreat_count += 1
                        if move.eval_delta is not None:
                            retreat_eval_deltas.append(move.eval_delta)
                        retreat_game_ids[game_id] += 1
                    else:
                        non_retreat_count += 1
                        if move.eval_delta is not None:
                            non_retreat_eval_deltas.append(move.eval_delta)

    total = retreat_count + non_retreat_count
    if total == 0:
        return _empty_pattern("piece_retreats_under_pressure")

    freq = retreat_count / total
    avg_retreat_delta = sum(retreat_eval_deltas) / len(retreat_eval_deltas) if retreat_eval_deltas else 0
    avg_nonretreat_delta = sum(non_retreat_eval_deltas) / len(non_retreat_eval_deltas) if non_retreat_eval_deltas else 0
    impact = avg_retreat_delta - avg_nonretreat_delta

    top_games = sorted(retreat_game_ids.items(), key=lambda x: -x[1])[:5]
    example_ids = [gid for gid, _ in top_games]

    return {
        "pattern_name": "piece_retreats_under_pressure",
        "description": "Retreating pieces when under pressure instead of counter-attacking",
        "frequency": round(freq * 100, 1),
        "frequency_label": f"Retreats {retreat_count} of {total} pressure situations ({freq * 100:.1f}%)",
        "impact": round(impact, 1),
        "impact_label": f"Avg eval delta on retreat: {avg_retreat_delta:.0f}cp vs counter: {avg_nonretreat_delta:.0f}cp",
        "detail": {
            "retreat_count": retreat_count,
            "non_retreat_count": non_retreat_count,
            "avg_eval_delta_retreat": round(avg_retreat_delta, 1),
            "avg_eval_delta_counter": round(avg_nonretreat_delta, 1),
        },
        "example_game_ids": example_ids,
        "severity": _severity(abs(impact) / 10) if impact else "low",
    }


def _is_retreat_move(move: MoveAnalysis, all_moves: list, idx: int) -> bool:
    """Determine if a move is a backward piece retreat by UCI coordinates."""
    uci = move.move_played
    if not uci or len(uci) < 4:
        return False

    # Skip pawn moves and castling
    san = move.move_played_san
    if san and san[0].islower() and san[0] != 'o':
        return False  # pawn move
    if san and san.startswith('O'):
        return False  # castling

    from_rank = int(uci[1])
    to_rank = int(uci[3])

    # Determine direction based on color
    if move.color and move.color.value == "white":
        return to_rank < from_rank  # White retreating = moving to lower rank
    else:
        return to_rank > from_rank  # Black retreating = moving to higher rank


def detect_same_piece_twice_opening(db: Session) -> dict:
    """In ply 1-20, detect when the same piece moves more than once
    before all minor pieces are developed."""
    games = db.query(Game).filter(Game.time_class == "blitz").all()
    if not games:
        return _empty_pattern("same_piece_twice_opening")

    games_with_repeat = []
    games_without_repeat = []

    for game in games:
        try:
            _, sans, boards = _parse_pgn_moves(game.pgn)
            if not sans:
                continue

            player_is_white = game.player_color.value == "white"
            piece_move_counts = defaultdict(int)
            moved_same_piece_twice = False

            for ply_idx in range(min(20, len(sans))):
                is_white_move = (ply_idx % 2 == 0)
                is_player_move = (is_white_move == player_is_white)
                if not is_player_move:
                    continue

                san = sans[ply_idx]
                # Skip castling
                if san.startswith('O'):
                    continue

                board_before = boards[ply_idx]
                # Get the UCI move to identify which piece moved
                pgn_game = chess.pgn.read_game(io.StringIO(game.pgn))
                if not pgn_game:
                    break

                temp_board = pgn_game.board()
                uci_move = None
                for j, mv in enumerate(pgn_game.mainline_moves()):
                    if j == ply_idx:
                        uci_move = mv.uci()
                        break
                    temp_board.push(mv)

                if not uci_move:
                    continue

                from_sq = uci_move[:2]
                piece = board_before.piece_at(chess.parse_square(from_sq))
                if piece and piece.piece_type != chess.PAWN:
                    piece_key = f"{piece.symbol()}_{from_sq[0]}"  # e.g., N_g for knight from g-file
                    piece_move_counts[piece_key] += 1
                    if piece_move_counts[piece_key] > 1:
                        moved_same_piece_twice = True

            if moved_same_piece_twice:
                games_with_repeat.append(game)
            else:
                games_without_repeat.append(game)
        except Exception:
            continue

    total = len(games_with_repeat) + len(games_without_repeat)
    if total == 0:
        return _empty_pattern("same_piece_twice_opening")

    freq = len(games_with_repeat) / total
    wr_repeat = _win_rate(games_with_repeat)
    wr_no_repeat = _win_rate(games_without_repeat)
    impact = wr_repeat - wr_no_repeat

    example_ids = [g.id for g in games_with_repeat[:5]]

    return {
        "pattern_name": "same_piece_twice_opening",
        "description": "Moving the same piece twice in the opening before completing development",
        "frequency": round(freq * 100, 1),
        "frequency_label": f"{len(games_with_repeat)} of {total} games ({freq * 100:.1f}%)",
        "impact": round(impact, 1),
        "impact_label": f"Win rate {wr_repeat:.1f}% with repeat vs {wr_no_repeat:.1f}% without",
        "detail": {
            "games_with_repeat": len(games_with_repeat),
            "games_without_repeat": len(games_without_repeat),
            "win_rate_with_repeat": round(wr_repeat, 1),
            "win_rate_without_repeat": round(wr_no_repeat, 1),
        },
        "example_game_ids": example_ids,
        "severity": _severity(abs(impact)),
    }


def detect_pawn_storms_castled_king(db: Session) -> dict:
    """Detect pushing pawns in front of own castled king."""
    games = db.query(Game).filter(Game.time_class == "blitz").all()
    if not games:
        return _empty_pattern("pawn_storms_castled_king")

    storm_games = []
    no_storm_games = []

    for game in games:
        try:
            pgn_game = chess.pgn.read_game(io.StringIO(game.pgn))
            if not pgn_game:
                continue

            player_is_white = game.player_color.value == "white"
            board = pgn_game.board()
            castled = False
            castled_side = None  # 'kingside' or 'queenside'
            pawn_storm_detected = False

            for ply_idx, move in enumerate(pgn_game.mainline_moves()):
                is_white_move = (ply_idx % 2 == 0)
                is_player_move = (is_white_move == player_is_white)
                san = board.san(move)

                if is_player_move:
                    # Detect castling
                    if san == 'O-O':
                        castled = True
                        castled_side = 'kingside'
                    elif san == 'O-O-O':
                        castled = True
                        castled_side = 'queenside'

                    # After castling, check for pawn storms in front of own king
                    if castled and not pawn_storm_detected:
                        uci = move.uci()
                        from_sq = uci[:2]
                        piece = board.piece_at(chess.parse_square(from_sq))

                        if piece and piece.piece_type == chess.PAWN:
                            file = from_sq[0]
                            if castled_side == 'kingside' and file in ('f', 'g', 'h'):
                                pawn_storm_detected = True
                            elif castled_side == 'queenside' and file in ('a', 'b', 'c'):
                                pawn_storm_detected = True

                board.push(move)

            if pawn_storm_detected:
                storm_games.append(game)
            elif castled:
                no_storm_games.append(game)
        except Exception:
            continue

    total = len(storm_games) + len(no_storm_games)
    if total == 0:
        return _empty_pattern("pawn_storms_castled_king")

    freq = len(storm_games) / total
    wr_storm = _win_rate(storm_games)
    wr_no_storm = _win_rate(no_storm_games)
    impact = wr_storm - wr_no_storm

    example_ids = [g.id for g in storm_games[:5]]

    return {
        "pattern_name": "pawn_storms_castled_king",
        "description": "Pushing pawns in front of your own castled king",
        "frequency": round(freq * 100, 1),
        "frequency_label": f"{len(storm_games)} of {total} castled games ({freq * 100:.1f}%)",
        "impact": round(impact, 1),
        "impact_label": f"Win rate {wr_storm:.1f}% with pawn storm vs {wr_no_storm:.1f}% without",
        "detail": {
            "storm_games": len(storm_games),
            "non_storm_castled_games": len(no_storm_games),
            "win_rate_storm": round(wr_storm, 1),
            "win_rate_no_storm": round(wr_no_storm, 1),
        },
        "example_game_ids": example_ids,
        "severity": _severity(abs(impact)),
    }


def detect_endgame_avoidance(db: Session) -> dict:
    """Compare games reaching endgame vs those ending in middlegame via
    resignation, timeout, or blunder."""
    analyzed_ids = [r[0] for r in db.query(GameSummary.game_id).all()]
    if not analyzed_ids:
        # Fallback: use total_moves as proxy (short games rarely reach endgame)
        games = db.query(Game).filter(Game.time_class == "blitz").all()
        if not games:
            return _empty_pattern("endgame_avoidance")

        short_games = [g for g in games if g.total_moves and g.total_moves <= 25]
        long_games = [g for g in games if g.total_moves and g.total_moves > 25]
        total = len(short_games) + len(long_games)
        if total == 0:
            return _empty_pattern("endgame_avoidance")

        freq = len(short_games) / total
        wr_short = _win_rate(short_games)
        wr_long = _win_rate(long_games)

        return {
            "pattern_name": "endgame_avoidance",
            "description": "Games ending before reaching the endgame phase",
            "frequency": round(freq * 100, 1),
            "frequency_label": f"{len(short_games)} of {total} games end in ≤25 moves ({freq * 100:.1f}%)",
            "impact": round(wr_short - wr_long, 1),
            "impact_label": f"Win rate {wr_short:.1f}% in short games vs {wr_long:.1f}% in long games",
            "detail": {
                "short_games": len(short_games),
                "long_games": len(long_games),
                "win_rate_short": round(wr_short, 1),
                "win_rate_long": round(wr_long, 1),
                "note": "Based on move count (analysis needed for phase detection)",
            },
            "example_game_ids": [g.id for g in short_games[:5]],
            "severity": _severity(abs(wr_short - wr_long)),
        }

    # With analysis data: check which phase the game ended in
    games_ending_middlegame = []
    games_reaching_endgame = []

    for game_id in analyzed_ids:
        game = db.get(Game, game_id)
        if not game:
            continue
        last_move = db.query(MoveAnalysis).filter(
            MoveAnalysis.game_id == game_id,
        ).order_by(MoveAnalysis.ply.desc()).first()

        if not last_move:
            continue

        if last_move.game_phase == GamePhase.endgame:
            games_reaching_endgame.append(game)
        else:
            games_ending_middlegame.append(game)

    total = len(games_ending_middlegame) + len(games_reaching_endgame)
    if total == 0:
        return _empty_pattern("endgame_avoidance")

    freq = len(games_ending_middlegame) / total
    wr_mid = _win_rate(games_ending_middlegame)
    wr_end = _win_rate(games_reaching_endgame)
    impact = wr_mid - wr_end

    example_ids = [g.id for g in games_ending_middlegame[:5]]

    return {
        "pattern_name": "endgame_avoidance",
        "description": "Games ending in the middlegame via resignation/timeout/blunder before reaching endgame",
        "frequency": round(freq * 100, 1),
        "frequency_label": f"{len(games_ending_middlegame)} of {total} analyzed games end before endgame ({freq * 100:.1f}%)",
        "impact": round(impact, 1),
        "impact_label": f"Win rate {wr_mid:.1f}% (middlegame end) vs {wr_end:.1f}% (reached endgame)",
        "detail": {
            "games_ending_middlegame": len(games_ending_middlegame),
            "games_reaching_endgame": len(games_reaching_endgame),
            "win_rate_middlegame_end": round(wr_mid, 1),
            "win_rate_endgame": round(wr_end, 1),
        },
        "example_game_ids": example_ids,
        "severity": _severity(abs(impact)),
    }


def detect_losing_streak_behavior(db: Session) -> dict:
    """After a loss, does CPL increase? After 2+ consecutive losses, how bad?
    Group games by session (within 60 min of each other)."""
    # Get games in chronological order with summaries
    games = db.query(Game).filter(
        Game.time_class == "blitz",
    ).order_by(Game.end_time).all()

    if len(games) < 10:
        return _empty_pattern("losing_streak_behavior")

    # Build session groups (games within 60 min of each other)
    sessions = []
    current_session = [games[0]]
    for g in games[1:]:
        prev = current_session[-1]
        if g.end_time and prev.end_time:
            gap = (g.end_time - prev.end_time).total_seconds()
            if gap < 3600:
                current_session.append(g)
                continue
        sessions.append(current_session)
        current_session = [g]
    sessions.append(current_session)

    # Analyze CPL after losses vs wins (need GameSummary data)
    analyzed_ids = {r[0] for r in db.query(GameSummary.game_id).all()}
    summary_map = {}
    for gs in db.query(GameSummary).all():
        summary_map[gs.game_id] = gs

    cpl_after_loss = []
    cpl_after_win = []
    cpl_after_2_losses = []
    games_after_2_losses = []

    for session in sessions:
        consecutive_losses = 0
        for i, game in enumerate(session):
            if i > 0 and game.id in summary_map:
                s = summary_map[game.id]
                if s.avg_centipawn_loss is not None:
                    prev_result = session[i - 1].result
                    if prev_result == GameResult.loss:
                        cpl_after_loss.append(s.avg_centipawn_loss)
                    elif prev_result == GameResult.win:
                        cpl_after_win.append(s.avg_centipawn_loss)

                    if consecutive_losses >= 2:
                        cpl_after_2_losses.append(s.avg_centipawn_loss)
                        games_after_2_losses.append(game)

            if game.result == GameResult.loss:
                consecutive_losses += 1
            else:
                consecutive_losses = 0

    # Also compute win rate after loss vs after win (no analysis needed)
    wr_after_loss_games = []
    wr_after_win_games = []
    wr_after_2_loss_games = []

    for session in sessions:
        consecutive_losses = 0
        for i, game in enumerate(session):
            if i > 0:
                prev_result = session[i - 1].result
                if prev_result == GameResult.loss:
                    wr_after_loss_games.append(game)
                elif prev_result == GameResult.win:
                    wr_after_win_games.append(game)

                if consecutive_losses >= 2:
                    wr_after_2_loss_games.append(game)

            if game.result == GameResult.loss:
                consecutive_losses += 1
            else:
                consecutive_losses = 0

    avg_cpl_after_loss = sum(cpl_after_loss) / len(cpl_after_loss) if cpl_after_loss else None
    avg_cpl_after_win = sum(cpl_after_win) / len(cpl_after_win) if cpl_after_win else None
    avg_cpl_after_2 = sum(cpl_after_2_losses) / len(cpl_after_2_losses) if cpl_after_2_losses else None

    wr_after_loss = _win_rate(wr_after_loss_games)
    wr_after_win = _win_rate(wr_after_win_games)
    wr_after_2_loss = _win_rate(wr_after_2_loss_games)

    impact = wr_after_loss - wr_after_win

    return {
        "pattern_name": "losing_streak_behavior",
        "description": "Performance degradation after losses — tilt detection",
        "frequency": round(len(wr_after_loss_games) / len(games) * 100, 1) if games else 0,
        "frequency_label": f"{len(wr_after_loss_games)} games played immediately after a loss",
        "impact": round(impact, 1),
        "impact_label": f"Win rate after loss: {wr_after_loss:.1f}% vs after win: {wr_after_win:.1f}%",
        "detail": {
            "total_sessions": len(sessions),
            "avg_games_per_session": round(sum(len(s) for s in sessions) / len(sessions), 1),
            "win_rate_after_loss": round(wr_after_loss, 1),
            "win_rate_after_win": round(wr_after_win, 1),
            "win_rate_after_2_consecutive_losses": round(wr_after_2_loss, 1),
            "avg_cpl_after_loss": round(avg_cpl_after_loss, 1) if avg_cpl_after_loss else None,
            "avg_cpl_after_win": round(avg_cpl_after_win, 1) if avg_cpl_after_win else None,
            "avg_cpl_after_2_consecutive_losses": round(avg_cpl_after_2, 1) if avg_cpl_after_2 else None,
            "games_after_2_consecutive_losses": len(wr_after_2_loss_games),
        },
        "example_game_ids": [g.id for g in games_after_2_losses[:5]] if games_after_2_losses else [],
        "severity": _severity(abs(impact)),
    }


def detect_time_trouble(db: Session) -> dict:
    """Parse %clk from PGN. Detect games where player had <30s remaining.
    Compare blunder rate in time trouble vs adequate time."""
    # Only query analyzed games that have move analysis
    analyzed_ids = {r[0] for r in db.query(GameSummary.game_id).all()}

    games = db.query(Game).filter(
        Game.time_class == "blitz",
    ).all()

    if not games:
        return _empty_pattern("time_trouble_correlation")

    time_trouble_games = []
    adequate_time_games = []
    time_trouble_blunders = 0
    time_trouble_moves = 0
    adequate_blunders = 0
    adequate_moves = 0

    for game in games:
        clocks = parse_clocks_from_pgn(game.pgn)
        if not clocks:
            continue

        player_is_white = game.player_color.value == "white"

        # Player clocks are at even indices (0,2,4...) for white, odd for black
        player_clocks = clocks[0::2] if player_is_white else clocks[1::2]

        if not player_clocks:
            continue

        min_time = min(player_clocks)
        had_time_trouble = min_time < 30.0

        if had_time_trouble:
            time_trouble_games.append(game)
        else:
            adequate_time_games.append(game)

        # If we have analysis, count blunders in time trouble vs adequate time
        if game.id in analyzed_ids:
            moves = db.query(MoveAnalysis).filter(
                MoveAnalysis.game_id == game.id,
                MoveAnalysis.is_player_move == True,
            ).order_by(MoveAnalysis.ply).all()

            for i, move in enumerate(moves):
                # Map move index to clock index
                clock_idx = i
                if clock_idx < len(player_clocks):
                    remaining = player_clocks[clock_idx]
                    is_blunder = move.classification in (
                        MoveClassification.blunder, MoveClassification.mistake
                    )
                    if remaining < 30:
                        time_trouble_moves += 1
                        if is_blunder:
                            time_trouble_blunders += 1
                    else:
                        adequate_moves += 1
                        if is_blunder:
                            adequate_blunders += 1

    total = len(time_trouble_games) + len(adequate_time_games)
    if total == 0:
        return _empty_pattern("time_trouble_correlation")

    freq = len(time_trouble_games) / total
    wr_trouble = _win_rate(time_trouble_games)
    wr_adequate = _win_rate(adequate_time_games)
    impact = wr_trouble - wr_adequate

    blunder_rate_trouble = (time_trouble_blunders / time_trouble_moves * 100) if time_trouble_moves > 0 else None
    blunder_rate_adequate = (adequate_blunders / adequate_moves * 100) if adequate_moves > 0 else None

    example_ids = [g.id for g in time_trouble_games[:5]]

    return {
        "pattern_name": "time_trouble_correlation",
        "description": "Performance when clock drops below 30 seconds",
        "frequency": round(freq * 100, 1),
        "frequency_label": f"{len(time_trouble_games)} of {total} games enter time trouble ({freq * 100:.1f}%)",
        "impact": round(impact, 1),
        "impact_label": f"Win rate {wr_trouble:.1f}% in time trouble vs {wr_adequate:.1f}% with adequate time",
        "detail": {
            "games_in_time_trouble": len(time_trouble_games),
            "games_with_adequate_time": len(adequate_time_games),
            "win_rate_time_trouble": round(wr_trouble, 1),
            "win_rate_adequate_time": round(wr_adequate, 1),
            "blunder_rate_time_trouble": round(blunder_rate_trouble, 1) if blunder_rate_trouble is not None else None,
            "blunder_rate_adequate_time": round(blunder_rate_adequate, 1) if blunder_rate_adequate is not None else None,
            "time_trouble_moves_analyzed": time_trouble_moves,
            "adequate_moves_analyzed": adequate_moves,
        },
        "example_game_ids": example_ids,
        "severity": _severity(abs(impact)),
    }


def detect_first_move_syndrome(db: Session) -> dict:
    """How often does the player's move match Stockfish's #1 vs #2/#3?
    Track by game phase."""
    analyzed_ids = [r[0] for r in db.query(GameSummary.game_id).all()]
    if not analyzed_ids:
        return _empty_pattern("first_move_syndrome")

    phase_stats = defaultdict(lambda: {"total": 0, "matched_best": 0, "matched_top3": 0})

    for game_id in analyzed_ids:
        moves = db.query(MoveAnalysis).filter(
            MoveAnalysis.game_id == game_id,
            MoveAnalysis.is_player_move == True,
        ).all()

        for move in moves:
            phase = move.game_phase.value if move.game_phase else "unknown"
            phase_stats[phase]["total"] += 1

            if move.move_played == move.best_move:
                phase_stats[phase]["matched_best"] += 1
            elif move.top_3_lines:
                top3_moves_san = [line["moves"][0] if line.get("moves") else None for line in move.top_3_lines]
                if move.move_played_san in top3_moves_san:
                    phase_stats[phase]["matched_top3"] += 1

    total_moves = sum(p["total"] for p in phase_stats.values())
    total_best = sum(p["matched_best"] for p in phase_stats.values())
    total_top3 = sum(p["matched_top3"] for p in phase_stats.values())

    if total_moves == 0:
        return _empty_pattern("first_move_syndrome")

    best_pct = total_best / total_moves * 100
    top3_pct = (total_best + total_top3) / total_moves * 100

    phase_breakdown = {}
    for phase, stats in phase_stats.items():
        if stats["total"] > 0:
            phase_breakdown[phase] = {
                "total_moves": stats["total"],
                "matched_best_pct": round(stats["matched_best"] / stats["total"] * 100, 1),
                "matched_top3_pct": round(
                    (stats["matched_best"] + stats["matched_top3"]) / stats["total"] * 100, 1
                ),
            }

    return {
        "pattern_name": "first_move_syndrome",
        "description": "How often the player finds Stockfish's best move vs settling for 2nd/3rd best",
        "frequency": round(best_pct, 1),
        "frequency_label": f"Plays the #1 move {best_pct:.1f}% of the time ({total_best}/{total_moves})",
        "impact": round(100 - best_pct, 1),
        "impact_label": f"Misses best move {100 - best_pct:.1f}% of the time; top-3 match: {top3_pct:.1f}%",
        "detail": {
            "best_move_match_pct": round(best_pct, 1),
            "top3_match_pct": round(top3_pct, 1),
            "total_player_moves_analyzed": total_moves,
            "by_phase": phase_breakdown,
        },
        "example_game_ids": analyzed_ids[:5],
        "severity": "medium" if best_pct < 40 else "low",
    }


# ── Aggregator ──

def detect_all_patterns(db: Session) -> list[dict]:
    """Run all 8 behavioral pattern detectors and return combined results."""
    detectors = [
        ("early_queen_trades", detect_early_queen_trades),
        ("piece_retreats", detect_piece_retreats),
        ("same_piece_twice", detect_same_piece_twice_opening),
        ("pawn_storms", detect_pawn_storms_castled_king),
        ("endgame_avoidance", detect_endgame_avoidance),
        ("losing_streak", detect_losing_streak_behavior),
        ("time_trouble", detect_time_trouble),
        ("first_move_syndrome", detect_first_move_syndrome),
    ]

    results = []
    for name, detector in detectors:
        try:
            logger.info(f"Running behavioral detector: {name}")
            result = detector(db)
            results.append(result)
        except Exception as e:
            logger.error(f"Detector {name} failed: {e}")
            results.append(_empty_pattern(name, error=str(e)))

    # Sort by absolute impact (highest first)
    results.sort(key=lambda r: abs(r.get("impact", 0)), reverse=True)
    return results


# ── Helpers ──

def _win_rate(games: list) -> float:
    if not games:
        return 0.0
    wins = sum(1 for g in games if g.result == GameResult.win)
    return wins / len(games) * 100


def _severity(impact_pct: float) -> str:
    if impact_pct >= 10:
        return "high"
    elif impact_pct >= 5:
        return "medium"
    return "low"


def _empty_pattern(name: str, error: str | None = None) -> dict:
    return {
        "pattern_name": name,
        "description": "",
        "frequency": 0,
        "frequency_label": "Insufficient data",
        "impact": 0,
        "impact_label": "Insufficient data" if not error else f"Error: {error}",
        "detail": {},
        "example_game_ids": [],
        "severity": "low",
    }
