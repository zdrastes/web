import httpx
import pytest

from app import tracker_client
from app.tracker_client import (
    KNOWN_LABELS_FIELD_ID,
    LABEL_FIELD_IDS,
    LABEL_FIELD_NAMES,
    TrackerClient,
    TrackerError,
    extract_labels,
    normalize_issue,
    parse_datetime,
)


def make_client(handler, **kwargs):
    return TrackerClient(
        "https://tracker.test",
        "token",
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
        **kwargs,
    )


def test_pagination_walks_all_pages(monkeypatch):
    monkeypatch.setattr(tracker_client, "PAGE_SIZE", 2)
    calls = []

    def handler(request):
        calls.append(str(request.url.params["offset"]))
        offset = int(request.url.params["offset"])
        pages = {
            0: [{"key": "DEMO-1"}, {"key": "DEMO-2"}],
            2: [{"key": "DEMO-3"}],
        }
        return httpx.Response(200, json={"issues": pages[offset]})

    with make_client(handler) as client:
        issues = client.get_all_issues()

    assert [issue["key"] for issue in issues] == ["DEMO-1", "DEMO-2", "DEMO-3"]
    assert calls == ["0", "2"]


def test_retry_after_on_429():
    attempts = {"count": 0}
    pauses = []

    def handler(request):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"issues": [{"key": "DEMO-1"}]})

    sleeps = []
    client = TrackerClient(
        "https://tracker.test",
        "token",
        transport=httpx.MockTransport(handler),
        sleep=pauses.append,
    )
    with client:
        assert client.get_all_issues()[0]["key"] == "DEMO-1"
    assert pauses == [9.0]  # Retry-After 7 + 2


def test_server_error_exhausts_attempts():
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    with make_client(handler) as client:
        with pytest.raises(TrackerError):
            client.get_all_issues()


def test_transport_error_raises_tracker_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with make_client(handler) as client:
        with pytest.raises(TrackerError):
            client.get_all_issues()


def test_request_sends_basic_auth_and_params():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"issues": []})

    with make_client(handler, status_ids=("11", "12")) as client:
        client.get_all_issues()

    import base64

    assert seen["auth"] == "Basic " + base64.b64encode(b"demo_user:token").decode()
    assert seen["params"]["namespace_code"] == "demo-namespace"
    assert seen["params"]["project_code"] == "DEMO"
    assert seen["params"]["status_id"] == "11,12"
    assert seen["params"]["limit"] == str(tracker_client.PAGE_SIZE)


def test_normalize_basic_shape():
    raw = {"key": "DEMO-9", "summary": "Проблема", "created": "2026-11-10T09:00:00Z", "labels": ["demo_label_1"]}
    issue = normalize_issue(raw)
    assert issue["key"] == "DEMO-9"
    assert issue["summary"] == "Проблема"
    assert issue["labels"] == ["demo_label_1"]
    assert issue["created_at"].tzinfo is not None
    assert issue["created_at"].isoformat() == "2026-11-10T09:00:00+00:00"
    assert issue["status"] == ""


def test_normalize_labels_from_fields():
    raw = {
        "id": "DEMO-10",
        "fields": [{"id": KNOWN_LABELS_FIELD_ID, "value": ["demo_spot"]}],
        "state": {"name": "Закрыта"},
    }
    issue = normalize_issue(raw)
    assert issue["labels"] == ["demo_spot"]
    assert issue["status"] == "Закрыта"


def test_normalize_labels_from_dict_list():
    raw = {"key": "DEMO-11", "tags": [{"name": "demo_label_2"}, {"value": ""}, "demo_label_3"]}
    assert normalize_issue(raw)["labels"] == ["demo_label_2", "demo_label_3"]


def test_normalize_without_key_returns_none():
    assert normalize_issue({"summary": "без ключа"}) is None
    assert normalize_issue("не словарь") is None


def test_extract_labels_direct_field_wins():
    raw = {"labels": ["demo_a"], "fields": [{"id": KNOWN_LABELS_FIELD_ID, "value": ["demo_b"]}]}
    assert extract_labels(raw) == ["demo_a"]


# Коды и имена полей меток — настраиваются в конфигурации трекера:
# у демо-продуктов поля меток ищутся по id и по имени.
WMS_LABELS_FIELD_ID = "00000000-0000-0000-0000-000000000002"
WMS_WH_LABELS_FIELD_ID = "00000000-0000-0000-0000-000000000003"


def test_extract_labels_wms_fields_by_id():
    """WMS: метки собираются из обоих полей — «Метки» и «Метки склада»."""
    raw = {
        "id": "WMS-1",
        "fields": [
            {"id": WMS_LABELS_FIELD_ID, "name": "Метки", "value": [{"id": "x1", "label": "Пункт выдачи"}]},
            {"id": WMS_WH_LABELS_FIELD_ID, "name": "Метки склада", "value": [{"id": "x2", "label": "Демо-склад"}]},
            {"id": "11111111-1111-1111-1111-111111111111", "name": "Priority", "value": [{"label": "Средний"}]},
        ],
    }
    assert extract_labels(raw) == ["Пункт выдачи", "Демо-склад"]


def test_extract_labels_trans_field_by_name():
    """Trans: поле меток ищется по имени «Label New» — id заранее не известен."""
    raw = {
        "id": "LTS-7",
        "fields": [
            {"id": "other-uuid", "name": "Label New", "value": [{"id": "t1", "label": "Демо-груз"}]},
            {"id": "one-more", "name": "Priority", "value": [{"label": "Высокий"}]},
        ],
    }
    assert extract_labels(raw) == ["Демо-груз"]


def test_extract_labels_merges_and_dedupes_fields():
    raw = {
        "fields": [
            {"id": WMS_LABELS_FIELD_ID, "value": [{"label": "Пункт выдачи"}]},
            {"id": WMS_WH_LABELS_FIELD_ID, "value": [{"label": "Пункт выдачи"}, {"label": "Демо-сортировка"}]},
        ],
    }
    assert extract_labels(raw) == ["Пункт выдачи", "Демо-сортировка"]


def test_extract_labels_from_dict_fields():
    """Словарная форма полей {field_id: value}, которую может отдавать API трекера."""
    raw = {"key": "WMS-2", "fields": {WMS_LABELS_FIELD_ID: [{"label": "Пункт выдачи"}]}}
    assert extract_labels(raw) == ["Пункт выдачи"]


def test_extract_labedemo_by_name_matches_spl_field_without_id():
    """Подстраховка: поле «Метки» узнаётся и по имени, не только по зашитому id."""
    raw = {"fields": [{"id": "whatever", "name": "Метки", "value": [{"label": "demo_spot"}]}]}
    assert extract_labels(raw) == ["demo_spot"]


def test_label_field_registry_covers_known_projects():
    assert KNOWN_LABELS_FIELD_ID in LABEL_FIELD_IDS
    assert {"Метки", "Label New"} <= LABEL_FIELD_NAMES


def test_parse_datetime_variants():
    assert parse_datetime(1762834800).year == 2025
    assert parse_datetime(1762834800000).year == 2025  # миллисекунды
    assert parse_datetime("2026-03-01T12:00:00+03:00").hour == 9  # приведено к UTC
    assert parse_datetime("мусор") is None
    assert parse_datetime(None) is None
    assert parse_datetime(True) is None
