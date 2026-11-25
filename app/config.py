"""Конфигурация приложения: переменные окружения из .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    # Пустое значение в .env считается «не задано»: иначе пустая DB_URL= затирала бы дефолт.
    return os.environ.get(name, "").strip() or default


@dataclass(frozen=True)
class Settings:
    """Все настраиваемые параметры сайта. Меняются только через .env."""

    tracker_base_url: str
    tracker_token: str
    tracker_namespace: str
    tracker_project: str
    tracker_status_ids: tuple[str, ...]

    # Вход через Keycloak (SSO): issuer, client_id, client_secret и redirect_uri.
    keycloak_issuer: str
    keycloak_client_id: str
    keycloak_client_secret: str
    keycloak_redirect_uri: str

    # Логины, получающие роль admin при первом входе; остальные — viewer.
    admins: frozenset[str]

    session_ttl_hours: int
    secure_cookies: bool

    # Демо-режим: без трекера и Keycloak, на синтетических данных (DEMO_MODE=1).
    demo_mode: bool

    database_url: str
    sync_interval_minutes: int
    default_weeks: int
    static_dir: Path

    @property
    def tracker_configured(self) -> bool:
        return bool(self.tracker_token)

    @property
    def keycloak_configured(self) -> bool:
        return bool(
            self.keycloak_issuer
            and self.keycloak_client_id
            and self.keycloak_client_secret
            and self.keycloak_redirect_uri
        )


def load_settings() -> Settings:
    admins = frozenset(part.strip() for part in _env("ADMINS").split(",") if part.strip())
    status_ids = tuple(part.strip() for part in _env("TRACKER_STATUS_IDS").split(",") if part.strip())

    return Settings(
        tracker_base_url=_env("TRACKER_BASE_URL", "https://tracker.example.com"),
        tracker_token=_env("TRACKER_TOKEN"),
        tracker_namespace=_env("TRACKER_NAMESPACE", "demo-namespace"),
        tracker_project=_env("TRACKER_PROJECT", "DEMO"),
        tracker_status_ids=status_ids,
        keycloak_issuer=_env("KEYCLOAK_ISSUER"),
        keycloak_client_id=_env("KEYCLOAK_CLIENT_ID"),
        keycloak_client_secret=_env("KEYCLOAK_CLIENT_SECRET"),
        keycloak_redirect_uri=_env("KEYCLOAK_REDIRECT_URI"),
        admins=admins,
        session_ttl_hours=int(_env("SESSION_TTL_HOURS", "12")),
        secure_cookies=_env("SECURE_COOKIES") in {"1", "true", "yes"},
        demo_mode=_env("DEMO_MODE") in {"1", "true", "yes"},
        database_url=_env("DB_URL", "sqlite:///" + (PROJECT_ROOT / "l2_analytics.db").as_posix()),
        sync_interval_minutes=int(_env("SYNC_INTERVAL_MINUTES", "30")),
        default_weeks=int(_env("DEFAULT_WEEKS", "6")),
        static_dir=Path(__file__).resolve().parent / "static",
    )
