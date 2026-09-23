"""JWT username/password authentication and user management.

Three ways to get an account:
1. Self-register via POST /api/auth/register when ALLOW_SIGNUP=true.
2. Use the env-defined admin user (ADMIN_USERNAME / ADMIN_PASSWORD); credentials
   are verified at request time, so no seed step is needed.
3. Add users to the `users` collection with `python -m scripts.create_user`.

Tokens are signed with HS256 using JWT_SECRET. When JWT_SECRET is unset the JWT
login endpoint is disabled but the legacy X-API-Key auth still works.
"""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.db.documentdb import db

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

_PBKDF2_ROUNDS = 120_000


# --- Password hashing (stdlib PBKDF2-HMAC-SHA256, no native deps) ---
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), _PBKDF2_ROUNDS
    )
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, hexhash = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), _PBKDF2_ROUNDS
        )
        return hmac.compare_digest(dk.hex(), hexhash)
    except Exception:
        return False


# --- JWT ---
def create_access_token(
    subject: str,
    extra: Optional[dict] = None,
    expires_minutes: Optional[int] = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(
            minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
        ),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


# --- Users ---
def users():
    return db["users"]


def get_user(username: str) -> Optional[dict]:
    """Return a user record or None.

    The env-defined admin user is resolved from configuration (no DB write); all
    other users come from the `users` collection.
    """
    if (
        settings.ADMIN_USERNAME
        and settings.ADMIN_PASSWORD
        and username == settings.ADMIN_USERNAME
    ):
        return {
            "username": settings.ADMIN_USERNAME,
            "name": settings.ADMIN_DISPLAY_NAME or settings.ADMIN_USERNAME,
            "role": "admin",
            "password_hash": hash_password(settings.ADMIN_PASSWORD),
            "env_admin": True,
        }
    return users().find_one({"username": username})


def public_user(user: dict) -> dict:
    return {
        "username": user.get("username"),
        "name": user.get("name", user.get("username")),
        "role": user.get("role", "user"),
    }


def create_user(username: str, password: str, name: str = "", role: str = "user") -> dict:
    if get_user(username):
        raise ValueError(f"User {username!r} already exists")
    doc = {
        "username": username,
        "name": name or username,
        "role": role,
        "password_hash": hash_password(password),
        "created_at": datetime.now(timezone.utc),
    }
    users().insert_one(doc)
    return doc


def register_user(username: str, password: str, name: str = "") -> dict:
    """Self-register a new standard user (role "user").

    Raises ValueError on invalid input or duplicate username.
    """
    username = (username or "").strip()
    if not username:
        raise ValueError("Username is required.")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters.")
    if len(name or "") > 80:
        raise ValueError("Name is too long.")
    return create_user(username, password, name=name, role="user")


def signup_enabled() -> bool:
    """True when self-registration is allowed and JWT login is enabled."""
    return login_enabled() and settings.ALLOW_SIGNUP


def authenticate_user(username: str, password: str) -> Optional[dict]:
    if not username or not password:
        return None
    user = get_user(username)
    if not user or not user.get("password_hash"):
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def login_enabled() -> bool:
    """True when the JWT login endpoint can issue tokens."""
    return bool(settings.JWT_SECRET)


# --- FastAPI dependency ---
async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    x_api_key: str | None = Header(default=None),
) -> dict:
    """Guard protected routes.

    Accepts a valid JWT (Authorization: Bearer <token>) or, for backwards
    compatibility, a legacy X-API-Key. When authentication is fully disabled the
    dependency passes an anonymous user through.
    """
    if not settings.auth_enabled:
        return {"username": "anonymous", "role": "guest"}

    if credentials and credentials.credentials:
        try:
            payload = decode_token(credentials.credentials)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token.")
        username = payload.get("sub")
        if username:
            user = get_user(username)
            if user:
                return user
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    if x_api_key and settings.api_keys:
        from app.services.security import verify_api_key

        try:
            verify_api_key(x_api_key)
            return {"username": "api-key", "role": "admin", "api_key": True}
        except HTTPException:
            pass

    raise HTTPException(status_code=401, detail="Invalid or missing credentials.")