"""Data integrity tests — cross-table consistency and constraints."""

import pytest
from sqlalchemy import func

from app.models.models import (
    Game, MoveAnalysis, GameSummary, CoachingSession, DrillPosition,
    PlaySession, MoveClassification, GamePhase, PlayerColor,
    GameResult, TimeClass, SessionResult, SessionType,
)


class TestReferentialIntegrity:
    """Every FK references a valid parent."""

    def test_move_analysis_references_valid_game(self, db):
        game_ids = {g.id for g in db.query(Game).all()}
        analysis_game_ids = {
            a.game_id for a in db.query(MoveAnalysis).all()
        }
        orphans = analysis_game_ids - game_ids
        assert len(orphans) == 0, f"Orphan MoveAnalysis game_ids: {orphans}"

    def test_game_summary_references_valid_game(self, db):
        game_ids = {g.id for g in db.query(Game).all()}
        summary_game_ids = {
            s.game_id for s in db.query(GameSummary).all()
        }
        orphans = summary_game_ids - game_ids
        assert len(orphans) == 0, f"Orphan GameSummary game_ids: {orphans}"

    def test_drill_position_references_valid_game(self, db):
        game_ids = {g.id for g in db.query(Game).all()}
        drill_game_ids = {
            d.game_id for d in db.query(DrillPosition).all()
        }
        orphans = drill_game_ids - game_ids
        assert len(orphans) == 0, f"Orphan DrillPosition game_ids: {orphans}"

    def test_coaching_session_references_valid_game(self, db):
        game_ids = {g.id for g in db.query(Game).all()}
        coaching_game_ids = {
            c.game_id for c in db.query(CoachingSession).all()
            if c.game_id is not None
        }
        orphans = coaching_game_ids - game_ids
        assert len(orphans) == 0, f"Orphan CoachingSession game_ids: {orphans}"


class TestUniquenessConstraints:
    """No duplicate (game_id, ply) pairs."""

    def test_no_duplicate_move_analysis(self, db):
        dupes = db.query(
            MoveAnalysis.game_id, MoveAnalysis.ply, func.count()
        ).group_by(
            MoveAnalysis.game_id, MoveAnalysis.ply
        ).having(func.count() > 1).all()
        assert len(dupes) == 0, f"Duplicate MoveAnalysis (game_id, ply): {dupes}"

    def test_no_duplicate_drill_positions(self, db):
        dupes = db.query(
            DrillPosition.game_id, DrillPosition.ply, func.count()
        ).group_by(
            DrillPosition.game_id, DrillPosition.ply
        ).having(func.count() > 1).all()
        assert len(dupes) == 0, f"Duplicate DrillPosition (game_id, ply): {dupes}"

    def test_no_duplicate_game_summaries(self, db):
        dupes = db.query(
            GameSummary.game_id, func.count()
        ).group_by(
            GameSummary.game_id
        ).having(func.count() > 1).all()
        assert len(dupes) == 0, f"Duplicate GameSummary game_ids: {dupes}"

    def test_no_duplicate_chess_com_ids(self, db):
        dupes = db.query(
            Game.chess_com_id, func.count()
        ).group_by(
            Game.chess_com_id
        ).having(func.count() > 1).all()
        assert len(dupes) == 0, f"Duplicate chess_com_ids: {dupes}"


class TestEnumValidity:
    """All enum values in the database are valid."""

    def test_game_result_values(self, db):
        valid = {e.value for e in GameResult}
        for g in db.query(Game).all():
            assert g.result.value in valid, f"Invalid GameResult: {g.result}"

    def test_player_color_values(self, db):
        valid = {e.value for e in PlayerColor}
        for g in db.query(Game).all():
            assert g.player_color.value in valid, f"Invalid PlayerColor: {g.player_color}"

    def test_time_class_values(self, db):
        valid = {e.value for e in TimeClass}
        for g in db.query(Game).all():
            if g.time_class:
                assert g.time_class.value in valid, f"Invalid TimeClass: {g.time_class}"

    def test_classification_values(self, db):
        valid = {e.value for e in MoveClassification}
        for a in db.query(MoveAnalysis).all():
            if a.classification:
                assert a.classification.value in valid

    def test_game_phase_values(self, db):
        valid = {e.value for e in GamePhase}
        for a in db.query(MoveAnalysis).all():
            if a.game_phase:
                assert a.game_phase.value in valid

    def test_session_result_values(self, db):
        valid = {e.value for e in SessionResult}
        for ps in db.query(PlaySession).all():
            if ps.session_result:
                assert ps.session_result.value in valid

    def test_session_type_values(self, db):
        valid = {e.value for e in SessionType}
        for cs in db.query(CoachingSession).all():
            assert cs.session_type.value in valid


