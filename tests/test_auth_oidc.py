"""Вход через Keycloak: /auth/login, /auth/callback и выход.

Discovery и обмен кода мокаются на границе app.keycloak — сетевых запросов
в тестах нет. Всё между ними (state-cookie, PKCE-параметры, провижининг
пользователя, серверная сессия) проверяется на настоящем коде.
"""
import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import auth
from app import db as app_db
from app import keycloak
from app.main import create_app


@pytest.fixture()
def fake_discovery(monkeypatch):
    document = {
        "authorization_endpoint": "https://keycloak.test/protocol/openid-connect/auth",
        "token_endpoint": "https://keycloak.test/protocol/openid-connect/token",
        "jwks_uri": "https://keycloak.test/protocol/openid-connect/certs",
        "end_session_endpoint": "https://keycloak.test/protocol/openid-connect/logout",
    }
    monkeypatch.setattr(keycloak, "discover", lambda settings: document)
    return document


def state_from_cookie(client) -> dict:
    """Разбирает подписанный state-cookie тем же кодом, что и /auth/callback."""
    settings = client.app.state.settings
    challenge = keycloak.unpack_state_cookie(settings, client.cookies.get(keycloak.OIDC_STATE_COOKIE))
    assert challenge is not None
    return challenge


def login_via_keycloak(client, monkeypatch, username="admin", display_name=""):
    """Полный вход через /auth/login -> /auth/callback с моком обмена кода."""
    seen = {}

    def fake_exchange(settings, code, code_verifier, expected_nonce):
        seen.update(code=code, code_verifier=code_verifier, expected_nonce=expected_nonce)
        return {"username": username, "display_name": display_name}

    monkeypatch.setattr(keycloak, "exchange_code", fake_exchange)
    redirect = client.get("/auth/login", follow_redirects=False)
    assert redirect.status_code == 303, redirect.text
    challenge = state_from_cookie(client)
    response = client.get(
        "/auth/callback",
        params={"code": "single-use-code", "state": challenge["state"]},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    # обмен кода получил verifier/nonce из cookie, а не заглушки
    assert seen["code"] == "single-use-code"
    assert seen["code_verifier"] == challenge["verifier"]
    assert seen["expected_nonce"] == challenge["nonce"]
    return response


def test_login_requires_configuration(tmp_path, make_settings):
    settings = make_settings(tmp_path, keycloak_issuer="", keycloak_client_id="")
    client = TestClient(create_app(settings))
    response = client.get("/auth/login")
    assert response.status_code == 503
    assert "KEYCLOAK_" in response.json()["detail"]


def test_login_redirects_to_keycloak_with_pkce(client, fake_discovery):
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 303
    location = urlparse(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == fake_discovery["authorization_endpoint"]
    query = parse_qs(location.query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["l2-analytics"]
    assert query["redirect_uri"] == ["https://l2.test/auth/callback"]
    assert query["scope"] == ["openid profile"]
    assert query["code_challenge_method"] == ["S256"]
    challenge = state_from_cookie(client)
    assert query["state"] == [challenge["state"]]
    assert query["nonce"] == [challenge["nonce"]]
    # challenge в URL соответствует verifier'у в cookie (S256)
    digest = hashlib.sha256(challenge["verifier"].encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert query["code_challenge"] == [expected]
    # state-cookie скрыт от JS и живёт не дольше самого входа
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie and "Max-Age=600" in set_cookie


def test_callback_rejects_missing_tampered_and_replayed_state(client, fake_discovery):
    assert client.get("/auth/callback", params={"code": "c", "state": "x"}).status_code == 401

    client.get("/auth/login", follow_redirects=False)
    challenge = state_from_cookie(client)
    tampered = client.get(
        "/auth/callback", params={"code": "c", "state": challenge["state"] + "x"}, follow_redirects=False
    )
    assert tampered.status_code == 401

    # битая подпись cookie: state от другого клиента не принимается
    client.cookies.set(keycloak.OIDC_STATE_COOKIE, "broken.value")
    assert client.get(
        "/auth/callback", params={"code": "c", "state": challenge["state"]}, follow_redirects=False
    ).status_code == 401


def test_callback_completes_login_and_provisions_viewer(tmp_path, make_settings, fake_discovery, monkeypatch):
    client = TestClient(create_app(make_settings(tmp_path)))
    login_via_keycloak(client, monkeypatch, username="ann.petrova", display_name="Анна Петрова")

    me = client.get("/api/me").json()
    assert me["username"] == "ann.petrova"
    assert me["display_name"] == "Анна Петрова"
    assert me["is_admin"] is False
    # новый пользователь — viewer с дашбордом; точные функции выдаёт админ
    assert me["permissions"] == ["dashboard"]
    # временный state-cookie удалён после входа
    assert not client.cookies.get(keycloak.OIDC_STATE_COOKIE)


def test_callback_provisions_admin_from_env(tmp_path, make_settings, fake_discovery, monkeypatch):
    settings = make_settings(tmp_path, admins=frozenset({"ann.petrova"}))
    client = TestClient(create_app(settings))
    login_via_keycloak(client, monkeypatch, username="ann.petrova")

    me = client.get("/api/me").json()
    assert me["is_admin"] is True
    assert set(me["permissions"]) == set(app_db.USER_FUNCTIONS)


def test_existing_user_permissions_survive_relogin(tmp_path, make_settings, fake_discovery, monkeypatch):
    """Повторный вход не сбрасывает выданные админом функции."""
    settings = make_settings(tmp_path)
    engine = app_db.create_engine(settings.database_url)
    app_db.init_db(engine)
    with app_db.session_factory(engine)() as session:
        session.add(app_db.SiteUser(
            username="ann.petrova",
            display_name="",
            role="viewer",
            permissions=["dashboard", "sync"],
        ))
        session.commit()

    client = TestClient(create_app(settings))
    login_via_keycloak(client, monkeypatch, username="ann.petrova")
    me = client.get("/api/me").json()
    assert me["permissions"] == ["dashboard", "sync"]


def test_callback_reports_exchange_failure(client, fake_discovery, monkeypatch):
    def failing_exchange(*args):
        raise keycloak.KeycloakError("Keycloak отклонил код авторизации")

    monkeypatch.setattr(keycloak, "exchange_code", failing_exchange)
    client.get("/auth/login", follow_redirects=False)
    challenge = state_from_cookie(client)
    response = client.get(
        "/auth/callback", params={"code": "c", "state": challenge["state"]}, follow_redirects=False
    )
    assert response.status_code == 502
    assert "отклонил код" in response.text
    # сессия не создана
    assert client.get("/api/me").json()["username"] is None


def test_login_purges_expired_sessions(tmp_path, make_settings, fake_discovery, monkeypatch):
    """Истёкшие сессии удаляются при входе: user_sessions не накапливает просрочку."""
    settings = make_settings(tmp_path)
    client = TestClient(create_app(settings))
    engine = app_db.create_engine(settings.database_url)
    with app_db.session_factory(engine)() as session:
        session.add(app_db.UserSession(
            id="stale-hash",
            username="old",
            display_name="",
            is_admin=False,
            created_at=app_db.utcnow() - timedelta(hours=13),
            expires_at=app_db.utcnow() - timedelta(hours=1),
        ))
        session.commit()

    login_via_keycloak(client, monkeypatch, username="admin")

    with app_db.session_factory(engine)() as session:
        assert session.query(app_db.UserSession).filter(
            app_db.UserSession.expires_at <= app_db.utcnow()
        ).count() == 0
        remaining = session.query(app_db.UserSession).all()
        assert [row.username for row in remaining] == ["admin"]


def direct_login(client, username="admin"):
    """Сессия без Keycloak: SiteUser + серверная сессия напрямую (механизм app.auth).

    Повторяет helper login() из test_api; дублирование сознательное — тесты
    не должны зависеть от импортов друг друга.
    """
    settings = client.app.state.settings
    with client.app.state.session_factory() as session:
        site_user = session.get(app_db.SiteUser, username)
        if site_user is None:
            role = "admin" if username in settings.admins else "viewer"
            site_user = app_db.SiteUser(
                username=username,
                display_name="",
                role=role,
                permissions=list(app_db.ROLE_PRESETS[role]),
            )
            session.add(site_user)
        token = auth.create_session(session, site_user, settings.session_ttl_hours)
    client.cookies.set(auth.SESSION_COOKIE, token)


def test_logout_returns_keycloak_end_session_url(client, fake_discovery):
    direct_login(client)
    body = client.post("/auth/logout").json()
    assert body["ok"] is True
    assert body["logout_url"] == (
        fake_discovery["end_session_endpoint"] + "?client_id=l2-analytics"
    )
    assert client.get("/api/me").json()["username"] is None


def test_logout_without_keycloak_clears_session_locally(client, monkeypatch):
    def unavailable(settings):
        raise keycloak.KeycloakError("Keycloak недоступен")

    monkeypatch.setattr(keycloak, "discover", unavailable)
    direct_login(client)
    body = client.post("/auth/logout").json()
    assert body == {"ok": True, "logout_url": None}
    assert client.get("/api/me").json()["username"] is None
