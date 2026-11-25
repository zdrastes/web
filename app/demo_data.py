"""Демо-режим: синтетические задачи вместо трекера.

Генератор детерминированный (сид фиксирован): одинаковый запуск даёт одинаковый
набор данных. Никаких реальных названий, имён и внутренних адресов — только
обезличенные формулировки. Служит для проверки дашборда без доступа к трекеру
и без утечки информации.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

DEMO_SEED = 20260101
DEMO_ISSUE_COUNT = 420

# Метки: те же коды, что входят в стартовые группы db.DEFAULT_GROUP_NAMES,
# плюс свободные метки (в группы не распределены — видны в «Настройках меток»).
DEMO_LABELS: tuple[str, ...] = (
    "demo_access",
    "demo_report",
    "demo_integration",
    "demo_ui",
    "demo_load",
    "demo_data_fix",
    "free_label_1",
    "free_label_2",
)

# Распределение меток по группам: попадает в DEFAULT_GROUP_NAMES (по порядку).
DEMO_GROUP_LABELS: dict[str, tuple[str, ...]] = {
    "Операции": ("demo_access", "demo_integration"),
    "Продукт": ("demo_report", "demo_ui"),
    "Разработка": ("demo_load",),
    "Поддержка": ("demo_data_fix",),
    "Инфраструктура": (),
    "Аналитика": (),
    "Отчётность": (),
}

DEMO_PRODUCT_CODES = {
    "DEMO": ("demo-namespace", "DEMO"),
    "DEMO-STORE": ("demo-namespace", "DEMO-STORE"),
    "DEMO-TRANS": ("demo-namespace", "DEMO-TRANS"),
}

DEMO_STATUSES = ("New", "In progress", "Resolved", "Closed")

_DEMO_SUMMARY_TOPICS = (
    "Не отображается раздел отчёта",
    "Ошибка при выгрузке данных",
    "Медленная загрузка страницы",
    "Некорректный счётчик в виджете",
    "Нет доступа к вкладке",
    "Дублирование записей",
    "Сбой ночной синхронизации",
    "Не приходят уведомления",
    "Неверный формат даты",
    "Пустой график за неделю",
)


def demo_issues(product_name: str, weeks: int = 8) -> list[dict[str, Any]]:
    """Синтетические задачи одного продукта: created_at разбросан по последним неделям."""
    generator = random.Random(f"{DEMO_SEED}-{product_name}")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    namespace, project_code = DEMO_PRODUCT_CODES.get(product_name, ("demo-namespace", product_name))
    issues: list[dict[str, Any]] = []
    for index in range(DEMO_ISSUE_COUNT):
        created_at = now - timedelta(days=generator.randint(0, weeks * 7 - 1),
                                     hours=generator.randint(0, 23), minutes=generator.randint(0, 59))
        labels = generator.sample(DEMO_LABELS, generator.randint(0, 2))
        issues.append({
            "key": f"{project_code}-{1000 + index}",
            "summary": f"{namespace}: {generator.choice(_DEMO_SUMMARY_TOPICS)}",
            "status": generator.choice(DEMO_STATUSES),
            "labels": labels,
            "created_at": created_at,
            "updated_at": created_at,
            "raw": {"demo": True},
        })
    return issues


def seed_demo_data(session_factory: Callable[[], Any]) -> None:
    """Пересев демо-данных: группы с метками + кэш задач по каждому продукту."""
    from . import db  # локальный импорт — избегаем цикла

    with session_factory() as session:
        products = db.load_products(session)
        if not products:
            return
        for product in products:
            group_specs = [
                {
                    "name": name,
                    "category": None,
                    "product_id": product["id"],
                    "labels": [{"label": label, "category": None} for label in labels],
                }
                for name, labels in DEMO_GROUP_LABELS.items()
            ]
            db.replace_groups(session, group_specs)
            issues = demo_issues(product["name"])
            db.upsert_issues(session, product["id"], issues, datetime.now(timezone.utc).replace(tzinfo=None))
        session.commit()
