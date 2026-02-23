# Chess Coach — CLAUDE.md

Project-specific context for Claude Code sessions. See DOCTRINE.md for operating principles.

## WHAT THIS IS

Personalized chess coaching platform for eddobbles2021 on Chess.com. Ingests full game history, runs Stockfish analysis, uses Claude to explain WHY moves are right or wrong — not just what the engine recommends.

## CURRENT STATE

**Database:** 5,093 games imported from Chess.com (June 2021 — Feb 2026). SQLite locally, Postgres on Railway.

**Working end-to-end:**
- Chess.com PubAPI sync (incremental, all 57 monthly archives)
- Stockfish 16 analysis at depth 18 (move classification, game phase detection, critical moments, top-3 lines)
- Claude coaching: single move explanations (Sonnet), full game reviews (Sonnet), pattern diagnosis (Opus), game walkthroughs (Sonnet), behavioral analysis (Opus), monthly reports (Opus)
- Drill trainer with SM-2 spaced repetition + "What Would You Play?" replay mode
- Pre-session warm-up generator with personalized drill selection
- Time management analytics with clock time parsing
- Weekly progress snapshots with trend analysis
- Playing session detection with tilt/fatigue analysis
- Behavioral pattern mining (8 cross-game detectors)
- Frontend SPA: Dashboard, Game History, Game Review (board + walkthrough), Patterns, Drills, Sessions, Progress, Opening Book
- 24 API endpoints across 5 routers

**Phase completion:**
- Phase 1 (Foundation): DONE
- Phase 2 (Engine Analysis): DONE
- Phase 3 (Coaching MVP): DONE
- Phase 4 (Frontend v1): DONE
- Phase 5 (Pattern Analytics): DONE
- Phase 6 (Drill Trainer): DONE
- Phase 7 (Backfill & Polish): DONE
- Phase 8 (Advanced Analytics): DONE

## WHAT WAS ADDED IN PHASE 7

1. **Tactical theme classification** (`app/services/tactics.py`) — Pure python-chess position analysis detecting: forks, pins, skewers, back-rank threats, discovered/double check, hanging/trapped/overloaded pieces, passed pawns, promotions, winning exchanges, plus eval-context themes.
2. **Opening Book view** — New frontend tab + `/api/dashboard/opening-book/{eco}` API endpoint. Shows your most common moves at each ply, alternatives, color breakdown, drill count per opening.
3. **CLI batch tooling** (`cli.py`) — Commands: `sync`, `analyze --limit N --depth 18`, `extract-drills`, `tag-themes [--force]`, `status`. Progress tracking with ETA.
4. **Dashboard caching** — In-memory cache with 5-min TTL on expensive queries (summary, opening-book).
5. **Drill themes wired in** — `extract_drill_positions()` now auto-classifies tactical themes on creation.

## WHAT WAS ADDED IN PHASE 8

