"""Supabase JWT authentication for Dobbles.AI Chess Coach."""

import logging
from datetime import datetime, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.models import User

logger = logging.getLogger(__name__)


def _decode_supabase_token(token: str) -> dict:
    """Decode and validate a Supabase JWT access token.

    Uses HS256 with the Supabase JWT secret if available,
    otherwise decodes without verification (dev mode).
    """
    if settings.supabase_jwt_secret:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )

    # Development fallback: decode without signature verification
    logger.warning("SUPABASE_JWT_SECRET not set — decoding token without verification")
    return jwt.decode(token, options={"verify_signature": False})


def _extract_token(request: Request) -> Optional[str]:
    """Extract Bearer token from Authorization header or cookie."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]

    # Also check cookies for the Supabase session token
    token = request.cookies.get("sb-access-token")
    if token:
        return token

    return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency — validates token and returns the User record.

    Creates the User on first login (auto-provision from Supabase claims).
    """
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = _decode_supabase_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    sub = payload.get("sub")  # Supabase user UUID
    email = payload.get("email", "")

    if not sub:
        raise HTTPException(status_code=401, detail="Invalid token: missing sub")

    # Look up or create user
    user = db.query(User).filter(User.supabase_id == sub).first()
    if not user:
        user = User(
            supabase_id=sub,
            email=email,
            display_name=email.split("@")[0] if email else "Player",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"Auto-provisioned user {user.id} ({email})")

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Like get_current_user but returns None instead of 401 for unauthenticated requests."""
    token = _extract_token(request)
    if not token:
        return None

    try:
        payload = _decode_supabase_token(token)
    except jwt.InvalidTokenError:
        return None

    sub = payload.get("sub")
    if not sub:
        return None

    return db.query(User).filter(User.supabase_id == sub).first()
