"""Comprehensive API endpoint tests — all 23+ endpoints across 5 routers."""

import json
from unittest.mock import patch, MagicMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# GAMES ROUTER
# ═══════════════════════════════════════════════════════════════════════════

class TestGamesRouter:
    """Tests for GET /api/games, GET /api/games/{id}, POST /api/games/sync."""

    def test_list_games_default(self, client):
        resp = client.get("/api/games")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert "pages" in data
        assert "games" in data
        assert data["total"] == 50
        assert data["page"] == 1
        assert len(data["games"]) <= 50

    def test_list_games_pagination(self, client):
        resp = client.get("/api/games?page=1&per_page=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["games"]) == 10
        assert data["per_page"] == 10
        assert data["pages"] == 5  # 50 / 10

    def test_list_games_filter_result(self, client):
        resp = client.get("/api/games?result=win")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        for g in data["games"]:
            assert g["result"] == "win"

    def test_list_games_filter_time_class(self, client):
        resp = client.get("/api/games?time_class=blitz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 50  # all test games are blitz

    def test_list_games_filter_opening(self, client):
        resp = client.get("/api/games?opening=Italian")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 15

    def test_list_games_filter_analyzed(self, client):
        resp = client.get("/api/games?analyzed=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10  # games 1-10 have summaries

    def test_list_games_fields(self, client):
        resp = client.get("/api/games?per_page=1")
        game = resp.json()["games"][0]
        expected_fields = [
            "id", "chess_com_id", "player_color", "result", "result_type",
            "time_class", "opening_name", "eco", "player_rating",
            "opponent_rating", "total_moves", "end_time", "has_analysis",
        ]
        for field in expected_fields:
            assert field in game, f"Missing field: {field}"

    def test_get_game_valid(self, client, db):
        from app.models.models import Game
        game = db.query(Game).first()
        resp = client.get(f"/api/games/{game.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == game.id
        assert "pgn" in data
        assert "white_username" in data
        assert "player_color" in data

    def test_get_game_with_summary(self, client, db):
        """Game 1 has a summary — verify it's included."""
        from app.models.models import Game
        game = db.query(Game).first()
        resp = client.get(f"/api/games/{game.id}")
        data = resp.json()
        assert data["summary"] is not None
        assert "avg_centipawn_loss" in data["summary"]
        assert "blunder_count" in data["summary"]

    def test_get_game_not_found(self, client):
        resp = client.get("/api/games/99999")
        assert resp.status_code == 404

    def test_sync_games_mocked(self, client):
        """Mock Chess.com API and verify sync works."""
        mock_result = {"new_games": 5, "skipped": 10, "errors": 0, "total_fetched": 15}
        with patch("app.routers.games.sync_games", return_value=mock_result):
            resp = client.post("/api/games/sync")
            assert resp.status_code == 200
            data = resp.json()
            assert data["new_games"] == 5
            assert data["skipped"] == 10


# ═══════════════════════════════════════════════════════════════════════════
# ANALYSIS ROUTER
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalysisRouter:
    """Tests for POST /api/analysis/batch, GET /api/analysis/status, GET /api/analysis/game/{id}."""

    def test_analysis_status(self, client):
        resp = client.get("/api/analysis/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_games"] == 50
        assert data["analyzed"] == 10
        assert data["remaining"] == 40
        assert data["percent_complete"] == 20.0

    def test_get_game_analysis_valid(self, client, db):
        """Game 1 has move analysis — verify it returns moves."""
        from app.models.models import Game
        game = db.query(Game).first()
        resp = client.get(f"/api/analysis/game/{game.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == game.id
        assert "moves" in data
        assert len(data["moves"]) > 0
        move = data["moves"][0]
        expected_fields = [
            "ply", "move_number", "color", "is_player_move", "fen_before",
            "move_played", "move_played_san", "best_move", "best_move_san",
            "eval_before", "eval_after", "eval_delta", "classification",
            "game_phase", "top_3_lines",
        ]
        for field in expected_fields:
            assert field in move, f"Missing field: {field}"

    def test_get_game_analysis_player_only(self, client, db):
        from app.models.models import Game
        game = db.query(Game).first()
        resp = client.get(f"/api/analysis/game/{game.id}?player_only=true")
        assert resp.status_code == 200
        data = resp.json()
        for move in data["moves"]:
            assert move["is_player_move"] is True

    def test_get_game_analysis_not_found(self, client):
        resp = client.get("/api/analysis/game/99999")
        assert resp.status_code == 404

    def test_get_game_analysis_unanalyzed(self, client, db):
        """A game without analysis should return 404."""
        from app.models.models import Game, MoveAnalysis
        # Find a game with no analysis (games 21+)
        game = db.query(Game).filter(Game.chess_com_id == "test_game_30").first()
        if game:
            has_analysis = db.query(MoveAnalysis).filter(
                MoveAnalysis.game_id == game.id
            ).first()
            if not has_analysis:
                resp = client.get(f"/api/analysis/game/{game.id}")
                assert resp.status_code == 404

    def test_batch_analysis_mocked(self, client):
        """Mock Stockfish and verify batch analysis endpoint."""
        mock_result = {"total": 5, "completed": 5, "errors": 0, "details": []}
        with patch("app.routers.analysis.batch_analyze", return_value=mock_result):
            resp = client.post(
                "/api/analysis/batch",
                json={"limit": 5, "time_class": "blitz"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 5
            assert data["completed"] == 5


# ═══════════════════════════════════════════════════════════════════════════
# COACHING ROUTER
# ═══════════════════════════════════════════════════════════════════════════

class TestCoachingRouter:
    """Tests for all coaching endpoints."""

    def _mock_anthropic_response(self, text="Test coaching response"):
        """Create a mock Anthropic client that returns a canned response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = text
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response
        return mock_client

    def test_game_review_mocked(self, client, db):
        from app.models.models import Game
        game = db.query(Game).first()  # Game 1 has summary
        mock_client = self._mock_anthropic_response("Great game! Here is your review...")
        with patch("app.services.coaching._get_client", return_value=mock_client):
            resp = client.post(f"/api/coach/game-review/{game.id}")
            assert resp.status_code == 200
            data = resp.json()
            assert "review" in data
            assert "stats" in data
            assert data["game_id"] == game.id
            assert "avg_cpl" in data["stats"]
            assert "blunders" in data["stats"]

    def test_game_review_not_found(self, client):
        resp = client.post("/api/coach/game-review/99999")
        assert resp.status_code == 404

    def test_game_review_unanalyzed(self, client, db):
        """Game without analysis should return 400."""
        from app.models.models import Game
        game = db.query(Game).filter(Game.chess_com_id == "test_game_30").first()
        if game:
            mock_client = self._mock_anthropic_response()
            with patch("app.services.coaching._get_client", return_value=mock_client):
                resp = client.post(f"/api/coach/game-review/{game.id}")
                assert resp.status_code == 400

    def test_move_explain_mocked(self, client, db):
        from app.models.models import Game
        game = db.query(Game).first()
        mock_client = self._mock_anthropic_response("This move is a mistake because...")
        with patch("app.services.coaching._get_client", return_value=mock_client):
            resp = client.post(
                "/api/coach/move-explain",
                json={"game_id": game.id, "ply": 1},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "coaching" in data
            assert "ply" in data
            assert "move_played" in data

    def test_move_explain_no_analysis(self, client, db):
        from app.models.models import Game
        game = db.query(Game).filter(Game.chess_com_id == "test_game_30").first()
        if game:
            mock_client = self._mock_anthropic_response()
            with patch("app.services.coaching._get_client", return_value=mock_client):
                resp = client.post(
                    "/api/coach/move-explain",
                    json={"game_id": game.id, "ply": 1},
                )
                assert resp.status_code == 400

    def test_move_explain_invalid_game(self, client):
        resp = client.post(
            "/api/coach/move-explain",
            json={"game_id": 99999, "ply": 1},
        )
        assert resp.status_code == 404

    def test_walkthrough_mocked(self, client, db):
        from app.models.models import Game
        game = db.query(Game).first()  # has analysis + summary
        walkthrough_xml = (
            '<walkthrough>\n'
            '<moment id="1" ply="1">\nGreat opening move.\n</moment>\n'
            '</walkthrough>\n'
            '<narrative>\nA solid game overall.\n</narrative>'
        )
        mock_client = self._mock_anthropic_response(walkthrough_xml)
        with patch("app.services.coaching._get_client", return_value=mock_client):
            resp = client.post(f"/api/coach/walkthrough/{game.id}")
            assert resp.status_code == 200
            data = resp.json()
            assert "commentary_points" in data
            assert "narrative_summary" in data
            assert data["game_id"] == game.id

    def test_walkthrough_not_found(self, client):
        resp = client.post("/api/coach/walkthrough/99999")
        assert resp.status_code == 404

    def test_walkthrough_unanalyzed(self, client, db):
        from app.models.models import Game
        game = db.query(Game).filter(Game.chess_com_id == "test_game_30").first()
        if game:
            mock_client = self._mock_anthropic_response()
            with patch("app.services.coaching._get_client", return_value=mock_client):
                resp = client.post(f"/api/coach/walkthrough/{game.id}")
                assert resp.status_code == 400

    def test_behavioral_analysis_mocked(self, client):
        mock_client = self._mock_anthropic_response("Behavioral analysis narrative...")
        with patch("app.services.coaching._get_client", return_value=mock_client):
            resp = client.post("/api/coach/behavioral-analysis")
            assert resp.status_code == 200
            data = resp.json()
            assert "patterns" in data
            assert "narrative" in data
            assert isinstance(data["patterns"], list)

    def test_diagnose_mocked(self, client):
        mock_client = self._mock_anthropic_response("Pattern diagnosis: ...")
        with patch("app.services.coaching._get_client", return_value=mock_client):
            resp = client.post("/api/coach/diagnose")
            assert resp.status_code == 200
            data = resp.json()
            assert "diagnosis" in data
            assert "analyzed_games" in data
            assert "session_id" in data

    def test_list_coaching_sessions(self, client):
        resp = client.get("/api/coach/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "sessions" in data
        assert data["total"] >= 5  # We seeded 5

    def test_list_coaching_sessions_pagination(self, client):
        resp = client.get("/api/coach/sessions?page=1&per_page=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) <= 2

    def test_list_coaching_sessions_filter_type(self, client):
        resp = client.get("/api/coach/sessions?session_type=game_review")
        assert resp.status_code == 200
        data = resp.json()
        for s in data["sessions"]:
            assert s["session_type"] == "game_review"


# ═══════════════════════════════════════════════════════════════════════════
# DRILLS ROUTER
# ═══════════════════════════════════════════════════════════════════════════

class TestDrillsRouter:
    """Tests for GET /api/drills, POST /api/drills/{id}/attempt, etc."""

    def test_get_drills(self, client):
        resp = client.get("/api/drills")
        assert resp.status_code == 200
        data = resp.json()
        assert "drills" in data
        assert "count" in data

    def test_get_drills_with_count(self, client):
        resp = client.get("/api/drills?count=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["drills"]) <= 3

    def test_get_drills_filter_phase(self, client):
        resp = client.get("/api/drills?game_phase=opening")
        assert resp.status_code == 200
        data = resp.json()
        for d in data["drills"]:
            assert d["game_phase"] == "opening"

    def test_get_drills_filter_eco(self, client):
        resp = client.get("/api/drills?opening_eco=C50")
        assert resp.status_code == 200
        data = resp.json()
        for d in data["drills"]:
            assert d["opening_eco"] == "C50"

    def test_get_drills_fields(self, client):
        resp = client.get("/api/drills?count=1")
        data = resp.json()
        if data["drills"]:
            drill = data["drills"][0]
            expected_fields = [
                "id", "fen", "game_phase", "opening_eco", "tactical_theme",
                "difficulty", "times_shown", "times_correct", "game_id",
            ]
            for field in expected_fields:
                assert field in drill, f"Missing field: {field}"

    def test_drill_attempt_correct(self, client, db):
        from app.models.models import DrillPosition
        drill = db.query(DrillPosition).first()
        correct_move = drill.correct_move_san
        mock_client = MagicMock()
        with patch("app.services.coaching._get_client", return_value=mock_client):
            resp = client.post(
                f"/api/drills/{drill.id}/attempt",
                json={"move_san": correct_move},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["correct"] is True
            assert data["correct_move"] == correct_move
            assert "next_review" in data

    def test_drill_attempt_wrong(self, client, db):
        from app.models.models import DrillPosition
        drill = db.query(DrillPosition).filter(DrillPosition.id > 1).first()
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "This is coaching feedback."
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response
        with patch("app.services.coaching._get_client", return_value=mock_client):
            resp = client.post(
                f"/api/drills/{drill.id}/attempt",
                json={"move_san": "WRONG_MOVE"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["correct"] is False

    def test_drill_attempt_not_found(self, client):
        resp = client.post(
            "/api/drills/99999/attempt",
            json={"move_san": "e4"},
        )
        assert resp.status_code == 404

    def test_drill_stats(self, client):
        resp = client.get("/api/drills/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_drills" in data
        assert data["total_drills"] >= 15

    def test_extract_drills_mocked(self, client):
        """Extract drills from already-analyzed games."""
        resp = client.post("/api/drills/extract")
        assert resp.status_code == 200
        data = resp.json()
        assert "created" in data
        assert "skipped" in data


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD ROUTER
# ═══════════════════════════════════════════════════════════════════════════

class TestDashboardRouter:
    """Tests for all dashboard endpoints."""

    def test_dashboard_summary(self, client):
        # Clear cache to get fresh data
        from app.routers.dashboard import _cache
        _cache.clear()

        resp = client.get("/api/dashboard/summary")
        assert resp.status_code == 200
        data = resp.json()
        expected_fields = [
            "total_games", "analyzed_games", "record", "win_rate",
            "avg_cpl", "avg_blunders_per_game", "rating_trend", "by_time_class",
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
        assert data["total_games"] == 50
        assert data["analyzed_games"] == 10
        assert "wins" in data["record"]
        assert "losses" in data["record"]
        assert "draws" in data["record"]

    def test_opening_stats(self, client):
        resp = client.get("/api/dashboard/openings")
        assert resp.status_code == 200
        data = resp.json()
        assert "openings" in data
        assert len(data["openings"]) > 0
        opening = data["openings"][0]
        assert "opening_name" in opening
        assert "games" in opening
        assert "win_rate" in opening

    def test_pattern_stats(self, client):
        resp = client.get("/api/dashboard/patterns")
        assert resp.status_code == 200
        data = resp.json()
        assert "phase_performance" in data
        assert "color_performance" in data
        assert "mistakes_by_phase" in data
        assert "white" in data["color_performance"]
        assert "black" in data["color_performance"]

    def test_time_analysis(self, client):
        resp = client.get("/api/dashboard/time-analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert "by_hour" in data
        assert "by_day" in data
        assert isinstance(data["by_hour"], list)
        assert isinstance(data["by_day"], list)

    def test_opening_book_valid(self, client):
        from app.routers.dashboard import _cache
        _cache.clear()

        resp = client.get("/api/dashboard/opening-book/C50")
        assert resp.status_code == 200
        data = resp.json()
        assert data["eco"] == "C50"
        assert data["total_games"] == 15
        assert "book_moves" in data
        assert "win_rate" in data
        assert "as_white" in data
        assert "as_black" in data
        assert "drill_count" in data

    def test_opening_book_fields(self, client):
        from app.routers.dashboard import _cache
        _cache.clear()

        resp = client.get("/api/dashboard/opening-book/C50")
        data = resp.json()
        if data.get("book_moves"):
            move = data["book_moves"][0]
            assert "ply" in move
            assert "main_move" in move
            assert "main_count" in move
            assert "alternatives" in move

    def test_opening_book_invalid_eco(self, client):
        resp = client.get("/api/dashboard/opening-book/Z99")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_sessions_summary(self, client):
        from app.routers.dashboard import _cache
        _cache.clear()

        resp = client.get("/api/dashboard/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_sessions" in data
        assert data["total_sessions"] == 3
        assert "performance_by_session_length" in data
        assert "tilt_detection" in data
        assert "optimal_session_length" in data
        assert "best_sessions" in data
        assert "worst_sessions" in data

    def test_sessions_performance_buckets(self, client):
        from app.routers.dashboard import _cache
        _cache.clear()

        resp = client.get("/api/dashboard/sessions")
        data = resp.json()
        perf = data["performance_by_session_length"]
        assert isinstance(perf, list)
        # Should have 4 bucket labels
        labels = {p["games"] for p in perf}
        assert labels == {"1-3", "4-6", "7-10", "10+"}

    def test_session_detail_valid(self, client, db):
        from app.models.models import PlaySession
        session = db.query(PlaySession).first()
        date_str = session.start_time.strftime("%Y-%m-%d")
        resp = client.get(f"/api/dashboard/sessions/{date_str}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == date_str
        assert "game_count" in data
        assert "games" in data
        assert "rating_delta" in data

    def test_session_detail_invalid_date(self, client):
        resp = client.get("/api/dashboard/sessions/2099-01-01")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════
# INFRASTRUCTURE
# ═══════════════════════════════════════════════════════════════════════════

class TestInfrastructure:
    """Root routes and health check."""

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "chess-coach"

    def test_root_serves_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_static_css(self, client):
        resp = client.get("/static/css/style.css")
        assert resp.status_code == 200

    def test_static_js(self, client):
        resp = client.get("/static/js/app.js")
        assert resp.status_code == 200

    def test_invalid_json_returns_422(self, client):
        resp = client.post(
            "/api/coach/move-explain",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_missing_required_fields_returns_422(self, client):
        resp = client.post("/api/coach/move-explain", json={})
        assert resp.status_code == 422