class TestDataConsistency:
    """Cross-table logical consistency."""

    def test_summaries_have_analysis(self, db):
        """Every game with a summary should have MoveAnalysis records."""
        for gs in db.query(GameSummary).all():
            analysis_count = db.query(MoveAnalysis).filter(
                MoveAnalysis.game_id == gs.game_id
            ).count()
            assert analysis_count > 0, (
                f"GameSummary for game {gs.game_id} has no MoveAnalysis records"
            )

    def test_play_session_has_games(self, db):
        """Every PlaySession references at least 1 game."""
        for ps in db.query(PlaySession).all():
            assert ps.game_count >= 1
            assert len(ps.game_ids) >= 1

    def test_play_session_game_ids_valid(self, db):
        """Every game_id in PlaySession.game_ids references a valid Game."""
        game_ids = {g.id for g in db.query(Game).all()}
        for ps in db.query(PlaySession).all():
            for gid in ps.game_ids:
                assert gid in game_ids, (
                    f"PlaySession {ps.id} references non-existent game {gid}"
                )

    def test_game_counts_match(self, db):
        """Total games = sum of wins + losses + draws."""
        total = db.query(Game).count()
        wins = db.query(Game).filter(Game.result == GameResult.win).count()
        losses = db.query(Game).filter(Game.result == GameResult.loss).count()
        draws = db.query(Game).filter(Game.result == GameResult.draw).count()
        assert total == wins + losses + draws

    def test_play_session_game_count_matches_ids(self, db):
        """PlaySession.game_count matches len(game_ids)."""
        for ps in db.query(PlaySession).all():
            assert ps.game_count == len(ps.game_ids), (
                f"PlaySession {ps.id}: game_count={ps.game_count} "
                f"but len(game_ids)={len(ps.game_ids)}"
            )

    def test_drill_positions_have_valid_fen(self, db):
        """Every drill FEN should be parseable by python-chess."""
        import chess
        for dp in db.query(DrillPosition).all():
            try:
                board = chess.Board(dp.fen)
                assert board.is_valid()
            except Exception as e:
                pytest.fail(f"Drill {dp.id} has invalid FEN '{dp.fen}': {e}")


class TestDashboardCacheTests:
    """Verify dashboard cache behavior."""

    def test_cache_populates(self, client):
        from app.routers.dashboard import _cache
        _cache.clear()

        # First call should miss cache
        resp = client.get("/api/dashboard/summary")
        assert resp.status_code == 200

        # Cache should now be populated
        assert "dashboard_summary" in _cache

    def test_cache_returns_same_data(self, client):
        from app.routers.dashboard import _cache
        _cache.clear()

        resp1 = client.get("/api/dashboard/summary")
        resp2 = client.get("/api/dashboard/summary")
        assert resp1.json() == resp2.json()

    def test_cache_key_isolation(self, client):
        from app.routers.dashboard import _cache
        _cache.clear()

        client.get("/api/dashboard/opening-book/C50")
        client.get("/api/dashboard/opening-book/B20")

        assert "opening_book_C50" in _cache
        assert "opening_book_B20" in _cache
        # Verify they're different
        c50_data = _cache["opening_book_C50"][1]
        b20_data = _cache["opening_book_B20"][1]
        assert c50_data["eco"] == "C50"
        assert b20_data["eco"] == "B20"
