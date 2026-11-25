"""Клиент трекера: постраничная выборка задач, retry на 429, нормализация полей.

Образец — get_open_issues() из справки трекера, но:
- без фильтра по status_id по умолчанию (для аналитики нужны и закрытые);
- ошибка страницы поднимается как TrackerError: кэш остаётся нетронутым и помечается stale.
Форма ответа: fields — список {id, name, value} (плюс словарная
форма {field_id: value}, которую обрабатывают боты — оставлена для устойчивости).
"""
from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

PAGE_SIZE = 500
MAX_PAGES = 500
MAX_ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 2.0
PAGE_PAUSE_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 30.0

# Поле «Метки» есть в каждом проекте, но у каждого проекта оно своё.
KNOWN_LABELS_FIELD_ID = "00000000-0000-4000-8000-000000000001"  # «Метки»
LABEL_FIELD_IDS = frozenset({
    KNOWN_LABELS_FIELD_ID,
    "00000000-0000-0000-0000-000000000002",  # «Метки»
    "00000000-0000-0000-0000-000000000003",  # «Метки склада»
})
LABEL_FIELD_NAMES = frozenset({"Метки", "Label New"})

KEY_CANDIDATES = ("key", "id", "issue_id", "issueId")
SUMMARY_CANDIDATES = ("summary", "name", "title", "subject")
STATUS_CANDIDATES = ("status", "state")
CREATED_AT_CANDIDATES = ("created_at", "createdAt", "created", "creation_date", "creationDate", "create_time")
UPDATED_AT_CANDIDATES = ("updated_at", "updatedAt", "updated", "update_time")
LABEL_LIST_KEYS = ("labels", "tags", "label")
LABEL_NAME_KEYS = ("name", "value", "title", "label", "text")


class TrackerError(RuntimeError):
    """Трекер недоступен или ответил ошибкой."""


def _pick(raw: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = raw.get(name)
        if value not in (None, ""):
            return value
    return None


def parse_datetime(value: Any) -> datetime | None:
    """ISO-строка или unix-время (секунды/миллисекунды) -> aware UTC; иначе None."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value / 1000 if abs(value) > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _labels_from_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            labels.append(item.strip())
        elif isinstance(item, dict):
            for key in LABEL_NAME_KEYS:
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    labels.append(candidate.strip())
                    break
    return labels


def _unique(labels: list[str]) -> list[str]:
    """Убирает повторы, сохраняя порядок первого вхождения."""
    seen: set[str] = set()
    unique: list[str] = []
    for label in labels:
        if label not in seen:
            seen.add(label)
            unique.append(label)
    return unique


def _is_label_field(field: dict[str, Any]) -> bool:
    return field.get("id") in LABEL_FIELD_IDS or field.get("name") in LABEL_FIELD_NAMES


def extract_labels(raw: dict[str, Any]) -> list[str]:
    """Метки задачи: прямые поля либо поля «Метки» проекта (по id или имени).

    Метки могут жить в нескольких полях («Метки» и «Метки склада») — собираем
    значения всех подходящих полей.
    """
    for key in LABEL_LIST_KEYS:
        labels = _labels_from_list(raw.get(key))
        if labels:
            return labels
    labels: list[str] = []
    fields = raw.get("fields")
    if isinstance(fields, list):
        for field in fields:
            if isinstance(field, dict) and _is_label_field(field):
                labels.extend(_labels_from_list(field.get("value")))
    elif isinstance(fields, dict):
        for field_id, value in fields.items():
            if field_id in LABEL_FIELD_IDS:
                labels.extend(_labels_from_list(value))
    return _unique(labels)


def normalize_issue(raw: Any) -> dict[str, Any] | None:
    """Ответ API -> {key, summary, status, labels, created_at, updated_at, raw}.

    Без ключа задача не опознана — возвращаем None (и логируем форму ответа,
    чтобы админ смог дополнить списки кандидатов).
    """
    if not isinstance(raw, dict):
        return None
    key = _pick(raw, KEY_CANDIDATES)
    if key is None:
        logger.debug("Задача без распознаваемого ключа: %r", sorted(raw))
        return None
    status = _pick(raw, STATUS_CANDIDATES)
    return {
        "key": str(key),
        "summary": str(_pick(raw, SUMMARY_CANDIDATES) or ""),
        "status": str(status.get("name")) if isinstance(status, dict) else str(status or ""),
        "labels": extract_labels(raw),
        "created_at": parse_datetime(_pick(raw, CREATED_AT_CANDIDATES)),
        "updated_at": parse_datetime(_pick(raw, UPDATED_AT_CANDIDATES)),
        "raw": raw,
    }


class TrackerClient:
    """Постраничная выборка задач проекта (GET /public-api/v1/issues, Basic auth)."""

    def __init__(
        self,
        base_url: str,
        token: str,
        namespace: str = "demo-namespace",
        project: str = "DEMO",
        status_ids: tuple[str, ...] = (),
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        credentials = base64.b64encode(f"demo_user:{token}".encode()).decode()
        self._namespace = namespace
        self._project = project
        self._status_ids = status_ids
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Basic {credentials}", "Accept": "application/json"},
            timeout=timeout_seconds,
            transport=transport,
        )

    def get_all_issues(self) -> list[dict[str, Any]]:
        """Все задачи проекта постранично; на 429 — Retry-After."""
        issues: list[dict[str, Any]] = []
        offset = 0
        for _page in range(MAX_PAGES):
            page = self._get_page(offset)
            issues.extend(page)
            if len(page) < PAGE_SIZE:
                return issues
            offset += PAGE_SIZE
            self._sleep(PAGE_PAUSE_SECONDS)
        raise TrackerError(f"Выборка задач не уместилась в {MAX_PAGES} страниц")

    def _get_page(self, offset: int) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "namespace_code": self._namespace,
            "project_code": self._project,
            "limit": PAGE_SIZE,
            "offset": offset,
            "order": "desk",
        }
        if self._status_ids:
            params["status_id"] = ",".join(self._status_ids)

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.get("/public-api/v1/issues", params=params)
            except httpx.HTTPError as error:
                if attempt == MAX_ATTEMPTS - 1:
                    raise TrackerError(f"Трекер недоступен: {error}") from error
                self._sleep(RETRY_PAUSE_SECONDS * (attempt + 1))
                continue
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "")
                pause = int(retry_after) + 2 if retry_after.isdigit() else 5 * (attempt + 1)
                self._sleep(pause)
                continue
            if response.status_code == 200:
                return self._parse_issues(response)
            if 500 <= response.status_code < 600 and attempt < MAX_ATTEMPTS - 1:
                self._sleep(RETRY_PAUSE_SECONDS)
                continue
            raise TrackerError(f"Трекер ответил {response.status_code}: {response.text[:200]}")

        raise TrackerError(f"Страница offset={offset} не загружена за {MAX_ATTEMPTS} попыток")

    @staticmethod
    def _parse_issues(response: httpx.Response) -> list[dict[str, Any]]:
        try:
            payload = response.json()
        except ValueError as error:
            raise TrackerError(f"Трекер вернул не-JSON ответ: {error}") from error
        issues = payload.get("issues") if isinstance(payload, dict) else None
        if not isinstance(issues, list):
            raise TrackerError("В ответе трекера нет списка issues")
        return [item for item in issues if isinstance(item, dict)]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TrackerClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
