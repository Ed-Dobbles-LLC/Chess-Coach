"""Test database seeding with realistic chess game data.

Creates 50 games across 5 openings, with analysis, summaries, drills,
coaching sessions, and play sessions. No external API calls.
"""

import random
from datetime import datetime, timedelta, timezone, date

from app.models.models import (
    Game, MoveAnalysis, GameSummary, CoachingSession, DrillPosition,
    PlaySession, PlayerColor, GameResult, TimeClass, MoveClassification,
    GamePhase, SessionType, SessionResult,
)

# ---------------------------------------------------------------------------
# PGN Templates (valid, parsable by python-chess)
# ---------------------------------------------------------------------------

_ITALIAN_PGN_MOVES = (
    "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d4 exd4 "
    "6. cxd4 Bb4+ 7. Bd2 Bxd2+ 8. Nbxd2 d5 9. exd5 Nxd5 "
    "10. Qb3 Nce7 11. O-O O-O 12. Rfe1 c6 13. a4 Nf4"
)

_SICILIAN_PGN_MOVES = (
    "1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 "
    "6. Be2 e5 7. Nb3 Be7 8. O-O O-O 9. Be3 Be6 "
    "10. Qd2 Nbd7 11. a4 Rc8 12. f3 Qc7"
)

_QGD_PGN_MOVES = (
    "1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Be7 5. e3 O-O "
    "6. Nf3 Nbd7 7. Rc1 c6 8. Bd3 dxc4 9. Bxc4 Nd5 "
    "10. Bxe7 Qxe7 11. O-O Nxc3 12. Rxc3 e5"
)

_FRENCH_PGN_MOVES = (
    "1. e4 e6 2. d4 d5 3. Nc3 Nf6 4. e5 Nfd7 5. f4 c5 "
    "6. Nf3 Nc6 7. Be3 cxd4 8. Nxd4 Bc5 9. Qd2 O-O "
    "10. O-O-O a6 11. Nxc6 bxc6 12. Na4 Be7"
)

_KINGS_INDIAN_PGN_MOVES = (
    "1. d4 Nf6 2. c4 g6 3. Nc3 Bg7 4. e4 d6 5. Nf3 O-O "
    "6. Be2 e5 7. O-O Nc6 8. d5 Ne7 9. Ne1 Nd7 "
    "10. Nd3 f5 11. f3 f4 12. b4 g5"
)

OPENING_TEMPLATES = [
    {"eco": "C50", "name": "Italian Game", "moves": _ITALIAN_PGN_MOVES},
    {"eco": "B20", "name": "Sicilian Defense", "moves": _SICILIAN_PGN_MOVES},
    {"eco": "D30", "name": "Queens Gambit Declined", "moves": _QGD_PGN_MOVES},
    {"eco": "C00", "name": "French Defense", "moves": _FRENCH_PGN_MOVES},
    {"eco": "E60", "name": "Kings Indian Defense", "moves": _KINGS_INDIAN_PGN_MOVES},
]

RESULTS_MAP = {
    "1-0": ("win", GameResult.win, "checkmated"),
    "0-1": ("loss", GameResult.loss, "resigned"),
    "1/2-1/2": ("draw", GameResult.draw, "agreed"),
}


def _make_pgn(white, black, white_elo, black_elo, eco, opening, result_str,
              moves, with_clocks=True):
    """Build a valid PGN string."""
    headers = (
        f'[Event "Live Chess"]\n'
        f'[Site "Chess.com"]\n'
        f'[White "{white}"]\n'
        f'[Black "{black}"]\n'
        f'[Result "{result_str}"]\n'
        f'[WhiteElo "{white_elo}"]\n'
        f'[BlackElo "{black_elo}"]\n'
        f'[TimeControl "300"]\n'
        f'[ECO "{eco}"]\n'
        f'[Opening "{opening}"]\n'
        f'[Termination "Normal"]\n\n'
    )

    if with_clocks:
        # Add clock annotations to the moves string
        annotated = _add_clock_annotations(moves)
    else:
        annotated = moves

    return headers + annotated + " " + result_str


