from sqlalchemy import (
    Column, Integer, String, Boolean, Float, Text, DateTime, ForeignKey, Enum, JSON,
    UniqueConstraint, Date
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from app.database import Base


class PlayerColor(str, enum.Enum):
    white = "white"
    black = "black"


class GameResult(str, enum.Enum):
    win = "win"
    loss = "loss"
    draw = "draw"


class TimeClass(str, enum.Enum):
    bullet = "bullet"
    blitz = "blitz"
    rapid = "rapid"
    daily = "daily"


class MoveClassification(str, enum.Enum):
    best = "best"
    excellent = "excellent"
    good = "good"
    inaccuracy = "inaccuracy"
    mistake = "mistake"
    blunder = "blunder"


class GamePhase(str, enum.Enum):
    opening = "opening"
    middlegame = "middlegame"
    endgame = "endgame"


class SessionType(str, enum.Enum):
    game_review = "game_review"
    pattern_diagnosis = "pattern_diagnosis"
    drill = "drill"
    behavioral_analysis = "behavioral_analysis"


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    chess_com_id = Column(String, unique=True, nullable=False, index=True)
    pgn = Column(Text, nullable=False)
    white_username = Column(String, nullable=False, index=True)
    black_username = Column(String, nullable=False, index=True)
    player_color = Column(Enum(PlayerColor), nullable=False)
    result = Column(Enum(GameResult), nullable=False)
    result_type = Column(String, nullable=False)
    time_control = Column(String)
    time_class = Column(Enum(TimeClass))
    rated = Column(Boolean, default=True)
    eco = Column(String)
    opening_name = Column(String)
    end_time = Column(DateTime(timezone=True), nullable=False, index=True)
    white_rating = Column(Integer)
    black_rating = Column(Integer)
    player_rating = Column(Integer)
    opponent_rating = Column(Integer)
    total_moves = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    move_analyses = relationship("MoveAnalysis", back_populates="game", cascade="all, delete-orphan")
    summary = relationship("GameSummary", back_populates="game", uselist=False, cascade="all, delete-orphan")
    coaching_sessions = relationship("CoachingSession", back_populates="game", cascade="all, delete-orphan")
    drill_positions = relationship("DrillPosition", back_populates="game", cascade="all, delete-orphan")


class MoveAnalysis(Base):
    __tablename__ = "move_analysis"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    move_number = Column(Integer, nullable=False)
    ply = Column(Integer, nullable=False)
    color = Column(Enum(PlayerColor), nullable=False)
    is_player_move = Column(Boolean, nullable=False)
    fen_before = Column(String, nullable=False)
    move_played = Column(String, nullable=False)
    move_played_san = Column(String, nullable=False)
    best_move = Column(String)
    best_move_san = Column(String)
    eval_before = Column(Float)
    eval_after = Column(Float)
    eval_delta = Column(Float)
    classification = Column(Enum(MoveClassification))
    depth = Column(Integer)
    game_phase = Column(Enum(GamePhase))
    top_3_lines = Column(JSON)
    clock_times = Column(JSON)  # {player_clock: float, opponent_clock: float} in seconds remaining
    clock_seconds = Column(Float)         # Seconds remaining after this move
    time_spent_seconds = Column(Float)    # Seconds consumed on this move

    game = relationship("Game", back_populates="move_analyses")

    __table_args__ = (
        UniqueConstraint("game_id", "ply", name="uq_game_ply"),
    )


class GameSummary(Base):
    __tablename__ = "game_summaries"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, unique=True)
    avg_centipawn_loss = Column(Float)
    blunder_count = Column(Integer, default=0)
    mistake_count = Column(Integer, default=0)
    inaccuracy_count = Column(Integer, default=0)
    opening_accuracy = Column(Float)
    middlegame_accuracy = Column(Float)
    endgame_accuracy = Column(Float)
    critical_moments = Column(JSON)
    coaching_notes = Column(Text)

    game = relationship("Game", back_populates="summary")


class CoachingSession(Base):
    __tablename__ = "coaching_sessions"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=True)
    session_type = Column(Enum(SessionType), nullable=False)
    prompt_sent = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    model_used = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    game = relationship("Game", back_populates="coaching_sessions")


class DrillPosition(Base):
    __tablename__ = "drill_positions"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    ply = Column(Integer, nullable=False)
    fen = Column(String, nullable=False)
    correct_move_san = Column(String, nullable=False)
    player_move_san = Column(String, nullable=False)
    eval_delta = Column(Float)
    tactical_theme = Column(JSON)
    game_phase = Column(Enum(GamePhase))
    opening_eco = Column(String)
    times_shown = Column(Integer, default=0)
    times_correct = Column(Integer, default=0)
    next_review_date = Column(Date)
    difficulty_rating = Column(Float)

    game = relationship("Game", back_populates="drill_positions")

    __table_args__ = (
        UniqueConstraint("game_id", "ply", name="uq_drill_game_ply"),
    )


class SessionResult(str, enum.Enum):
    net_positive = "net_positive"
    net_negative = "net_negative"
    breakeven = "breakeven"


class PlaySession(Base):
    __tablename__ = "play_sessions"

    id = Column(Integer, primary_key=True, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=False)
    game_count = Column(Integer, nullable=False)
    game_ids = Column(JSON, nullable=False)  # List of game IDs in this session
    starting_rating = Column(Integer)
    ending_rating = Column(Integer)
    rating_delta = Column(Integer)
    win_count = Column(Integer, default=0)
    loss_count = Column(Integer, default=0)
    draw_count = Column(Integer, default=0)
    avg_cpl = Column(Float)             # For analyzed games in session
    avg_cpl_first_half = Column(Float)  # CPL for first half of session
    avg_cpl_second_half = Column(Float) # CPL for second half of session
    longest_loss_streak = Column(Integer, default=0)
    session_result = Column(Enum(SessionResult))


class WeeklySnapshot(Base):
    __tablename__ = "weekly_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    week_start = Column(Date, nullable=False, unique=True, index=True)
    week_end = Column(Date, nullable=False)
    games_played = Column(Integer, default=0)
    win_rate = Column(Float)
    avg_cpl = Column(Float)
    blunder_rate = Column(Float)  # blunders per game
    opening_cpl = Column(Float)
    middlegame_cpl = Column(Float)
    endgame_cpl = Column(Float)
    rating_start = Column(Integer)
    rating_end = Column(Integer)
    rating_delta = Column(Integer)
    most_common_mistake_pattern = Column(String)
    drill_accuracy = Column(Float)
    time_trouble_pct = Column(Float)
