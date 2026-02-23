"""Tactical theme detection for chess positions.

Analyzes positions using python-chess to detect common tactical patterns
like forks, pins, skewers, back-rank threats, hanging pieces, etc.
Pure position analysis — no engine needed.
"""

import chess
from typing import Optional


def detect_tactical_themes(fen: str, best_move_san: str, player_move_san: str) -> list[str]:
    """
    Detect tactical themes present in a position where the player made a mistake.

    Analyzes:
    1. What the best move accomplishes (what themes the player missed)
    2. What the player's move gave up (what themes the opponent can exploit)

    Returns list of theme strings.
    """
    themes = []
    board = chess.Board(fen)

    try:
        best_move = board.parse_san(best_move_san)
    except (ValueError, chess.InvalidMoveError):
        return themes

    # Analyze the best move (what the player should have played)
    themes.extend(_analyze_move_themes(board, best_move))

    # Analyze what the player's move gave up
    try:
        player_move = board.parse_san(player_move_san)
        themes.extend(_analyze_position_weaknesses(board, player_move))
    except (ValueError, chess.InvalidMoveError):
        pass

    # Analyze the static position for themes
    themes.extend(_analyze_static_position(board))

    return list(set(themes))  # deduplicate


def _analyze_move_themes(board: chess.Board, move: chess.Move) -> list[str]:
    """Detect what tactical themes a move creates."""
    themes = []
    moving_color = board.turn
    opponent_color = not moving_color

    piece = board.piece_at(move.from_square)
    if not piece:
        return themes

    captured = board.piece_at(move.to_square)

    # --- Capture themes ---
    if captured:
        if captured.piece_type > piece.piece_type:
            themes.append("winning_exchange")
        if captured.piece_type == chess.QUEEN:
            themes.append("queen_capture")

    # --- Check themes ---
    board_after = board.copy()
    board_after.push(move)

    if board_after.is_check():
        themes.append("check")
        if board_after.is_checkmate():
            themes.append("checkmate")

        # Discovered check: the moving piece isn't giving the check
        checkers = board_after.checkers()
        if checkers and move.to_square not in checkers:
            themes.append("discovered_check")

        # Double check
        if checkers and len(checkers) > 1:
            themes.append("double_check")

    # --- Fork detection ---
    fork_targets = _detect_fork(board, move)
    if fork_targets:
        themes.append("fork")
        if piece.piece_type == chess.KNIGHT:
            themes.append("knight_fork")
        if chess.KING in fork_targets:
            themes.append("royal_fork")

    # --- Pin detection ---
    if _creates_pin(board, move):
        themes.append("pin")

    # --- Skewer detection ---
    if _creates_skewer(board, move):
        themes.append("skewer")

    # --- Back rank threats ---
    if _is_back_rank_threat(board, move):
        themes.append("back_rank")

    # --- Promotion ---
    if move.promotion:
        themes.append("promotion")
        if move.promotion == chess.QUEEN:
            themes.append("queen_promotion")
        else:
            themes.append("underpromotion")

    # --- Pawn structure themes ---
    if piece.piece_type == chess.PAWN:
        # Passed pawn advance
        if _is_passed_pawn(board, move.to_square, moving_color):
            themes.append("passed_pawn")

    return themes


def _analyze_position_weaknesses(board: chess.Board, player_move: chess.Move) -> list[str]:
    """Detect what weaknesses the player's move creates or ignores."""
    themes = []

    board_after = board.copy()
    board_after.push(player_move)
    opponent = board_after.turn

    # Hanging piece: did the player leave a piece undefended?
    for square in chess.SQUARES:
        piece = board_after.piece_at(square)
        if piece and piece.color != opponent:
            if board_after.is_attacked_by(opponent, square):
                if not board_after.is_attacked_by(not opponent, square):
                    if piece.piece_type != chess.PAWN:
                        themes.append("hanging_piece")
                        break

    # King exposed: moved king or weakened king's pawn shield
    moving_piece = board.piece_at(player_move.from_square)
    if moving_piece and moving_piece.piece_type == chess.KING:
        themes.append("king_walk")

    # Trapped piece: did the move create a trapped piece?
    piece_at_dest = board_after.piece_at(player_move.to_square)
    if piece_at_dest and piece_at_dest.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK):
        legal_escapes = 0
        for m in board_after.legal_moves:
            if m.from_square == player_move.to_square:
                legal_escapes += 1
        if legal_escapes <= 1:
            themes.append("trapped_piece")

    return themes


