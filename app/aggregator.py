"""Чистая агрегация задач трекера в формат данных дашборда (id="ld-source-data").

Без сети и базы: на входе задачи (с продуктом), продукты и настройки групп.
Правила счёта — план, раздел 5, теперь внутри каждого продукта:
  1. период обращения = спринт, в чей диапазон дат (по UTC-дате created_at, как в
     трекере) попадает created_at; если спринты не заданы — ISO-неделя created_at;
  2. «Краткие итоги» продукта = ВСЕ задачи продукта за период (не только метки);
  3. внутри продукта обращение попадает в первую (по порядку) группу среди его меток;
  4. «причина» внутри группы = первая метка этой группы по порядку;
  5. rates: доля группы от суммы групп продукта за период; у причины — доля внутри группы;
  6. метки вне групп продукта не считаются в группах (но входят в итог продукта).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable


def utc_date(value: datetime) -> date:
    """Дата обращения по UTC. Наивное время считаем UTC (так пишет SQLite)."""
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(timezone.utc).date()


def utc_iso_week(value: datetime) -> tuple[int, int]:
    """(год, номер ISO-недели) по UTC."""
    iso = utc_date(value).isocalendar()
    return iso.year, iso.week


def last_week_keys(today: date, depth: int) -> list[tuple[int, int]]:
    """Последние depth ISO-недели по возрастанию, включая текущую (переход через год — сам)."""
    depth = max(1, depth)
    start = today - timedelta(weeks=depth - 1)
    return [
        (day.isocalendar().year, day.isocalendar().week)
        for day in (start + timedelta(weeks=step) for step in range(depth))
    ]


def week_label(key: tuple[int, int]) -> str:
    return f"W{key[1]}"


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def sorted_sprints(sprints: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Спринты с датами (объектами date или ISO-строками) по возрастанию начала."""
    periods = []
    for item in sprints or []:
        date_from = _coerce_date(item.get("date_from"))
        date_to = _coerce_date(item.get("date_to"))
        if not date_from or not date_to:
            continue
        periods.append({"name": str(item.get("name") or ""), "date_from": date_from, "date_to": date_to})
    return sorted(periods, key=lambda sprint: (sprint["date_from"], sprint["date_to"]))


def sprint_index(periods: list[dict[str, Any]], day: date) -> int | None:
    """Индекс спринта, в чей диапазон (включительно) попадает день."""
    for index, sprint in enumerate(periods):
        if sprint["date_from"] <= day <= sprint["date_to"]:
            return index
    return None


def _sorted_labels(group: dict[str, Any]) -> list[dict[str, Any]]:
    labels = [item for item in (group.get("labels") or []) if str(item.get("label") or "").strip()]
    return sorted(labels, key=lambda item: item.get("sort_order", 0))


