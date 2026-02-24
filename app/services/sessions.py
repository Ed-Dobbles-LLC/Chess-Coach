"""Playing session detection and tilt/fatigue analysis.

A 'session' is a group of consecutive blitz games where the gap between
one game's end_time and the next is < 60 minutes.
"""

import logging
from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import Session as DBSession

from app.models.models import (
    Game, GameSummary, PlaySession, SessionResult, GameResult, TimeClass,
)

logger = logging.getLogger(__name__)

SESSION_GAP_SECONDS = 3600  # 60 minutes


def detect_sessions(db: DBSession) -> list[list[Game]]:
    """Walk through all blitz games ordered by end_time and group into sessions."""
    games = db.query(Game).filter(
        Game.time_class == TimeClass.blitz,
        Game.end_time.isnot(None),
    ).order_by(Game.end_time).all()

    if not games:
        return []

    sessions = []
    current = [games[0]]

    for g in games[1:]:
        gap = (g.end_time - current[-1].end_time).total_seconds()
        if gap < SESSION_GAP_SECONDS:
            current.append(g)
        else:
            sessions.append(current)
            current = [g]
    sessions.append(current)

    return sessions


def build_play_sessions(db: DBSession) -> dict:
    """Compute and store PlaySession records from game data."""
    # Clear existing
    db.query(PlaySession).delete()
    db.flush()

    sessions = detect_sessions(db)
    if not sessions:
        return {"created": 0}

    # Build summary lookup
    summary_map = {}
    for gs in db.query(GameSummary).all():
        summary_map[gs.game_id] = gs

    created = 0
    for game_group in sessions:
        ps = _build_session_record(game_group, summary_map)
        db.add(ps)
        created += 1

    db.commit()
    return {"created": created, "total_games_grouped": sum(len(s) for s in sessions)}


def _build_session_record(games: list[Game], summary_map: dict) -> PlaySession:
    """Build a single PlaySession from a group of games."""
    wins = sum(1 for g in games if g.result == GameResult.win)
    losses = sum(1 for g in games if g.result == GameResult.loss)
    draws = len(games) - wins - losses

    starting_rating = games[0].player_rating
    ending_rating = games[-1].player_rating
    rating_delta = (ending_rating - starting_rating) if starting_rating and ending_rating else None

    # Longest loss streak
    max_streak = 0
    current_streak = 0
    for g in games:
        if g.result == GameResult.loss:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    # CPL stats (only for analyzed games)
    cpls = []
    for g in games:
        s = summary_map.get(g.id)
        if s and s.avg_centipawn_loss is not None:
            cpls.append(s.avg_centipawn_loss)

    avg_cpl = sum(cpls) / len(cpls) if cpls else None

    # First half vs second half CPL
    mid = len(games) // 2
    first_half_cpls = []
    second_half_cpls = []
    for i, g in enumerate(games):
        s = summary_map.get(g.id)
        if s and s.avg_centipawn_loss is not None:
            if i < mid:
                first_half_cpls.append(s.avg_centipawn_loss)
            else:
                second_half_cpls.append(s.avg_centipawn_loss)

    avg_cpl_first = sum(first_half_cpls) / len(first_half_cpls) if first_half_cpls else None
    avg_cpl_second = sum(second_half_cpls) / len(second_half_cpls) if second_half_cpls else None

    # Session result
    if rating_delta is not None:
        if rating_delta > 0:
            result = SessionResult.net_positive
        elif rating_delta < 0:
            result = SessionResult.net_negative
        else:
            result = SessionResult.breakeven
    else:
        if wins > losses:
            result = SessionResult.net_positive
        elif losses > wins:
            result = SessionResult.net_negative
        else:
            result = SessionResult.breakeven

    # Approximate session start: first game's end_time minus estimated game duration.
    # For 5|5 blitz, average game is ~6 minutes. Use total_moves as proxy if available.
    first_game = games[0]
    try:
        if first_game.end_time and first_game.total_moves and isinstance(first_game.total_moves, (int, float)):
            # ~10 seconds per move pair is a reasonable blitz estimate
            estimated_duration = timedelta(seconds=int(first_game.total_moves) * 10)
            session_start = first_game.end_time - estimated_duration
        else:
            session_start = first_game.end_time
    except (TypeError, ValueError):
        session_start = first_game.end_time

    return PlaySession(
        start_time=session_start,
        end_time=games[-1].end_time,
        game_count=len(games),
        game_ids=[g.id for g in games],
        starting_rating=starting_rating,
        ending_rating=ending_rating,
        rating_delta=rating_delta,
        win_count=wins,
        loss_count=losses,
        draw_count=draws,
        avg_cpl=round(avg_cpl, 1) if avg_cpl else None,
        avg_cpl_first_half=round(avg_cpl_first, 1) if avg_cpl_first else None,
        avg_cpl_second_half=round(avg_cpl_second, 1) if avg_cpl_second else None,
        longest_loss_streak=max_streak,
        session_result=result,
    )