def _analyze_static_position(board: chess.Board) -> list[str]:
    """Detect static positional themes in the position."""
    themes = []
    color = board.turn

    # King safety
    king_sq = board.king(color)
    if king_sq is not None:
        king_rank = chess.square_rank(king_sq)
        # King in center (hasn't castled) past move 8
        if board.fullmove_number > 8:
            if color == chess.WHITE and king_rank == 0:
                king_file = chess.square_file(king_sq)
                if 2 <= king_file <= 5:  # c1-f1
                    themes.append("king_in_center")
            elif color == chess.BLACK and king_rank == 7:
                king_file = chess.square_file(king_sq)
                if 2 <= king_file <= 5:
                    themes.append("king_in_center")

    # Overloaded piece detection (simplified)
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece and piece.color == color:
            defending_count = 0
            for sq2 in chess.SQUARES:
                other = board.piece_at(sq2)
                if other and other.color == color and sq2 != square:
                    if board.is_attacked_by(not color, sq2):
                        # This piece might be defending sq2
                        if _is_defending(board, square, sq2):
                            defending_count += 1
            if defending_count >= 2:
                themes.append("overloaded_piece")
                break

    return themes


def _detect_fork(board: chess.Board, move: chess.Move) -> list[int]:
    """Detect if a move creates a fork. Returns piece types being forked."""
    board_after = board.copy()
    board_after.push(move)

    moving_piece = board_after.piece_at(move.to_square)
    if not moving_piece:
        return []

    opponent = not moving_piece.color
    attacked_valuable = []

    for square in chess.SQUARES:
        target = board_after.piece_at(square)
        if target and target.color == opponent:
            if board_after.is_attacked_by(moving_piece.color, square):
                # Check if this specific piece attacks the target
                if _piece_attacks_square(board_after, move.to_square, square):
                    if target.piece_type >= chess.ROOK or target.piece_type == chess.KING:
                        attacked_valuable.append(target.piece_type)

    if len(attacked_valuable) >= 2:
        return attacked_valuable
    return []


def _piece_attacks_square(board: chess.Board, from_sq: int, to_sq: int) -> bool:
    """Check if a specific piece attacks a specific square."""
    piece = board.piece_at(from_sq)
    if not piece:
        return False
    attacks = board.attacks(from_sq)
    return to_sq in attacks


def _creates_pin(board: chess.Board, move: chess.Move) -> bool:
    """Detect if a move creates a pin against the opponent's king."""
    board_after = board.copy()
    board_after.push(move)

    opponent = board_after.turn
    king_sq = board_after.king(opponent)
    if king_sq is None:
        return False

    piece = board_after.piece_at(move.to_square)
    if not piece or piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        return False

    # Check if any opponent piece is between this piece and the king
    # along the attack line
    if not _piece_attacks_square(board_after, move.to_square, king_sq):
        # Check if there's exactly one piece between us and the king
        between_squares = _squares_between(move.to_square, king_sq)
        if between_squares is None:
            return False

        opponent_pieces_between = []
        for sq in between_squares:
            p = board_after.piece_at(sq)
            if p and p.color == opponent:
                opponent_pieces_between.append(sq)
            elif p:
                return False  # Friendly piece blocks, not a pin

        return len(opponent_pieces_between) == 1

    return False


def _creates_skewer(board: chess.Board, move: chess.Move) -> bool:
    """Detect if a move creates a skewer (attack through a valuable piece to another)."""
    board_after = board.copy()
    board_after.push(move)

    piece = board_after.piece_at(move.to_square)
    if not piece or piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        return False

    if board_after.is_check():
        # A check that attacks through the king to a piece behind is a skewer
        king_sq = board_after.king(board_after.turn)
        if king_sq is None:
            return False

        # Find what's behind the king on the attack line
        behind = _square_behind(move.to_square, king_sq)
        if behind is not None:
            target = board_after.piece_at(behind)
            if target and target.color == board_after.turn:
                return True

    return False


