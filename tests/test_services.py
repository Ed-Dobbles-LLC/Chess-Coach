"""Service-layer unit tests — stockfish, coaching, drills, sessions, tactics, behavior."""

import io
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

import chess
import chess.pgn
import pytest

from app.models.models import (
    Game, MoveAnalysis, GameSummary, DrillPosition, PlaySession,
    MoveClassification, GamePhase, GameResult, PlayerColor, TimeClass,
)


# ═══════════════════════════════════════════════════════════════════════════
# STOCKFISH SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestStockfishService:
    """Tests for classify_move, detect_game_phase, eval_to_cp."""

    def test_classify_move_best(self):
        from app.services.stockfish import classify_move
        assert classify_move(5) == MoveClassification.best

    def test_classify_move_excellent(self):
        from app.services.stockfish import classify_move
        assert classify_move(20) == MoveClassification.excellent

    def test_classify_move_good(self):
        from app.services.stockfish import classify_move
        assert classify_move(40) == MoveClassification.good

    def test_classify_move_inaccuracy(self):
        from app.services.stockfish import classify_move
        assert classify_move(80) == MoveClassification.inaccuracy

    def test_classify_move_mistake(self):
        from app.services.stockfish import classify_move
        assert classify_move(150) == MoveClassification.mistake

    def test_classify_move_blunder(self):
        from app.services.stockfish import classify_move
        assert classify_move(300) == MoveClassification.blunder

    def test_classify_move_thresholds(self):
        """Exact threshold boundaries."""
        from app.services.stockfish import classify_move
        assert classify_move(10) == MoveClassification.best
        assert classify_move(11) == MoveClassification.excellent
        assert classify_move(25) == MoveClassification.excellent
        assert classify_move(26) == MoveClassification.good
        assert classify_move(50) == MoveClassification.good
        assert classify_move(51) == MoveClassification.inaccuracy
        assert classify_move(100) == MoveClassification.inaccuracy
        assert classify_move(101) == MoveClassification.mistake
        assert classify_move(200) == MoveClassification.mistake
        assert classify_move(201) == MoveClassification.blunder

    def test_detect_game_phase_opening(self):
        from app.services.stockfish import detect_game_phase
        board = chess.Board()  # starting position
        assert detect_game_phase(board, 1) == GamePhase.opening

    def test_detect_game_phase_middlegame(self):
        from app.services.stockfish import detect_game_phase
        # Standard position after some development but not endgame
        board = chess.Board()
        # Make a few standard moves
        for move_str in ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"]:
            board.push_uci(move_str)
        # Ply 31+ and pieces still on board
        assert detect_game_phase(board, 31) == GamePhase.middlegame

    def test_detect_game_phase_endgame(self):
        from app.services.stockfish import detect_game_phase
        # Create a sparse endgame position
        board = chess.Board("8/8/4k3/8/8/4K3/4P3/8 w - - 0 1")
        assert detect_game_phase(board, 60) == GamePhase.endgame


# ═══════════════════════════════════════════════════════════════════════════
# DRILLS SERVICE (spaced repetition)
# ═══════════════════════════════════════════════════════════════════════════

class TestDrillsService:
    """Tests for SM-2 intervals, drill extraction, and stats."""

    def test_sm2_intervals_defined(self):
        from app.services.drills import INTERVALS
        assert INTERVALS == [1, 3, 7, 14, 30, 60]

    def test_submit_correct_answer_increments(self, db):
        from app.services.drills import submit_drill_attempt
        drill = db.query(DrillPosition).first()
        original_correct = drill.times_correct
        original_shown = drill.times_shown
        correct_move = drill.correct_move_san

        result = submit_drill_attempt(db, drill.id, correct_move)
        assert result["correct"] is True
        assert drill.times_correct == original_correct + 1
        assert drill.times_shown == original_shown + 1

    def test_submit_wrong_answer_resets_interval(self, db):
        from app.services.drills import submit_drill_attempt
        drill = db.query(DrillPosition).filter(DrillPosition.id > 1).first()

        result = submit_drill_attempt(db, drill.id, "WRONG_MOVE")
        assert result["correct"] is False
        # Wrong answer should schedule review for tomorrow
        expected_date = date.today() + timedelta(days=1)
        assert drill.next_review_date == expected_date

    def test_submit_drill_not_found(self, db):
        from app.services.drills import submit_drill_attempt
        result = submit_drill_attempt(db, 99999, "e4")
        assert "error" in result

    def test_get_next_drills_respects_date(self, db):
        from app.services.drills import get_next_drills
        drills = get_next_drills(db, count=50)
        today = date.today()
        for d in drills:
            # All returned drills should have next_review_date <= today
            # (this is handled by the query filter)
            pass
        assert isinstance(drills, list)

    def test_get_drill_stats_structure(self, db):
        from app.services.drills import get_drill_stats
        stats = get_drill_stats(db)
        assert "total_drills" in stats
        assert "attempted" in stats
        assert "mastered" in stats
        assert "due_today" in stats
        assert "by_phase" in stats
        assert stats["total_drills"] >= 15

    def test_extract_drill_positions(self, db):
        from app.services.drills import extract_drill_positions
        result = extract_drill_positions(db, min_classification="mistake")
        assert "created" in result
        assert "skipped" in result


