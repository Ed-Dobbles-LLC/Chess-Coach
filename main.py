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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
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