def _add_clock_annotations(moves_str):
    """Add realistic {[%clk ...]} annotations to moves."""
    tokens = moves_str.split()
    result = []
    white_clock = 300.0
    black_clock = 300.0

    for token in tokens:
        if token.endswith("."):
            result.append(token)
            continue
        # It's a move
        if result and result[-1].endswith("."):
            # White's move
            white_clock -= random.uniform(2, 15)
            white_clock = max(white_clock, 5.0)
            mins = int(white_clock) // 60
            secs = int(white_clock) % 60
            frac = int((white_clock % 1) * 10)
            result.append(f"{token} {{[%clk 0:{mins:02d}:{secs:02d}.{frac}]}}")
        else:
            # Black's move
            black_clock -= random.uniform(2, 15)
            black_clock = max(black_clock, 5.0)
            mins = int(black_clock) // 60
            secs = int(black_clock) % 60
            frac = int((black_clock % 1) * 10)
            result.append(f"{token} {{[%clk 0:{mins:02d}:{secs:02d}.{frac}]}}")

    return " ".join(result)


def _fen_at_ply(pgn_text, target_ply):
    """Get FEN at a given ply from a PGN string."""
    import chess.pgn, io
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if not game:
        return "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    board = game.board()
    for i, move in enumerate(game.mainline_moves()):
        if i + 1 == target_ply:
            return board.fen()
        board.push(move)
    return board.fen()


def _san_at_ply(pgn_text, target_ply):
    """Get the SAN move played at a given ply."""
    import chess.pgn, io
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if not game:
        return "e4"
    board = game.board()
    for i, move in enumerate(game.mainline_moves()):
        if i + 1 == target_ply:
            return board.san(move)
        board.push(move)
    return "e4"


def _uci_at_ply(pgn_text, target_ply):
    """Get the UCI move at a given ply."""
    import chess.pgn, io
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if not game:
        return "e2e4"
    board = game.board()
    for i, move in enumerate(game.mainline_moves()):
        if i + 1 == target_ply:
            return move.uci()
        board.push(move)
    return "e2e4"