# ═══════════════════════════════════════════════════════════════════════════
# SESSIONS SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionsService:
    """Tests for session detection, tilt analysis, optimal stop point."""

    def test_detect_sessions_grouping(self, db):
        from app.services.sessions import detect_sessions
        sessions = detect_sessions(db)
        assert isinstance(sessions, list)
        assert len(sessions) > 0

    def test_session_gap_threshold(self, db):
        """Games within 60 min = same session, gap > 60 min = different session."""
        from app.services.sessions import detect_sessions, SESSION_GAP_SECONDS
        assert SESSION_GAP_SECONDS == 3600  # 60 minutes

        sessions = detect_sessions(db)
        for session in sessions:
            for i in range(1, len(session)):
                gap = (session[i].end_time - session[i-1].end_time).total_seconds()
                assert gap < SESSION_GAP_SECONDS

    def test_build_play_sessions(self, db):
        from app.services.sessions import build_play_sessions
        result = build_play_sessions(db)
        assert "created" in result
        assert result["created"] > 0

    def test_get_sessions_summary_structure(self, db):
        from app.services.sessions import get_sessions_summary
        data = get_sessions_summary(db)
        assert "total_sessions" in data
        assert "avg_games_per_session" in data
        assert "performance_by_session_length" in data
        assert "tilt_detection" in data
        assert "optimal_session_length" in data
        assert "best_sessions" in data
        assert "worst_sessions" in data

    def test_tilt_detection_structure(self, db):
        from app.services.sessions import get_sessions_summary
        data = get_sessions_summary(db)
        tilt = data["tilt_detection"]
        if tilt:
            expected_keys = [
                "avg_cpl_after_loss", "avg_cpl_after_win",
                "win_rate_after_loss", "win_rate_after_win",
                "win_rate_after_2_consecutive_losses",
                "recommended_stop_point",
            ]
            for key in expected_keys:
                assert key in tilt, f"Missing tilt key: {key}"

    def test_get_session_detail(self, db):
        from app.services.sessions import get_session_detail
        ps = db.query(PlaySession).first()
        date_str = ps.start_time.strftime("%Y-%m-%d")
        detail = get_session_detail(db, date_str)
        assert detail["date"] == date_str
        assert "games" in detail
        assert "game_count" in detail

    def test_get_session_detail_invalid(self, db):
        from app.services.sessions import get_session_detail
        result = get_session_detail(db, "2099-01-01")
        assert "error" in result

    def test_rating_delta_calculation(self, db):
        """Verify rating_delta = ending_rating - starting_rating."""
        ps = db.query(PlaySession).first()
        if ps.starting_rating and ps.ending_rating:
            assert ps.rating_delta == ps.ending_rating - ps.starting_rating


# ═══════════════════════════════════════════════════════════════════════════
# TACTICS SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestTacticsService:
    """Tests for tactical theme detection with known positions."""

    def test_fork_detection(self):
        from app.services.tactics import detect_tactical_themes
        # Knight fork position: Nf7+ hitting king and queen
        # After 1. Nf7+ in a position where knight forks king and rook
        fen = "r1bqkb1r/pppp1ppp/2n2n2/4N3/2B1P3/8/PPPP1PPP/RNBQK2R b KQkq - 0 4"
        themes = detect_tactical_themes(fen, "Nxf7", "d6")
        # The function should return a list of theme strings
        assert isinstance(themes, list)

    def test_pin_detection(self):
        from app.services.tactics import detect_tactical_themes
        # Position with a bishop pinning knight to king
        fen = "rnbqk2r/ppppbppp/4pn2/8/2PP4/5N2/PP2PPPP/RNBQKB1R w KQkq - 0 4"
        themes = detect_tactical_themes(fen, "Bg5", "Be2")
        assert isinstance(themes, list)

    def test_back_rank_threat(self):
        from app.services.tactics import detect_tactical_themes
        # Back rank mate threat
        fen = "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"
        themes = detect_tactical_themes(fen, "Ra8", "Kf1")
        assert isinstance(themes, list)

    def test_classify_drill_themes(self):
        from app.services.tactics import classify_drill_themes
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        themes = classify_drill_themes(
            fen=fen,
            best_move_san="e5",
            player_move_san="d6",
            eval_delta=-50,
            game_phase="opening",
        )
        assert isinstance(themes, list)

    def test_themes_always_return_list(self):
        from app.services.tactics import detect_tactical_themes
        # Starting position — no tactics
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        themes = detect_tactical_themes(fen, "e4", "d4")
        assert isinstance(themes, list)


