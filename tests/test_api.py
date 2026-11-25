import pytest
from fastapi.testclient import TestClient

from app import auth
from app import db as app_db
from app.main import create_app


def login(client, username="admin"):
    """Вход в тестах: серверная сессия создаётся напрямую, как после /auth/callback.

    Сам OIDC-флоу (редирект на Keycloak, обмен кода, state-cookie) проверяется
    в test_auth_oidc — здесь важны права и сессии, а не обмен с Keycloak.
    """
    settings = client.app.state.settings
    with client.app.state.session_factory() as session:
        site_user = session.get(app_db.SiteUser, username)
        if site_user is None:
            # как provision_oidc_user: админ — по ADMINS, остальные — viewer-пресет
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


def test_index_serves_dashboard(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'js/dashboard-core.js' in response.text
    assert 'css/dashboard.css' in response.text
    assert 'id="ld-source-data"' in response.text
    # Ядро дашборда отдаётся отдельным файлом и объявляет публичный API
    assert "L2Dashboard" in client.get("/js/dashboard-core.js").text
    assert "topbar" in client.get("/css/dashboard.css").text


def test_me_is_anonymous_without_session(client):
    body = client.get("/api/me").json()
    assert body["username"] is None
    assert body["permissions"] == []


def test_data_requires_auth(client):
    assert client.get("/api/data").status_code == 401


def test_login_creates_session_and_me(client):
    login(client)
    me = client.get("/api/me")
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "admin"
    assert body["is_admin"] is True
    assert set(body["permissions"]) == {"dashboard", "sync", "settings", "period", "sprints", "users"}


def test_login_redirects_authenticated_to_dashboard(client):
    login(client)
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_logout_drops_session(client):
    login(client)
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/api/me").json()["username"] is None


def test_data_has_dashboard_format_with_seeded_groups(client):
    login(client)
    payload = client.get("/api/data").json()
    assert payload["source"] == "wb-tracker"
    assert payload["stale"] is False
    data = payload["data"]
    assert len(data["weeks"]) == 6
    names = [product["name"] for product in data["products"]]
    # кэш пуст: итоги считаются по всем задачам каждого продукта — пока нули
    assert names == ["SPL", "WMS", "Trans"]
    assert all(product["counts"] == [0] * 6 for product in data["products"])
    # дефолтные группы (ПМ|МС, СГТ, …) принадлежат первому продукту
    assert [group["name"] for group in data["products"][0]["groups"]] == [
        "ПМ|МС", "СГТ", "Финансы", "ВЭД", "FMS", "ЭДО", "YMS"
    ]
    assert all(product["groups"] == [] for product in data["products"][1:])


def test_data_respects_weeks_param(client):
    login(client)
    payload = client.get("/api/data", params={"weeks": 2}).json()
    assert len(payload["data"]["weeks"]) == 2


def test_settings_requires_auth_and_settings_permission(client):
    """Чтение настроек тоже требует функцию «settings» (вкладка «Пользователи»)."""
    assert client.get("/api/settings").status_code == 401
    login(client, "viewer")
    assert client.get("/api/settings").status_code == 403
    assert client.put("/api/settings", json={"groups": [{"name": "X", "labels": []}]}).status_code == 403


def test_tracker_labels_requires_admin(client):
    login(client, "viewer")
    assert client.get("/api/tracker/labels").status_code == 403
    assert client.post("/api/sync").status_code == 403


def test_settings_put_replaces_groups_atomically(client):
    login(client)
    payload = {"groups": [{"name": "Первый контур", "labels": ["ls_return_box", "ls_verik"]}]}
    response = client.put("/api/settings", json=payload)
    assert response.status_code == 200
    groups = response.json()["groups"]
    assert [group["name"] for group in groups] == ["Первый контур"]
    assert [item["label"] for item in groups[0]["labels"]] == ["ls_return_box", "ls_verik"]

    data = client.get("/api/data").json()["data"]
    # продукты не меняются от замены групп; группа без product_id попадает в первый продукт
    assert [product["name"] for product in data["products"]] == ["SPL", "WMS", "Trans"]
    assert [group["name"] for group in data["products"][0]["groups"]] == ["Первый контур"]
    assert all(product["groups"] == [] for product in data["products"][1:])


def test_settings_put_rejects_empty_name_and_empty_list(client):
    login(client)
    empty_name = client.put("/api/settings", json={"groups": [{"name": "   ", "labels": []}]})
    assert empty_name.status_code == 422
    empty_list = client.put("/api/settings", json={"groups": []})
    assert empty_list.status_code == 422


def test_settings_survives_app_restart(tmp_path, make_settings):
    settings = make_settings(tmp_path)
    first = TestClient(create_app(settings))
    login(first)
    first.put("/api/settings", json={"groups": [{"name": "Стабильные группы", "labels": []}]})

    after_restart = TestClient(create_app(settings))
    login(after_restart)
    names = [group["name"] for group in after_restart.get("/api/settings").json()["groups"]]
    assert names == ["Стабильные группы"]


def test_tracker_labels_lists_cache_and_assigned(client):
    login(client)
    labels = client.get("/api/tracker/labels").json()["labels"]
    # кэш пуст: известны только метки из настроек (их нет — список пуст)
    assert labels == []


def test_hidden_labels_round_trip(client):
    """Удалённая метка исчезает из списка, возвращается полной заменой списка (PUT hidden)."""
    login(client)
    put = client.put("/api/tracker/labels/hidden", params={"product": 1}, json={"labels": ["ls_junk", "ls_junk"]})
    assert put.status_code == 200, put.text
    assert put.json()["hidden"] == ["ls_junk"]
    labels = client.get("/api/tracker/labels", params={"product": 1}).json()
    assert labels["hidden"] == ["ls_junk"]
    assert labels["labels"] == []

    client.put("/api/tracker/labels/hidden", params={"product": 1}, json={"labels": []})
    assert client.get("/api/tracker/labels", params={"product": 1}).json()["hidden"] == []


def test_hidden_labels_keep_assigned_visible(client):
    """Метки, уже распределённые по группам, видны даже попав в удалённые — их расшифровки правятся здесь же."""
    login(client)
    client.put("/api/settings", json={"groups": [{"name": "ПМ|МС", "product_id": 1, "labels": ["ls_return_box"]}]})
    client.put("/api/tracker/labels/hidden", params={"product": 1}, json={"labels": ["ls_return_box", "ls_junk"]})

    body = client.get("/api/tracker/labels", params={"product": 1}).json()
    assert body["hidden"] == ["ls_junk", "ls_return_box"]
    assert [item["label"] for item in body["labels"]] == ["ls_return_box"]
    assert body["labels"][0]["groups"] == ["ПМ|МС"]


def test_hidden_labels_reject_unknown_product_and_require_settings(client):
    login(client, "viewer")
    assert client.put("/api/tracker/labels/hidden", params={"product": 1}, json={"labels": []}).status_code == 403
    login(client)
    blank = client.put("/api/tracker/labels/hidden", params={"product": 1}, json={"labels": [" "]})
    assert blank.status_code == 422
    unknown = client.put("/api/tracker/labels/hidden", params={"product": 99}, json={"labels": []})
    assert unknown.status_code == 422
    missing = client.put("/api/tracker/labels/hidden", json={"labels": []})
    assert missing.status_code == 422


def test_sync_without_token_returns_503(client):
    login(client)
    response = client.post("/api/sync")
    assert response.status_code == 503
    assert "TRACKER_TOKEN" in response.json()["detail"]


def test_settings_are_not_available_without_login(client):
    assert client.get("/api/settings").status_code == 401


def test_sprints_requires_auth_and_sprints_permission(client):
    """Спринты закрыты функцией «sprints»: viewer без неё не входит."""
    assert client.get("/api/sprints").status_code == 401
    login(client, "viewer")
    assert client.get("/api/sprints").status_code == 403
    assert client.put("/api/sprints", json={"sprints": []}).status_code == 403


def test_period_permission_no_longer_opens_sprints(client):
    """«Период отчёта» даёт только свои даты и выбор готовых спринтов на главной —
    редактирование спринтов теперь требует отдельную функцию «sprints»."""
    login(client)
    created = client.post("/api/users", json={
        "username": "planner",
        "role": "viewer",
        "permissions": ["dashboard", "period"],
    })
    assert created.status_code == 200, created.text
    client.post("/auth/logout")
    login(client, "planner")
    assert client.get("/api/sprints").status_code == 403
    assert client.put("/api/sprints", json={"sprints": []}).status_code == 403
    assert client.get("/api/data", params={"weeks": 2}).status_code == 200
    assert client.get("/api/settings").status_code == 403
    assert client.get("/api/users").status_code == 403


def test_sprints_permission_allows_sprints_without_settings(client):
    """Функция «sprints» открывает вкладку спринтов, но не остальные настройки."""
    login(client)
    created = client.post("/api/users", json={
        "username": "planner",
        "role": "viewer",
        "permissions": ["dashboard", "sprints"],
    })
    assert created.status_code == 200, created.text
    client.post("/auth/logout")
    login(client, "planner")
    assert client.get("/api/sprints").status_code == 200
    put = client.put("/api/sprints", json={"sprints": [
        {"name": "w46", "date_from": "2026-11-09", "date_to": "2026-11-15"},
    ]})
    assert put.status_code == 200, put.text
    assert client.get("/api/data").status_code == 200
    assert client.get("/api/settings").status_code == 403
    assert client.get("/api/users").status_code == 403


def test_settings_permission_does_not_open_sprints(client):
    """Функция «settings» без «period» спринтов больше не открывает."""
    login(client)
    client.post("/api/users", json={"username": "viewer", "role": "viewer"})
    client.put("/api/users/viewer", json={"permissions": ["dashboard", "settings"]})
    client.post("/auth/logout")
    login(client, "viewer")
    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/sprints").status_code == 403


def test_sprints_put_replaces_and_feeds_data(client):
    login(client)
    payload = {"sprints": [
        {"name": "w46", "date_from": "2026-11-09", "date_to": "2026-11-15"},
        {"name": "w47", "date_from": "2026-11-16", "date_to": "2026-11-22"},
    ]}
    response = client.put("/api/sprints", json=payload)
    assert response.status_code == 200, response.text
    sprints = response.json()["sprints"]
    assert [item["name"] for item in sprints] == ["w46", "w47"]
    assert sprints[0]["date_from"] == "2026-11-09"

    data = client.get("/api/data").json()["data"]
    assert data["weeks"] == ["w46", "w47"]


def test_sprints_put_rejects_overlap_duplicates_and_inverted_range(client):
    login(client)
    overlap = client.put("/api/sprints", json={"sprints": [
        {"name": "w46", "date_from": "2026-11-09", "date_to": "2026-11-16"},
        {"name": "w47", "date_from": "2026-11-16", "date_to": "2026-11-22"},
    ]})
    assert overlap.status_code == 422
    duplicated = client.put("/api/sprints", json={"sprints": [
        {"name": "w46", "date_from": "2026-11-09", "date_to": "2026-11-15"},
        {"name": "w46", "date_from": "2026-11-16", "date_to": "2026-11-22"},
    ]})
    assert duplicated.status_code == 422
    inverted = client.put("/api/sprints", json={"sprints": [
        {"name": "w47", "date_from": "2026-11-22", "date_to": "2026-11-16"},
    ]})
    assert inverted.status_code == 422


def test_clearing_sprints_restores_iso_weeks(client):
    login(client)
    client.put("/api/sprints", json={"sprints": [
        {"name": "w46", "date_from": "2026-11-09", "date_to": "2026-11-15"},
    ]})
    assert client.get("/api/data").json()["data"]["weeks"] == ["w46"]
    client.put("/api/sprints", json={"sprints": []})
    assert len(client.get("/api/data").json()["data"]["weeks"]) == 6


def test_data_with_custom_date_range_overrides_sprints(client):
    """Свои даты пользователя перекрывают настройки спринтов (w47 не применяется)."""
    login(client)
    client.put("/api/sprints", json={"sprints": [
        {"name": "w47", "date_from": "2026-11-16", "date_to": "2026-11-22"},
    ]})
    payload = client.get("/api/data", params={"date_from": "2026-11-19", "date_to": "2026-11-20"}).json()
    assert payload["data"]["weeks"] == ["17.11–18.11", "19.11–20.11"]
    assert payload["data"]["default_weeks"] == ["w47"]


def test_custom_date_range_requires_both_dates(client):
    login(client)
    assert client.get("/api/data", params={"date_from": "2026-11-19"}).status_code == 422
    assert client.get("/api/data", params={"date_to": "2026-11-20"}).status_code == 422
    inverted = client.get("/api/data", params={"date_from": "2026-11-20", "date_to": "2026-11-19"})
    assert inverted.status_code == 422


def test_label_notes_requires_auth_and_settings_permission(client):
    assert client.get("/api/labels").status_code == 401
    login(client, "viewer")
    assert client.get("/api/labels").status_code == 403
    assert client.put("/api/labels", json={"notes": {"ls_a": "текст"}}).status_code == 403


def test_label_notes_defaults_and_round_trip(client):
    """Дефолты отдаются сразу; пустая строка перекрывает дефолт и в /api/data."""
    login(client)
    body = client.get("/api/labels").json()
    assert body["defaults"]["ls_trs_12"] == "Проблемы с заявками 12 типа (спецзаявки)"
    assert body["notes"] == {}

    response = client.put("/api/labels", json={"notes": {"ls_trs_12": "", "ls_a": "Своя расшифровка"}})
    assert response.status_code == 200
    assert response.json()["notes"] == {"ls_trs_12": "", "ls_a": "Своя расшифровка"}

    data = client.get("/api/data").json()["data"]
    assert data["label_notes"]["ls_trs_12"] == ""
    assert data["label_notes"]["ls_a"] == "Своя расшифровка"
    assert data["label_notes"]["ls_redirect_trs"] == "Перенаправление к логистам для удаления заявки"


def test_label_notes_put_rejects_empty_label_name(client):
    login(client)
    response = client.put("/api/labels", json={"notes": {"ls_a": "текст", "": "нет имени"}})
    assert response.status_code == 422
    assert client.get("/api/labels").json()["notes"] == {}


def test_users_requires_auth_and_users_permission(client):
    """Список пользователей доступен только тем, у кого есть функция «users"."""
    assert client.get("/api/users").status_code == 401
    login(client, "viewer")
    assert client.get("/api/users").status_code == 403


def test_users_permission_gates_user_management(client):
    """Управление пользователями — отдельно от остальных настроек."""
    login(client)
    client.post("/api/users", json={"username": "viewer", "role": "viewer"})
    client.put("/api/users/viewer", json={"permissions": ["dashboard", "settings", "period"]})
    client.post("/auth/logout")
    login(client, "viewer")
    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", json={"username": "x", "password": "y"}).status_code == 403
    assert client.put("/api/users/viewer", json={"display_name": "X"}).status_code == 403


def test_upgrade_user_permissions_adds_new_functions(tmp_path, make_settings):
    """Учётки старых версий получают новые функции: админ — period/sprints/users,
    редактор — period/sprints."""
    settings = make_settings(tmp_path)
    engine = app_db.create_engine(settings.database_url)
    app_db.init_db(engine)
    with app_db.session_factory(engine)() as session:
        session.add(app_db.SiteUser(
            username="old_admin",
            display_name="",
            role="admin",
            permissions=["dashboard", "sync", "settings", "download"],
        ))
        session.add(app_db.SiteUser(
            username="old_editor",
            display_name="",
            role="editor",
            permissions=["dashboard", "sync", "settings"],
        ))
        session.commit()

    TestClient(create_app(settings))

    with app_db.session_factory(engine)() as session:
        # «download» раньше была функцией — у старых учёток остаётся и не мешает.
        assert set(session.get(app_db.SiteUser, "old_admin").permissions) == set(app_db.USER_FUNCTIONS) | {"download"}
        assert set(session.get(app_db.SiteUser, "old_editor").permissions) == {
            "dashboard", "sync", "settings", "period", "sprints"
        }


def test_admins_seeded_from_env(client):
    """Первый старт: ADMINS (логины Keycloak) переезжают в базу с полным пресетом."""
    login(client)
    users = client.get("/api/users").json()["users"]
    assert [user["username"] for user in users] == ["admin"]
    assert users[0]["role"] == "admin"
    assert set(users[0]["permissions"]) == set(app_db.USER_FUNCTIONS)


def test_users_create_and_login(client):
    """Созданный заранее пользователь входит своим Keycloak-логином и получает свои функции."""
    login(client)
    response = client.post("/api/users", json={
        "username": "logist",
        "display_name": "Логист Ирина",
        "role": "editor",
    })
    assert response.status_code == 200, response.text
    created = next(user for user in response.json()["users"] if user["username"] == "logist")
    assert created["display_name"] == "Логист Ирина"
    assert created["role"] == "editor"
    assert created["permissions"] == ["dashboard", "sync", "settings", "period", "sprints"]

    client.post("/auth/logout")
    login(client, "logist")
    me = client.get("/api/me").json()
    assert me["username"] == "logist"
    assert me["display_name"] == "Логист Ирина"
    assert me["is_admin"] is False
    assert me["permissions"] == ["dashboard", "sync", "settings", "period", "sprints"]


def test_users_create_rejects_empty_duplicate_and_spaces(client):
    login(client)
    empty = client.post("/api/users", json={"username": ""})
    assert empty.status_code == 422
    duplicate = client.post("/api/users", json={"username": "admin"})
    assert duplicate.status_code == 422
    spaces = client.post("/api/users", json={"username": "два слова"})
    assert spaces.status_code == 422
    assert len(client.get("/api/users").json()["users"]) == 1


def test_users_update_display_name_and_permissions(client):
    login(client)
    client.post("/api/users", json={"username": "viewer", "role": "viewer"})
    response = client.put("/api/users/viewer", json={
        "display_name": "Наблюдатель Аня",
        "permissions": ["dashboard", "sync"],
    })
    assert response.status_code == 200, response.text
    viewer = next(user for user in response.json()["users"] if user["username"] == "viewer")
    assert viewer["display_name"] == "Наблюдатель Аня"
    assert viewer["permissions"] == ["dashboard", "sync"]

    # функция «settings» у viewer по-прежнему нет — вкладка настроек закрыта
    client.post("/auth/logout")
    login(client, "viewer")
    assert client.get("/api/settings").status_code == 403


def test_users_update_rejects_self_role_change(client):
    """Свою роль и функции менять нельзя — иначе можно отнять права у самого себя."""
    login(client)
    response = client.put("/api/users/admin", json={"role": "viewer"})
    assert response.status_code == 422
    assert client.put("/api/users/admin", json={"display_name": "Главный"}).status_code == 200


def test_products_requires_auth_and_settings_permission(client):
    """Продукты настраиваются там же, где группы, — нужна функция «settings»."""
    assert client.get("/api/products").status_code == 401
    login(client, "viewer")
    assert client.get("/api/products").status_code == 403
    assert client.post("/api/products", json={"name": "X", "namespace": "n", "project_code": "P"}).status_code == 403


def test_products_crud_round_trip(client):
    """Продукт создаётся, обновляется и удаляется; последний продукт удалить нельзя."""
    login(client)
    seeded = client.get("/api/products").json()["products"]
    assert [p["name"] for p in seeded] == ["SPL", "WMS", "Trans"]

    created = client.post("/api/products", json={"name": "FMS", "namespace": "ns", "project_code": "FMS"})
    assert created.status_code == 200, created.text
    fms = next(p for p in created.json()["products"] if p["name"] == "FMS")
    assert fms["namespace"] == "ns" and fms["project_code"] == "FMS"

    updated = client.put(f"/api/products/{fms['id']}", json={"name": "FMS Логистика"})
    assert updated.status_code == 200
    assert [p["name"] for p in updated.json()["products"]].count("FMS Логистика") == 1

    deleted = client.delete(f"/api/products/{fms['id']}")
    assert deleted.status_code == 200
    assert [p["name"] for p in deleted.json()["products"]] == ["SPL", "WMS", "Trans"]

    # единственный продукт удалить нельзя (после удаления двух останется один)
    ids = [p["id"] for p in client.get("/api/products").json()["products"]]
    for product_id in ids[:2]:
        assert client.delete(f"/api/products/{product_id}").status_code == 200
    last = client.get("/api/products").json()["products"]
    assert len(last) == 1
    assert client.delete(f"/api/products/{last[0]['id']}").status_code == 422


def test_products_create_rejects_empty_name(client):
    login(client)
    assert client.post("/api/products", json={"name": "  ", "namespace": "n", "project_code": "P"}).status_code == 422
    assert client.post("/api/products", json={"name": "X", "namespace": "", "project_code": "P"}).status_code == 422


def test_l2_report_serves_dashboard(client):
    """Статический маршрут /l2-report.html отдаёт тот же дашборд, что и «/».
    Ссылка на него живёт в кнопке «Скачать HTML» дашборда."""
    response = client.get("/l2-report.html")
    assert response.status_code == 200
    assert 'js/dashboard-core.js' in response.text
    assert 'id="ld-source-data"' in response.text
