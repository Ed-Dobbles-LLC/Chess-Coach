# Missing Features

Features described in the test prompt but **not implemented** in the codebase.

## Models Not Found

- **WeeklySnapshot** — No `WeeklySnapshot` model exists in `app/models/models.py`. Referenced by progress tracking and monthly report features.

## API Endpoints Not Found

- **`GET /api/dashboard/time-management`** — Does not exist. (`GET /api/dashboard/time-analysis` exists and covers time-of-day/day-of-week performance, but not the time-management-specific fields like `time_trouble_stats`, `time_vs_accuracy`, `opening_time_waste`, `avg_time_per_move_by_phase`.)
- **`GET /api/dashboard/progress?weeks=12`** — Does not exist. No progress/trend endpoint with weekly snapshots.
- **`POST /api/coach/monthly-report`** — Does not exist. No monthly report generation endpoint.
- **`GET /api/drills/replay-positions`** — Does not exist. No replay-specific drill endpoint.
- **`POST /api/drills/replay-positions/{id}/reveal`** — Does not exist. No reveal endpoint for replay drills.
- **`GET /api/drills/warmup`** — Does not exist. No warmup drill selection endpoint.

## CLI Commands Not Found

- **`python cli.py backfill-clocks`** — Does not exist. No CLI command to backfill clock_seconds/time_spent_seconds on MoveAnalysis from PGN `%clk` annotations. (The `clock_times` JSON column on MoveAnalysis exists, but there's no backfill command.)
- **`python cli.py snapshot`** — Does not exist. No command to create a WeeklySnapshot for the current week.
- **`python cli.py backfill-snapshots`** — Does not exist. No command to create historical weekly snapshots.

## Services Not Found

- **`app/services/time_management.py`** — Does not exist. No dedicated time management analysis service.
- **`app/services/progress.py`** — Does not exist. No weekly snapshot or progress tracking service.

## Summary

| Category | Described | Exists | Missing |
|----------|-----------|--------|---------|
| Models | 7 | 6 | 1 (WeeklySnapshot) |
| API Endpoints | 26+ | 23 | 6 |
| CLI Commands | 9 | 6 | 3 |
| Services | 9 | 7 | 2 |

These gaps represent features that were planned or referenced in the test specification but have not yet been built. The existing 23 endpoints, 6 models, 6 CLI commands, and 7 services are all functional and tested.
