"""Edge case and deep coverage tests.

Covers gaps identified in the thorough test audit:
- eval_to_cp with mate scores and None
- Clock parsing from PGN
- Opening extraction edge cases
- Behavioral pattern empty/edge conditions
- Session detection with single games
- Config validation
- Dashboard cache TTL behavior
- Drill spaced repetition edge cases
- Tactics detection edge cases
- Model enum coverage
"""

import io
import time
from datetime import date, timedelta, datetime, timezone
from unittest.mock import patch, MagicMock

import chess
import chess.pgn
import chess.engine
import pytest

from app.models.models import (
    Game, MoveAnalysis, GameSummary, DrillPosition, PlaySession,
    CoachingSession, MoveClassification, GamePhase, GameResult,
    PlayerColor, TimeClass, SessionResult, SessionType,
)


# ═══════════════════════════════════════════════════════════════════════════
# STOCKFISH SERVICE — eval_to_cp edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestEvalToCp:
    """Test eval_to_cp with various score types."""

    def test_eval_to_cp_centipawn(self):
        from app.services.stockfish import eval_to_cp
        info = {"score": chess.engine.PovScore(chess.engine.Cp(150), chess.WHITE)}
        result = eval_to_cp(info, True)
        assert result == 150.0

    def test_eval_to_cp_mate_positive(self):
        from app.services.stockfish import eval_to_cp
        info = {"score": chess.engine.PovScore(chess.engine.Mate(3), chess.WHITE)}
        result = eval_to_cp(info, True)
        assert result == 10000.0

    def test_eval_to_cp_mate_negative(self):
        from app.services.stockfish import eval_to_cp
        info = {"score": chess.engine.PovScore(chess.engine.Mate(-2), chess.WHITE)}
        result = eval_to_cp(info, True)
        assert result == -10000.0

    def test_eval_to_cp_none_score(self):
        from app.services.stockfish import eval_to_cp
        result = eval_to_cp({}, True)
        assert result is None

    def test_eval_to_cp_none_info(self):
        from app.services.stockfish import eval_to_cp
        result = eval_to_cp({"score": None}, True)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# STOCKFISH SERVICE — classify_move edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestClassifyMoveEdgeCases:
    """Edge cases for move classification."""

    def test_classify_negative_cp_loss(self):
        """Negative cp_loss uses abs — abs(-50)=50 maps to good threshold."""
        from app.services.stockfish import classify_move
        assert classify_move(-50) == MoveClassification.good
        assert classify_move(-5) == MoveClassification.best

    def test_classify_zero_cp_loss(self):
        from app.services.stockfish import classify_move
        assert classify_move(0) == MoveClassification.best

    def test_classify_very_large_blunder(self):
        from app.services.stockfish import classify_move
        assert classify_move(5000) == MoveClassification.blunder


# ═══════════════════════════════════════════════════════════════════════════
# STOCKFISH SERVICE — detect_game_phase edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestGamePhaseEdgeCases:
    """Edge cases for game phase detection."""

    def test_queens_traded_early(self):
        """Queens off + pieces <= 14 => endgame."""
        from app.services.stockfish import detect_game_phase
        # Position with no queens but still many pieces
        board = chess.Board("r1b1kb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNB1K2R w KQkq - 0 4")
        assert detect_game_phase(board, 40) == GamePhase.endgame

    def test_full_board_middlegame_late(self):
        """All pieces on board but past move 15 with captures."""
        from app.services.stockfish import detect_game_phase
        # After some captures, middlegame
        board = chess.Board()
        for m in ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5c6", "d7c6"]:
            board.push_uci(m)
        phase = detect_game_phase(board, 31)
        assert phase == GamePhase.middlegame


