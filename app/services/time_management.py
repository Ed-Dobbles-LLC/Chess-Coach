"""Time management analytics.

Parses clock data from PGN, backfills MoveAnalysis records, and computes
time-vs-accuracy statistics.
"""

import io
import re
import logging
from collections import defaultdict

import chess.pgn
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import (
    Game, MoveAnalysis, GameSummary, DrillPosition,
    MoveClassification, GamePhase,
)

logger = logging.getLogger(__name__)

CLK_PATTERN = re.compile(r'\[%clk (\d+):(\d+):(\d+(?:\.\d+)?)\]')


def extract_clock_times(pgn_text: str) -> list[dict]:
    """Extract clock times from PGN %clk annotations.

    Returns a list of {ply, clock_remaining, time_spent} dicts.
    time_spent is the delta between the previous clock for the same color
    and this move's clock.
    """
    clocks_raw = []
    for m in CLK_PATTERN.finditer(pgn_text):
        hours = int(m.group(1))
        minutes = int(m.group(2))
        seconds = float(m.group(3))
        clocks_raw.append(hours * 3600 + minutes * 60 + seconds)

    if not clocks_raw:
        return []

    result = []
    # clocks_raw[0] = ply 1 (white's first move), [1] = ply 2 (black's first), etc.
    # Track previous clock per color for time_spent calculation
    prev_white = None
    prev_black = None

    for i, remaining in enumerate(clocks_raw):
        ply = i + 1
        is_white = (ply % 2 == 1)

        if is_white:
            time_spent = (prev_white - remaining) if prev_white is not None else 0.0
            prev_white = remaining
        else:
            time_spent = (prev_black - remaining) if prev_black is not None else 0.0
            prev_black = remaining

        # Clamp time_spent to avoid negative values from increment
        time_spent = max(0.0, time_spent)

        result.append({
            "ply": ply,
            "clock_remaining": round(remaining, 1),
            "time_spent": round(time_spent, 1),
        })

    return result


def backfill_clocks_for_game(db: Session, game: Game) -> int:
    """Parse clocks from a game's PGN and update its MoveAnalysis records.

    Returns the number of moves updated.
    """
    clock_data = extract_clock_times(game.pgn)
    if not clock_data:
        return 0

    clock_by_ply = {c["ply"]: c for c in clock_data}

    moves = db.query(MoveAnalysis).filter(
        MoveAnalysis.game_id == game.id,
    ).all()

    updated = 0
    for move in moves:
        cd = clock_by_ply.get(move.ply)
        if cd:
            move.clock_seconds = cd["clock_remaining"]
            move.time_spent_seconds = cd["time_spent"]
            updated += 1

    return updated