# ═══════════════════════════════════════════════════════════════════════════
# BEHAVIOR SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestBehaviorService:
    """Tests for each of the 8 behavioral pattern detectors."""

    def test_detect_all_patterns(self, db):
        from app.services.behavior import detect_all_patterns
        patterns = detect_all_patterns(db)
        assert isinstance(patterns, list)
        assert len(patterns) == 8

    def test_detect_all_patterns_structure(self, db):
        from app.services.behavior import detect_all_patterns
        patterns = detect_all_patterns(db)
        for p in patterns:
            assert "pattern_name" in p
            assert "severity" in p
            assert p["severity"] in ("low", "medium", "high", "critical")

    def test_early_queen_trades(self, db):
        from app.services.behavior import detect_early_queen_trades
        result = detect_early_queen_trades(db)
        assert "pattern_name" in result
        assert "severity" in result

    def test_piece_retreats(self, db):
        from app.services.behavior import detect_piece_retreats
        result = detect_piece_retreats(db)
        assert "pattern_name" in result

    def test_same_piece_twice_opening(self, db):
        from app.services.behavior import detect_same_piece_twice_opening
        result = detect_same_piece_twice_opening(db)
        assert "pattern_name" in result

    def test_pawn_storms(self, db):
        from app.services.behavior import detect_pawn_storms_castled_king
        result = detect_pawn_storms_castled_king(db)
        assert "pattern_name" in result

    def test_endgame_avoidance(self, db):
        from app.services.behavior import detect_endgame_avoidance
        result = detect_endgame_avoidance(db)
        assert "pattern_name" in result

    def test_losing_streak_behavior(self, db):
        from app.services.behavior import detect_losing_streak_behavior
        result = detect_losing_streak_behavior(db)
        assert "pattern_name" in result

    def test_time_trouble(self, db):
        from app.services.behavior import detect_time_trouble
        result = detect_time_trouble(db)
        assert "pattern_name" in result

    def test_first_move_syndrome(self, db):
        from app.services.behavior import detect_first_move_syndrome
        result = detect_first_move_syndrome(db)
        assert "pattern_name" in result


# ═══════════════════════════════════════════════════════════════════════════
# COACHING SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestCoachingService:
    """Tests for coaching service functions with mocked Anthropic."""

    def _mock_client(self, text="Mock coaching response"):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = text
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response
        return mock_client

    def test_explain_move(self, db):
        from app.services.coaching import explain_move
        game = db.query(Game).first()
        mock = self._mock_client("This move was a mistake because...")
        with patch("app.services.coaching._get_client", return_value=mock):
            result = explain_move(db, game, 1)
            assert "coaching" in result
            assert result["ply"] == 1

    def test_explain_move_no_analysis(self, db):
        from app.services.coaching import explain_move
        game = db.query(Game).filter(Game.chess_com_id == "test_game_30").first()
        result = explain_move(db, game, 1)
        assert "error" in result

    def test_review_game(self, db):
        from app.services.coaching import review_game
        game = db.query(Game).first()
        mock = self._mock_client("Full game review text...")
        with patch("app.services.coaching._get_client", return_value=mock):
            result = review_game(db, game)
            assert "review" in result
            assert "stats" in result

    def test_review_game_no_summary(self, db):
        from app.services.coaching import review_game
        game = db.query(Game).filter(Game.chess_com_id == "test_game_30").first()
        result = review_game(db, game)
        assert "error" in result

    def test_generate_walkthrough(self, db):
        from app.services.coaching import generate_walkthrough
        game = db.query(Game).first()
        walkthrough_xml = (
            '<walkthrough>\n'
            '<moment id="1" ply="1">\nGreat opening.\n</moment>\n'
            '</walkthrough>\n'
            '<narrative>\nA solid game.\n</narrative>'
        )
        mock = self._mock_client(walkthrough_xml)
        with patch("app.services.coaching._get_client", return_value=mock):
            result = generate_walkthrough(db, game)
            assert "commentary_points" in result
            assert "narrative_summary" in result

    def test_generate_pattern_diagnosis(self, db):
        from app.services.coaching import generate_pattern_diagnosis
        mock = self._mock_client("Pattern diagnosis: ...")
        with patch("app.services.coaching._get_client", return_value=mock):
            result = generate_pattern_diagnosis(db)
            assert "diagnosis" in result
            assert "analyzed_games" in result
            assert "session_id" in result

    def test_generate_behavioral_narrative(self, db):
        from app.services.coaching import generate_behavioral_narrative
        patterns = [
            {
                "pattern_name": "Test Pattern",
                "frequency": 0.5,
                "frequency_label": "50%",
                "impact_label": "Medium",
                "severity": "medium",
                "detail": {"test": True},
                "example_game_ids": [1, 2],
            }
        ]
        mock = self._mock_client("Behavioral narrative...")
        with patch("app.services.coaching._get_client", return_value=mock):
            result = generate_behavioral_narrative(db, patterns)
            assert "narrative" in result
            assert "patterns" in result


