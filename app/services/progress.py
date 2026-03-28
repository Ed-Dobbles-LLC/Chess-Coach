"""Weekly progress snapshots and trend tracking.

Computes and stores WeeklySnapshot records for historical and current weeks,
then generates trend analysis from the snapshot series.
"""

import logging
from datetime import date, timedelta, datetime, timezone
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import (
    Game, GameSummary, MoveAnalysis, DrillPosition, WeeklySnapshot,
    GameResult, MoveClassification, GamePhase,
)

logger = logging.getLogger(__name__)


def _week_start(d: date) -> date:
    """Return Monday of the week containing date d."""
    return d - timedelta(days=d.weekday())


def _week_end(d: date) -> date:
    """Return Sunday of the week containing date d."""
    return _week_start(d) + timedelta(days=6)


def compute_snapshot(db: Session, week_start: date) -> dict | None:
    """Compute a snapshot for a specific week. Returns None if no games that week."""
    week_end = week_start + timedelta(days=6)
    ws_dt = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
    we_dt = datetime(week_end.year, week_end.month, week_end.day, 23, 59, 59, tzinfo=timezone.utc)

    games = db.query(Game).filter(
        Game.time_class == "blitz",
        Game.end_time >= ws_dt,
        Game.end_time <= we_dt,
    ).order_by(Game.end_time).all()

    if not games:
        return None

    games_played = len(games)
    wins = sum(1 for g in games if g.result == GameResult.win)
    win_rate = round(wins / games_played * 100, 1) if games_played > 0 else 0

    # Rating
    ratings = [g.player_rating for g in games if g.player_rating is not None]
    rating_start = ratings[0] if ratings else None
    rating_end = ratings[-1] if ratings else None
    rating_delta = (rating_end - rating_start) if rating_start and rating_end else None

    # CPL stats from analyzed games
    game_ids = [g.id for g in games]
    summaries = db.query(GameSummary).filter(GameSummary.game_id.in_(game_ids)).all()
    summary_map = {s.game_id: s for s in summaries}

    cpls = [s.avg_centipawn_loss for s in summaries if s.avg_centipawn_loss is not None]
    avg_cpl = round(sum(cpls) / len(cpls), 1) if cpls else None

    blunders = [s.blunder_count for s in summaries if s.blunder_count is not None]
    blunder_rate = round(sum(blunders) / len(blunders), 2) if blunders else None

    # Phase CPL
    opening_cpls = [s.opening_accuracy for s in summaries if s.opening_accuracy is not None]
    middlegame_cpls = [s.middlegame_accuracy for s in summaries if s.middlegame_accuracy is not None]
    endgame_cpls = [s.endgame_accuracy for s in summaries if s.endgame_accuracy is not None]

    opening_cpl = round(sum(opening_cpls) / len(opening_cpls), 1) if opening_cpls else None
    middlegame_cpl = round(sum(middlegame_cpls) / len(middlegame_cpls), 1) if middlegame_cpls else None
    endgame_cpl = round(sum(endgame_cpls) / len(endgame_cpls), 1) if endgame_cpls else None

    # Most common mistake pattern: count blunders by phase
    mistake_counts = defaultdict(int)
    for s in summaries:
        if s.blunder_count and s.blunder_count > 0:
            # Check which phase had the most mistakes for this game
            phase_cpls = {
                "opening": s.opening_accuracy or 0,
                "middlegame": s.middlegame_accuracy or 0,
                "endgame": s.endgame_accuracy or 0,
            }
            worst_phase = max(phase_cpls, key=phase_cpls.get)
            mistake_counts[worst_phase] += 1

    most_common = max(mistake_counts, key=mistake_counts.get) if mistake_counts else None

    # Drill accuracy for the week
    drill_shown = db.query(func.sum(DrillPosition.times_shown)).scalar() or 0
    drill_correct = db.query(func.sum(DrillPosition.times_correct)).scalar() or 0
    drill_accuracy = round(drill_correct / drill_shown * 100, 1) if drill_shown > 0 else None

    # Time trouble percentage
    from app.services.behavior import parse_clocks_from_pgn
    trouble_count = 0
    clock_count = 0
    for g in games:
        clocks = parse_clocks_from_pgn(g.pgn)
        if not clocks:
            continue
        clock_count += 1
        player_is_white = g.player_color.value == "white"
        player_clocks = clocks[0::2] if player_is_white else clocks[1::2]
        if player_clocks and min(player_clocks) < 30:
            trouble_count += 1

    time_trouble_pct = round(trouble_count / clock_count * 100, 1) if clock_count > 0 else None

    return {
        "week_start": week_start,
        "week_end": week_end,
        "games_played": games_played,
        "win_rate": win_rate,
        "avg_cpl": avg_cpl,
        "blunder_rate": blunder_rate,
        "opening_cpl": opening_cpl,
        "middlegame_cpl": middlegame_cpl,
        "endgame_cpl": endgame_cpl,
        "rating_start": rating_start,
        "rating_end": rating_end,
        "rating_delta": rating_delta,
        "most_common_mistake_pattern": most_common,
        "drill_accuracy": drill_accuracy,
        "time_trouble_pct": time_trouble_pct,
    }


def store_snapshot(db: Session, data: dict) -> WeeklySnapshot:
    """Create or update a WeeklySnapshot from computed data."""
    existing = db.query(WeeklySnapshot).filter(
        WeeklySnapshot.week_start == data["week_start"]
    ).first()

    if existing:
        for key, val in data.items():
            setattr(existing, key, val)
        return existing

    snap = WeeklySnapshot(**data)
    db.add(snap)
    return snap


