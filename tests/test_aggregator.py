from datetime import date, datetime, timezone

import pytest

from app.aggregator import aggregate, last_week_keys, utc_iso_week, utc_date

UTC = timezone.utc

PRODUCTS = [
    {"id": 1, "name": "DEMO", "sort_order": 0},
    {"id": 2, "name": "WMS", "sort_order": 1},
]

GROUPS = [
    {
        "name": "Операции",
        "sort_order": 0,
        "product_id": 1,
        "labels": [
            {"label": "demo_label_1", "sort_order": 0},
            {"label": "demo_label_2", "sort_order": 1},
        ],
    },
    {
        "name": "Продукт",
        "sort_order": 1,
        "product_id": 1,
        "labels": [{"label": "demo_label_3", "sort_order": 0}],
    },
    {
        "name": "WMS-группа",
        "sort_order": 2,
        "product_id": 2,
        "labels": [{"label": "demo_label_4", "sort_order": 0}],
    },
]

SPRINTS = [
    {"name": "w46", "date_from": date(2026, 11, 9), "date_to": date(2026, 11, 15)},
    {"name": "w47", "date_from": date(2026, 11, 16), "date_to": date(2026, 11, 22)},
]


def issue(day: int, month: int = 11, hour: int = 10, labels=(), product_id: int = 1):
    return {
        "created_at": datetime(2026, month, day, hour, tzinfo=UTC),
        "labels": list(labels),
        "product_id": product_id,
    }


def project(data, name):
    return next(item for item in data["products"] if item["name"] == name)


def group(data, name):
    for item in data["products"]:
        for item_group in item["groups"]:
            if item_group["name"] == name:
                return item_group
    raise AssertionError(f"группа «{name}» не найдена")


def test_utc_iso_week_uses_utc_date():
    assert utc_iso_week(datetime(2026, 1, 1, 0, 30, tzinfo=UTC)) == (2026, 1)
    assert utc_iso_week(datetime(2025, 12, 31, 23, 30, tzinfo=UTC)) == (2026, 1)


def test_utc_date_is_date_only():
    assert utc_date(datetime(2026, 11, 15, 23, 59, tzinfo=UTC)) == date(2026, 11, 15)


def test_last_week_keys_wraps_year():
    # 2026-01-04 — понедельник; неделя 2026-12-28…2027-01-03 — это 53-я неделя 2026 года
    # (у 2026 года 53 ISO-недели, т.к. 1 января — четверг)
    keys = last_week_keys(date(2027, 1, 4), 2)
    assert keys == [(2026, 53), (2027, 1)]


def test_project_counts_count_all_tasks_including_unlabeled():
    """Краткие итоги проекта = ВСЕ задачи проекта за период, даже без меток."""
    data = aggregate(
        [
            issue(12, labels=["demo_label_1"]),
            issue(12, labels=[]),
            issue(13, labels=["незнакомая метка"]),
        ],
        PRODUCTS,
        GROUPS,
        1,
        today=date(2026, 11, 15),
    )
    assert data["weeks"] == ["W46"]
    assert project(data, "DEMO")["counts"] == [3]
    assert group(data, "Операции")["counts"] == [1]
    assert group(data, "Продукт")["counts"] == [0]


def test_issue_with_labels_of_two_groups_counts_once_in_first_group():
    data = aggregate(
        [issue(12, labels=["demo_label_3", "demo_label_1"])], PRODUCTS, GROUPS, 1, today=date(2026, 11, 15)
    )
    assert group(data, "Операции")["counts"] == [1]
    assert group(data, "Продукт")["counts"] == [0]


def test_reason_is_first_label_of_group_by_order():
    # обе метки из Операции: demo_label_1 (порядок 0) и demo_label_2 (порядок 1)
    data = aggregate(
        [issue(12, labels=["demo_label_2", "demo_label_1"])], PRODUCTS, GROUPS, 1, today=date(2026, 11, 15)
    )
    reasons = {reason["name"]: reason["counts"][0] for reason in group(data, "Операции")["reasons"]}
    assert reasons["demo_label_1"] == 1
    assert reasons["demo_label_2"] == 0


def test_labels_of_other_product_do_not_leak():
    """Метки WMS не попадают в группы DEMO и наоборот."""
    data = aggregate(
        [
            issue(12, labels=["demo_label_4"], product_id=1),
            issue(12, labels=["demo_label_1"], product_id=2),
        ],
        PRODUCTS,
        GROUPS,
        1,
        today=date(2026, 11, 15),
    )
    assert group(data, "Операции")["counts"] == [0]
    assert group(data, "WMS-группа")["counts"] == [0]