1. **Interactive Game Walkthrough** (`POST /api/coach/walkthrough/{game_id}`) — Move-by-move guided replay where Claude comments only at inflection points (mistakes, blunders, eval swings, phase transitions, game end). Single Claude API call for cost efficiency with XML-structured prompts. Frontend with step-through navigation and autoplay.
2. **Behavioral Pattern Detection** (`app/services/behavior.py`) — 8 cross-game behavioral detectors: early queen trades, piece retreats under pressure, same piece twice in opening, pawn storms on castled king, endgame avoidance, losing streak behavior, time trouble correlation, first move syndrome. Claude Opus generates narrative diagnosis.
3. **Tilt & Session Detection** (`app/services/sessions.py`, `PlaySession` model) — Groups games into sessions (60-min gap), tracks performance degradation. Computes optimal session length, tilt detection (CPL/win rate after losses), best/worst sessions.
4. **Time Management Analysis** (`app/services/time_management.py`) — Parses `%clk` annotations from PGN, backfills `clock_seconds`/`time_spent_seconds` on MoveAnalysis. `GET /api/dashboard/time-management` computes time-vs-accuracy buckets, time trouble stats, opening time waste.
5. **"What Would You Play?" Training Mode** (`GET /api/drills/replay-positions`, `POST /api/drills/replay-positions/{id}/reveal`) — Presents positions from player's own games, collects guess, then reveals answer with Claude coaching. Tracks offline accuracy vs game accuracy.
6. **Weekly Progress Snapshots** (`WeeklySnapshot` model, `GET /api/dashboard/progress`) — Stores weekly metrics (CPL, blunder rate, rating, phase performance). Trend analysis with linear regression. `POST /api/coach/monthly-report` generates Opus narrative.
7. **Pre-Session Warm-Up Generator** (`GET /api/drills/warmup`) — Generates personalized 5-drill warm-up targeting recent weaknesses (worst phase, most frequent blunder type, problematic openings). Prominent "Warm Up" button on dashboard.
8. **CLI additions** — `backfill-clocks`, `snapshot`, `backfill-snapshots` commands.
9. **Frontend additions** — Progress tab (rating trend, CPL/blunder charts, time management stats, monthly report), Sessions tab (tilt metrics, session history), Walkthrough mode in Game Review.

## ARCHITECTURE

```
app/
  config.py              — Settings from env vars / .env
  database.py            — SQLAlchemy engine (SQLite or Postgres auto-detect)
  models/
    models.py            — 7 tables: games, move_analysis, game_summaries, coaching_sessions, drill_positions, play_sessions, weekly_snapshots
  routers/
    games.py             — GET /api/games, GET /api/games/{id}, POST /api/games/sync
    analysis.py          — POST /api/analysis/batch, GET /api/analysis/status, GET /api/analysis/game/{id}
    coaching.py          — POST /api/coach/game-review/{id}, /move-explain, /walkthrough/{id}, /behavioral-analysis, /diagnose, /monthly-report, GET /sessions
    drills.py            — GET /api/drills, POST /{id}/attempt, GET /stats, POST /extract, GET /replay-positions, POST /replay-positions/{id}/reveal, GET /warmup
    dashboard.py         — GET /api/dashboard/summary, /openings, /patterns, /time-analysis, /opening-book/{eco}, /time-management, /progress, /sessions, /sessions/{date}
  services/
    chess_com.py         — Chess.com PubAPI ingestion + clock time extraction
    stockfish.py         — Engine analysis pipeline (depth 18 batch, depth 22 deep)
    coaching.py          — Claude prompt templates and API calls (walkthrough, behavioral, monthly report)
    drills.py            — Spaced repetition logic and drill extraction
    tactics.py           — Tactical theme detection (forks, pins, skewers, etc.)
    behavior.py          — Behavioral pattern mining (8 cross-game detectors)
    sessions.py          — Playing session detection and tilt analysis
    time_management.py   — Clock time parsing and time-vs-accuracy analytics
    progress.py          — Weekly snapshot computation and trend analysis
    warmup.py            — Pre-session warm-up generator
static/
  index.html             — SPA shell with 8 views (Dashboard, Games, Review, Patterns, Drills, Sessions, Progress, Opening Book)
  css/style.css          — Dobbles.AI design system
  js/app.js              — Client-side application (board renderer, charts, navigation, walkthrough, replay mode)
main.py                  — FastAPI app entry point, mounts routers and static files
cli.py                   — CLI batch operations (sync, analyze, extract-drills, tag-themes, build-sessions, backfill-clocks, snapshot, backfill-snapshots, status)
```

## KEY DECISIONS

- **SQLite default** for local dev, Postgres via `DATABASE_URL` env var on Railway
- **No React** — single HTML/JS file, canvas-based charts, text-based board renderer
- **Stockfish evaluates, Claude teaches** — never ask Claude to calculate
- **Sonnet for moves/games, Opus for pattern diagnosis** — cost optimization
- **SM-2 intervals** for drill spacing: 1, 3, 7, 14, 30, 60 days

