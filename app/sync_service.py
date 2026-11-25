"""Синхронизация кэша задач с трекером и запись её состояния.

Продуктов несколько (см. db.load_products): по каждому продукту со своим
namespace и кодом проекта делается полная выборка задач, кэш продукта
сверяется со своей выборкой 1-в-1.
"""
from __future__ import annotations

import logging
from typing import Callable

from . import db
from .config import Settings
from .db import utcnow
from .tracker_client import TrackerClient, TrackerError, normalize_issue

logger = logging.getLogger(__name__)


class SyncNotConfigured(RuntimeError):
    """В .env нет TRACKER_TOKEN — синхронизация невозможна."""


def perform_sync(
    settings: Settings,
    session_factory: Callable[[], object],
    client_factory: Callable[[dict], TrackerClient] | None = None,
) -> dict:
    """Полная выборка задач трекера по каждому продукту -> upsert в issues_cache.

    client_factory(продукт) -> клиент, точка подмены в тестах; без неё клиенты
    создаются по namespace/коду проекта из настроек продукта.
    Бросает SyncNotConfigured или TrackerError; при неудаче любого продукта
    состояние синхронизации помечается ошибкой, кэш остальных продуктов сохраняется.
    """
    if not settings.tracker_configured:
        raise SyncNotConfigured("Не задан TRACKER_TOKEN в .env")
    with session_factory() as session:
        products = db.load_products(session)
    syncable = [product for product in products if product["namespace"] and product["project_code"]]
    if not syncable:
        raise SyncNotConfigured("Ни у одного продукта не заданы namespace и код проекта")

    fetched = stored = removed = 0
    errors: list[str] = []
    for product in syncable:
        client = client_factory(product) if client_factory else TrackerClient(
            settings.tracker_base_url,
            settings.tracker_token,
            namespace=product["namespace"],
            project=product["project_code"],
            status_ids=settings.tracker_status_ids,
        )
        try:
            raw_issues = client.get_all_issues()
        except TrackerError as error:
            errors.append(f"{product['name']}: {error}")
            continue
        finally:
            if client_factory is None:
                client.close()
        normalized = [item for item in (normalize_issue(raw) for raw in raw_issues) if item is not None]
        synced_at = utcnow()
        with session_factory() as session:
            stored += db.upsert_issues(session, product["id"], normalized, synced_at)
            removed += db.delete_issues_missing(session, product["id"], [issue["key"] for issue in normalized])
            session.commit()
        fetched += len(raw_issues)
        logger.info(
            "Синхронизация «%s»: получено %d, сохранено %d",
            product["name"], len(raw_issues), len(normalized),
        )

    if errors:
        record_failure(session_factory, "; ".join(errors))
        if fetched:
            # Часть продуктов синхронизировалась: кэш частично свежий, но помечен ошибкой
            with session_factory() as session:
                state = db.get_sync_state(session)
                state.last_success_at = utcnow()
                session.commit()
    else:
        synced_at = utcnow()
        with session_factory() as session:
            state = db.get_sync_state(session)
            state.last_success_at = synced_at
            state.last_error = None
            session.commit()
    return {"fetched": fetched, "stored": stored, "removed": removed}


def record_failure(session_factory: Callable[[], object], message: str) -> None:
    with session_factory() as session:
        state = db.get_sync_state(session)
        state.last_error = message[:500]
        state.last_error_at = utcnow()
        session.commit()
