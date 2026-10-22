"""Auth Plugin — Einfache PIN-basierte Authentifizierung.

Optional, kann über FINANCE_PLUGINS=auth aktiviert werden.
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import Session, relationship

from app.db.database import Base, get_db
from app.plugins import FinancePlugin
from app.models.account import Account


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ----- Datenmodell -----

class User(Base):
    """Ein Benutzer (lokal, keine E-Mail nötig)."""
    __tablename__ = "plugin_auth_users"

    id = Column(String, primary_key=True)
    username = Column(String(50), nullable=False, unique=True)
    pin_hash = Column(String(64), nullable=False)  # SHA-256
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


class Session(Base):
    """Login-Session mit Token."""
    __tablename__ = "plugin_auth_sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("plugin_auth_users.id"), nullable=False)
    token = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    user = relationship("User")


# ----- Schemas -----

class SetupRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    pin: str = Field(..., min_length=4, max_length=8, pattern=r"^\d{4,8}$")


class LoginRequest(BaseModel):
    username: str
    pin: str


class TokenResponse(BaseModel):
    token: str
    expires_at: datetime


class UserRead(BaseModel):
    id: str
    username: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----- Security helpers -----

def hash_pin(pin: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Return (salt, hash)."""
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + pin).encode()).hexdigest()
    return salt, h


def verify_pin(pin: str, salt: str, stored_hash: str) -> bool:
    _, h = hash_pin(pin, salt)
    return hmac.compare_digest(h, stored_hash)


def create_token() -> str:
    return secrets.token_urlsafe(32)


SESSION_TTL_HOURS = 24 * 30  # 30 days


# ----- Router -----

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/setup", response_model=UserRead, status_code=201)
def setup_first_user(data: SetupRequest, db: Session = Depends(get_db)):
    """Create the first user (only if no user exists)."""
    existing = db.query(User).first()
    if existing:
        raise HTTPException(status_code=400, detail="Benutzer existiert bereits")

    salt, pin_hash = hash_pin(data.pin)
    # Store as "salt:hash" for simplicity
    stored = f"{salt}:{pin_hash}"

    user = User(
        id=secrets.token_urlsafe(16),
        username=data.username,
        pin_hash=stored,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")

    try:
        salt, stored_hash = user.pin_hash.split(":", 1)
    except ValueError:
        raise HTTPException(status_code=500, detail="Ungültiges PIN-Format")

    if not verify_pin(data.pin, salt, stored_hash):
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")

    token = create_token()
    session = Session(
        id=secrets.token_urlsafe(16),
        user_id=user.id,
        token=token,
        expires_at=_utcnow() + timedelta(hours=SESSION_TTL_HOURS),
    )
    db.add(session)
    db.commit()

    # Set HttpOnly cookie
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=False,  # True in production with HTTPS
        samesite="lax",
        max_age=SESSION_TTL_HOURS * 3600,
    )

    return TokenResponse(token=token, expires_at=session.expires_at)


@router.post("/logout")
def logout(response: Response, authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    token = authorization.replace("Bearer ", "") if authorization else None
    if token:
        db.query(Session).filter(Session.token == token).delete()
        db.commit()
    response.delete_cookie("auth_token")
    return {"ok": True}


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """Dependency: validate token and return user."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")

    token = authorization[7:]
    session = db.query(Session).filter(Session.token == token).first()
    if not session or session.expires_at < _utcnow():
        raise HTTPException(status_code=401, detail="Session abgelaufen")

    user = db.query(User).filter(User.id == session.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden")

    return user


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user


# ----- Plugin Class -----

class AuthPlugin(FinancePlugin):
    name = "auth"
    version = "0.1.0"

    def register(self, app):
        engine = app.state.db_engine
        from app.db.database import Base
        Base.metadata.create_all(bind=engine, tables=[User.__table__, Session.__table__])
        app.include_router(router)


PLUGIN = AuthPlugin()