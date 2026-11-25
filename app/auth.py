"""Серверные сессии после входа через Keycloak.

В cookie — случайный токен (HttpOnly, SameSite=Lax), в БД — только его sha256;
TTL задаётся в .env. Идентификацию выполняет Keycloak (app/keycloak.py), а права
читаются из карточки пользователя на вкладке «Пользователи».
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from fastapi import Response
from sqlalchemy.orm import Session

from .config import Settings
from .db import SiteUser, UserSession, utcnow

SESSION_COOKIE = "l2_session"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, site_user: SiteUser, ttl_hours: int) -> str:
    """Создаёт сессию и возвращает сырой токен для cookie (в БД уходит только хэш)."""
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            id=token_hash(token),
            username=site_user.username,
            display_name=site_user.display_name or site_user.username,
            is_admin=site_user.role == "admin",
            expires_at=utcnow() + timedelta(hours=ttl_hours),
        )
    )
    db.commit()
    return token


def purge_expired_sessions(db: Session) -> int:
    """Удаляет истёкшие сессии: старт приложения и каждый вход.

    Коммит делает вызывающий код.
    """
    return db.query(UserSession).filter(UserSession.expires_at <= utcnow()).delete()


def get_session(cookies: dict[str, str], db: Session) -> UserSession | None:
    token = cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.get(UserSession, token_hash(token))
    if session is None or session.expires_at <= utcnow():
        return None
    return session


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
