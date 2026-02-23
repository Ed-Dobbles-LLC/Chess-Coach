"""Dobbles.AI Chess Coach — FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import engine, Base
from app.routers import games, analysis, coaching, drills, dashboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _safe_add_column(engine, table_name: str, column_name: str, column_type: str):
    """Add a column if it doesn't already exist. Works for SQLite and Postgres."""
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    existing = [c["name"] for c in insp.get_columns(table_name)]
    if column_name not in existing:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
        logger.info(f"Added column {table_name}.{column_name}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    # Migrate new columns onto existing tables
    try:
        _safe_add_column(engine, "move_analysis", "clock_times", "TEXT")
    except Exception as e:
        logger.warning(f"Column migration skipped: {e}")
    logger.info("Database tables ready.")
    yield


app = FastAPI(
    title="Dobbles.AI Chess Coach",
    description="Personalized chess coaching powered by Stockfish analysis and Claude explanations.",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(games.router)
app.include_router(analysis.router)
app.include_router(coaching.router)
app.include_router(drills.router)
app.include_router(dashboard.router)


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "chess-coach"}
