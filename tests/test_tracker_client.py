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
            0: [{"key": "SPL-1"}, {"key": "SPL-2"}],
            2: [{"key": "SPL-3"}],
        }
        return httpx.Response(200, json={"issues": pages[offset]})

    with make_client(handler) as client:
        issues = client.get_all_issues()

    assert [issue["key"] for issue in issues] == ["SPL-1", "SPL-2", "SPL-3"]
    assert calls == ["0", "2"]


def test_retry_after_on_429():
    attempts = {"count": 0}
    pauses = []

    def handler(request):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"issues": [{"key": "SPL-1"}]})

    sleeps = []
    client = TrackerClient(
        "https://tracker.test",
        "token",
        transport=httpx.MockTransport(handler),
        sleep=pauses.append,
    )
    with client:
        assert client.get_all_issues()[0]["key"] == "SPL-1"
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

    assert seen["auth"] == "Basic " + base64.b64encode(b"botband_sa:token").decode()
    assert seen["params"]["namespace_code"] == "LOGSUPPORT"
    assert seen["params"]["project_code"] == "SPL"
    assert seen["params"]["status_id"] == "11,12"
    assert seen["params"]["limit"] == str(tracker_client.PAGE_SIZE)


def test_normalize_basic_shape():
    raw = {"key": "SPL-9", "summary": "Проблема", "created": "2026-11-10T09:00:00Z", "labels": ["ls_return_box"]}
    issue = normalize_issue(raw)
    assert issue["key"] == "SPL-9"
    assert issue["summary"] == "Проблема"
    assert issue["labels"] == ["ls_return_box"]
    assert issue["created_at"].tzinfo is not None
    assert issue["created_at"].isoformat() == "2026-11-10T09:00:00+00:00"
    assert issue["status"] == ""


def test_normalize_labels_from_fields():
    raw = {
        "id": "SPL-10",
        "fields": [{"id": KNOWN_LABELS_FIELD_ID, "value": ["ls_SPOT"]}],
        "state": {"name": "Закрыта"},
    }
    issue = normalize_issue(raw)
    assert issue["labels"] == ["ls_SPOT"]
    assert issue["status"] == "Закрыта"


def test_normalize_labels_from_dict_list():
    raw = {"key": "SPL-11", "tags": [{"name": "ls_tender"}, {"value": ""}, "ls_verik"]}
    assert normalize_issue(raw)["labels"] == ["ls_tender", "ls_verik"]


def test_normalize_without_key_returns_none():
    assert normalize_issue({"summary": "без ключа"}) is None
    assert normalize_issue("не словарь") is None


def test_extract_labels_direct_field_wins():
    raw = {"labels": ["ls_a"], "fields": [{"id": KNOWN_LABELS_FIELD_ID, "value": ["ls_b"]}]}
    assert extract_labels(raw) == ["ls_a"]


# Коды и имена полей меток — из команд otchet ботов: у WMS два поля по id
# (WMS/services/otchet.py:409-410), у Trans поле ищется по имени (trans/services/otchet.py:387).
WMS_LABELS_FIELD_ID = "d564db15-d2dd-4037-964f-3094317b2b62"
WMS_WH_LABELS_FIELD_ID = "1ee5b170-9812-48ae-8d46-1976a8bda0c1"


def test_extract_labels_wms_fields_by_id():
    """WMS: метки собираются из обоих полей — «Метки» и «Метки склада»."""
    raw = {
        "id": "WMS-1",
        "fields": [
            {"id": WMS_LABELS_FIELD_ID, "name": "Метки", "value": [{"id": "x1", "label": "ПВЗ"}]},
            {"id": WMS_WH_LABELS_FIELD_ID, "name": "Метки склада", "value": [{"id": "x2", "label": "Склад Коледино"}]},
            {"id": "dde38365-35c4-4f37-bc85-cec8d8237269", "name": "Priority", "value": [{"label": "Средний"}]},
        ],
    }
    assert extract_labels(raw) == ["ПВЗ", "Склад Коледино"]


def test_extract_labels_trans_field_by_name():
    """Trans: поле меток ищется по имени «Label New» — id заранее не известен."""
    raw = {
        "id": "LTS-7",
        "fields": [
            {"id": "other-uuid", "name": "Label New", "value": [{"id": "t1", "label": "Трансгран"}]},
            {"id": "one-more", "name": "Priority", "value": [{"label": "Высокий"}]},
        ],
    }
    assert extract_labels(raw) == ["Трансгран"]


def test_extract_labels_merges_and_dedupes_fields():
    raw = {
        "fields": [
            {"id": WMS_LABELS_FIELD_ID, "value": [{"label": "ПВЗ"}]},
            {"id": WMS_WH_LABELS_FIELD_ID, "value": [{"label": "ПВЗ"}, {"label": "Сорт-центр"}]},
        ],
    }
    assert extract_labels(raw) == ["ПВЗ", "Сорт-центр"]


def test_extract_labels_from_dict_fields():
    """Словарная форма полей {field_id: value}, которую обрабатывают боты."""
    raw = {"key": "WMS-2", "fields": {WMS_LABELS_FIELD_ID: [{"label": "ПВЗ"}]}}
    assert extract_labels(raw) == ["ПВЗ"]


def test_extract_labels_by_name_matches_spl_field_without_id():
    """Подстраховка: поле «Метки» узнаётся и по имени, не только по зашитому id."""
    raw = {"fields": [{"id": "whatever", "name": "Метки", "value": [{"label": "ls_SPOT"}]}]}
    assert extract_labels(raw) == ["ls_SPOT"]


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