def _is_back_rank_threat(board: chess.Board, move: chess.Move) -> bool:
    """Detect if a move creates a back rank mate threat."""
    board_after = board.copy()
    board_after.push(move)

    if board_after.is_checkmate():
        opponent = board_after.turn
        king_sq = board_after.king(opponent)
        if king_sq is not None:
            king_rank = chess.square_rank(king_sq)
            if (opponent == chess.WHITE and king_rank == 0) or \
               (opponent == chess.BLACK and king_rank == 7):
                return True

    # Even if not checkmate, check if rook/queen moves to back rank with threats
    piece = board_after.piece_at(move.to_square)
    if piece and piece.piece_type in (chess.ROOK, chess.QUEEN):
        opponent = not piece.color
        opp_back_rank = 0 if opponent == chess.WHITE else 7
        if chess.square_rank(move.to_square) == opp_back_rank:
            return True

    return False


def _is_passed_pawn(board: chess.Board, square: int, color: chess.Color) -> bool:
    """Check if a pawn is passed (no opposing pawns can block or capture it)."""
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    opponent = not color

    for f in range(max(0, file - 1), min(8, file + 2)):
        for r in range(rank, 8 if color == chess.WHITE else -1, 1 if color == chess.WHITE else -1):
            sq = chess.square(f, r)
            if sq == square:
                continue
            piece = board.piece_at(sq)
            if piece and piece.piece_type == chess.PAWN and piece.color == opponent:
                return False
    return True


def _is_defending(board: chess.Board, defender_sq: int, target_sq: int) -> bool:
    """Check if piece at defender_sq defends target_sq."""
    piece = board.piece_at(defender_sq)
    if not piece:
        return False
    return target_sq in board.attacks(defender_sq)


def _squares_between(sq1: int, sq2: int) -> Optional[list[int]]:
    """Get squares between two squares on a line (diagonal, rank, or file)."""
    r1, f1 = chess.square_rank(sq1), chess.square_file(sq1)
    r2, f2 = chess.square_rank(sq2), chess.square_file(sq2)

    dr = 0 if r2 == r1 else (1 if r2 > r1 else -1)
    df = 0 if f2 == f1 else (1 if f2 > f1 else -1)

    if dr == 0 and df == 0:
        return None
    if abs(r2 - r1) != abs(f2 - f1) and r1 != r2 and f1 != f2:
        return None  # Not on a line

    squares = []
    r, f = r1 + dr, f1 + df
    while (r, f) != (r2, f2):
        if 0 <= r < 8 and 0 <= f < 8:
            squares.append(chess.square(f, r))
        r += dr
        f += df
        if len(squares) > 7:
            break
    return squares


def _square_behind(attacker_sq: int, target_sq: int) -> Optional[int]:
    """Get the square directly behind target_sq from attacker_sq's perspective."""
    r1, f1 = chess.square_rank(attacker_sq), chess.square_file(attacker_sq)
    r2, f2 = chess.square_rank(target_sq), chess.square_file(target_sq)

    dr = 0 if r2 == r1 else (1 if r2 > r1 else -1)
    df = 0 if f2 == f1 else (1 if f2 > f1 else -1)

    nr, nf = r2 + dr, f2 + df
    if 0 <= nr < 8 and 0 <= nf < 8:
        return chess.square(nf, nr)
    return None


def classify_drill_themes(fen: str, best_move_san: str, player_move_san: str,
                          eval_delta: float, game_phase: str) -> list[str]:
    """
    High-level theme classifier for drill positions. Combines tactical detection
    with eval context for richer theme labels.

    Returns sorted list of theme strings.
    """
    themes = detect_tactical_themes(fen, best_move_san, player_move_san)

    # Add eval-context themes
    abs_delta = abs(eval_delta) if eval_delta else 0

    if abs_delta >= 500:
        themes.append("game_losing_blunder")
    elif abs_delta >= 300:
        themes.append("major_blunder")

    # Phase-specific themes
    if game_phase == "opening":
        themes.append("opening_mistake")
    elif game_phase == "endgame":
        themes.append("endgame_technique")

    return sorted(set(themes))