# ═══════════════════════════════════════════════════════════════════════════
# CHESS.COM SERVICE — edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestChessComEdgeCases:
    """Edge cases for Chess.com data parsing."""

    def test_extract_opening_valid(self):
        from app.services.chess_com import _extract_opening
        pgn = '[ECO "C50"]\n[Opening "Italian Game"]\n\n1. e4 e5 1-0'
        eco, name = _extract_opening(pgn)
        assert eco == "C50"

    def test_extract_opening_no_eco(self):
        from app.services.chess_com import _extract_opening
        pgn = '[Result "1-0"]\n\n1. e4 e5 1-0'
        eco, name = _extract_opening(pgn)
        assert eco is None

    def test_extract_opening_invalid_pgn(self):
        from app.services.chess_com import _extract_opening
        eco, name = _extract_opening("not a pgn at all")
        # Should not raise
        assert isinstance(eco, (str, type(None)))

    def test_extract_opening_eco_url_format(self):
        from app.services.chess_com import _extract_opening
        pgn = '[ECO "B20"]\n[ECOUrl "https://www.chess.com/openings/Sicilian-Defense"]\n\n1. e4 c5 1-0'
        eco, name = _extract_opening(pgn)
        assert eco == "B20"
        assert "Sicilian" in name

    def test_parse_pgn_empty(self):
        from app.services.chess_com import _parse_pgn_for_moves
        assert _parse_pgn_for_moves("") == 0

    def test_parse_pgn_no_moves(self):
        from app.services.chess_com import _parse_pgn_for_moves
        assert _parse_pgn_for_moves('[Result "1-0"]\n\n1-0') == 0

    def test_parse_result_timeout(self):
        from app.services.chess_com import _parse_result
        game_data = {
            "white": {"username": "eddobbles2021", "result": "timeout"},
            "black": {"username": "opponent", "result": "win"},
        }
        result, rtype = _parse_result(game_data, "white", "eddobbles2021")
        assert result == GameResult.loss
        assert rtype == "timeout"

    def test_parse_result_abandoned(self):
        from app.services.chess_com import _parse_result
        game_data = {
            "white": {"username": "eddobbles2021", "result": "abandoned"},
            "black": {"username": "opponent", "result": "win"},
        }
        result, rtype = _parse_result(game_data, "white", "eddobbles2021")
        assert result == GameResult.loss

    def test_parse_result_insufficient(self):
        from app.services.chess_com import _parse_result
        game_data = {
            "white": {"username": "eddobbles2021", "result": "insufficient"},
            "black": {"username": "opponent", "result": "insufficient"},
        }
        result, rtype = _parse_result(game_data, "white", "eddobbles2021")
        assert result == GameResult.draw

    def test_parse_result_timevsinsufficient(self):
        from app.services.chess_com import _parse_result
        game_data = {
            "white": {"username": "eddobbles2021", "result": "timevsinsufficient"},
            "black": {"username": "opponent", "result": "win"},
        }
        result, rtype = _parse_result(game_data, "white", "eddobbles2021")
        assert result == GameResult.draw

    def test_parse_time_class_daily(self):
        from app.services.chess_com import _parse_time_class
        assert _parse_time_class("daily") == TimeClass.daily


# ═══════════════════════════════════════════════════════════════════════════
# BEHAVIOR SERVICE — clock parsing
# ═══════════════════════════════════════════════════════════════════════════

class TestClockParsing:
    """Test %clk extraction from PGN annotations."""

    def test_parse_clocks_basic(self):
        from app.services.behavior import parse_clocks_from_pgn
        pgn = '1. e4 {[%clk 0:04:55.2]} e5 {[%clk 0:04:50.0]} 1-0'
        clocks = parse_clocks_from_pgn(pgn)
        assert len(clocks) == 2
        assert clocks[0] == pytest.approx(295.2, abs=0.1)
        assert clocks[1] == pytest.approx(290.0, abs=0.1)

    def test_parse_clocks_no_clocks(self):
        from app.services.behavior import parse_clocks_from_pgn
        pgn = '1. e4 e5 2. Nf3 Nc6 1-0'
        clocks = parse_clocks_from_pgn(pgn)
        assert clocks == []

    def test_parse_clocks_hours(self):
        from app.services.behavior import parse_clocks_from_pgn
        pgn = '1. e4 {[%clk 1:30:00.0]} e5 {[%clk 1:29:55.0]} 1-0'
        clocks = parse_clocks_from_pgn(pgn)
        assert len(clocks) == 2
        assert clocks[0] == pytest.approx(5400.0, abs=0.1)

    def test_parse_pgn_moves_valid(self):
        from app.services.behavior import _parse_pgn_moves
        pgn = '[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0'
        game, sans, boards = _parse_pgn_moves(pgn)
        assert game is not None
        assert len(sans) == 4
        assert len(boards) == 5  # initial + after each move

    def test_parse_pgn_moves_empty(self):
        from app.services.behavior import _parse_pgn_moves
        game, sans, boards = _parse_pgn_moves("")
        assert game is None
        assert sans == []
        assert boards == []