def get_sessions_summary(db: DBSession) -> dict:
    """Compute the full sessions dashboard response."""
    sessions = db.query(PlaySession).order_by(PlaySession.start_time).all()
    if not sessions:
        return {"error": "No sessions found. Run `python cli.py build-sessions` first."}

    total = len(sessions)
    avg_games = sum(s.game_count for s in sessions) / total

    # Performance by session length buckets
    buckets = {
        "1-3": {"sessions": [], "label": "1-3"},
        "4-6": {"sessions": [], "label": "4-6"},
        "7-10": {"sessions": [], "label": "7-10"},
        "10+": {"sessions": [], "label": "10+"},
    }
    for s in sessions:
        if s.game_count <= 3:
            buckets["1-3"]["sessions"].append(s)
        elif s.game_count <= 6:
            buckets["4-6"]["sessions"].append(s)
        elif s.game_count <= 10:
            buckets["7-10"]["sessions"].append(s)
        else:
            buckets["10+"]["sessions"].append(s)

    perf_by_length = []
    for key, bucket in buckets.items():
        ss = bucket["sessions"]
        if not ss:
            perf_by_length.append({
                "games": key, "count": 0,
                "avg_rating_delta": 0, "win_rate": 0,
            })
            continue
        deltas = [s.rating_delta for s in ss if s.rating_delta is not None]
        total_wins = sum(s.win_count for s in ss)
        total_games = sum(s.game_count for s in ss)
        perf_by_length.append({
            "games": key,
            "count": len(ss),
            "avg_rating_delta": round(sum(deltas) / len(deltas), 1) if deltas else 0,
            "win_rate": round(total_wins / total_games * 100, 1) if total_games > 0 else 0,
        })

    # Tilt detection — game-level analysis from all sessions
    games = db.query(Game).filter(
        Game.time_class == TimeClass.blitz,
        Game.end_time.isnot(None),
    ).order_by(Game.end_time).all()

    summary_map = {}
    for gs in db.query(GameSummary).all():
        summary_map[gs.game_id] = gs

    tilt = _compute_tilt_stats(games, summary_map)

    # Optimal session length — at what game count does cumulative delta go negative?
    optimal = _compute_optimal_length(sessions)

    # Best and worst sessions
    sessions_with_delta = [s for s in sessions if s.rating_delta is not None and s.game_count >= 3]
    worst = sorted(sessions_with_delta, key=lambda s: s.rating_delta)[:5]
    best = sorted(sessions_with_delta, key=lambda s: -s.rating_delta)[:5]

    return {
        "total_sessions": total,
        "avg_games_per_session": round(avg_games, 1),
        "performance_by_session_length": perf_by_length,
        "tilt_detection": tilt,
        "optimal_session_length": optimal,
        "worst_sessions": [_session_summary(s) for s in worst],
        "best_sessions": [_session_summary(s) for s in best],
    }


def get_session_detail(db: DBSession, date_str: str) -> dict:
    """Return detailed game-by-game data for a session on a specific date."""
    sessions = db.query(PlaySession).all()

    # Find session matching the date
    target = None
    for s in sessions:
        if s.start_time and s.start_time.strftime("%Y-%m-%d") == date_str:
            target = s
            break

    if not target:
        return {"error": f"No session found for date {date_str}"}

    # Load games
    games = db.query(Game).filter(Game.id.in_(target.game_ids)).order_by(Game.end_time).all()

    summary_map = {}
    for gs in db.query(GameSummary).filter(GameSummary.game_id.in_(target.game_ids)).all():
        summary_map[gs.game_id] = gs

    game_details = []
    for g in games:
        s = summary_map.get(g.id)
        game_details.append({
            "game_id": g.id,
            "end_time": g.end_time.isoformat() if g.end_time else None,
            "result": g.result.value,
            "result_type": g.result_type,
            "player_rating": g.player_rating,
            "opponent_rating": g.opponent_rating,
            "opening_name": g.opening_name,
            "player_color": g.player_color.value,
            "total_moves": g.total_moves,
            "avg_cpl": s.avg_centipawn_loss if s else None,
            "blunders": s.blunder_count if s else None,
            "mistakes": s.mistake_count if s else None,
        })

    return {
        "date": date_str,
        "start_time": target.start_time.isoformat() if target.start_time else None,
        "end_time": target.end_time.isoformat() if target.end_time else None,
        "game_count": target.game_count,
        "rating_delta": target.rating_delta,
        "session_result": target.session_result.value if target.session_result else None,
        "win_count": target.win_count,
        "loss_count": target.loss_count,
        "draw_count": target.draw_count,
        "longest_loss_streak": target.longest_loss_streak,
        "avg_cpl": target.avg_cpl,
        "avg_cpl_first_half": target.avg_cpl_first_half,
        "avg_cpl_second_half": target.avg_cpl_second_half,
        "games": game_details,
    }


