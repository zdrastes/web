"""FastAPI-приложение «Аналитики L2»: API, статика, сессии, фоновая синхронизация.

Архитектура — план, раздел 2: бэкенд отдаёт /api/data ровно в формате ld-source-data,
фронт вызывает уже существующий window.L2Dashboard.replaceData(...).
"""
from __future__ import annotations

import html
import logging
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from . import aggregator, auth, db, keycloak, sync_service
from .config import Settings, load_settings
from .db import UserSession
from .scheduler import start_background_sync
from .tracker_client import TrackerError

logger = logging.getLogger(__name__)

LOGIN_REDIRECT_STATUS = 303
SESSION_PAGE_REDIRECT = LOGIN_REDIRECT_STATUS


class LabelIn(BaseModel):
    label: str
    category: str | None = None


class GroupIn(BaseModel):
    name: str
    category: str | None = None
    product_id: int | None = None
    labels: list[LabelIn | str] = Field(default_factory=list)


class SettingsIn(BaseModel):
    groups: list[GroupIn] = Field(min_length=1)


class SprintIn(BaseModel):
    name: str
    date_from: date
    date_to: date


class SprintsIn(BaseModel):
    sprints: list[SprintIn] = Field(default_factory=list)


class LabelNotesIn(BaseModel):
    notes: dict[str, str] = Field(default_factory=dict)


class HiddenLabelsIn(BaseModel):
    labels: list[str] = Field(default_factory=list)


class ProductIn(BaseModel):
    name: str
    namespace: str = ""
    project_code: str = ""


class ProductUpdateIn(BaseModel):
    name: str | None = None
    namespace: str | None = None
    project_code: str | None = None


class UserIn(BaseModel):
    username: str = ""
    display_name: str = ""
    role: str = "viewer"
    # None = не заданы явно → берём пресет роли; [] = полностью без функций
    permissions: list[str] | None = None


class UserUpdateIn(BaseModel):
    display_name: str | None = None
    role: str | None = None
    permissions: list[str] | None = None


def _is_stale(state) -> bool:
    """Свежесть кэша: неудачная синхронизация позже последней успешной (план, п. 5.6)."""
    if state.last_error_at is None:
        return False
    return state.last_success_at is None or state.last_error_at > state.last_success_at


def _group_spec(group: GroupIn) -> dict[str, Any]:
    labels = [
        {"label": item, "category": None}
        if isinstance(item, str)
        else {"label": item.label, "category": item.category}
        for item in group.labels
    ]
    return {
        "name": group.name,
        "category": group.category,
        "product_id": group.product_id,
        "labels": [item for item in labels if item["label"].strip()],
    }


