"""Проверки конфигурации: пустые значения .env не ломают старт приложения."""
import pytest

from app import db
from app.config import load_settings


def test_empty_db_url_falls_back_to_default_sqlite(monkeypatch):
    monkeypatch.setenv("DB_URL", "")
    settings = load_settings()

    assert settings.database_url.startswith("sqlite:///")
    assert settings.database_url.endswith("l2_analytics.db")


def test_empty_numeric_settings_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("SESSION_TTL_HOURS", "")
    monkeypatch.setenv("SYNC_INTERVAL_MINUTES", "")
    monkeypatch.setenv("DEFAULT_WEEKS", "")
    settings = load_settings()

    assert settings.session_ttl_hours == 12
    assert settings.sync_interval_minutes == 30
    assert settings.default_weeks == 6


def test_bad_db_url_gives_clear_error():
    with pytest.raises(RuntimeError, match="DB_URL"):
        db.create_engine("это-не-url")


def test_valid_sqlite_url_creates_engine(tmp_path):
    engine = db.create_engine("sqlite:///" + (tmp_path / "test.db").as_posix())

    assert engine is not None
    engine.dispose()


def test_sqlite_engine_enables_wal_and_busy_timeout(tmp_path):
    engine = db.create_engine("sqlite:///" + (tmp_path / "wal.db").as_posix())

    with engine.connect() as connection:
        mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
        busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()

    assert str(mode).lower() == "wal"
    assert busy_timeout == 30000
    engine.dispose()


def test_keycloak_configured_requires_all_values(monkeypatch):
    """Вход работает только с полным набором KEYCLOAK_*: частично заданный — не настроен."""
    values = {
        "KEYCLOAK_ISSUER": "https://keycloak.test/realms/l2",
        "KEYCLOAK_CLIENT_ID": "l2-analytics",
        "KEYCLOAK_CLIENT_SECRET": "secret",
        "KEYCLOAK_REDIRECT_URI": "https://l2.test/auth/callback",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert load_settings().keycloak_configured is True

    for missing in values:
        for name, value in values.items():
            monkeypatch.setenv(name, "" if name == missing else value)
        assert load_settings().keycloak_configured is False, missing
