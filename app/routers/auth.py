"""Authentication endpoints for Dobbles.AI Chess Coach."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import User
from app.services.auth import get_current_user
from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "chess_com_username": user.chess_com_username,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.put("/me")
def update_me(
    updates: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the authenticated user's profile (display name, chess.com username)."""
    if "display_name" in updates:
        user.display_name = updates["display_name"]
    if "chess_com_username" in updates:
        user.chess_com_username = updates["chess_com_username"]
    db.commit()
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "chess_com_username": user.chess_com_username,
    }


@router.get("/config")
def get_auth_config():
    """Return public Supabase config for the frontend (no secrets)."""
    return {
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
    }