## PLAYER PROFILE (eddobbles2021)

- 5,093 games, 5,077 blitz (5|5), 16 rapid
- Record: 2,473W - 2,445L - 175D (48.6% win rate)
- Blitz rating range: 638-1,212 (current ~813)
- As White: 49.9% WR | As Black: 47.2% WR
- Top opening: Italian Game (511 games, 54% WR)
- Puzzle rating 1,435 → 622-point puzzle-to-blitz gap indicates tactical knowledge that breaks down under time pressure

## COMMANDS

```bash
# Start server
uvicorn main:app --host 0.0.0.0 --port 8000

# CLI batch tools (recommended for heavy work)
python cli.py sync                    # Sync games from Chess.com
python cli.py analyze --limit 200     # Batch Stockfish analysis with progress/ETA
python cli.py extract-drills          # Extract drill positions from analyzed games
python cli.py tag-themes              # Tag tactical themes on untagged drills
python cli.py tag-themes --force      # Re-tag all drills
python cli.py build-sessions          # Build play session records
python cli.py backfill-clocks         # Parse clock times from PGN into MoveAnalysis
python cli.py backfill-clocks --limit 100  # Clock backfill on a subset
python cli.py snapshot                # Compute weekly snapshot for current week
python cli.py backfill-snapshots      # Generate snapshots for all historical weeks
python cli.py status                  # Show database status

# API equivalents
curl -X POST http://localhost:8000/api/games/sync
curl -X POST http://localhost:8000/api/analysis/batch -H "Content-Type: application/json" -d '{"limit": 200}'
curl -X POST http://localhost:8000/api/coach/game-review/5093
curl -X POST http://localhost:8000/api/coach/walkthrough/5093
curl -X POST http://localhost:8000/api/coach/behavioral-analysis
curl -X POST http://localhost:8000/api/coach/monthly-report
curl -X POST http://localhost:8000/api/drills/extract
curl http://localhost:8000/api/drills/replay-positions?count=10
curl http://localhost:8000/api/drills/warmup
curl http://localhost:8000/api/dashboard/time-management
curl http://localhost:8000/api/dashboard/progress?weeks=12
curl http://localhost:8000/api/dashboard/sessions
```

## ENV VARS

```
DATABASE_URL          — Connection string (default: sqlite:///chess_coach.db)
ANTHROPIC_API_KEY     — Claude API access
CHESS_COM_USERNAME    — Target player (default: eddobbles2021)
STOCKFISH_PATH        — Binary location (default: /usr/games/stockfish)
STOCKFISH_DEPTH       — Batch analysis depth (default: 18)
STOCKFISH_DEEP_DEPTH  — Single-game deep review depth (default: 22)
```

## DEPLOYMENT

- **Railway project:** https://railway.com/project/12a4ab27-3e6d-4da8-b40c-0024e4a27f74
- **Railway service:** chess-coach (FastAPI + Stockfish in Docker)
- **Railway Postgres:** auto-injected via `DATABASE_URL`
- Token in `.env` as `RAILWAY_TOKEN` (never commit)

### Deploy to Railway

1. In Railway dashboard → New Service → Deploy from GitHub repo
2. Railway auto-detects `Dockerfile` + `railway.toml`
3. Set environment variables in Railway dashboard:
   - `ANTHROPIC_API_KEY` — Claude API key
   - `CHESS_COM_USERNAME` — `eddobbles2021`
   - `STOCKFISH_PATH` — `/usr/games/stockfish` (installed via Dockerfile apt-get)
   - `STOCKFISH_DEPTH` — `18`
   - `DATABASE_URL` — auto-injected by Railway Postgres plugin
4. Add Postgres plugin → Railway auto-injects `DATABASE_URL`
5. Deploy triggers on push to main branch

## SENSITIVE FILES

- `.env` — API keys and Railway token (gitignored)
- `chess_coach.db` — Local SQLite database (gitignored)
