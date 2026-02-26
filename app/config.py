import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = os.environ.get(
        "DATABASE_URL", "sqlite:///chess_coach.db"
    )
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    chess_com_username: str = os.environ.get("CHESS_COM_USERNAME", "eddobbles2021")
    stockfish_path: str = os.environ.get("STOCKFISH_PATH", "/usr/games/stockfish")
    stockfish_depth: int = int(os.environ.get("STOCKFISH_DEPTH", "18"))
    stockfish_deep_depth: int = int(os.environ.get("STOCKFISH_DEEP_DEPTH", "22"))

    # Stockfish engine settings
    stockfish_threads: int = 2
    stockfish_hash_mb: int = 256

    # Supabase auth (shared Dobbles.AI project)
    supabase_url: str = os.environ.get(
        "SUPABASE_URL", "https://xwguviuinmafenlqwtka.supabase.co"
    )
    supabase_anon_key: str = os.environ.get(
        "SUPABASE_ANON_KEY",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inh3Z3V2aXVpbm1hZmVubHF3dGthIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE4NTU3MDksImV4cCI6MjA4NzQzMTcwOX0.kCJ47zKNbj-jPFVPEV98WRcbyfqMrYRoM01CUPt-fHs",
    )
    supabase_jwt_secret: str = os.environ.get("SUPABASE_JWT_SECRET", "")

    # Classification thresholds (centipawn loss)
    threshold_best: int = 10
    threshold_excellent: int = 25
    threshold_good: int = 50
    threshold_inaccuracy: int = 100
    threshold_mistake: int = 200

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
