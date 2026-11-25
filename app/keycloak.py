"""Вход через Keycloak: OpenID Connect, Authorization Code Flow + PKCE.

Бэкенд — конфиденциальный клиент (client_secret в переменных окружения): код авторизации
обменивается на токены на token endpoint Keycloak, id_token проверяется по
JWKS (подпись RS256), issuer, аудит, срок годности и nonce. Приложение живёт
своими серверными сессиями (UserSession + cookie) — Keycloak нужен только
на входе, каждый запрос к нему не ходит.

Endpoints читаются из discovery `{issuer}/.well-known/openid-configuration`
и кэшируются на час: JWKS запрашивается при каждом обмене кода, поэтому
ротация ключей Keycloak вход не ломает.

Значения настройки — из переменных окружения: KEYCLOAK_ISSUER (адрес realm),
KEYCLOAK_CLIENT_ID, KEYCLOAK_CLIENT_SECRET, KEYCLOAK_REDIRECT_URI.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError

from .config import Settings

OIDC_STATE_COOKIE = "l2_oidc"
STATE_COOKIE_MAX_AGE_SECONDS = 600
CONFIGURATION_CACHE_TTL_SECONDS = 3600
REQUEST_TIMEOUT_SECONDS = 10.0
# Допустимое расхождение часов с сервером Keycloak при проверке exp.
ID_TOKEN_CLOCK_LEEWAY_SECONDS = 30.0


class KeycloakError(RuntimeError):
    """Вход не удался: Keycloak недоступен или вернул невалидный ответ."""


def is_configured(settings: Settings) -> bool:
    """True — все KEYCLOAK_* заданы; иначе вход вернёт понятную 503."""
    return all(
        (
            settings.keycloak_issuer,
            settings.keycloak_client_id,
            settings.keycloak_client_secret,
            settings.keycloak_redirect_uri,
        )
    )


_configuration_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def discover(settings: Settings) -> dict[str, Any]:
    """OpenID-конфигурация realm'а с кэшем на час (в тестах патчится)."""
    cached = _configuration_cache.get(settings.keycloak_issuer)
    now = time.monotonic()
    if cached and now - cached[0] < CONFIGURATION_CACHE_TTL_SECONDS:
        return cached[1]

    url = settings.keycloak_issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.get(url)
            response.raise_for_status()
            document = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise KeycloakError(f"Keycloak недоступен ({url}): {error}") from error
    _configuration_cache[settings.keycloak_issuer] = (now, document)
    return document


def new_login_challenge() -> dict[str, str]:
    """Одноразовые параметры входа: state, nonce и пара PKCE (verifier/challenge)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return {
        "state": secrets.token_urlsafe(16),
        "nonce": secrets.token_urlsafe(16),
        "verifier": verifier,
        "challenge": challenge,
    }


def authorization_url(settings: Settings, challenge: dict[str, str]) -> str:
    """Адрес страницы входа Keycloak для одного захода (state/nonce/PKCE внутри)."""
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.keycloak_client_id,
            "redirect_uri": settings.keycloak_redirect_uri,
            "scope": "openid profile",
            "state": challenge["state"],
            "nonce": challenge["nonce"],
            "code_challenge": challenge["challenge"],
            "code_challenge_method": "S256",
        }
    )
    return discover(settings)["authorization_endpoint"] + "?" + query


def _signature(secret: str, payload: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def pack_state_cookie(settings: Settings, data: dict[str, str]) -> str:
    """Подписанный клиентским секретом cookie-конверт (state, nonce, verifier).

    Подпись нужна, чтобы нельзя было подсунуть чужой state с извне — проверка
    сравнивает подпись, а не доверяет содержимому cookie.
    """
    envelope = {**data, "iat": int(time.time())}
    payload = (
        base64.urlsafe_b64encode(json.dumps(envelope, separators=(",", ":")).encode("utf-8"))
        .rstrip(b"=")
        .decode("ascii")
    )
    return f"{payload}.{_signature(settings.keycloak_client_secret, payload.encode('ascii'))}"


def unpack_state_cookie(settings: Settings, value: str | None) -> dict[str, str] | None:
    """Обратное pack_state_cookie; None — подпись не совпала, устарел или битый."""
    if not value or "." not in value:
        return None
    payload, _, signature = value.rpartition(".")
    if not hmac.compare_digest(_signature(settings.keycloak_client_secret, payload.encode("ascii")), signature):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if int(time.time()) - int(data.get("iat") or 0) > STATE_COOKIE_MAX_AGE_SECONDS:
        return None
    if any(not isinstance(data.get(field), str) or not data[field] for field in ("state", "nonce", "verifier")):
        return None
    return {field: data[field] for field in ("state", "nonce", "verifier")}


def exchange_code(
    settings: Settings, code: str, code_verifier: str, expected_nonce: str
) -> dict[str, str]:
    """Код авторизации -> проверенные claims id_token (username, display_name[, employee_id])."""
    configuration = discover(settings)
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            token_response = client.post(
                configuration["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.keycloak_redirect_uri,
                    "client_id": settings.keycloak_client_id,
                    "client_secret": settings.keycloak_client_secret,
                    "code_verifier": code_verifier,
                },
            )
            if token_response.status_code != 200:
                raise KeycloakError(
                    f"Keycloak отклонил код авторизации (HTTP {token_response.status_code})"
                )
            id_token = token_response.json().get("id_token")
            if not id_token:
                raise KeycloakError("Keycloak не вернул id_token")
            jwks_response = client.get(configuration["jwks_uri"])
            jwks_response.raise_for_status()
            jwks = jwks_response.json()
    except httpx.HTTPError as error:
        raise KeycloakError(f"Keycloak недоступен: {error}") from error
    return _decode_id_token(settings, id_token, jwks, expected_nonce)


def _decode_id_token(
    settings: Settings, id_token: str, jwks: dict[str, Any], expected_nonce: str
) -> dict[str, str]:
    claims = JsonWebToken(["RS256"]).decode(
        id_token,
        JsonWebKey.import_key_set(jwks),
        claims_options={
            "iss": {"value": settings.keycloak_issuer.rstrip("/")},
            "aud": {"value": settings.keycloak_client_id},
        },
    )
    try:
        claims.validate(leeway=ID_TOKEN_CLOCK_LEEWAY_SECONDS)
    except JoseError as error:
        raise KeycloakError(f"id_token не прошёл проверку: {error}") from error
    if not hmac.compare_digest(str(claims.get("nonce") or ""), expected_nonce):
        raise KeycloakError("Keycloak вернул id_token с чужим nonce")
    username = str(claims.get("preferred_username") or "").strip()
    if not username:
        raise KeycloakError("Keycloak не вернул preferred_username в id_token")
    result = {"username": username, "display_name": str(claims.get("name") or "").strip()}
    if claims.get("employee_id") is not None:
        result["employee_id"] = str(claims["employee_id"])
    return result


def end_session_url(settings: Settings) -> str | None:
    """Адрес выхода из Keycloak (RP-initiated logout); None — если endpoint не объявлен.

    Без post_logout_redirect_uri: он требует отдельной настройки клиента в Keycloak,
    а подтверждение выхода на экране Keycloak и так достаточно.
    """
    try:
        endpoint = discover(settings).get("end_session_endpoint")
    except KeycloakError:
        # Keycloak недоступен — локальный выход (удаление сессии) всё равно работает.
        return None
    if not endpoint:
        return None
    return endpoint + "?" + urlencode({"client_id": settings.keycloak_client_id})