def seed_all(db):
    """Seed the test database with realistic chess data."""
    random.seed(42)  # Reproducible

    games = []
    base_time = datetime(2025, 6, 15, 20, 0, 0, tzinfo=timezone.utc)

    # ── GAMES ──────────────────────────────────────────────────────────
    # Games 1-15: Italian Game, player as white
    # Games 1-10 form one big session (8+ games, gaps < 60 min)
    # Games 5,6,7,8: consecutive losses
    italian = OPENING_TEMPLATES[0]
    game_configs = [
        # (result_str, player_color, time_offset_minutes)
        # Session 1: games 1-10 (big session)
        ("1-0", "white", 0),       # game 1: win
        ("1-0", "white", 10),      # game 2: win
        ("1-0", "white", 20),      # game 3: win
        ("1-0", "white", 30),      # game 4: win
        ("0-1", "white", 40),      # game 5: loss (streak start)
        ("0-1", "white", 50),      # game 6: loss
        ("0-1", "white", 60),      # game 7: loss (note: 60 min gap is < threshold)
        ("0-1", "white", 69),      # game 8: loss (4th in a row)
        ("1-0", "white", 78),      # game 9: win
        ("1/2-1/2", "white", 87),  # game 10: draw
        # Separate sessions
        ("1-0", "white", 200),     # game 11
        ("0-1", "white", 210),     # game 12
        ("1-0", "white", 220),     # game 13
        ("1-0", "white", 280),     # game 14 (gap > 60 min = new session)
        ("1/2-1/2", "white", 295), # game 15
    ]

    for i, (res_str, pcolor, offset) in enumerate(game_configs):
        _res_lookup = RESULTS_MAP[res_str]
        gresult = _res_lookup[1]
        rtype = _res_lookup[2]
        if pcolor == "white" and gresult == GameResult.win:
            rtype = "checkmated"  # opponent checkmated
        elif pcolor == "white" and gresult == GameResult.loss:
            rtype = "resigned"
        rating = 800 + random.randint(-50, 50)
        opp_rating = 800 + random.randint(-50, 50)
        pgn = _make_pgn(
            "eddobbles2021", f"opponent_{i+1}",
            rating, opp_rating,
            italian["eco"], italian["name"],
            res_str, italian["moves"],
            with_clocks=(i < 12),  # first 12 with clocks
        )
        g = Game(
            chess_com_id=f"test_game_{i+1}",
            pgn=pgn,
            white_username="eddobbles2021",
            black_username=f"opponent_{i+1}",
            player_color=PlayerColor.white,
            result=gresult,
            result_type=rtype,
            time_control="300",
            time_class=TimeClass.blitz,
            rated=True,
            eco=italian["eco"],
            opening_name=italian["name"],
            end_time=base_time + timedelta(minutes=offset),
            white_rating=rating,
            black_rating=opp_rating,
            player_rating=rating,
            opponent_rating=opp_rating,
            total_moves=26,
        )
        db.add(g)
        games.append(g)

    # Games 16-25: Sicilian, player as black
    sicilian = OPENING_TEMPLATES[1]
    sic_base = datetime(2025, 8, 10, 18, 0, 0, tzinfo=timezone.utc)
    sic_results = ["0-1", "0-1", "0-1", "0-1", "1-0", "1-0", "1-0", "1-0", "1-0", "1/2-1/2"]
    for i, res_str in enumerate(sic_results):
        _res_lookup = RESULTS_MAP[res_str]
        gresult = _res_lookup[1]
        # For player as black: 0-1 = win for black = player win, 1-0 = white wins = player loss
        if res_str == "0-1":
            gresult = GameResult.win
            rtype = "resigned"
        elif res_str == "1-0":
            gresult = GameResult.loss
            rtype = "checkmated"
        else:
            gresult = GameResult.draw
            rtype = "agreed"
        rating = 820 + random.randint(-30, 30)
        opp_rating = 815 + random.randint(-30, 30)
        pgn = _make_pgn(
            f"opponent_{16+i}", "eddobbles2021",
            opp_rating, rating,
            sicilian["eco"], sicilian["name"],
            res_str, sicilian["moves"],
            with_clocks=(i < 8),
        )
        g = Game(
            chess_com_id=f"test_game_{16+i}",
            pgn=pgn,
            white_username=f"opponent_{16+i}",
            black_username="eddobbles2021",
            player_color=PlayerColor.black,
            result=gresult,
            result_type=rtype,
            time_control="300",
            time_class=TimeClass.blitz,
            rated=True,
            eco=sicilian["eco"],
            opening_name=sicilian["name"],
            end_time=sic_base + timedelta(minutes=i * 12),
            white_rating=opp_rating,
            black_rating=rating,
            player_rating=rating,
            opponent_rating=opp_rating,
            total_moves=24,
        )
        db.add(g)
        games.append(g)

    # Games 26-35: QGD, player as white
    qgd = OPENING_TEMPLATES[2]
    qgd_base = datetime(2025, 10, 5, 21, 0, 0, tzinfo=timezone.utc)
    qgd_results = ["1-0", "1-0", "1-0", "1-0", "1-0", "0-1", "0-1", "0-1", "1/2-1/2", "1/2-1/2"]
    for i, res_str in enumerate(qgd_results):
        _res_lookup = RESULTS_MAP[res_str]
        gresult = _res_lookup[1]
        rtype = _res_lookup[2]
        rating = 850 + random.randint(-20, 30)
        opp_rating = 840 + random.randint(-20, 30)
        pgn = _make_pgn(
            "eddobbles2021", f"opponent_{26+i}",
            rating, opp_rating,
            qgd["eco"], qgd["name"],
            res_str, qgd["moves"],
            with_clocks=(i < 6),
        )
        g = Game(
            chess_com_id=f"test_game_{26+i}",
            pgn=pgn,
            white_username="eddobbles2021",
            black_username=f"opponent_{26+i}",
            player_color=PlayerColor.white,
            result=gresult,
            result_type=rtype,
            time_control="300",
            time_class=TimeClass.blitz,
            rated=True,
            eco=qgd["eco"],
            opening_name=qgd["name"],
            end_time=qgd_base + timedelta(minutes=i * 15),
            white_rating=rating,
            black_rating=opp_rating,
            player_rating=rating,
            opponent_rating=opp_rating,
            total_moves=24,
        )
        db.add(g)
        games.append(g)

    # Games 36-42: French, player as black
    french = OPENING_TEMPLATES[3]
    fr_base = datetime(2025, 12, 20, 19, 0, 0, tzinfo=timezone.utc)
    fr_results = ["0-1", "0-1", "0-1", "1-0", "1-0", "1-0", "1/2-1/2"]
    for i, res_str in enumerate(fr_results):
        if res_str == "0-1":
            gresult = GameResult.win
            rtype = "resigned"
        elif res_str == "1-0":
            gresult = GameResult.loss
            rtype = "checkmated"
        else:
            gresult = GameResult.draw
            rtype = "agreed"
        rating = 860 + random.randint(-15, 25)
        opp_rating = 855 + random.randint(-15, 25)
        pgn = _make_pgn(
            f"opponent_{36+i}", "eddobbles2021",
            opp_rating, rating,
            french["eco"], french["name"],
            res_str, french["moves"],
            with_clocks=False,
        )
        g = Game(
            chess_com_id=f"test_game_{36+i}",
            pgn=pgn,
            white_username=f"opponent_{36+i}",
            black_username="eddobbles2021",
            player_color=PlayerColor.black,
            result=gresult,
            result_type=rtype,
            time_control="300",
            time_class=TimeClass.blitz,
            rated=True,
            eco=french["eco"],
            opening_name=french["name"],
            end_time=fr_base + timedelta(minutes=i * 14),
            white_rating=opp_rating,
            black_rating=rating,
            player_rating=rating,
            opponent_rating=opp_rating,
            total_moves=24,
        )
        db.add(g)
        games.append(g)

    # Games 43-50: King's Indian, player as white
    ki = OPENING_TEMPLATES[4]
    ki_base = datetime(2026, 2, 1, 20, 0, 0, tzinfo=timezone.utc)
    ki_results = ["1-0", "1-0", "1-0", "1-0", "0-1", "0-1", "0-1", "1/2-1/2"]
    # Games 43-44 form a 2-game session (close together)
    ki_offsets = [0, 8, 120, 130, 140, 250, 260, 270]
    for i, (res_str, offset) in enumerate(zip(ki_results, ki_offsets)):
        _res_lookup = RESULTS_MAP[res_str]
        gresult = _res_lookup[1]
        rtype = _res_lookup[2]
        rating = 870 + random.randint(-10, 20)
        opp_rating = 860 + random.randint(-10, 20)
        pgn = _make_pgn(
            "eddobbles2021", f"opponent_{43+i}",
            rating, opp_rating,
            ki["eco"], ki["name"],
            res_str, ki["moves"],
            with_clocks=(i < 4),
        )
        g = Game(
            chess_com_id=f"test_game_{43+i}",
            pgn=pgn,
            white_username="eddobbles2021",
            black_username=f"opponent_{43+i}",
            player_color=PlayerColor.white,
            result=gresult,
            result_type=rtype,
            time_control="300",
            time_class=TimeClass.blitz,
            rated=True,
            eco=ki["eco"],
            opening_name=ki["name"],
            end_time=ki_base + timedelta(minutes=offset),
            white_rating=rating,
            black_rating=opp_rating,
            player_rating=rating,
            opponent_rating=opp_rating,
            total_moves=24,
        )
        db.add(g)
        games.append(g)

    db.flush()  # Assign IDs

    # ── MOVE ANALYSIS (games 1-20) ─────────────────────────────────────
    for game in games[:20]:
        pgn_text = game.pgn
        player_is_white = game.player_color == PlayerColor.white

        import chess.pgn as cpgn, io
        pgn_game = cpgn.read_game(io.StringIO(pgn_text))
        if not pgn_game:
            continue
        board = pgn_game.board()
        moves_list = list(pgn_game.mainline_moves())

        for ply_idx, move in enumerate(moves_list):
            ply = ply_idx + 1
            move_number = (ply + 1) // 2
            is_white = (ply % 2 == 1)
            color = PlayerColor.white if is_white else PlayerColor.black
            is_player = (is_white == player_is_white)

            fen_before = board.fen()
            san = board.san(move)
            uci = move.uci()
            board.push(move)

            # Simulate eval values
            base_eval = random.uniform(-50, 50)
            if is_player:
                cp_loss = random.choice([0, 0, 0, 5, 15, 30, 80, 150, 250])
                eval_after = base_eval - cp_loss
            else:
                cp_loss = random.choice([0, 0, 5, 10, 20])
                eval_after = base_eval + cp_loss

            from app.services.stockfish import classify_move, detect_game_phase
            classification = classify_move(cp_loss) if is_player else classify_move(cp_loss)
            phase = detect_game_phase(board, ply)

            ma = MoveAnalysis(
                game_id=game.id,
                move_number=move_number,
                ply=ply,
                color=color,
                is_player_move=is_player,
                fen_before=fen_before,
                move_played=uci,
                move_played_san=san,
                best_move=uci,  # For simplicity, best = played for most
                best_move_san=san,
                eval_before=round(base_eval, 1),
                eval_after=round(eval_after, 1),
                eval_delta=round(-cp_loss, 1) if is_player else None,
                classification=classification,
                depth=18,
                game_phase=phase,
                top_3_lines=[{"moves": [san], "eval": int(base_eval)}],
            )
            db.add(ma)

    db.flush()

    # ── GAME SUMMARIES (games 1-10) ────────────────────────────────────
    for game in games[:10]:
        analyses = db.query(MoveAnalysis).filter(
            MoveAnalysis.game_id == game.id,
            MoveAnalysis.is_player_move == True,
        ).all()

        cp_losses = [abs(a.eval_delta) for a in analyses if a.eval_delta is not None]
        avg_cpl = sum(cp_losses) / len(cp_losses) if cp_losses else 0
        blunders = sum(1 for a in analyses if a.classification == MoveClassification.blunder)
        mistakes = sum(1 for a in analyses if a.classification == MoveClassification.mistake)
        inaccuracies = sum(1 for a in analyses if a.classification == MoveClassification.inaccuracy)

        opening_analyses = [a for a in analyses if a.game_phase == GamePhase.opening]
        mid_analyses = [a for a in analyses if a.game_phase == GamePhase.middlegame]
        end_analyses = [a for a in analyses if a.game_phase == GamePhase.endgame]

        def _phase_avg(phase_list):
            vals = [abs(a.eval_delta) for a in phase_list if a.eval_delta is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        # Critical moments: plies where cp_loss > 100
        critical = [a.ply for a in analyses if a.eval_delta is not None and abs(a.eval_delta) > 100]

        gs = GameSummary(
            game_id=game.id,
            avg_centipawn_loss=round(avg_cpl, 1),
            blunder_count=blunders,
            mistake_count=mistakes,
            inaccuracy_count=inaccuracies,
            opening_accuracy=_phase_avg(opening_analyses),
            middlegame_accuracy=_phase_avg(mid_analyses),
            endgame_accuracy=_phase_avg(end_analyses),
            critical_moments=critical if critical else [],
        )
        db.add(gs)

    db.flush()

    # ── COACHING SESSIONS ──────────────────────────────────────────────
    coaching_data = [
        (games[0].id, SessionType.game_review, "Review game 1", "Great opening play..."),
        (games[1].id, SessionType.game_review, "Review game 2", "Solid middlegame..."),
        (games[2].id, SessionType.game_review, "Review game 3", "Nice endgame technique..."),
        (None, SessionType.pattern_diagnosis, "Diagnose patterns", "Top weakness: time management..."),
        (None, SessionType.behavioral_analysis, "Behavioral", "Tilt pattern detected..."),
    ]
    for gid, stype, prompt, response in coaching_data:
        cs = CoachingSession(
            game_id=gid,
            session_type=stype,
            prompt_sent=prompt,
            response=response,
            model_used="claude-sonnet-4-20250514",
        )
        db.add(cs)

    db.flush()

    # ── DRILL POSITIONS ────────────────────────────────────────────────
    drill_configs = []
    # Create 15 drills from the first 15 analyzed games
    for idx, game in enumerate(games[:15]):
        # Pick a ply that's a player move (odd if white, even if black)
        target_ply = 3 if game.player_color == PlayerColor.white else 4
        fen = _fen_at_ply(game.pgn, target_ply)
        correct = _san_at_ply(game.pgn, target_ply)
        player_move = _san_at_ply(game.pgn, target_ply)

        phase = GamePhase.opening if target_ply < 10 else GamePhase.middlegame
        themes = ["fork", "pin"] if idx % 3 == 0 else (["hanging_piece"] if idx % 3 == 1 else ["tactics"])

        # Vary the review/accuracy stats
        shown = random.randint(0, 8)
        correct_count = random.randint(0, shown) if shown > 0 else 0
        review_offset = random.randint(-5, 5)

        drill_configs.append({
            "game_id": game.id,
            "ply": target_ply,
            "fen": fen,
            "correct_move_san": correct,
            "player_move_san": player_move,
            "eval_delta": random.uniform(-300, -50),
            "tactical_theme": themes,
            "game_phase": phase,
            "opening_eco": game.eco,
            "times_shown": shown,
            "times_correct": correct_count,
            "next_review_date": date.today() + timedelta(days=review_offset),
            "difficulty_rating": round(random.uniform(1.0, 4.0), 1),
        })

    for dc in drill_configs:
        dp = DrillPosition(**dc)
        db.add(dp)

    db.flush()

    # ── PLAY SESSIONS ──────────────────────────────────────────────────
    # Session 1: games 1-10 (big session, 10 games)
    ps1 = PlaySession(
        start_time=games[0].end_time,
        end_time=games[9].end_time,
        game_count=10,
        game_ids=[g.id for g in games[:10]],
        starting_rating=games[0].player_rating,
        ending_rating=games[9].player_rating,
        rating_delta=games[9].player_rating - games[0].player_rating,
        win_count=5,
        loss_count=4,
        draw_count=1,
        avg_cpl=45.2,
        avg_cpl_first_half=38.0,
        avg_cpl_second_half=52.4,
        longest_loss_streak=4,
        session_result=SessionResult.net_negative,
    )
    db.add(ps1)

    # Session 2: games 43-44 (2-game session)
    ps2 = PlaySession(
        start_time=games[42].end_time,
        end_time=games[43].end_time,
        game_count=2,
        game_ids=[games[42].id, games[43].id],
        starting_rating=games[42].player_rating,
        ending_rating=games[43].player_rating,
        rating_delta=games[43].player_rating - games[42].player_rating,
        win_count=2,
        loss_count=0,
        draw_count=0,
        avg_cpl=None,
        avg_cpl_first_half=None,
        avg_cpl_second_half=None,
        longest_loss_streak=0,
        session_result=SessionResult.net_positive,
    )
    db.add(ps2)

    # Session 3: games 45-47 (3 games)
    ps3 = PlaySession(
        start_time=games[44].end_time,
        end_time=games[46].end_time,
        game_count=3,
        game_ids=[games[44].id, games[45].id, games[46].id],
        starting_rating=games[44].player_rating,
        ending_rating=games[46].player_rating,
        rating_delta=games[46].player_rating - games[44].player_rating,
        win_count=1,
        loss_count=2,
        draw_count=0,
        avg_cpl=None,
        avg_cpl_first_half=None,
        avg_cpl_second_half=None,
        longest_loss_streak=2,
        session_result=SessionResult.net_negative,
    )
    db.add(ps3)

    db.commit()
