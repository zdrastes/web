"""Демо-режим: синтетические задачи вместо трекера.

Генератор детерминированный (сид фиксирован): одинаковый запуск даёт одинаковый
набор данных. Никаких реальных названий, имён и внутренних адресов — только
обезличенные формулировки. Служит для проверки дашборда на GitHub без доступа
к трекеру и без утечки информации.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

DEMO_SEED = 20260101
DEMO_ISSUE_COUNT = 420

# Метки: те же коды, что входят в стартовые группы db.DEFAULT_GROUP_NAMES,
# плюс свободные метки (в группы не распределены — видны в «Настройках меток»).
DEMO_LABELS: tuple[str, ...] = (
    "ls_redirect_trs",
    "ls_trs_12",
    "demo_access",
    "demo_report",
    "demo_integration",
    "demo_ui",
    "demo_load",
    "demo_data_fix",
    "free_label_1",
    "free_label_2",
)

DEMO_PRODUCT_CODES = {
    "SPL": ("demo-namespace", "DEMO"),
    "WMS": ("demo-namespace", "DEMO-WMS"),
    "Trans": ("demo-namespace", "DEMO-LTS"),
}

DEMO_STATUSES = ("New", "In progress", "Resolved", "Closed")

_DEMO_SUMMARY_TOPICS = (
    "Не отображается раздел отчёта",
    "Ошибка при выгрузке данных",
    "Медленная загрузка страницы",
    "Некорректный счётчик в виджете",
    "Нет доступа к вкладке",
    "Дублирование записей в таблице",
    "Сбой ночной синхронизации",
    "Не приходят уведомления",
    "Неверный формат даты",
    "Пустой график за неделю",
)


def demo_issues(product_name: str, weeks: int = 8) -> list[dict[str, Any]]:
    """Синтетические задачи одного продукта: created_at разбросан по последним неделям."""
    generator = random.Random(DEMO_SEED + product_name)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    namespace, project_code = DEMO_PRODUCT_CODES[product_name]
    issues: list[dict[str, Any]] = []
    for index in range(DEMO_ISSUE_COUNT):
        created_at = now - timedelta(days=generator.randint(0, weeks * 7 - 1),
                                     hours=generator.randint(0, 23), minutes=generator.randint(0, 59))
        labels = generator.sample(DEMO_LABELS, generator.randint(0, 2))
        issues.append(
            {
                "key": f"{project_code}-{1000 + index}",
                "summary": f"{namespace}: {generator.choice(_DEMO_SUMMARY_TOPICS)}",
                "status": generator.choice(DEMO_STATUSES),
                "labels": labels,
                "created_at": created_at,
                "updated_at": created_at,
                "raw": {"demo": True},
            }
        )
    return issues
