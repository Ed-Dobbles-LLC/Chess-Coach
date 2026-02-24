"""Model-layer tests — ORM model creation, relationships, and JSON serialization.

Validates that all 6 SQLAlchemy models create correctly, handle nullable fields,
and their JSON columns work as expected.
"""

import json
from datetime import datetime, date, timezone

import pytest
from sqlalchemy import inspect

from app.models.models import (
    Game, MoveAnalysis, GameSummary, CoachingSession, DrillPosition,
    PlaySession, MoveClassification, GamePhase, GameResult, PlayerColor,
    TimeClass, SessionResult, SessionType,
)


class TestGameModel:
    """Verify Game model creation and field handling."""

    def test_create_game_required_fields(self, db):
        g = Game(
            chess_com_id="model_test_001",
            white_username="alice",
            black_username="bob",
            player_color=PlayerColor.white,
            result=GameResult.win,
            result_type="checkmate",
            time_class=TimeClass.blitz,
            pgn="1. e4 e5 1-0",
            end_time=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        db.add(g)
        db.flush()
        assert g.id is not None

    def test_game_nullable_fields(self, db):
        g = Game(
            chess_com_id="model_test_002",
            white_username="alice",
            black_username="bob",
            player_color=PlayerColor.black,
            result=GameResult.draw,
            result_type="stalemate",
            time_class=TimeClass.rapid,
            pgn="1. d4 d5 1/2-1/2",
            end_time=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        db.add(g)
        db.flush()
        assert g.opening_name is None
        assert g.eco is None
        assert g.player_rating is None
        assert g.opponent_rating is None
        assert g.total_moves is None
        assert g.time_control is None

    def test_game_all_fields(self, db):
        g = Game(
            chess_com_id="model_test_003",
            white_username="alice",
            black_username="bob",
            player_color=PlayerColor.white,
            result=GameResult.loss,
            result_type="checkmate",
            time_class=TimeClass.bullet,
            pgn="1. e4 e5 0-1",
            opening_name="King's Pawn",
            eco="C20",
            player_rating=1000,
            opponent_rating=1050,
            total_moves=30,
            end_time=datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc),
            time_control="60",
        )
        db.add(g)
        db.flush()
        assert g.player_rating == 1000
        assert g.eco == "C20"


class TestMoveAnalysisModel:
    """Verify MoveAnalysis model."""

    def test_create_move_analysis(self, db):
        game = db.query(Game).first()
        ma = MoveAnalysis(
            game_id=game.id,
            ply=99,
            move_number=50,
            color="white",
            is_player_move=True,
            fen_before="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            move_played="e2e4",
            move_played_san="e4",
            best_move="e2e4",
            best_move_san="e4",
            eval_before=0.2,
            eval_after=0.3,
            eval_delta=-0.1,
            classification=MoveClassification.best,
            game_phase=GamePhase.opening,
        )
        db.add(ma)
        db.flush()
        assert ma.id is not None

    def test_move_analysis_top_3_lines_json(self, db):
        game = db.query(Game).first()
        lines = [
            {"moves": ["e4", "e5"], "eval": 0.2},
            {"moves": ["d4", "d5"], "eval": 0.1},
        ]
        ma = MoveAnalysis(
            game_id=game.id,
            ply=98,
            move_number=49,
            color="white",
            is_player_move=True,
            fen_before="start",
            move_played="e2e4",
            move_played_san="e4",
            classification=MoveClassification.good,
            top_3_lines=lines,
        )
        db.add(ma)
        db.flush()
        db.expire(ma)
        assert ma.top_3_lines[0]["moves"][0] == "e4"

    def test_move_analysis_clock_times_json(self, db):
        game = db.query(Game).first()
        ma = MoveAnalysis(
            game_id=game.id,
            ply=97,
            move_number=49,
            color="black",
            is_player_move=False,
            fen_before="start",
            move_played="e7e5",
            move_played_san="e5",
            clock_times={"white": 285.0, "black": 292.0},
        )
        db.add(ma)
        db.flush()
        db.expire(ma)
        assert ma.clock_times["white"] == 285.0


class TestGameSummaryModel:
    """Verify GameSummary model."""

    def test_create_summary(self, db):
        from sqlalchemy import not_
        existing_ids = [gs.game_id for gs in db.query(GameSummary).all()]
        game = db.query(Game).filter(not_(Game.id.in_(existing_ids))).first()
        if game:
            gs = GameSummary(
                game_id=game.id,
                avg_centipawn_loss=42.5,
                blunder_count=1,
                mistake_count=3,
                inaccuracy_count=5,
                critical_moments=2,
            )
            db.add(gs)
            db.flush()
            assert gs.avg_centipawn_loss == 42.5
            assert gs.blunder_count == 1

    def test_summary_accuracy_fields(self, db):
        gs = db.query(GameSummary).first()
        for attr in ["opening_accuracy", "middlegame_accuracy", "endgame_accuracy"]:
            val = getattr(gs, attr)
            assert val is None or isinstance(val, (int, float))


class TestDrillPositionModel:
    """Verify DrillPosition model."""

    def test_drill_tactical_theme_json(self, db):
        game = db.query(Game).first()
        dp = DrillPosition(
            game_id=game.id,
            ply=97,
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            correct_move_san="e4",
            player_move_san="d4",
            eval_delta=-100,
            game_phase=GamePhase.opening,
            opening_eco="C50",
            tactical_theme=["fork", "pin"],
        )
        db.add(dp)
        db.flush()
        assert "fork" in dp.tactical_theme
        assert "pin" in dp.tactical_theme

    def test_drill_spaced_repetition_fields(self, db):
        dp = db.query(DrillPosition).first()
        assert dp.times_shown >= 0
        assert dp.times_correct >= 0
        assert dp.next_review_date is None or isinstance(dp.next_review_date, date)
        assert dp.difficulty_rating is None or isinstance(dp.difficulty_rating, (int, float))


class TestPlaySessionModel:
    """Verify PlaySession model."""

    def test_play_session_fields(self, db):
        ps = db.query(PlaySession).first()
        assert ps.game_count >= 1
        assert isinstance(ps.game_ids, list)
        assert ps.win_count >= 0
        assert ps.loss_count >= 0
        assert ps.draw_count >= 0
        assert ps.win_count + ps.loss_count + ps.draw_count == ps.game_count

    def test_play_session_result_enum(self, db):
        ps = db.query(PlaySession).first()
        assert ps.session_result in (
            SessionResult.net_positive, SessionResult.net_negative, SessionResult.breakeven
        )


class TestCoachingSessionModel:
    """Verify CoachingSession model."""

    def test_coaching_session_fields(self, db):
        cs = db.query(CoachingSession).first()
        valid_types = {e for e in SessionType}
        assert cs.session_type in valid_types
        assert isinstance(cs.response, str)
        assert isinstance(cs.prompt_sent, str)

    def test_create_coaching_session(self, db):
        game = db.query(Game).first()
        cs = CoachingSession(
            game_id=game.id,
            session_type=SessionType.game_review,
            prompt_sent="Test prompt",
            response="Test response",
            model_used="claude-sonnet-4-20250514",
        )
        db.add(cs)
        db.flush()
        assert cs.id is not None
        assert cs.created_at is not None


class TestTableSchema:
    """Verify table schema matches expected structure."""

    def test_all_tables_exist(self, db):
        inspector = inspect(db.bind)
        tables = inspector.get_table_names()
        expected = ["games", "move_analysis", "game_summaries",
                    "coaching_sessions", "drill_positions", "play_sessions"]
        for table in expected:
            assert table in tables, f"Missing table: {table}"

    def test_games_table_columns(self, db):
        inspector = inspect(db.bind)
        columns = {c["name"] for c in inspector.get_columns("games")}
        required = {"id", "chess_com_id", "white_username", "black_username",
                     "player_color", "result", "time_class", "pgn"}
        assert required.issubset(columns)

    def test_move_analysis_table_columns(self, db):
        inspector = inspect(db.bind)
        columns = {c["name"] for c in inspector.get_columns("move_analysis")}
        required = {"id", "game_id", "ply", "move_number", "color",
                     "is_player_move", "fen_before", "move_played"}
        assert required.issubset(columns)

    def test_drill_positions_table_columns(self, db):
        inspector = inspect(db.bind)
        columns = {c["name"] for c in inspector.get_columns("drill_positions")}
        required = {"id", "game_id", "ply", "fen", "correct_move_san",
                     "times_shown", "times_correct", "next_review_date"}
        assert required.issubset(columns)

    def test_play_sessions_table_columns(self, db):
        inspector = inspect(db.bind)
        columns = {c["name"] for c in inspector.get_columns("play_sessions")}
        required = {"id", "start_time", "end_time", "game_count",
                     "win_count", "loss_count", "draw_count"}
        assert required.issubset(columns)