def compute_current_snapshot(db: Session) -> dict:
    """Compute and store snapshot for the current week."""
    ws = _week_start(date.today())
    data = compute_snapshot(db, ws)
    if not data:
        return {"message": "No games this week."}

    store_snapshot(db, data)
    db.commit()
    return {"week_start": str(ws), "games_played": data["games_played"]}


def backfill_all_snapshots(db: Session) -> dict:
    """Generate snapshots for all historical weeks with game data."""
    # Find date range of all games
    earliest = db.query(func.min(Game.end_time)).filter(Game.time_class == "blitz").scalar()
    latest = db.query(func.max(Game.end_time)).filter(Game.time_class == "blitz").scalar()

    if not earliest or not latest:
        return {"created": 0, "updated": 0}

    start_week = _week_start(earliest.date())
    end_week = _week_start(latest.date())

    created = 0
    updated = 0
    current = start_week

    while current <= end_week:
        data = compute_snapshot(db, current)
        if data:
            existing = db.query(WeeklySnapshot).filter(
                WeeklySnapshot.week_start == current
            ).first()
            if existing:
                updated += 1
            else:
                created += 1
            store_snapshot(db, data)

        current += timedelta(weeks=1)

    db.commit()
    return {"created": created, "updated": updated, "total_weeks": created + updated}


def get_progress(db: Session, weeks: int = 12) -> dict:
    """Get recent snapshots and compute trend analysis."""
    snapshots = db.query(WeeklySnapshot).order_by(
        WeeklySnapshot.week_start.desc()
    ).limit(weeks).all()

    snapshots = list(reversed(snapshots))  # Chronological order

    if not snapshots:
        return {"error": "No snapshots found. Run `python cli.py backfill-snapshots` first."}

    snapshot_data = [
        {
            "week_start": str(s.week_start),
            "week_end": str(s.week_end),
            "games_played": s.games_played,
            "win_rate": s.win_rate,
            "avg_cpl": s.avg_cpl,
            "blunder_rate": s.blunder_rate,
            "opening_cpl": s.opening_cpl,
            "middlegame_cpl": s.middlegame_cpl,
            "endgame_cpl": s.endgame_cpl,
            "rating_start": s.rating_start,
            "rating_end": s.rating_end,
            "rating_delta": s.rating_delta,
            "most_common_mistake_pattern": s.most_common_mistake_pattern,
            "drill_accuracy": s.drill_accuracy,
            "time_trouble_pct": s.time_trouble_pct,
        }
        for s in snapshots
    ]

    # Compute trends using simple linear regression
    trends = _compute_trends(snapshots)

    return {
        "snapshots": snapshot_data,
        "trends": trends,
    }


def _compute_trends(snapshots: list[WeeklySnapshot]) -> dict:
    """Compute simple trend indicators from snapshot series."""
    if len(snapshots) < 2:
        return {}

    def slope(values):
        """Simple linear regression slope."""
        n = len(values)
        if n < 2:
            return 0
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(values) / n
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
        den = sum((x - x_mean) ** 2 for x in xs)
        return num / den if den != 0 else 0

    def trend_label(s):
        if s > 0.5:
            return "improving"
        elif s < -0.5:
            return "declining"
        return "stable"

    # Rating trend
    ratings = [s.rating_end for s in snapshots if s.rating_end is not None]
    rating_slope = slope(ratings) if len(ratings) >= 2 else 0

    # CPL trend (lower is better, so negative slope = improving)
    cpls = [s.avg_cpl for s in snapshots if s.avg_cpl is not None]
    cpl_slope = slope(cpls) if len(cpls) >= 2 else 0

    # Blunder rate trend
    blunders = [s.blunder_rate for s in snapshots if s.blunder_rate is not None]
    blunder_slope = slope(blunders) if len(blunders) >= 2 else 0

    # Find biggest improvement and concern
    improvements = []
    concerns = []

    # Check phase CPLs over last N weeks vs first N weeks
    n = min(4, len(snapshots) // 2)
    if n >= 1:
        for phase in ["opening_cpl", "middlegame_cpl", "endgame_cpl"]:
            early = [getattr(s, phase) for s in snapshots[:n] if getattr(s, phase) is not None]
            late = [getattr(s, phase) for s in snapshots[-n:] if getattr(s, phase) is not None]
            if early and late:
                early_avg = sum(early) / len(early)
                late_avg = sum(late) / len(late)
                delta = early_avg - late_avg
                name = phase.replace("_cpl", "")
                if delta > 3:
                    improvements.append(f"{name} CPL dropped from {early_avg:.0f} to {late_avg:.0f}")
                elif delta < -3:
                    concerns.append(f"{name} CPL increased from {early_avg:.0f} to {late_avg:.0f}")

        # Blunder rate
        early_b = [s.blunder_rate for s in snapshots[:n] if s.blunder_rate is not None]
        late_b = [s.blunder_rate for s in snapshots[-n:] if s.blunder_rate is not None]
        if early_b and late_b:
            eb = sum(early_b) / len(early_b)
            lb = sum(late_b) / len(late_b)
            if lb - eb > 0.3:
                concerns.append(f"blunder rate increased from {eb:.1f} to {lb:.1f}")
            elif eb - lb > 0.3:
                improvements.append(f"blunder rate dropped from {eb:.1f} to {lb:.1f}")

    return {
        "rating_trend": trend_label(rating_slope),
        "rating_slope": round(rating_slope, 2),
        "cpl_trend": trend_label(-cpl_slope),  # Negative CPL slope = improving
        "cpl_slope": round(cpl_slope, 2),
        "blunder_trend": trend_label(-blunder_slope),
        "biggest_improvement": improvements[0] if improvements else None,
        "biggest_concern": concerns[0] if concerns else None,
    }