def _sprint_spec(sprint: SprintIn) -> dict[str, Any]:
    return {"name": sprint.name, "date_from": sprint.date_from, "date_to": sprint.date_to}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = db.create_engine(settings.database_url)
    # SPL — продукт из настроек (.env); WMS и Trans — проекты ботов из db.DEFAULT_PRODUCTS
    # (коды чтения задач — из команд otchet ботов: WMS/services/otchet.py, trans/services/otchet.py).
    bot_products = [spec for spec in db.DEFAULT_PRODUCTS if spec["name"] != "SPL"]
    db.init_db(engine, default_products=[
        {"name": "SPL", "namespace": settings.tracker_namespace, "project_code": settings.tracker_project},
        *bot_products,
    ])
    db.init_db(engine)
    # Первый старт: админы из .env/Vault переезжают в базу, дальше ими управляет
    # вкладка «Пользователи»; прочие пользователи создаются при первом входе
    # через Keycloak (provision_oidc_user).
    db.seed_admins(engine, settings.admins)
    # Пользователям старых версий добавляются новые функции (period, users)
    db.upgrade_user_permissions(engine)
    session_factory = db.session_factory(engine)

    def run_sync() -> None:
        try:
            sync_service.perform_sync(settings, session_factory)
        except Exception as error:  # фоновая задача не должна ронять процесс; pylint: disable=broad-exception-caught
            logger.warning("Синхронизация трекера не удалась: %s", error)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Истёкшие сессии чистим на старте и при каждом входе (см. /auth/callback).
        with session_factory() as startup_db:
            purged = auth.purge_expired_sessions(startup_db)
            startup_db.commit()
        if purged:
            logger.info("Удалено истёкших сессий: %d", purged)
        scheduler = None
        if settings.tracker_configured:
            # первая синхронизация в фоне — не задерживаем старт сервера
            threading.Thread(target=run_sync, name="tracker-sync-once", daemon=True).start()
            scheduler = start_background_sync(run_sync, settings.sync_interval_minutes)
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    # Фабрика приложения: локальный app сознательно затеняет module-level app (uvicorn app.main:app).
    app = FastAPI(title="Аналитика L2", lifespan=lifespan)  # pylint: disable=redefined-outer-name
    # Настройки и фабрика БД — для тестов и внешних инструментов (TestClient).
    app.state.settings = settings
    app.state.session_factory = session_factory

    def get_db() -> Iterator[DbSession]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def current_user(request: Request, db_session: DbSession = Depends(get_db)) -> UserSession:
        session = auth.get_session(request.cookies, db_session)
        if session is None:
            raise HTTPException(status_code=401, detail="Требуется вход")
        return session

    def require_permission(function: str):
        """Зависимость: функция должна быть выдана пользователю в карточке (вкладка «Пользователи»)."""

        def check(
            user: UserSession = Depends(current_user),
            db_session: DbSession = Depends(get_db),
        ) -> UserSession:
            # Права читаем из карточки на каждый запрос: смена роли действует сразу
            site_user = db_session.get(db.SiteUser, user.username)
            if site_user is None or function not in (site_user.permissions or []):
                raise HTTPException(status_code=403, detail="Недостаточно прав для этого действия")
            return user

        return check

    # HTML и скрипты не кэшируются «молча»: браузер всегда перепроверяет ETag,
    # иначе после обновления кода пользователь получает старый JS без хард-рефреша.
    @app.middleware("http")
    async def revalidate_shell(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path in {"/", "/l2-report.html"} or path.startswith(("/js/", "/css/")):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(settings.static_dir / "index.html")

    @app.get("/l2-report.html", include_in_schema=False)
    def l2_report() -> FileResponse:
        """Чистый шаблон для кнопки «Скачать HTML»: фронт подставит в него свежие данные."""
        return FileResponse(settings.static_dir / "index.html")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/me")
    def me(request: Request, db_session: DbSession = Depends(get_db)) -> dict[str, Any]:
        """Доступен без входа: аноним получает username=null и пустой список функций."""
        session = auth.get_session(request.cookies, db_session)
        if session is None:
            return {"username": None, "display_name": None, "is_admin": False, "permissions": []}
        site_user = db_session.get(db.SiteUser, session.username)
        return {
            "username": session.username,
            "display_name": ((site_user.display_name if site_user else "") or session.username),
            "is_admin": bool(site_user and site_user.role == "admin"),
            "permissions": list(site_user.permissions or []) if site_user else [],
        }

    @app.get("/api/data")
    def get_data(
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("dashboard")),
        weeks: int = Query(default=0, ge=1, le=104),
        date_from: date | None = Query(default=None),
        date_to: date | None = Query(default=None),
    ) -> dict[str, Any]:
        """Агрегат кэша трекера в формате ld-source-data (план, раздел 4).

        Спринты из настроек перекрывают недельное окно: параметр weeks действует,
        только пока спринты не заданы. Пользовательский диапазон date_from/date_to
        перекрывает и спринты, и окно: отчёт строится только по этим датам.
        """
        if (date_from is None) != (date_to is None):
            raise HTTPException(status_code=422, detail="Укажите обе даты периода: date_from и date_to")
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=422, detail="Дата начала позже даты конца")
        depth = weeks or settings.default_weeks
        issues = [
            {
                "created_at": db.as_utc(row.created_at),
                "labels": row.labels or [],
                "product_id": row.product_id,
            }
            for row in db_session.query(db.IssueCache).all()
        ]
        dashboard_data = aggregator.aggregate(
            issues,
            db.load_products(db_session),
            db.load_group_specs(db_session),
            depth,
            sprints=db.load_sprints(db_session),
            custom_range=(date_from, date_to) if date_from else None,
        )
        # Расшифровки меток: сохранённые значения перекрывают встроенные дефолты;
        # пустая строка = «без расшифровки» — дашборд покажет имя метки как есть.
        dashboard_data["label_notes"] = {
            **db.DEFAULT_LABEL_NOTES,
            **db.load_label_notes(db_session),
        }
        return {
            "source": "wb-tracker",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stale": _is_stale(db.get_sync_state(db_session)),
            "data": dashboard_data,
        }

    @app.get("/api/settings")
    def get_settings(
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("settings")),
    ) -> dict[str, Any]:
        """Продукты и группы всех продуктов; вкладка «Настройки групп» редактирует по продукту."""
        return {"products": db.load_products(db_session), "groups": db.load_group_specs(db_session)}

    @app.put("/api/settings")
    def put_settings(
        payload: SettingsIn,
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("settings")),
    ) -> dict[str, Any]:
        """Полная атомарная замена групп всех продуктов; пересчёт дашборда произойдёт на фронте."""
        specs = [_group_spec(group) for group in payload.groups]
        try:
            db.replace_groups(db_session, specs)
            db_session.commit()
        except ValueError as error:
            db_session.rollback()
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception:
            db_session.rollback()
            raise
        return {"products": db.load_products(db_session), "groups": db.load_group_specs(db_session)}

    @app.get("/api/products")
    def get_products(
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("settings")),
    ) -> dict[str, Any]:
        return {"products": db.load_products(db_session)}

    @app.post("/api/products")
    def post_product(
        payload: ProductIn,
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("settings")),
    ) -> dict[str, Any]:
        """Новый продукт: название + namespace/код проекта трекера (для синхронизации задач)."""
        try:
            db.create_product(db_session, payload.model_dump())
            db_session.commit()
        except ValueError as error:
            db_session.rollback()
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"products": db.load_products(db_session)}

    @app.put("/api/products/{product_id}")
    def put_product(
        product_id: int,
        payload: ProductUpdateIn,
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("settings")),
    ) -> dict[str, Any]:
        try:
            db.update_product(db_session, product_id, payload.model_dump(exclude_unset=True))
            db_session.commit()
        except ValueError as error:
            db_session.rollback()
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"products": db.load_products(db_session)}

    @app.delete("/api/products/{product_id}")
    def delete_product(
        product_id: int,
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("settings")),
    ) -> dict[str, Any]:
        """Продукт удаляется вместе с его группами и кэшем задач; единственный — нельзя."""
        try:
            db.delete_product(db_session, product_id)
            db_session.commit()
        except ValueError as error:
            db_session.rollback()
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"products": db.load_products(db_session), "groups": db.load_group_specs(db_session)}

    @app.get("/api/sprints")
    def get_sprints(
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("sprints")),
    ) -> dict[str, Any]:
        """Спринты с диапазонами дат; пусто — обращения считаются по ISO-неделям."""
        return {"sprints": db.load_sprints(db_session)}

    @app.put("/api/sprints")
    def put_sprints(
        payload: SprintsIn,
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("sprints")),
    ) -> dict[str, Any]:
        """Полная атомарная замена спринтов; пересечения диапазонов запрещены."""
        specs = [_sprint_spec(sprint) for sprint in payload.sprints]
        try:
            db.replace_sprints(db_session, specs)
            db_session.commit()
        except ValueError as error:
            db_session.rollback()
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception:
            db_session.rollback()
            raise
        return {"sprints": db.load_sprints(db_session)}

    @app.get("/api/labels")
    def get_label_notes(
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("settings")),
    ) -> dict[str, Any]:
        """Сохранённые расшифровки меток и встроенные дефолты (для предзаполнения полей)."""
        return {"notes": db.load_label_notes(db_session), "defaults": db.DEFAULT_LABEL_NOTES}

    @app.put("/api/labels")
    def put_label_notes(
        payload: LabelNotesIn,
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("settings")),
    ) -> dict[str, Any]:
        """Полная атомарная замена расшифровок; пустая строка отменяет расшифровку (и дефолт)."""
        try:
            db.replace_label_notes(db_session, payload.notes)
            db_session.commit()
        except ValueError as error:
            db_session.rollback()
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception:
            db_session.rollback()
            raise
        return {"notes": db.load_label_notes(db_session)}

    @app.get("/api/users")
    def get_users(
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("users")),
    ) -> dict[str, Any]:
        """Пользователи сайта: логин, имя, роль и разрешённые функции (вкладка «Пользователи»)."""
        return {"users": db.load_users(db_session)}

    @app.post("/api/users")
    def post_user(
        payload: UserIn,
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("users")),
    ) -> dict[str, Any]:
        """Создание пользователя (вход он выполняет своим Keycloak-логином);
        роль задаёт стартовый набор функций."""
        try:
            db.create_user(db_session, payload.model_dump())
            db_session.commit()
        except ValueError as error:
            db_session.rollback()
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception:
            db_session.rollback()
            raise
        return {"users": db.load_users(db_session)}

    @app.put("/api/users/{username}")
    def put_user(
        username: str,
        payload: UserUpdateIn,
        db_session: DbSession = Depends(get_db),
        actor: UserSession = Depends(require_permission("users")),
    ) -> dict[str, Any]:
        """Изменение пользователя (имя, роль, функции).

        Свою роль и функции менять нельзя — иначе можно по ошибке отнять права у самого себя.
        """
        if username == actor.username and (payload.role is not None or payload.permissions is not None):
            raise HTTPException(status_code=422, detail="Нельзя менять собственную роль и функции")
        try:
            db.update_user(db_session, username, payload.model_dump(exclude_unset=True))
            db_session.commit()
        except ValueError as error:
            db_session.rollback()
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception:
            db_session.rollback()
            raise
        return {"users": db.load_users(db_session)}

    def tracker_labels_response(db_session: DbSession, product_id: int) -> dict[str, Any]:
        """Метки продукта: видимые (из кэша задач + распределённые по группам) и удалённые."""
        cached = db_session.query(db.IssueCache.labels).filter(db.IssueCache.product_id == product_id).all()
        known = {str(label) for (labels_json,) in cached for label in (labels_json or [])}
        assigned: dict[str, list[str]] = {}
        for group in db.load_group_specs(db_session):
            if group["product_id"] != product_id:
                continue
            for item in group["labels"]:
                assigned.setdefault(item["label"], []).append(group["name"])
        hidden = set(db.load_hidden_labels(db_session).get(product_id, []))
        return {
            "product_id": product_id,
            # Удалённые метки скрываются, пока они свободны: уже распределённые по группам
            # остаются видимыми — их расшифровки правятся здесь же.
            "labels": [
                {"label": label, "groups": assigned.get(label, [])}
                for label in sorted((known | set(assigned)) - (hidden - set(assigned)))
            ],
            "hidden": sorted(hidden),
        }

    @app.get("/api/tracker/labels")
    def tracker_labels(
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("settings")),
        product: int = Query(default=0),
    ) -> dict[str, Any]:
        """Метки выбранного продукта (из кэша его задач), группы, где они распределены,
        и список удалённых (hidden).

        Без параметра product берётся первый продукт — совместимо со старым фронтендом.
        """
        products = db.load_products(db_session)
        product_id = product or (products[0]["id"] if products else 0)
        return tracker_labels_response(db_session, product_id)

    @app.put("/api/tracker/labels/hidden")
    def put_hidden_labels(
        payload: HiddenLabelsIn,
        product: int = Query(...),
        db_session: DbSession = Depends(get_db),
        _user: UserSession = Depends(require_permission("settings")),
    ) -> dict[str, Any]:
        """Полная замена списка удалённых меток продукта; расшифровки меток не затрагиваются."""
        try:
            db.replace_hidden_labels(db_session, product, payload.labels)
            db_session.commit()
        except ValueError as error:
            db_session.rollback()
            raise HTTPException(status_code=422, detail=str(error)) from error
        return tracker_labels_response(db_session, product)

    @app.post("/api/sync")
    def sync_now(_user: UserSession = Depends(require_permission("sync"))) -> dict[str, Any]:
        """Форс-синхронизация кэша с трекером; при неудаче кэш остаётся прежним."""
        try:
            return sync_service.perform_sync(settings, session_factory)
        except sync_service.SyncNotConfigured as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except TrackerError as error:
            raise HTTPException(status_code=503, detail=f"Трекер недоступен: {error}") from error

    def login_error_page(detail: str, status_code: int) -> HTMLResponse:
        """Простая страница ошибки входа: причина и ссылка на повторную попытку."""
        safe_detail = html.escape(detail)
        return HTMLResponse(
            "<!doctype html><html lang=ru><meta charset=utf-8><title>Вход не выполнен</title>"
            "<body style='font-family:Arial,sans-serif;max-width:460px;margin:80px auto;text-align:center'>"
            "<h1>Вход не выполнен</h1>"
            f"<p style='color:#666'>{safe_detail}</p>"
            "<p><a href='/auth/login'>Попробовать снова</a></p></body></html>",
            status_code=status_code,
        )

    @app.get("/auth/login", include_in_schema=False)
    def login_redirect(request: Request, db_session: DbSession = Depends(get_db)):
        """Вход: живая сессия — на дашборд, иначе редирект на страницу входа Keycloak."""
        if auth.get_session(request.cookies, db_session):
            return RedirectResponse("/", status_code=SESSION_PAGE_REDIRECT)
        if not keycloak.is_configured(settings):
            raise HTTPException(status_code=503, detail="Вход не настроен: заполните KEYCLOAK_* в .env или Vault")
        challenge = keycloak.new_login_challenge()
        try:
            authorize_url = keycloak.authorization_url(settings, challenge)
        except keycloak.KeycloakError as keycloak_error:
            logger.warning("Keycloak недоступен при входе: %s", keycloak_error)
            return login_error_page(str(keycloak_error), 502)
        response = RedirectResponse(authorize_url, status_code=LOGIN_REDIRECT_STATUS)
        # state/nonce/verifier едут в подписанном cookie: callback сверит подпись и state
        response.set_cookie(
            keycloak.OIDC_STATE_COOKIE,
            keycloak.pack_state_cookie(settings, challenge),
            max_age=keycloak.STATE_COOKIE_MAX_AGE_SECONDS,
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookies,
            path="/",
        )
        return response

    @app.get("/auth/callback", include_in_schema=False)
    def login_callback(
        request: Request,
        db_session: DbSession = Depends(get_db),
        code: str = Query(default=""),
        state: str = Query(default=""),
        error: str = Query(default=""),
        error_description: str = Query(default=""),
    ):
        """Ответ Keycloak: код обменивается на токены, создаётся серверная сессия.

        Провижининг пользователя (db.provision_oidc_user) и новая сессия уходят
        одним commit'ом внутри create_session.
        """
        if error:
            return login_error_page(error_description or f"Keycloak вернул ошибку: {error}", 401)
        challenge = keycloak.unpack_state_cookie(settings, request.cookies.get(keycloak.OIDC_STATE_COOKIE))
        if challenge is None or not secrets.compare_digest(challenge["state"], state):
            return login_error_page("Сессия входа устарела или повреждена — попробуйте войти снова.", 401)
        if not code:
            return login_error_page("Keycloak не вернул код авторизации.", 401)
        try:
            claims = keycloak.exchange_code(settings, code, challenge["verifier"], challenge["nonce"])
        except keycloak.KeycloakError as keycloak_error:
            logger.warning("Вход через Keycloak не удался: %s", keycloak_error)
            return login_error_page(str(keycloak_error), 502)
        site_user = db.provision_oidc_user(db_session, claims, settings.admins)
        # истёкшие сессии уйдут тем же commit, что и новая (внутри create_session)
        auth.purge_expired_sessions(db_session)
        token = auth.create_session(db_session, site_user, settings.session_ttl_hours)
        logger.info("Вход через Keycloak: %s", site_user.username)
        response = RedirectResponse("/", status_code=SESSION_PAGE_REDIRECT)
        response.delete_cookie(keycloak.OIDC_STATE_COOKIE, path="/")
        auth.set_session_cookie(response, token, settings)
        return response

    @app.post("/auth/logout", include_in_schema=False)
    def logout(db_session: DbSession = Depends(get_db), user: UserSession = Depends(current_user)):
        """Локальный выход (сессия и cookie) + адрес выхода из Keycloak, если он объявлен."""
        db_session.delete(user)
        db_session.commit()
        response = JSONResponse({"ok": True, "logout_url": keycloak.end_session_url(settings)})
        auth.clear_session_cookie(response)
        return response

    # Отдача статики (css/js) монтируется после всех маршрутов: свои маршруты
    # (/api/*, /, /l2-report.html, /auth/*) всегда приоритетнее, остальное — файлы.
    app.mount("/", StaticFiles(directory=settings.static_dir), name="static")

    return app


app = create_app()