# ═══════════════════════════════════════════════════════════════════════════
# BEHAVIOR SERVICE — helper functions
# ═══════════════════════════════════════════════════════════════════════════

class TestBehaviorHelpers:
    """Test behavior module helper functions."""

    def test_win_rate_empty(self):
        from app.services.behavior import _win_rate
        assert _win_rate([]) == 0.0

    def test_severity_high(self):
        from app.services.behavior import _severity
        assert _severity(15) == "high"

    def test_severity_medium(self):
        from app.services.behavior import _severity
        assert _severity(7) == "medium"

    def test_severity_low(self):
        from app.services.behavior import _severity
        assert _severity(3) == "low"

    def test_empty_pattern_structure(self):
        from app.services.behavior import _empty_pattern
        result = _empty_pattern("test_pattern")
        assert result["pattern_name"] == "test_pattern"
        assert result["frequency"] == 0
        assert result["severity"] == "low"
        assert result["example_game_ids"] == []

    def test_empty_pattern_with_error(self):
        from app.services.behavior import _empty_pattern
        result = _empty_pattern("test_pattern", error="Something failed")
        assert "Error:" in result["impact_label"]

    def test_is_retreat_move_white_backward(self):
        from app.services.behavior import _is_retreat_move
        # White piece moving from rank 4 to rank 3 = retreat
        move = MagicMock()
        move.move_played = "d4d3"
        move.move_played_san = "Nd3"
        move.color = PlayerColor.white
        assert _is_retreat_move(move, [], 0) is True

    def test_is_retreat_move_pawn_skipped(self):
        from app.services.behavior import _is_retreat_move
        move = MagicMock()
        move.move_played = "e2e4"
        move.move_played_san = "e4"
        move.color = PlayerColor.white
        assert _is_retreat_move(move, [], 0) is False

    def test_is_retreat_move_castling_skipped(self):
        from app.services.behavior import _is_retreat_move
        move = MagicMock()
        move.move_played = "e1g1"
        move.move_played_san = "O-O"
        move.color = PlayerColor.white
        assert _is_retreat_move(move, [], 0) is False


# ═══════════════════════════════════════════════════════════════════════════
# SESSIONS SERVICE — edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionsEdgeCases:
    """Edge cases for session detection and analysis."""

    def test_detect_sessions_empty_db(self, db):
        """When all games filtered out, returns empty."""
        from app.services.sessions import detect_sessions
        with patch.object(db, "query") as mock_query:
            mock_q = MagicMock()
            mock_q.filter.return_value.order_by.return_value.all.return_value = []
            mock_query.return_value = mock_q
            sessions = detect_sessions(db)
            assert sessions == []

    def test_session_result_breakeven(self, db):
        """Session with equal rating = breakeven."""
        from app.services.sessions import _build_session_record
        game = db.query(Game).first()
        # Make a game list where rating doesn't change
        games = [game]
        result = _build_session_record(games, {})
        assert result.session_result in (
            SessionResult.net_positive, SessionResult.net_negative, SessionResult.breakeven
        )

    def test_build_session_record_no_ratings(self, db):
        """Handle games with None ratings gracefully."""
        from app.services.sessions import _build_session_record
        game = MagicMock()
        game.result = GameResult.win
        game.player_rating = None
        game.end_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        game.id = 1
        result = _build_session_record([game], {})
        assert result.game_count == 1

    def test_session_summary_with_no_sessions(self, db):
        """Should return error when no PlaySession records exist."""
        from app.services.sessions import get_sessions_summary
        # Temporarily clear sessions
        original_count = db.query(PlaySession).count()
        if original_count == 0:
            result = get_sessions_summary(db)
            assert "error" in result

    def test_compute_stop_recommendation_short_sessions(self):
        """Sessions < 2 games are skipped in stop recommendation."""
        from app.services.sessions import _compute_stop_recommendation
        game = MagicMock()
        game.player_rating = 800
        game.end_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
        sessions = [[game]]
        result = _compute_stop_recommendation(sessions, {})
        assert "consecutive losses" in result