def get_time_management_stats(db: Session) -> dict:
    """Compute time management analytics from clock data in MoveAnalysis."""

    # Check if we have any clock data
    has_clocks = db.query(MoveAnalysis).filter(
        MoveAnalysis.clock_seconds.isnot(None),
        MoveAnalysis.is_player_move == True,
    ).count()

    if has_clocks == 0:
        return {"error": "No clock data available. Run `python cli.py backfill-clocks` first."}

    # Avg time per move by phase
    phase_time = {}
    for phase in ["opening", "middlegame", "endgame"]:
        avg = db.query(func.avg(MoveAnalysis.time_spent_seconds)).filter(
            MoveAnalysis.is_player_move == True,
            MoveAnalysis.game_phase == phase,
            MoveAnalysis.time_spent_seconds.isnot(None),
        ).scalar()
        phase_time[phase] = round(avg, 1) if avg else None

    # Time trouble stats: games where player clock went under 30s
    # Get all player moves with clock data
    player_moves = db.query(MoveAnalysis).filter(
        MoveAnalysis.is_player_move == True,
        MoveAnalysis.clock_seconds.isnot(None),
    ).all()

    # Group by game to find games with time trouble
    moves_by_game = defaultdict(list)
    for m in player_moves:
        moves_by_game[m.game_id].append(m)

    games_with_trouble = 0
    games_without_trouble = 0
    trouble_blunders = 0
    trouble_moves = 0
    adequate_blunders = 0
    adequate_moves = 0

    for game_id, moves in moves_by_game.items():
        min_clock = min(m.clock_seconds for m in moves if m.clock_seconds is not None)
        if min_clock < 30:
            games_with_trouble += 1
        else:
            games_without_trouble += 1

        for m in moves:
            if m.clock_seconds is None:
                continue
            is_blunder = m.classification in (
                MoveClassification.blunder, MoveClassification.mistake
            )
            if m.clock_seconds < 30:
                trouble_moves += 1
                if is_blunder:
                    trouble_blunders += 1
            else:
                adequate_moves += 1
                if is_blunder:
                    adequate_blunders += 1

    total_games = games_with_trouble + games_without_trouble
    blunder_rate_trouble = round(trouble_blunders / trouble_moves * 100, 1) if trouble_moves > 0 else None
    blunder_rate_adequate = round(adequate_blunders / adequate_moves * 100, 1) if adequate_moves > 0 else None

    # Win rates in time trouble vs adequate time
    trouble_game_ids = [
        gid for gid, moves in moves_by_game.items()
        if min(m.clock_seconds for m in moves if m.clock_seconds is not None) < 30
    ]
    adequate_game_ids = [
        gid for gid, moves in moves_by_game.items()
        if min(m.clock_seconds for m in moves if m.clock_seconds is not None) >= 30
    ]

    from app.models.models import GameResult
    trouble_wins = db.query(Game).filter(
        Game.id.in_(trouble_game_ids), Game.result == GameResult.win
    ).count() if trouble_game_ids else 0
    adequate_wins = db.query(Game).filter(
        Game.id.in_(adequate_game_ids), Game.result == GameResult.win
    ).count() if adequate_game_ids else 0

    wr_trouble = round(trouble_wins / len(trouble_game_ids) * 100, 1) if trouble_game_ids else None
    wr_adequate = round(adequate_wins / len(adequate_game_ids) * 100, 1) if adequate_game_ids else None

    # Time vs accuracy buckets
    time_buckets = [
        ("0-3s", 0, 3),
        ("3-5s", 3, 5),
        ("5-10s", 5, 10),
        ("10s+", 10, 9999),
    ]
    time_vs_accuracy = []
    for label, lo, hi in time_buckets:
        bucket_moves = [
            m for m in player_moves
            if m.time_spent_seconds is not None and lo <= m.time_spent_seconds < hi
        ]
        if not bucket_moves:
            time_vs_accuracy.append({"time_bucket": label, "avg_cpl": None, "blunder_pct": None, "moves": 0})
            continue
        cpls = [abs(m.eval_delta) for m in bucket_moves if m.eval_delta is not None]
        blunders = sum(
            1 for m in bucket_moves
            if m.classification in (MoveClassification.blunder, MoveClassification.mistake)
        )
        time_vs_accuracy.append({
            "time_bucket": label,
            "avg_cpl": round(sum(cpls) / len(cpls), 1) if cpls else None,
            "blunder_pct": round(blunders / len(bucket_moves) * 100, 1),
            "moves": len(bucket_moves),
        })

    # Opening time waste: time spent on frequently-played moves
    # Find moves the player has played 10+ times (by FEN prefix + move)
    # Simpler approach: average time on moves in opening phase
    opening_moves = [
        m for m in player_moves
        if m.game_phase == GamePhase.opening and m.time_spent_seconds is not None
    ]
    avg_opening_time = round(
        sum(m.time_spent_seconds for m in opening_moves) / len(opening_moves), 1
    ) if opening_moves else None

    # Count games where opening consumed >50% of time
    games_opening_heavy = 0
    for game_id, moves in moves_by_game.items():
        opening_time = sum(
            m.time_spent_seconds for m in moves
            if m.game_phase == GamePhase.opening and m.time_spent_seconds is not None
        )
        total_time = sum(
            m.time_spent_seconds for m in moves
            if m.time_spent_seconds is not None
        )
        if total_time > 0 and opening_time / total_time > 0.5:
            games_opening_heavy += 1

    recommendation = None
    if avg_opening_time and avg_opening_time > 5:
        recommendation = (
            f"You spend {avg_opening_time}s on opening moves you play every game. "
            f"Memorize your first 8 moves to save 40+ seconds for the middlegame."
        )

    return {
        "avg_time_per_move_by_phase": phase_time,
        "time_trouble_stats": {
            "games_with_under_30s": games_with_trouble,
            "pct_of_total": round(games_with_trouble / total_games * 100, 1) if total_games > 0 else 0,
            "blunder_rate_in_time_trouble": blunder_rate_trouble,
            "blunder_rate_with_time": blunder_rate_adequate,
            "win_rate_in_time_trouble": wr_trouble,
            "win_rate_with_time": wr_adequate,
        },
        "time_vs_accuracy": time_vs_accuracy,
        "opening_time_waste": {
            "avg_time_on_book_moves": avg_opening_time,
            "games_where_opening_consumed_over_50pct_time": games_opening_heavy,
            "recommendation": recommendation,
        },
        "total_moves_with_clock_data": has_clocks,
    }
