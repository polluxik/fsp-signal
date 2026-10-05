import hashlib
import hmac
import secrets
from datetime import timedelta, timezone, datetime
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import LoginSession, User, now


hasher = PasswordHasher()


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_password(raw: str, stored: str) -> bool:
    try:
        return hasher.verify(stored, raw)
    except (VerifyMismatchError, VerificationError):
        return False


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def new_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(40)
    db.add(LoginSession(user_id=user.id, token_hash=digest(token), expires_at=now()+timedelta(days=7)))
    db.commit()
    return token


def get_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw = request.cookies.get("fsp_session")
    if not raw:
        raise HTTPException(status_code=401, detail="LOGIN_REQUIRED")
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == digest(raw)))
    if not session or session.revoked_at or aware(session.expires_at) <= now():
        raise HTTPException(status_code=401, detail="LOGIN_REQUIRED")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="LOGIN_REQUIRED")
    return user


def require(user: User, role: str) -> None:
    if user.role != role:
        raise HTTPException(status_code=403, detail="ROLE_FORBIDDEN")
    if not user.email_verified_at:
        raise HTTPException(status_code=403, detail="EMAIL_NOT_VERIFIED")


def csrf_guard(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin:
        allowed = urlsplit(settings.public_base_url)
        supplied = urlsplit(origin)
        if (allowed.scheme, allowed.netloc) != (supplied.scheme, supplied.netloc):
            raise HTTPException(status_code=403, detail="ORIGIN_FORBIDDEN")
    cookie = request.cookies.get("fsp_csrf")
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(status_code=403, detail="CSRF_REQUIRED")


def set_auth_cookies(response, session_token: str) -> None:
    response.set_cookie("fsp_session", session_token, httponly=True, secure=settings.session_secure,
                        samesite="lax", max_age=7*24*3600, path="/")
    response.set_cookie("fsp_csrf", secrets.token_urlsafe(32), httponly=False,
                        secure=settings.session_secure, samesite="lax", max_age=7*24*3600, path="/")
