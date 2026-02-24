# Chess Coach — CLAUDE.md

Project-specific context for Claude Code sessions. See DOCTRINE.md for operating principles.

## WHAT THIS IS

Personalized chess coaching platform for eddobbles2021 on Chess.com. Ingests full game history, runs Stockfish analysis, uses Claude to explain WHY moves are right or wrong — not just what the engine recommends.

## CURRENT STATE

**Database:** 5,093 games imported from Chess.com (June 2021 — Feb 2026). SQLite locally, Postgres on Railway.

**Working end-to-end:**
- Chess.com PubAPI sync (incremental, all 57 monthly archives)
- Stockfish 16 analysis at depth 18 (move classification, game phase detection, critical moments, top-3 lines)
- Claude coaching: single move explanations (Sonnet), full game reviews (Sonnet), pattern diagnosis (Opus)
- Game walkthrough with inflection-point commentary
- Behavioral pattern mining (8 cross-game detectors)
- Playing session detection with tilt/fatigue analysis
- Drill trainer with SM-2 spaced repetition
- Frontend SPA: Dashboard, Games, Review, Patterns, Drills, Sessions, Opening Book (7 views)
- 23 API endpoints across 5 routers

**Phase completion:**
- Phase 1 (Foundation): DONE
- Phase 2 (Engine Analysis): DONE
- Phase 3 (Coaching MVP): DONE
- Phase 4 (Frontend v1): DONE
- Phase 5 (Pattern Analytics): DONE
- Phase 6 (Drill Trainer): DONE
- Phase 7 (Backfill & Polish): DONE
- Phase 8 (Behavioral & Session Analytics): DONE

## WHAT WAS ADDED IN PHASE 8

1. **Behavioral pattern mining** (`app/services/behavior.py`) — 8 cross-game detectors: early queen trades, piece retreats under pressure, same-piece-twice in opening, pawn storms on castled king, endgame avoidance, losing streak behavior, time trouble correlation, first-move syndrome. Each returns frequency, impact, severity, example games.
2. **Game walkthrough** — `POST /api/coach/walkthrough/{id}` endpoint with inflection-point commentary. Frontend guided step-through with autoplay.
3. **Session detection & tilt analysis** (`app/services/sessions.py`) — Groups consecutive blitz games (gap < 60 min) into sessions. Computes tilt metrics: CPL after loss vs win, win rate after 2+ consecutive losses, optimal stop point (crossover game where cumulative delta goes negative).
4. **PlaySession model** — New `play_sessions` table storing per-session stats: rating delta, W/L/D counts, CPL first-half vs second-half, longest loss streak.
5. **Sessions frontend tab** — Performance by session length chart (canvas), tilt indicator card, session history table with sparklines, clickable drill-down to game-by-game detail.
6. **Behavioral analysis endpoint** — `POST /api/coach/behavioral-analysis` runs all 8 detectors + Claude narrative synthesis.

## WHAT WAS ADDED IN PHASE 7

1. **Tactical theme classification** (`app/services/tactics.py`) — Pure python-chess position analysis detecting: forks, pins, skewers, back-rank threats, discovered/double check, hanging/trapped/overloaded pieces, passed pawns, promotions, winning exchanges, plus eval-context themes.
2. **Opening Book view** — New frontend tab + `/api/dashboard/opening-book/{eco}` API endpoint. Shows your most common moves at each ply, alternatives, color breakdown, drill count per opening.
3. **CLI batch tooling** (`cli.py`) — Commands: `sync`, `analyze --limit N --depth 18`, `extract-drills`, `tag-themes [--force]`, `status`. Progress tracking with ETA.
4. **Dashboard caching** — In-memory cache with 5-min TTL on expensive queries (summary, opening-book).
5. **Drill themes wired in** — `extract_drill_positions()` now auto-classifies tactical themes on creation.

## ARCHITECTURE

```
app/
  config.py          — Settings from env vars / .env
  database.py        — SQLAlchemy engine (SQLite or Postgres auto-detect)
  models/
    models.py        — 6 tables: games, move_analysis, game_summaries, coaching_sessions, drill_positions, play_sessions
  routers/
    games.py         — GET /api/games, GET /api/games/{id}, POST /api/games/sync
    analysis.py      — POST /api/analysis/batch, GET /api/analysis/status, GET /api/analysis/game/{id}
    coaching.py      — POST /api/coach/game-review/{id}, POST /api/coach/move-explain, POST /api/coach/diagnose,
                       POST /api/coach/walkthrough/{id}, POST /api/coach/behavioral-analysis, GET /api/coach/sessions
    drills.py        — GET /api/drills, POST /api/drills/{id}/attempt, GET /api/drills/stats, POST /api/drills/extract
    dashboard.py     — GET /api/dashboard/summary, /openings, /patterns, /time-analysis, /opening-book/{eco},
                       /sessions, /sessions/{date}
  services/
    chess_com.py     — Chess.com PubAPI ingestion (single-threaded, 1 req/sec)
    stockfish.py     — Engine analysis pipeline (depth 18 batch, depth 22 deep)
    coaching.py      — Claude prompt templates and API calls (move explain, game review, walkthrough, behavioral)
    drills.py        — Spaced repetition logic and drill extraction
    tactics.py       — Tactical theme detection (forks, pins, skewers, etc.)
    sessions.py      — Playing session detection, tilt analysis, optimal stop point
    behavior.py      — 8 cross-game behavioral pattern detectors
static/
  index.html         — SPA shell with 7 views (Dashboard, Games, Review, Patterns, Drills, Sessions, Opening Book)
  css/style.css      — Dobbles.AI design system
  js/app.js          — Client-side application (board renderer, charts, navigation)
main.py              — FastAPI app entry point, mounts routers and static files
cli.py               — CLI batch operations (sync, analyze, extract-drills, tag-themes, build-sessions, status)
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
python cli.py build-sessions          # Build PlaySession records from game history
python cli.py status                  # Show database status

# API equivalents
curl -X POST http://localhost:8000/api/games/sync
curl -X POST http://localhost:8000/api/analysis/batch -H "Content-Type: application/json" -d '{"limit": 200}'
curl -X POST http://localhost:8000/api/coach/game-review/5093
curl -X POST http://localhost:8000/api/drills/extract
curl http://localhost:8000/api/dashboard/sessions
curl -X POST http://localhost:8000/api/coach/behavioral-analysis
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
- **Railway token:** `c6d707bb-1eb9-436e-a01a-fe58eefecb5b`
- **Service ID:** `16e51c7a-2b69-475a-99b7-6a7bb02a2202`
- **Environment ID:** `cb260c13-5606-48ef-87a6-a34d104cf265`

### Deploy to Railway

**Quick redeploy (via API):**
```bash
curl -sk -X POST "https://backboard.railway.com/graphql/v2" \
  -H "Authorization: Bearer c6d707bb-1eb9-436e-a01a-fe58eefecb5b" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { serviceInstanceRedeploy(serviceId: \"16e51c7a-2b69-475a-99b7-6a7bb02a2202\", environmentId: \"cb260c13-5606-48ef-87a6-a34d104cf265\") }"}'
```

**Initial setup:**
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
