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
- Drill trainer with SM-2 spaced repetition
- Frontend SPA: Dashboard, Game History, Game Review (board + move list + coaching panel), Patterns, Drills
- 18 API endpoints across 5 routers

**Phase completion:**
- Phase 1 (Foundation): DONE
- Phase 2 (Engine Analysis): DONE
- Phase 3 (Coaching MVP): DONE
- Phase 4 (Frontend v1): DONE
- Phase 5 (Pattern Analytics): DONE
- Phase 6 (Drill Trainer): DONE
- Phase 7 (Backfill & Polish): ~70% — see NEXT STEPS below

## NEXT STEPS (Phase 7 gaps)

1. **Tactical theme classification** — `DrillPosition.tactical_theme` field exists but is never populated. Need logic to detect pins, forks, skewers, back-rank threats, etc. from Stockfish lines.
2. **Opening book view** — ECO codes stored but no dedicated opening study page with theory lines, your deviations from book, and per-opening drill launcher.
3. **Backfill tooling** — `batch_analyze()` works but no background job scheduler or CLI command. Full 5,093 game analysis needs to run as a long-lived background task.
4. **Caching** — No HTTP response caching, no precomputed aggregates. Dashboard queries hit the DB every time.
5. **Progressive curriculum** — Drills use spaced repetition but no staged learning path (fundamentals → intermediate → advanced).

## ARCHITECTURE

```
app/
  config.py          — Settings from env vars / .env
  database.py        — SQLAlchemy engine (SQLite or Postgres auto-detect)
  models/
    models.py        — 5 tables: games, move_analysis, game_summaries, coaching_sessions, drill_positions
  routers/
    games.py         — GET /api/games, GET /api/games/{id}, POST /api/games/sync
    analysis.py      — POST /api/analysis/batch, GET /api/analysis/status, GET /api/analysis/game/{id}
    coaching.py      — POST /api/coach/game-review/{id}, POST /api/coach/move-explain, POST /api/coach/diagnose, GET /api/coach/sessions
    drills.py        — GET /api/drills, POST /api/drills/{id}/attempt, GET /api/drills/stats, POST /api/drills/extract
    dashboard.py     — GET /api/dashboard/summary, /openings, /patterns, /time-analysis
  services/
    chess_com.py     — Chess.com PubAPI ingestion (single-threaded, 1 req/sec)
    stockfish.py     — Engine analysis pipeline (depth 18 batch, depth 22 deep)
    coaching.py      — Claude prompt templates and API calls
    drills.py        — Spaced repetition logic and drill extraction
static/
  index.html         — SPA shell with all 5 views
  css/style.css      — Dobbles.AI design system
  js/app.js          — Client-side application (board renderer, charts, navigation)
main.py              — FastAPI app entry point, mounts routers and static files
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

# Sync games from Chess.com
curl -X POST http://localhost:8000/api/games/sync

# Analyze last 200 blitz games
curl -X POST http://localhost:8000/api/analysis/batch -H "Content-Type: application/json" -d '{"limit": 200}'

# Generate AI review for a game
curl -X POST http://localhost:8000/api/coach/game-review/5093

# Extract drill positions
curl -X POST http://localhost:8000/api/drills/extract
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

## SENSITIVE FILES

- `.env` — API keys (gitignored)
- `chess_coach.db` — Local SQLite database (gitignored)