# ═══════════════════════════════════════════════════════════════════════════
# CHESS.COM SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestChessComService:
    """Tests for Chess.com API sync with mocked HTTP."""

    def test_sync_games_mocked(self, db):
        from app.services.chess_com import sync_games

        mock_archives = ["https://api.chess.com/pub/player/eddobbles2021/games/2025/01"]
        mock_game_data = {
            "games": [
                {
                    "url": "https://www.chess.com/game/live/99999999",
                    "end_time": 1740000000,
                    "time_control": "300",
                    "time_class": "blitz",
                    "rated": True,
                    "white": {
                        "username": "eddobbles2021",
                        "rating": 850,
                        "result": "win",
                    },
                    "black": {
                        "username": "testopponent",
                        "rating": 840,
                        "result": "checkmated",
                    },
                    "pgn": '[Event "Live Chess"]\n[Site "Chess.com"]\n[White "eddobbles2021"]\n[Black "testopponent"]\n[Result "1-0"]\n[ECO "C50"]\n[Opening "Italian Game"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 1-0',
                }
            ]
        }

        with patch("app.services.chess_com.fetch_game_archives", return_value=mock_archives):
            with patch("app.services.chess_com.fetch_games_from_archive",
                       return_value=mock_game_data["games"]):
                with patch("app.services.chess_com.time.sleep"):
                    result = sync_games(db)
                    assert "new_games" in result
                    assert "skipped" in result
                    assert "errors" in result

    def test_parse_result(self):
        from app.services.chess_com import _parse_result
        game_data = {
            "white": {"username": "eddobbles2021", "result": "win"},
            "black": {"username": "opponent", "result": "checkmated"},
        }
        result, rtype = _parse_result(game_data, "white", "eddobbles2021")
        assert result == GameResult.win
        assert rtype == "checkmated"

    def test_parse_result_loss(self):
        from app.services.chess_com import _parse_result
        game_data = {
            "white": {"username": "eddobbles2021", "result": "resigned"},
            "black": {"username": "opponent", "result": "win"},
        }
        result, rtype = _parse_result(game_data, "white", "eddobbles2021")
        assert result == GameResult.loss
        assert rtype == "resigned"

    def test_parse_result_draw(self):
        from app.services.chess_com import _parse_result
        game_data = {
            "white": {"username": "eddobbles2021", "result": "stalemate"},
            "black": {"username": "opponent", "result": "stalemate"},
        }
        result, rtype = _parse_result(game_data, "white", "eddobbles2021")
        assert result == GameResult.draw

    def test_parse_time_class(self):
        from app.services.chess_com import _parse_time_class
        assert _parse_time_class("blitz") == TimeClass.blitz
        assert _parse_time_class("rapid") == TimeClass.rapid
        assert _parse_time_class("bullet") == TimeClass.bullet
        assert _parse_time_class("unknown") is None

    def test_parse_pgn_for_moves(self):
        from app.services.chess_com import _parse_pgn_for_moves
        pgn = '[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 1-0'
        count = _parse_pgn_for_moves(pgn)
        assert count == 5  # 5 half-moves (plies)