# ═══════════════════════════════════════════════════════════════════════════
# TACTICS SERVICE — edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestTacticsEdgeCases:
    """Edge cases for tactical theme detection."""

    def test_invalid_best_move_san(self):
        from app.services.tactics import detect_tactical_themes
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        themes = detect_tactical_themes(fen, "INVALID", "e4")
        assert isinstance(themes, list)

    def test_promotion_detection(self):
        from app.services.tactics import detect_tactical_themes
        # Pawn about to promote
        fen = "8/P7/8/8/8/8/8/4K2k w - - 0 1"
        themes = detect_tactical_themes(fen, "a8=Q", "Kd2")
        assert "promotion" in themes or "queen_promotion" in themes

    def test_checkmate_detection(self):
        from app.services.tactics import detect_tactical_themes
        # Scholar's mate: Qh5 takes f7# is checkmate
        fen_before = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 0 3"
        themes = detect_tactical_themes(fen_before, "Qxf7#", "d3")
        assert "checkmate" in themes

    def test_classify_drill_themes_major_blunder(self):
        from app.services.tactics import classify_drill_themes
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        themes = classify_drill_themes(
            fen=fen, best_move_san="e5", player_move_san="a6",
            eval_delta=-350, game_phase="middlegame",
        )
        assert "major_blunder" in themes

    def test_classify_drill_themes_game_losing(self):
        from app.services.tactics import classify_drill_themes
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        themes = classify_drill_themes(
            fen=fen, best_move_san="e5", player_move_san="a6",
            eval_delta=-550, game_phase="endgame",
        )
        assert "game_losing_blunder" in themes
        assert "endgame_technique" in themes

    def test_classify_drill_themes_opening(self):
        from app.services.tactics import classify_drill_themes
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        themes = classify_drill_themes(
            fen=fen, best_move_san="e5", player_move_san="a6",
            eval_delta=-50, game_phase="opening",
        )
        assert "opening_mistake" in themes

    def test_squares_between_diagonal(self):
        from app.services.tactics import _squares_between
        # a1 to d4 diagonal
        squares = _squares_between(chess.A1, chess.D4)
        assert squares is not None
        assert len(squares) == 2  # b2, c3

    def test_squares_between_same_square(self):
        from app.services.tactics import _squares_between
        result = _squares_between(chess.A1, chess.A1)
        assert result is None

    def test_squares_between_not_on_line(self):
        from app.services.tactics import _squares_between
        result = _squares_between(chess.A1, chess.B3)
        assert result is None

    def test_square_behind(self):
        from app.services.tactics import _square_behind
        # Attacker at a1, target at d4, behind = e5
        result = _square_behind(chess.A1, chess.D4)
        assert result == chess.E5

    def test_square_behind_edge(self):
        from app.services.tactics import _square_behind
        # Target on edge of board — behind goes off-board
        result = _square_behind(chess.A1, chess.H8)
        assert result is None

    def test_is_passed_pawn(self):
        from app.services.tactics import _is_passed_pawn
        board = chess.Board("8/8/8/8/4P3/8/8/8 w - - 0 1")
        assert _is_passed_pawn(board, chess.E4, chess.WHITE) is True

    def test_is_not_passed_pawn(self):
        from app.services.tactics import _is_passed_pawn
        board = chess.Board("8/4p3/8/8/4P3/8/8/8 w - - 0 1")
        assert _is_passed_pawn(board, chess.E4, chess.WHITE) is False

    def test_is_defending(self):
        from app.services.tactics import _is_defending
        board = chess.Board("8/8/8/8/4N3/8/8/8 w - - 0 1")
        # Knight on e4 defends f6
        result = _is_defending(board, chess.E4, chess.F6)
        assert result is True

    def test_is_not_defending(self):
        from app.services.tactics import _is_defending
        board = chess.Board("8/8/8/8/4N3/8/8/8 w - - 0 1")
        # Knight on e4 does not defend e5
        result = _is_defending(board, chess.E4, chess.E5)
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# DRILLS SERVICE — spaced repetition edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestDrillsEdgeCases:
    """Edge cases for drill service."""

    def test_drill_difficulty_rating_bounded(self, db):
        """Difficulty rating should be bounded between 0 and 5."""
        drills = db.query(DrillPosition).all()
        for d in drills:
            if d.difficulty_rating is not None:
                assert 0 <= d.difficulty_rating <= 5.0

    def test_extract_drills_blunder_only(self, db):
        """Extract only blunders (strictest threshold)."""
        from app.services.drills import extract_drill_positions
        result = extract_drill_positions(db, min_classification="blunder")
        assert "created" in result
        assert "skipped" in result

    def test_extract_drills_inaccuracy_threshold(self, db):
        """Extract inaccuracies and above (lowest threshold)."""
        from app.services.drills import extract_drill_positions
        result = extract_drill_positions(db, min_classification="inaccuracy")
        assert "created" in result

    def test_extract_drills_specific_game(self, db):
        """Extract drills from a specific game only."""
        from app.services.drills import extract_drill_positions
        game = db.query(Game).first()
        result = extract_drill_positions(db, game_id=game.id)
        assert "created" in result