def test_same_label_in_different_products_counts_separately():
    """Одинаковые метки у разных продуктов считаются в группах своего продукта."""
    groups = [
        {"name": "DEMO-группа", "sort_order": 0, "product_id": 1, "labels": [{"label": "общая", "sort_order": 0}]},
        {"name": "WMS-группа", "sort_order": 1, "product_id": 2, "labels": [{"label": "общая", "sort_order": 0}]},
    ]
    data = aggregate(
        [
            issue(12, labels=["общая"], product_id=1),
            issue(12, labels=["общая"], product_id=2),
        ],
        PRODUCTS,
        groups,
        1,
        today=date(2026, 11, 15),
    )
    assert group(data, "DEMO-группа")["counts"] == [1]
    assert group(data, "WMS-группа")["counts"] == [1]


def test_rates_are_share_of_groups_within_product():
    data = aggregate(
        [
            issue(12, labels=["demo_label_1"]),
            issue(12, labels=["demo_label_3"]),
            issue(12, labels=[]),
        ],
        PRODUCTS,
        GROUPS,
        1,
        today=date(2026, 11, 15),
    )
    # в группах только 2 из 3 задач: доля Операции = 1/2
    assert group(data, "Операции")["rates"] == [pytest.approx(0.5)]
    assert group(data, "Продукт")["rates"] == [pytest.approx(0.5)]


def test_tasks_without_created_at_are_skipped():
    issues = [
        {"created_at": None, "labels": ["demo_label_1"], "product_id": 1},
        issue(12, labels=["demo_label_1"]),
    ]
    data = aggregate(issues, PRODUCTS, GROUPS, 1, today=date(2026, 11, 15))
    assert project(data, "DEMO")["counts"] == [1]


def test_sprints_replace_iso_weeks():
    data = aggregate(
        [issue(9, labels=["demo_label_1"]), issue(16, labels=["demo_label_3"])],
        PRODUCTS,
        GROUPS,
        1,
        sprints=SPRINTS,
    )
    assert data["weeks"] == ["w46", "w47"]
    assert group(data, "Операции")["counts"] == [1, 0]
    assert group(data, "Продукт")["counts"] == [0, 1]


def test_sprints_are_sorted_by_date_regardless_of_input_order():
    data = aggregate(
        [issue(9, labels=["demo_label_1"])], PRODUCTS, GROUPS, 1, sprints=list(reversed(SPRINTS))
    )
    assert data["weeks"] == ["w46", "w47"]
    assert group(data, "Операции")["counts"] == [1, 0]


def test_empty_sprints_fall_back_to_iso_weeks():
    data = aggregate([issue(12, labels=["demo_label_1"])], PRODUCTS, GROUPS, 1, sprints=[], today=date(2026, 11, 15))
    assert data["weeks"] == ["W46"]


def test_issue_outside_sprints_is_skipped():
    data = aggregate([issue(25, labels=["demo_label_1"])], PRODUCTS, GROUPS, 1, sprints=SPRINTS)
    assert project(data, "DEMO")["counts"] == [0, 0]


def test_custom_range_overrides_sprints():
    """Свои даты перекрывают спринты: колонка сравнения — предшествующее окно той же длины;
    границы включительно; default_weeks — дефолтный список."""
    data = aggregate(
        [
            issue(18, labels=["demo_label_1"]),
            issue(19, labels=["demo_label_1"]),
            issue(20, labels=["demo_label_3"]),
            issue(21, labels=["demo_label_1"]),
        ],
        PRODUCTS,
        GROUPS,
        1,
        sprints=SPRINTS,
        custom_range=(date(2026, 11, 19), date(2026, 11, 20)),
    )
    assert data["weeks"] == ["17.11–18.11", "19.11–20.11"]
    assert project(data, "DEMO")["counts"] == [1, 2]
    assert group(data, "Операции")["counts"] == [1, 1]
    assert group(data, "Продукт")["counts"] == [0, 1]
    assert data["default_weeks"] == ["w46", "w47"]


def test_custom_range_without_sprints_keeps_iso_default_weeks():
    """Без спринтов default_weeks — ISO-недели, которые показывались бы по умолчанию."""
    data = aggregate(
        [issue(19, labels=["demo_label_1"])],
        PRODUCTS,
        GROUPS,
        1,
        today=date(2026, 11, 15),
        custom_range=(date(2026, 11, 19), date(2026, 11, 20)),
    )
    assert data["weeks"] == ["17.11–18.11", "19.11–20.11"]
    assert data["default_weeks"] == ["W46"]


def test_project_without_groups_has_no_groups():
    """У проекта без своих групп список групп пуст — чужие группы не подтягиваются."""
    only_product = [{"id": 1, "name": "DEMO", "sort_order": 0}]
    other_groups = [GROUPS[2]]  # WMS-группа принадлежит продукту 2
    data = aggregate([issue(12, labels=["demo_label_1"])], only_product, other_groups, 1, today=date(2026, 11, 15))
    assert project(data, "DEMO")["counts"] == [1]
    assert project(data, "DEMO")["groups"] == []
