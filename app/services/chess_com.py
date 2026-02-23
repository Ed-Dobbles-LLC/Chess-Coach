"""Chess.com PubAPI game ingestion service.

Pulls game history for a player via monthly archives. Single-threaded with
polite delays to respect the API rate limit (one concurrent request).
"""

import logging
import re
import time
from datetime import datetime, timezone

import chess.pgn
import httpx
import io
from sqlalchemy.orm import Session
from sqlalchemy import inspect

from app.models.models import Game, PlayerColor, GameResult, TimeClass
from app.config import settings

logger = logging.getLogger(__name__)

CHESS_COM_BASE = "https://api.chess.com/pub"
REQUEST_HEADERS = {
    "User-Agent": "DobblesAI-ChessCoach/1.0 (contact: ed@dobbles.ai)"
}
DELAY_BETWEEN_REQUESTS = 1.0  # seconds


def _parse_result(game_data: dict, player_color: str, username: str) -> tuple[GameResult, str]:
    """Determine win/loss/draw and result type from Chess.com game data."""
    white = game_data.get("white", {})
    black = game_data.get("black", {})

    player = white if player_color == "white" else black
    player_result = player.get("result", "")

    if player_result == "win":
        # The opponent's result tells us HOW we won
        opponent = black if player_color == "white" else white
        return GameResult.win, opponent.get("result", "unknown")
    elif player_result in ("checkmated", "timeout", "resigned", "abandoned"):
        return GameResult.loss, player_result
    elif player_result in ("stalemate", "insufficient", "50move", "repetition",
                           "agreed", "timevsinsufficient"):
        return GameResult.draw, player_result
    else:
        return GameResult.draw, player_result


def _parse_time_class(tc: str) -> TimeClass | None:
    mapping = {
        "bullet": TimeClass.bullet,
        "blitz": TimeClass.blitz,
        "rapid": TimeClass.rapid,
        "daily": TimeClass.daily,
    }
    return mapping.get(tc)


def _parse_pgn_for_moves(pgn_text: str) -> int:
    """Count total plies (half-moves) in a PGN."""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game is None:
            return 0
        return sum(1 for _ in game.mainline_moves())
    except Exception:
        return 0


def _extract_opening(pgn_text: str) -> tuple[str | None, str | None]:
    """Extract ECO code and opening name from PGN headers."""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game is None:
            return None, None
        eco = game.headers.get("ECO")
        opening = game.headers.get("ECOUrl", "")
        # Chess.com stores opening as URL like /openings/Sicilian-Defense...
        if opening:
            opening = opening.split("/openings/")[-1].replace("-", " ") if "/openings/" in opening else opening
        else:
            opening = game.headers.get("Opening")
        return eco, opening if opening else None
    except Exception:
        return None, None


CLK_PATTERN = re.compile(r'\[%clk (\d+):(\d+):(\d+(?:\.\d+)?)\]')


def extract_clock_times(pgn_text: str) -> list[dict]:
    """Extract clock times from Chess.com PGN %clk annotations.

    Chess.com PGNs include {[%clk H:MM:SS]} after each move.

    Returns list of {ply, clock_remaining (seconds), time_spent (seconds)}.
    time_spent is the delta between this move's clock and the previous clock
    for the same color.
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

        time_spent = max(0.0, time_spent)

        result.append({
            "ply": ply,
            "clock_remaining": round(remaining, 1),
            "time_spent": round(time_spent, 1),
        })

    return result


def fetch_game_archives(username: str) -> list[str]:
    """Get list of monthly archive URLs for a player."""
    url = f"{CHESS_COM_BASE}/player/{username}/games/archives"
    with httpx.Client(headers=REQUEST_HEADERS, timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json().get("archives", [])


def fetch_games_from_archive(archive_url: str) -> list[dict]:
    """Fetch all games from a single monthly archive."""
    with httpx.Client(headers=REQUEST_HEADERS, timeout=60) as client:
        resp = client.get(archive_url)
        resp.raise_for_status()
        return resp.json().get("games", [])


def sync_games(db: Session, username: str | None = None, since_timestamp: int | None = None) -> dict:
    """
    Pull games from Chess.com and upsert into the database.

    Args:
        db: SQLAlchemy session
        username: Chess.com username (defaults to config)
        since_timestamp: Only import games after this Unix timestamp (for incremental sync)

    Returns:
        dict with counts of new_games, skipped, errors
    """
    username = (username or settings.chess_com_username).lower()
    archives = fetch_game_archives(username)

    stats = {"new_games": 0, "skipped": 0, "errors": 0, "total_fetched": 0}

    for archive_url in archives:
        time.sleep(DELAY_BETWEEN_REQUESTS)

        try:
            games = fetch_games_from_archive(archive_url)
        except Exception as e:
            logger.error(f"Failed to fetch archive {archive_url}: {e}")
            stats["errors"] += 1
            continue

        for game_data in games:
            stats["total_fetched"] += 1
            try:
                end_time = game_data.get("end_time", 0)

                if since_timestamp and end_time <= since_timestamp:
                    stats["skipped"] += 1
                    continue

                game_url = game_data.get("url", "")
                chess_com_id = game_url.split("/")[-1] if game_url else str(end_time)

                # Determine player color
                white_user = game_data.get("white", {}).get("username", "").lower()
                black_user = game_data.get("black", {}).get("username", "").lower()

                if white_user == username:
                    player_color = PlayerColor.white
                elif black_user == username:
                    player_color = PlayerColor.black
                else:
                    stats["skipped"] += 1
                    continue

                pgn_text = game_data.get("pgn", "")
                if not pgn_text:
                    stats["skipped"] += 1
                    continue

                result, result_type = _parse_result(game_data, player_color.value, username)

                white_rating = game_data.get("white", {}).get("rating")
                black_rating = game_data.get("black", {}).get("rating")
                player_rating = white_rating if player_color == PlayerColor.white else black_rating
                opponent_rating = black_rating if player_color == PlayerColor.white else white_rating

                eco, opening_name = _extract_opening(pgn_text)
                total_moves = _parse_pgn_for_moves(pgn_text)
                time_class = _parse_time_class(game_data.get("time_class", ""))

                end_dt = datetime.fromtimestamp(end_time, tz=timezone.utc)

                # Check if game already exists
                existing = db.query(Game).filter(
                    Game.chess_com_id == chess_com_id
                ).first()
                if existing:
                    stats["skipped"] += 1
                    continue

                game_obj = Game(
                    chess_com_id=chess_com_id,
                    pgn=pgn_text,
                    white_username=white_user,
                    black_username=black_user,
                    player_color=player_color,
                    result=result,
                    result_type=result_type,
                    time_control=game_data.get("time_control", ""),
                    time_class=time_class,
                    rated=game_data.get("rated", True),
                    eco=eco,
                    opening_name=opening_name,
                    end_time=end_dt,
                    white_rating=white_rating,
                    black_rating=black_rating,
                    player_rating=player_rating,
                    opponent_rating=opponent_rating,
                    total_moves=total_moves,
                )
                db.add(game_obj)
                stats["new_games"] += 1

            except Exception as e:
                logger.error(f"Failed to process game: {e}")
                stats["errors"] += 1

        db.commit()

    return stats