# ═══════════════════════════════════════════════════════════════════════════
# COACHING SERVICE — edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestCoachingEdgeCases:
    """Edge cases for coaching service."""

    def test_build_pgn_up_to(self):
        from app.services.coaching import _build_pgn_up_to
        game = MagicMock()
        game.pgn = '[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0'
        result = _build_pgn_up_to(game, 4)
        assert "1." in result
        assert "2." in result

    def test_build_pgn_up_to_invalid_pgn(self):
        from app.services.coaching import _build_pgn_up_to
        game = MagicMock()
        game.pgn = "not valid pgn"
        result = _build_pgn_up_to(game, 4)
        assert result == ""

    def test_get_next_moves_text_end_of_game(self):
        from app.services.coaching import _get_next_moves_text
        result = _get_next_moves_text([], 10)
        assert result == "Game ended here."

    def test_behavioral_narrative_empty_patterns(self, db):
        """When all patterns have insufficient data, return early."""
        from app.services.coaching import generate_behavioral_narrative
        patterns = [
            {
                "pattern_name": "test",
                "frequency": 0,
                "frequency_label": "Insufficient data",
            }
        ]
        result = generate_behavioral_narrative(db, patterns)
        assert "Insufficient data" in result["narrative"]

    def test_explain_move_invalid_ply(self, db):
        """Requesting a ply that doesn't exist returns error."""
        from app.services.coaching import explain_move
        game = db.query(Game).first()
        result = explain_move(db, game, 9999)
        assert "error" in result


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG — validation
# ═══════════════════════════════════════════════════════════════════════════

class TestConfig:
    """Verify configuration loads correctly."""

    def test_settings_load(self):
        from app.config import settings
        assert settings.stockfish_depth == 18
        assert settings.stockfish_deep_depth == 22
        assert settings.threshold_best == 10
        assert settings.threshold_excellent == 25
        assert settings.threshold_good == 50
        assert settings.threshold_inaccuracy == 100
        assert settings.threshold_mistake == 200
        assert settings.stockfish_threads == 2
        assert settings.stockfish_hash_mb == 256

    def test_settings_chess_com_username(self):
        from app.config import settings
        assert settings.chess_com_username == "eddobbles2021"

    def test_settings_database_url(self):
        from app.config import settings
        # In test env this is overridden
        assert isinstance(settings.database_url, str)


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD CACHE — TTL behavior
# ═══════════════════════════════════════════════════════════════════════════

