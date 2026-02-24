"""CLI command tests — all 6 commands from cli.py.

Each CLI function imports SessionLocal from app.database at call time,
so we patch app.database.SessionLocal to inject the test DB session.
"""

import argparse
from unittest.mock import patch, MagicMock

import pytest

from app.models.models import (
    Game, GameSummary, MoveAnalysis, DrillPosition, PlaySession, CoachingSession,
)


class TestCLISync:
    """Test: python cli.py sync"""

    def test_sync_command(self, db):
        from cli import cmd_sync

        mock_result = {"new_games": 3, "skipped": 5, "errors": 0, "total_fetched": 8}
        args = argparse.Namespace()

        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.chess_com.sync_games", return_value=mock_result):
                cmd_sync(args)


class TestCLIAnalyze:
    """Test: python cli.py analyze --limit 5"""

    def test_analyze_command(self, db):
        from cli import cmd_analyze

        args = argparse.Namespace(limit=2, depth=18)
        mock_analyze_result = {
            "game_id": 1, "moves_analyzed": 20, "avg_cpl": 45.0,
            "blunders": 1, "mistakes": 2, "inaccuracies": 3,
            "critical_moments": 1,
        }

        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.stockfish.analyze_game", return_value=mock_analyze_result):
                cmd_analyze(args)


class TestCLIExtractDrills:
    """Test: python cli.py extract-drills"""

    def test_extract_drills_command(self, db):
        from cli import cmd_extract_drills

        args = argparse.Namespace()

        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.drills.extract_drill_positions",
                       return_value={"created": 5, "skipped": 10}):
                cmd_extract_drills(args)


class TestCLITagThemes:
    """Test: python cli.py tag-themes [--force]"""

    def test_tag_themes_command(self, db):
        from cli import cmd_tag_themes

        args = argparse.Namespace(force=False)

        with patch("app.database.SessionLocal", return_value=db):
            cmd_tag_themes(args)

    def test_tag_themes_force(self, db):
        from cli import cmd_tag_themes

        args = argparse.Namespace(force=True)

        with patch("app.database.SessionLocal", return_value=db):
            cmd_tag_themes(args)


class TestCLIBuildSessions:
    """Test: python cli.py build-sessions"""

    def test_build_sessions_command(self, db):
        from cli import cmd_build_sessions

        args = argparse.Namespace()

        with patch("app.database.SessionLocal", return_value=db):
            with patch("app.services.sessions.build_play_sessions",
                       return_value={"created": 10, "total_games_grouped": 45}):
                cmd_build_sessions(args)


class TestCLIStatus:
    """Test: python cli.py status"""

    def test_status_command(self, db, capsys):
        from cli import cmd_status

        args = argparse.Namespace()

        with patch("app.database.SessionLocal", return_value=db):
            cmd_status(args)

        captured = capsys.readouterr()
        assert "CHESS COACH DATABASE STATUS" in captured.out
        assert "Games:" in captured.out
        assert "Analyzed:" in captured.out
        assert "Drill positions:" in captured.out
        assert "Play sessions:" in captured.out
