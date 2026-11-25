import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

# Тесты настраивают окружение ДО импорта app.main: у модульного app = create_app()
# не должно появляться своей базы в рабочей папке.
os.environ.setdefault("DB_URL", "sqlite:///" + Path(tempfile.gettempdir()).as_posix() + "/l2_analytics_default_test.db")

STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "static"


@pytest.fixture()
def make_settings(tmp_path):
    """Фабрика настроек: Keycloak настроен, но обмен кода тесты мокают сами
    (см. test_auth_oidc) — сетевых запросов к Keycloak тесты не делают.
    Путь к тестовой базе можно передать первым аргументом (как раньше) или не
    передавать — тогда он берётся из фикстуры tmp_path."""

    def _make(database_dir=None, **overrides):
        target = Path(database_dir) if database_dir is not None else tmp_path
        defaults = dict(
            tracker_base_url="https://tracker.test",
            tracker_token="",
            tracker_namespace="LOGSUPPORT",
            tracker_project="SPL",
            tracker_status_ids=(),
            keycloak_issuer="https://keycloak.test/realms/l2",
            keycloak_client_id="l2-analytics",
            keycloak_client_secret="test-secret",
            keycloak_redirect_uri="https://l2.test/auth/callback",
            admins=frozenset({"admin"}),
            session_ttl_hours=12,
            secure_cookies=False,
            database_url="sqlite:///" + (target / "test.db").as_posix(),
            sync_interval_minutes=30,
            default_weeks=6,
            static_dir=STATIC_DIR,
        )
        defaults.update(overrides)
        return Settings(**defaults)

    return _make


@pytest.fixture()
def client(tmp_path, make_settings):
    return TestClient(create_app(make_settings(tmp_path)))