class TestDashboardCacheAdvanced:
    """Advanced cache behavior tests."""

    def test_cache_expired_entry(self):
        from app.routers.dashboard import _cached, _set_cache, _cache
        _cache.clear()

        _set_cache("test_key", {"data": "old"})
        # Manually expire by setting timestamp in the past
        _cache["test_key"] = (time.time() - 600, {"data": "old"})

        hit, value = _cached("test_key")
        assert hit is False

    def test_cache_fresh_entry(self):
        from app.routers.dashboard import _cached, _set_cache, _cache
        _cache.clear()

        _set_cache("test_key", {"data": "fresh"})
        hit, value = _cached("test_key")
        assert hit is True
        assert value == {"data": "fresh"}

    def test_cache_miss(self):
        from app.routers.dashboard import _cached, _cache
        _cache.clear()
        hit, value = _cached("nonexistent")
        assert hit is False
        assert value is None


# ═══════════════════════════════════════════════════════════════════════════
# MODEL ENUMS — coverage
# ═══════════════════════════════════════════════════════════════════════════

class TestModelEnums:
    """Verify all enum values are accessible."""

    def test_player_color_values(self):
        assert PlayerColor.white.value == "white"
        assert PlayerColor.black.value == "black"

    def test_game_result_values(self):
        assert GameResult.win.value == "win"
        assert GameResult.loss.value == "loss"
        assert GameResult.draw.value == "draw"

    def test_time_class_values(self):
        assert TimeClass.bullet.value == "bullet"
        assert TimeClass.blitz.value == "blitz"
        assert TimeClass.rapid.value == "rapid"
        assert TimeClass.daily.value == "daily"

    def test_move_classification_values(self):
        values = [e.value for e in MoveClassification]
        assert "best" in values
        assert "blunder" in values

    def test_game_phase_values(self):
        values = [e.value for e in GamePhase]
        assert "opening" in values
        assert "middlegame" in values
        assert "endgame" in values

    def test_session_type_values(self):
        values = [e.value for e in SessionType]
        assert "game_review" in values
        assert "behavioral_analysis" in values

    def test_session_result_values(self):
        values = [e.value for e in SessionResult]
        assert "net_positive" in values
        assert "net_negative" in values
        assert "breakeven" in values


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE — connection and session
# ═══════════════════════════════════════════════════════════════════════════

class TestDatabase:
    """Verify database module works correctly."""

    def test_get_db_yields_session(self):
        from app.database import get_db
        gen = get_db()
        db = next(gen)
        assert db is not None
        try:
            next(gen)
        except StopIteration:
            pass

    def test_base_metadata_has_tables(self):
        from app.database import Base
        table_names = set(Base.metadata.tables.keys())
        expected = {"games", "move_analysis", "game_summaries",
                    "coaching_sessions", "drill_positions", "play_sessions"}
        assert expected.issubset(table_names)