def aggregate(
    issues: Iterable[dict[str, Any]],
    products: Iterable[dict[str, Any]],
    groups: Iterable[dict[str, Any]],
    weeks_depth: int,
    today: date | None = None,
    sprints: Iterable[dict[str, Any]] | None = None,
    custom_range: tuple[date, date] | None = None,
) -> dict[str, Any]:
    """issues: [{created_at, labels, product_id}]; products: [{id, name, sort_order}];
    groups: [{name, sort_order, product_id, labels: [...]}].

    Возвращает {"weeks": [...], "products": [{id, name, counts, groups: [...]}]},
    где counts — все задачи продукта за период, а groups — прежний формат «контуров»
    (counts/rates/reasons), пересчитанный внутри выбранного продукта.

    custom_range (дата начала, дата конца) перекрывает и спринты, и недельное окно:
    отчёт сворачивается в две колонки — выбранное окно и предшествующее ему окно той же
    длины (для сравнения).
    """
    today = today or datetime.now(timezone.utc).date()
    if custom_range:
        range_start, range_end = custom_range
        window_days = (range_end - range_start).days + 1
        prev_end = range_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=window_days - 1)
        periods = [
            {
                "name": f"{prev_start:%d.%m}–{prev_end:%d.%m}",
                "date_from": prev_start,
                "date_to": prev_end,
            },
            {
                "name": f"{range_start:%d.%m}–{range_end:%d.%m}",
                "date_from": range_start,
                "date_to": range_end,
            },
        ]
    else:
        periods = sorted_sprints(sprints)
    if periods:
        week_keys = [sprint["name"] for sprint in periods]

        def period_of(created_at: datetime) -> int | None:
            return sprint_index(periods, utc_date(created_at))
    else:
        keys = last_week_keys(today, weeks_depth)
        week_index = {key: index for index, key in enumerate(keys)}
        week_keys = [week_label(key) for key in keys]

        def period_of(created_at: datetime) -> int | None:
            return week_index.get(utc_iso_week(created_at))

    ordered_products = sorted(
        (product for product in products if product.get("id") is not None),
        key=lambda product: (product.get("sort_order", 0), str(product.get("id"))),
    )
    project_totals = {product["id"]: [0] * len(week_keys) for product in ordered_products}

    ordered_groups = sorted(groups, key=lambda group: (group.get("sort_order", 0), group.get("id", 0)))
    group_product_ids = [group.get("product_id") for group in ordered_groups]
    group_totals = [[0] * len(week_keys) for _ in ordered_groups]
    reason_totals: list[list[defaultdict[str, int]]] = [
        [defaultdict(int) for _ in range(len(week_keys))] for _ in ordered_groups
    ]

    # метка -> (индекс группы, порядок метки в группе); маршруты принадлежат продукту:
    # одинаковые метки в разных продуктах не перетекают в чужие группы
    label_routes: dict[tuple[Any, str], list[tuple[int, int]]] = defaultdict(list)
    for group_index, group in enumerate(ordered_groups):
        for label_order, item in enumerate(_sorted_labels(group)):
            label = str(item["label"]).strip()
            label_routes[(group.get("product_id"), label)].append((group_index, label_order))

    for issue in issues:
        created_at = issue.get("created_at")
        if not isinstance(created_at, datetime):
            continue
        index = period_of(created_at)
        if index is None:
            continue
        product_id = issue.get("product_id")
        if product_id in project_totals:
            project_totals[product_id][index] += 1
        matched: set[tuple[int, int]] = set()
        for label in issue.get("labels") or []:
            matched.update(label_routes.get((product_id, str(label).strip()), ()))
        if not matched:
            continue  # п.6: метки вне групп продукта не считаются в группах
        group_index, label_order = min(matched)
        group_totals[group_index][index] += 1
        reason_label = str(_sorted_labels(ordered_groups[group_index])[label_order]["label"]).strip()
        reason_totals[group_index][index][reason_label] += 1

    result_products = []
    for product in ordered_products:
        product_id = product["id"]
        indices = [gi for gi, owner in enumerate(group_product_ids) if owner == product_id]
        week_sums = [sum(group_totals[gi][wi] for gi in indices) for wi in range(len(week_keys))]
        product_groups = []
        for group_index in indices:
            group = ordered_groups[group_index]
            counts = group_totals[group_index]
            rates = [counts[i] / week_sums[i] if week_sums[i] else 0.0 for i in range(len(week_keys))]
            reasons = []
            for item in _sorted_labels(group):
                label = str(item["label"]).strip()
                reason_counts = [reason_totals[group_index][i].get(label, 0) for i in range(len(week_keys))]
                reason_rates = [
                    reason_counts[i] / counts[i] if counts[i] else 0.0 for i in range(len(week_keys))
                ]
                reasons.append(
                    {
                        "name": label,
                        "type": item.get("category") or group.get("category"),
                        "counts": reason_counts,
                        "rates": reason_rates,
                    }
                )
            product_groups.append(
                {"name": group["name"], "counts": counts, "rates": rates, "reasons": reasons}
            )
        all_sums = [sum(project_totals[p["id"]][wi] for p in ordered_products) for wi in range(len(week_keys))]
        project_rates = [
            project_totals[product_id][i] / all_sums[i] if all_sums[i] else 0.0 for i in range(len(week_keys))
        ]
        result_products.append(
            {
                "id": product_id,
                "name": product.get("name") or "",
                "counts": project_totals[product_id],
                "rates": project_rates,
                "groups": product_groups,
            }
        )

    result = {"weeks": week_keys, "products": result_products}
    if custom_range:
        default_periods = sorted_sprints(sprints)
        result["default_weeks"] = (
            [sprint["name"] for sprint in default_periods]
            if default_periods
            else [week_label(key) for key in last_week_keys(today, weeks_depth)]
        )
    return result