def _compute_tilt_stats(games: list[Game], summary_map: dict) -> dict:
    """Compute tilt indicators from game-level data within sessions."""
    # Group into sessions
    if not games:
        return {}

    sessions_groups = []
    current = [games[0]]
    for g in games[1:]:
        gap = (g.end_time - current[-1].end_time).total_seconds()
        if gap < SESSION_GAP_SECONDS:
            current.append(g)
        else:
            sessions_groups.append(current)
            current = [g]
    sessions_groups.append(current)

    cpl_after_loss = []
    cpl_after_win = []
    cpl_after_2_losses = []
    wr_after_loss_games = []
    wr_after_win_games = []
    wr_after_2_loss_games = []

    for session in sessions_groups:
        consecutive_losses = 0
        for i, game in enumerate(session):
            if i > 0:
                prev = session[i - 1]
                s = summary_map.get(game.id)

                if prev.result == GameResult.loss:
                    wr_after_loss_games.append(game)
                    if s and s.avg_centipawn_loss is not None:
                        cpl_after_loss.append(s.avg_centipawn_loss)
                elif prev.result == GameResult.win:
                    wr_after_win_games.append(game)
                    if s and s.avg_centipawn_loss is not None:
                        cpl_after_win.append(s.avg_centipawn_loss)

                if consecutive_losses >= 2:
                    wr_after_2_loss_games.append(game)
                    if s and s.avg_centipawn_loss is not None:
                        cpl_after_2_losses.append(s.avg_centipawn_loss)

            if game.result == GameResult.loss:
                consecutive_losses += 1
            else:
                consecutive_losses = 0

    def wr(game_list):
        if not game_list:
            return 0
        return round(sum(1 for g in game_list if g.result == GameResult.win) / len(game_list) * 100, 1)

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    # Recommended stop point
    wr_after_2 = wr(wr_after_2_loss_games)
    wr_baseline = wr(wr_after_win_games)
    recommended = _compute_stop_recommendation(sessions_groups, summary_map)

    return {
        "avg_cpl_after_loss": avg(cpl_after_loss),
        "avg_cpl_after_win": avg(cpl_after_win),
        "avg_cpl_after_2_consecutive_losses": avg(cpl_after_2_losses),
        "win_rate_after_loss": wr(wr_after_loss_games),
        "win_rate_after_win": wr(wr_after_win_games),
        "win_rate_after_2_consecutive_losses": wr_after_2,
        "games_after_loss": len(wr_after_loss_games),
        "games_after_2_losses": len(wr_after_2_loss_games),
        "recommended_stop_point": recommended,
    }


def _compute_stop_recommendation(sessions: list[list[Game]], summary_map: dict) -> str:
    """Determine when the player should stop playing based on session data."""
    # Compute average rating delta by game number within session
    delta_by_position = defaultdict(list)
    for session in sessions:
        if len(session) < 2:
            continue
        for i, game in enumerate(session):
            if game.player_rating and session[0].player_rating:
                delta = game.player_rating - session[0].player_rating
                delta_by_position[i + 1].append(delta)

    # Find the game number where average cumulative delta goes negative
    crossover = None
    for pos in sorted(delta_by_position.keys()):
        vals = delta_by_position[pos]
        avg_delta = sum(vals) / len(vals)
        if avg_delta < 0 and pos >= 3:
            crossover = pos
            break

    if crossover:
        return f"After {crossover} games or 2 consecutive losses"
    return "After 2 consecutive losses or 6 games in a session"


def _compute_optimal_length(sessions: list[PlaySession]) -> dict:
    """Find the game count at which cumulative rating delta goes negative."""
    delta_by_count = defaultdict(list)
    for s in sessions:
        if s.rating_delta is not None:
            delta_by_count[s.game_count].append(s.rating_delta)

    by_count = []
    for count in sorted(delta_by_count.keys()):
        deltas = delta_by_count[count]
        by_count.append({
            "game_count": count,
            "sessions": len(deltas),
            "avg_rating_delta": round(sum(deltas) / len(deltas), 1),
        })

    # Find where cumulative average goes negative for sessions of N+ games
    crossover = None
    for entry in by_count:
        if entry["game_count"] >= 4 and entry["avg_rating_delta"] < 0:
            crossover = entry["game_count"]
            break

    return {
        "crossover_game_count": crossover,
        "by_session_length": by_count[:15],  # Cap output size
    }


def _session_summary(s: PlaySession) -> dict:
    return {
        "date": s.start_time.strftime("%Y-%m-%d") if s.start_time else None,
        "start_time": s.start_time.isoformat() if s.start_time else None,
        "games": s.game_count,
        "rating_delta": s.rating_delta,
        "win_count": s.win_count,
        "loss_count": s.loss_count,
        "longest_loss_streak": s.longest_loss_streak,
        "session_result": s.session_result.value if s.session_result else None,
        "game_ids": s.game_ids,
    }