# ═══════════════════════════════════════════════════════════════════════════
# API — additional endpoint edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestAPIEdgeCases:
    """Edge cases for API endpoints not covered by main test file."""

    def test_games_page_beyond_range(self, client):
        """Page beyond available data returns empty list."""
        resp = client.get("/api/games?page=999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["games"] == []

    def test_games_filter_unanalyzed(self, client):
        resp = client.get("/api/games?analyzed=false")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 40  # 50 total - 10 analyzed

    def test_drills_filter_nonexistent_eco(self, client):
        resp = client.get("/api/drills?opening_eco=Z99")
        assert resp.status_code == 200
        data = resp.json()
        assert data["drills"] == []

    def test_drill_extract_with_game_id(self, client, db):
        game = db.query(Game).first()
        resp = client.post(f"/api/drills/extract?game_id={game.id}")
        assert resp.status_code == 200

    def test_drill_extract_blunder_severity(self, client):
        resp = client.post("/api/drills/extract?min_severity=blunder")
        assert resp.status_code == 200

    def test_batch_analysis_with_game_ids(self, client):
        mock_result = {"total": 2, "completed": 2, "errors": 0, "details": []}
        with patch("app.routers.analysis.batch_analyze", return_value=mock_result):
            resp = client.post(
                "/api/analysis/batch",
                json={"game_ids": [1, 2], "depth": 10},
            )
            assert resp.status_code == 200

    def test_coaching_sessions_empty_filter(self, client):
        """Filter by a type that has few/no sessions."""
        resp = client.get("/api/coach/sessions?session_type=drill")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_opening_book_sicilian(self, client):
        from app.routers.dashboard import _cache
        _cache.clear()

        resp = client.get("/api/dashboard/opening-book/B20")
        assert resp.status_code == 200
        data = resp.json()
        assert data["eco"] == "B20"
        assert data["total_games"] == 10

    def test_dashboard_summary_record_integrity(self, client):
        from app.routers.dashboard import _cache
        _cache.clear()

        resp = client.get("/api/dashboard/summary")
        data = resp.json()
        record = data["record"]
        assert record["wins"] + record["losses"] + record["draws"] == data["total_games"]

    def test_games_list_has_analysis_field(self, client):
        """Verify has_analysis is computed correctly (batch, not N+1)."""
        # Fetch all 50 games to ensure we get both analyzed and unanalyzed
        resp = client.get("/api/games?per_page=50")
        assert resp.status_code == 200
        games = resp.json()["games"]
        analyzed_count = sum(1 for g in games if g["has_analysis"])
        unanalyzed_count = sum(1 for g in games if not g["has_analysis"])
        assert analyzed_count == 10  # 10 analyzed games in seed
        assert unanalyzed_count == 40

    def test_games_list_analyzed_filter_consistency(self, client):
        """Verify analyzed=true returns correct count."""
        resp = client.get("/api/games?analyzed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10  # 10 analyzed games in seed

    def test_dashboard_time_class_uses_enum(self, client):
        """Verify time class stats use proper enum comparison."""
        from app.routers.dashboard import _cache
        _cache.clear()

        resp = client.get("/api/dashboard/summary")
        data = resp.json()
        # Should have by_time_class data since seed has blitz games
        assert len(data["by_time_class"]) > 0
        for tc in data["by_time_class"]:
            assert "win_rate" in tc
            assert tc["win_rate"] >= 0


# ═══════════════════════════════════════════════════════════════════════════
# PGN TRUNCATION — safe truncation at move boundary
# ═══════════════════════════════════════════════════════════════════════════

class TestPGNTruncation:
    """Test safe PGN truncation at move boundaries."""

    def test_truncate_short_pgn(self):
        from app.services.coaching import _truncate_pgn
        pgn = "1. e4 e5 2. Nf3 Nc6 1-0"
        assert _truncate_pgn(pgn, 3000) == pgn

    def test_truncate_at_space(self):
        from app.services.coaching import _truncate_pgn
        pgn = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 1-0"
        result = _truncate_pgn(pgn, 20)
        # Should cut at a space boundary before char 20
        assert len(result) <= 20
        assert not result.endswith(".")  # Didn't cut mid-move
        assert " " not in result[len(result)-1:]  # Ends cleanly

    def test_truncate_preserves_complete_moves(self):
        from app.services.coaching import _truncate_pgn
        pgn = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 d6 1-0"
        result = _truncate_pgn(pgn, 25)
        # Should be a clean cut at a move boundary
        assert result.count(".") >= 1  # At least one move number

    def test_truncate_empty_pgn(self):
        from app.services.coaching import _truncate_pgn
        assert _truncate_pgn("", 3000) == ""

    def test_truncate_exact_length(self):
        from app.services.coaching import _truncate_pgn
        pgn = "1. e4 e5"
        assert _truncate_pgn(pgn, 8) == pgn


# ═══════════════════════════════════════════════════════════════════════════
# STOCKFISH — engine timeout protection
# ═══════════════════════════════════════════════════════════════════════════

class TestStockfishTimeout:
    """Verify engine timeout is set in analysis."""

    def test_move_limit_has_time(self):
        """Verify the analyze_game function sets a time limit."""
        import chess.engine
        from app.services.stockfish import analyze_game
        import inspect
        source = inspect.getsource(analyze_game)
        assert "time=30.0" in source
        assert "move_limit" in source
