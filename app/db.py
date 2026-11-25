"""Модели SQLite и работа с базой."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy import create_engine as sa_create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()

# Стартовые группы = контуры дашборда (раздел «все контуры»).
DEFAULT_GROUP_NAMES = (
    "Операции", "Продукт", "Разработка", "Поддержка",
    "Инфраструктура", "Аналитика", "Отчётность",
)

# Стартовые расшифровки меток: показываются на дашборде вместо «сырого» имени метки.
# Админ может изменить любую расшифровку в «Настройках меток»; пустая строка = без расшифровки.
DEFAULT_LABEL_NOTES = {
    "demo_access": "Доступ к задачам демо-проекта",
    "demo_report": "Замечания к отчётам и данным",
}

# Стартовые продукты: демо-проект для публичной версии. Коды чтения задач
# настраиваются в .env (TRACKER_NAMESPACE / TRACKER_PROJECT).
DEFAULT_PRODUCTS = (
    {"name": "DEMO", "namespace": "demo-namespace", "project_code": "DEMO"},
    {"name": "WMS", "namespace": "demo-namespace", "project_code": "DEMO-WMS"},
    {"name": "Trans", "namespace": "demo-namespace", "project_code": "DEMO-LTS"},
)

# В ранних версиях в стартовые продукты попадали alias'ы создания задач — по ним
# выборка задач не возвращает ничего (см. fix_legacy_product_codes).
LEGACY_PRODUCT_CODES = {
    ("legacy-namespace", "legacy-wms"): ("demo-namespace", "DEMO-WMS"),
    ("legacy-namespace", "legacy-lts"): ("demo-namespace", "DEMO-LTS"),
}

# Функции, выдаваемые пользователю чекбоксами в карточке (вкладка «Пользователи»);
# без «Доступа к отчёту» пользователь не видит дашборд вообще.
# «Скачать HTML» отдельной функции не требует — кнопка видна всем с «dashboard».
USER_FUNCTIONS = ("dashboard", "sync", "settings", "period", "sprints", "users")

# Пресеты ролей: выбор роли проставляет чекбоксы, админ может донастроить вручную.
ROLE_PRESETS = {
    "admin": list(USER_FUNCTIONS),
    "editor": ["dashboard", "sync", "settings", "period", "sprints"],
    "viewer": ["dashboard"],
}

# Функции, добавляемые при старте пользователям, созданным до их появления:
# спринты раньше открывала функция «period», затем «settings», вкладка пользователей
# раньше закрывалась ролью админа — без «users» админ не смог бы управлять доступами.
ROLE_ADDED_FUNCTIONS = {
    "admin": ("period", "sprints", "users"),
    "editor": ("period", "sprints"),
}


def utcnow() -> datetime:
    """Наивное UTC-время: SQLite не хранит смещение, пишем всегда в UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_utc(value: datetime | None) -> datetime | None:
    """Прочитанное из SQLite наивное время считаем UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def to_naive_utc(value: datetime | None) -> datetime | None:
    """Приводит любое время к наивному UTC (формат хранения SQLite)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class Product(Base):
    """Продукт = проект трекера со своими группами, метками и задачами."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    # Параметры выборки задач из трекера; пустые — задачи этого продукта не синхронизируются
    namespace = Column(String(100), nullable=False, default="")
    project_code = Column(String(100), nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)


class LabelGroup(Base):
    """Группа = «контур» на дашборде; принадлежит продукту."""

    __tablename__ = "label_groups"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    # «Операции / Продукт / Разработка» — подпись группы (не редактируется в UI v1)
    category = Column(String(100), nullable=True)

    labels = relationship(
        "GroupLabel",
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="GroupLabel.sort_order",
    )


class GroupLabel(Base):
    """Метки, входящие в группу; каждая метка = «причина» на дашборде."""

    __tablename__ = "group_labels"
    __table_args__ = (UniqueConstraint("group_id", "label", name="uq_group_label"),)

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("label_groups.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(200), nullable=False, index=True)
    sort_order = Column(Integer, nullable=False, default=0)
    # Переопределяет тип «причины» на дашборде; если пусто — берётся category группы
    category = Column(String(100), nullable=True)

    group = relationship("LabelGroup", back_populates="labels")


class Sprint(Base):
    """Спринт = именованный диапазон дат; обращения считаются по created_at."""

    __tablename__ = "sprints"

    id = Column(Integer, primary_key=True)
    name = Column(String(40), nullable=False, unique=True)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)


class LabelNote(Base):
    """Расшифровка метки; пустая строка = без расшифровки (перекрывает дефолт)."""

    __tablename__ = "label_notes"

    label = Column(String(200), primary_key=True)
    note = Column(String(500), nullable=False, default="")


class HiddenLabel(Base):
    """Метка, удалённая из списка меток продукта (вкладка «Настройки меток»)."""

    __tablename__ = "hidden_labels"

    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True)
    label = Column(String(200), primary_key=True)


class IssueCache(Base):
    """Кэш задач трекера, обновляется синхронизацией; каждая задача принадлежит продукту."""

    __tablename__ = "issues_cache"

    # Составной ключ: трекер нумерует задачи внутри проекта (DEMO-100, …)
    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True)
    key = Column(String(100), primary_key=True)
    summary = Column(String(500), nullable=False, default="")
    status = Column(String(100), nullable=False, default="")
    labels = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, nullable=False)
    raw = Column(JSON, nullable=False, default=dict)


class UserSession(Base):
    """Сессия пользователя; в БД — только sha256-хэш токена из cookie."""

    __tablename__ = "user_sessions"

    id = Column(String(64), primary_key=True)
    username = Column(String(100), nullable=False)
    display_name = Column(String(200), nullable=False, default="")
    is_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    expires_at = Column(DateTime, nullable=False)


class SyncState(Base):
    """Состояние последней синхронизации (одна строка, id = 1)."""

    __tablename__ = "sync_state"

    id = Column(Integer, primary_key=True)
    last_success_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    last_error_at = Column(DateTime, nullable=True)


class SiteUser(Base):
    """Пользователь сайта: роль и разрешённые функции (вкладка «Пользователи»)."""

    __tablename__ = "site_users"

    username = Column(String(100), primary_key=True)
    # Историческая колонка парольного входа; после перехода на SSO не
    # используется, оставлена, чтобы старые базы (NOT NULL без дефолта)
    # принимали вставку новой строки без миграции.
    password_hash = Column(String(200), nullable=False, default="")
    display_name = Column(String(200), nullable=False, default="")
    role = Column(String(40), nullable=False, default="viewer")
    # Список функций из USER_FUNCTIONS; пусто — ни одной (дашборд тоже закрыт)
    permissions = Column(JSON, nullable=False, default=list)


def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """WAL: читатели не ждут писателя (синхронизация кэша не мешает сайту),
    busy_timeout даёт писателям дождаться друг друга вместо «database is locked»."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def create_engine(database_url: str) -> Engine:
    """Создаёт движок; при неверной DB_URL — понятная ошибка вместо трейсбека SQLAlchemy."""
    try:
        url = make_url(database_url)
    except ArgumentError as error:
        raise RuntimeError(
            f"Не удалось разобрать DB_URL: {database_url!r}. "
            "Пример значения в .env: DB_URL=sqlite:///l2_analytics.db "
            "(пустая строка — берётся файл рядом с проектом)."
        ) from error
    if url.drivername.startswith("sqlite"):
        engine = sa_create_engine(
            url, connect_args={"check_same_thread": False, "timeout": 30.0}
        )
        event.listens_for(engine, "connect")(_set_sqlite_pragmas)
        return engine
    return sa_create_engine(url)


def session_factory(engine: Engine):
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def init_db(engine: Engine, default_products: list[dict[str, str]] | None = None) -> None:
    """Создаёт таблицы, переносит базы до продуктов и досеивает стартовые настройки."""
    Base.metadata.create_all(engine)
    seed_default_products(engine, default_products)
    migrate_legacy(engine)
    fix_legacy_product_codes(engine)
    seed_default_groups(engine)


def fix_legacy_product_codes(engine: Engine) -> None:
    """Базы, созданные с alias'ами создания задач в продуктах.

    Задачи читаются по кодам проектов, поэтому по alias'ам
    синхронизация всегда получала пустой список. Меняем только строки с точной прежней
    связкой — правки администратора не трогаем.
    """
    with session_factory(engine)() as session:
        for product in session.query(Product).all():
            codes = LEGACY_PRODUCT_CODES.get((product.namespace, product.project_code))
            if codes:
                product.namespace, product.project_code = codes
        session.commit()


def seed_default_products(engine: Engine, specs: list[dict[str, str]] | None = None) -> None:
    """Первый старт: продукт из настроек (.env) + демо-продукты из DEFAULT_PRODUCTS."""
    with session_factory(engine)() as session:
        if session.query(Product).first() is not None:
            return
        for order, spec in enumerate(specs if specs is not None else DEFAULT_PRODUCTS):
            session.add(
                Product(
                    name=str(spec["name"]),
                    namespace=str(spec.get("namespace") or ""),
                    project_code=str(spec.get("project_code") or ""),
                    sort_order=order,
                )
            )
        ensure_sync_state(session)
        session.commit()


def migrate_legacy(engine: Engine) -> None:
    """Базы, созданные до продуктов: добавляем product_id, строки уходят первому продукту."""
    if engine.dialect.name != "sqlite":
        return
    with session_factory(engine)() as session:
        first = session.query(Product).order_by(Product.sort_order, Product.id).first()
    if first is None:
        return
    with engine.begin() as connection:
        group_columns = _table_columns(connection, "label_groups")
        if group_columns and "product_id" not in group_columns:
            connection.exec_driver_sql(
                f"ALTER TABLE label_groups ADD COLUMN product_id INTEGER NOT NULL DEFAULT {int(first.id)}"
            )
        cache_columns = _table_columns(connection, "issues_cache")
        if cache_columns and "product_id" not in cache_columns:
            _rebuild_issues_cache(connection, int(first.id))


def _table_columns(connection, table: str) -> set[str]:
    """Имена колонок таблицы; пустое множество — таблицы нет."""
    return {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}


def _rebuild_issues_cache(connection, product_id: int) -> None:
    """Старый кэш (PK по key) -> составной ключ (product_id, key).

    Перенос в новую таблицу и переименование — внутри одной транзакции SQLite,
    поэтому сбой посередине оставляет старую таблицу нетронутой.
    """
    connection.exec_driver_sql(
        """
        CREATE TABLE issues_cache_new (
            product_id INTEGER NOT NULL,
            key VARCHAR(100) NOT NULL,
            summary VARCHAR(500) NOT NULL DEFAULT '',
            status VARCHAR(100) NOT NULL DEFAULT '',
            labels JSON NOT NULL DEFAULT '[]',
            created_at DATETIME,
            updated_at DATETIME,
            synced_at DATETIME NOT NULL,
            raw JSON NOT NULL DEFAULT '{}',
            PRIMARY KEY (product_id, key)
        )
        """
    )
    connection.exec_driver_sql(
        f"INSERT INTO issues_cache_new (product_id, key, summary, status, labels, created_at, "
        f"updated_at, synced_at, raw) SELECT {product_id}, key, summary, status, labels, "
        f"created_at, updated_at, synced_at, raw FROM issues_cache"
    )
    connection.exec_driver_sql("DROP TABLE issues_cache")
    connection.exec_driver_sql("ALTER TABLE issues_cache_new RENAME TO issues_cache")


def seed_default_groups(engine: Engine) -> None:
    """Стартовые группы — контуры текущего дашборда; метки назначает админ в «Настройках»."""
    with session_factory(engine)() as session:
        if session.query(LabelGroup).first() is not None:
            return
        first = session.query(Product).order_by(Product.sort_order, Product.id).first()
        if first is None:
            return
        ensure_sync_state(session)
        for order, name in enumerate(DEFAULT_GROUP_NAMES):
            session.add(LabelGroup(name=name, sort_order=order, product_id=first.id))
        session.commit()


def seed_admins(engine: Engine, admins: frozenset[str]) -> None:
    """Первый старт: логины из ADMINS переезжают в базу админами.

    После первого старта входящими пользователями управляет вкладка «Пользователи»:
    новый пользователь создаётся автоматически (provision_oidc_user).
    """
    with session_factory(engine)() as session:
        if session.query(SiteUser).first() is not None:
            return
        for username in sorted(admins):
            session.add(
                SiteUser(
                    username=username,
                    display_name="",
                    role="admin",
                    permissions=list(ROLE_PRESETS["admin"]),
                )
            )
        session.commit()


def provision_oidc_user(session, claims: dict[str, Any], admins: frozenset[str]) -> SiteUser:
    """Пользователь для входа через SSO; при первом входе создаётся сам.

    Логин из ADMINS получает полный админ-пресет, остальные — viewer («dashboard»):
    доступ к клиенту SSO и так ограничен заявкой, а точные функции выдаёт
    админ на вкладке «Пользователи». commit делает вызывающий код.
    """
    username = str(claims.get("username") or "").strip()
    user = session.get(SiteUser, username)
    if user is None:
        role = "admin" if username in admins else "viewer"
        user = SiteUser(
            username=username,
            display_name=str(claims.get("display_name") or "").strip(),
            role=role,
            permissions=list(ROLE_PRESETS[role]),
        )
        session.add(user)
    elif not user.display_name and claims.get("display_name"):
        user.display_name = str(claims["display_name"]).strip()
    return user


def upgrade_user_permissions(engine: Engine) -> None:
    """Добавляет функции из ROLE_ADDED_FUNCTIONS тем, у кого их ещё нет.

    Только добавление: намеренно отнятые старые функции (например «download»
    у админа) не возвращаются.
    """
    with session_factory(engine)() as session:
        changed = False
        for user in session.query(SiteUser).all():
            grants = ROLE_ADDED_FUNCTIONS.get(user.role) or ()
            permissions = list(user.permissions or [])
            missing = [func for func in grants if func not in permissions]
            if missing:
                user.permissions = permissions + missing
                changed = True
        if changed:
            session.commit()


def ensure_sync_state(session) -> SyncState:
    state = session.get(SyncState, 1)
    if state is None:
        state = SyncState(id=1)
        session.add(state)
    return state


def get_sync_state(session) -> SyncState:
    return ensure_sync_state(session)


def load_products(session) -> list[dict[str, Any]]:
    """Продукты в порядке sort_order — вход агрегатора и ответ /api/products."""
    products = session.query(Product).order_by(Product.sort_order, Product.id).all()
    return [
        {
            "id": product.id,
            "name": product.name,
            "namespace": product.namespace,
            "project_code": product.project_code,
            "sort_order": product.sort_order,
        }
        for product in products
    ]


def create_product(session, spec: dict[str, Any]) -> None:
    """Новый продукт (POST /api/products); название, namespace и код проекта трекера обязательны."""
    name = str(spec.get("name") or "").strip()
    namespace = str(spec.get("namespace") or "").strip()
    project_code = str(spec.get("project_code") or "").strip()
    if not name:
        raise ValueError("У продукта должно быть название")
    if not namespace:
        raise ValueError("У продукта должен быть namespace трекера")
    if not project_code:
        raise ValueError("У продукта должен быть код проекта трекера")
    if session.query(Product).filter(Product.name == name).first() is not None:
        raise ValueError(f"Продукт «{name}» уже есть")
    session.add(
        Product(
            name=name,
            namespace=namespace,
            project_code=project_code,
            sort_order=session.query(Product).count(),
        )
    )


def update_product(session, product_id: int, changes: dict[str, Any]) -> None:
    """Изменение продукта (PUT /api/products/{id}); name/namespace/код проекта опциональны,
    но переданные значения не могут быть пустыми — иначе продукт перестанет синхронизироваться."""
    product = session.get(Product, product_id)
    if product is None:
        raise ValueError("Продукт не найден")
    if changes.get("name") is not None:
        name = str(changes["name"]).strip()
        if not name:
            raise ValueError("У продукта должно быть название")
        twin = session.query(Product).filter(Product.name == name).first()
        if twin is not None and twin.id != product.id:
            raise ValueError(f"Продукт «{name}» уже есть")
        product.name = name
    field_titles = {"namespace": "namespace трекера", "project_code": "код проекта трекера"}
    for field in ("namespace", "project_code"):
        if changes.get(field) is not None:
            value = str(changes[field]).strip()
            if not value:
                raise ValueError(f"У продукта должен быть {field_titles[field]}")
            setattr(product, field, value)


def delete_product(session, product_id: int) -> None:
    """Удаление продукта вместе с его группами и кэшем задач (DELETE /api/products/{id})."""
    product = session.get(Product, product_id)
    if product is None:
        raise ValueError("Продукт не найден")
    if session.query(Product).count() <= 1:
        raise ValueError("Нельзя удалить единственный продукт")
    group_ids = [row.id for row in session.query(LabelGroup.id).filter(LabelGroup.product_id == product_id)]
    if group_ids:
        session.query(GroupLabel).filter(GroupLabel.group_id.in_(group_ids)).delete(synchronize_session=False)
        session.query(LabelGroup).filter(LabelGroup.id.in_(group_ids)).delete(synchronize_session=False)
    session.query(IssueCache).filter(IssueCache.product_id == product_id).delete(synchronize_session=False)
    session.query(HiddenLabel).filter(HiddenLabel.product_id == product_id).delete(synchronize_session=False)
    session.delete(product)


def load_group_specs(session) -> list[dict[str, Any]]:
    """Группы с метками в порядке sort_order — вход агрегатора и ответ /api/settings."""
    groups = session.query(LabelGroup).order_by(LabelGroup.sort_order, LabelGroup.id).all()
    return [
        {
            "id": group.id,
            "product_id": group.product_id,
            "name": group.name,
            "sort_order": group.sort_order,
            "category": group.category,
            "labels": [
                {"label": item.label, "sort_order": item.sort_order, "category": item.category}
                for item in group.labels
            ],
        }
        for group in groups
    ]


def replace_groups(session, group_specs: list[dict[str, Any]]) -> None:
    """Атомарная полная замена групп и их меток (PUT /api/settings)."""
    products = {product.id: product.name for product in session.query(Product).all()}
    if not products:
        raise ValueError("Сначала создайте хотя бы один продукт")
    default_product_id = min(products)
    session.query(GroupLabel).delete()
    session.query(LabelGroup).delete()
    for order, spec in enumerate(group_specs):
        name = str(spec.get("name") or "").strip()
        if not name:
            raise ValueError("У каждой группы должно быть имя")
        product_id = spec.get("product_id") if spec.get("product_id") is not None else default_product_id
        if product_id not in products:
            raise ValueError(f"У группы «{name}» неизвестный продукт")
        group = LabelGroup(
            name=name, sort_order=order, category=spec.get("category"), product_id=product_id
        )
        seen: set[str] = set()
        for label_order, label_spec in enumerate(spec.get("labels") or []):
            label = str(label_spec.get("label") or "").strip()
            if not label or label in seen:
                continue
            seen.add(label)
            group.labels.append(
                GroupLabel(label=label, sort_order=label_order, category=label_spec.get("category"))
            )
        session.add(group)


def load_sprints(session) -> list[dict[str, Any]]:
    """Спринты в порядке sort_order — вход агрегатора и ответ /api/sprints."""
    sprints = session.query(Sprint).order_by(Sprint.sort_order, Sprint.id).all()
    return [
        {
            "id": sprint.id,
            "name": sprint.name,
            "date_from": sprint.date_from,
            "date_to": sprint.date_to,
            "sort_order": sprint.sort_order,
        }
        for sprint in sprints
    ]


def replace_sprints(session, sprint_specs: list[dict[str, Any]]) -> None:
    """Атомарная полная замена спринтов (PUT /api/sprints)."""
    session.query(Sprint).delete()
    seen_names: set[str] = set()
    windows: list[tuple[date, date, str]] = []
    for order, spec in enumerate(sprint_specs):
        name = str(spec.get("name") or "").strip()
        date_from, date_to = spec.get("date_from"), spec.get("date_to")
        if not name:
            raise ValueError("У каждого спринта должно быть имя")
        if name in seen_names:
            raise ValueError(f"Спринт «{name}» указан дважды")
        if not isinstance(date_from, date) or not isinstance(date_to, date):
            raise ValueError(f"У спринта «{name}» должны быть даты начала и конца")
        if date_to < date_from:
            raise ValueError(f"У спринта «{name}» дата конца раньше даты начала")
        seen_names.add(name)
        windows.append((date_from, date_to, name))
        session.add(Sprint(name=name, date_from=date_from, date_to=date_to, sort_order=order))
    # Пересечение диапазонов запрещено: иначе обращение попало бы в два спринта сразу
    # и сумма контуров не сходилась бы (правило «обращение считается один раз»).
    ordered = sorted(windows)
    for (_, previous_to, previous_name), (next_from, _, next_name) in zip(ordered, ordered[1:]):
        if previous_to >= next_from:
            raise ValueError(f"Диапазоны спринтов «{previous_name}» и «{next_name}» пересекаются")


def load_label_notes(session) -> dict[str, str]:
    """Сохраненные расшифровки меток: {метка: расшифровка}; пустая строка = без расшифровки."""
    return {row.label: row.note for row in session.query(LabelNote).all()}


def replace_label_notes(session, notes: dict[str, str]) -> None:
    """Атомарная полная замена расшифровок (PUT /api/labels). Пустая строка отменяет и дефолт."""
    session.query(LabelNote).delete()
    seen: set[str] = set()
    for label, note in notes.items():
        label = str(label).strip()
        if not label:
            raise ValueError("У каждой метки должно быть имя")
        if label in seen:
            raise ValueError(f"Метка «{label}» указана дважды")
        seen.add(label)
        session.add(LabelNote(label=label, note=str(note or "").strip()))


def load_hidden_labels(session) -> dict[int, list[str]]:
    """Удалённые метки по продуктам: {product_id: [метка, …]} — часть ответа /api/tracker/labels."""
    hidden: dict[int, list[str]] = {}
    for row in session.query(HiddenLabel).order_by(HiddenLabel.label).all():
        hidden.setdefault(row.product_id, []).append(row.label)
    return hidden


def replace_hidden_labels(session, product_id: int, labels: list[str]) -> None:
    """Атомарная полная замена удалённых меток продукта (PUT /api/tracker/labels/hidden)."""
    if session.get(Product, product_id) is None:
        raise ValueError("Продукт не найден")
    session.query(HiddenLabel).filter(HiddenLabel.product_id == product_id).delete(synchronize_session=False)
    seen: set[str] = set()
    for item in labels:
        label = str(item).strip()
        if not label:
            raise ValueError("У каждой метки должно быть имя")
        if label in seen:
            continue
        seen.add(label)
        session.add(HiddenLabel(product_id=product_id, label=label))


def load_users(session) -> list[dict[str, Any]]:
    """Пользователи сайта по алфавиту — ответ /api/users."""
    users = session.query(SiteUser).order_by(SiteUser.username).all()
    return [
        {
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "permissions": list(user.permissions or []),
        }
        for user in users
    ]


def _clean_permissions(raw) -> list[str]:
    """Оставляем только известные функции без повторов — остальное игнорируем."""
    picked: list[str] = []
    for item in raw or []:
        if item in USER_FUNCTIONS and item not in picked:
            picked.append(item)
    return picked


def _validated_role(role: str) -> str:
    if role not in ROLE_PRESETS:
        raise ValueError(f"Неизвестная роль «{role}»")
    return role


def create_user(session, spec: dict[str, Any]) -> None:
    """Создание пользователя (POST /api/users); логин обязателен.

    Пользователь входит через SSO под этим логином; запись здесь задаёт
    его функции. permissions не заданы явно → пресет роли; [] = полностью без функций.
    """
    username = str(spec.get("username") or "").strip()
    if not username:
        raise ValueError("У пользователя должен быть логин")
    if any(ch.isspace() for ch in username):
        raise ValueError("Логин не должен содержать пробелов")
    if session.get(SiteUser, username) is not None:
        raise ValueError(f"Пользователь «{username}» уже есть")
    role = _validated_role(str(spec.get("role") or "viewer"))
    raw_permissions = spec.get("permissions")
    permissions = list(ROLE_PRESETS[role]) if raw_permissions is None else _clean_permissions(raw_permissions)
    session.add(
        SiteUser(
            username=username,
            display_name=str(spec.get("display_name") or "").strip(),
            role=role,
            permissions=permissions,
        )
    )


def update_user(session, username: str, changes: dict[str, Any]) -> None:
    """Изменение пользователя (PUT /api/users/{username})."""
    user = session.get(SiteUser, username)
    if user is None:
        raise ValueError(f"Пользователь «{username}» не найден")
    if "display_name" in changes:
        user.display_name = str(changes["display_name"] or "").strip()
    if changes.get("role") is not None:
        user.role = _validated_role(str(changes["role"]))
    if changes.get("permissions") is not None:
        user.permissions = _clean_permissions(changes["permissions"])


def _existing_rows(session, product_id: int, keys: list[str]) -> dict[str, IssueCache]:
    """Существующие строки кэша продукта по ключам; IN разбит на части — лимит параметров SQLite."""
    found: dict[str, IssueCache] = {}
    for start in range(0, len(keys), 500):
        chunk = keys[start : start + 500]
        rows = session.query(IssueCache).filter(
            IssueCache.product_id == product_id, IssueCache.key.in_(chunk)
        )
        found.update({row.key: row for row in rows})
    return found


def upsert_issues(session, product_id: int, issues: list[dict[str, Any]], synced_at: datetime) -> int:
    """Обновляет кэш задач одного продукта: пришедшие строки upsert, поля перезаписываются."""
    if not issues:
        return 0
    existing = _existing_rows(session, product_id, list({issue["key"] for issue in issues}))
    for issue in issues:
        row = existing.get(issue["key"])
        if row is None:
            row = IssueCache(product_id=product_id, key=issue["key"])
            existing[issue["key"]] = row
            session.add(row)
        row.summary = issue.get("summary") or ""
        row.status = issue.get("status") or ""
        row.labels = issue.get("labels") or []
        row.created_at = to_naive_utc(issue.get("created_at"))
        row.updated_at = to_naive_utc(issue.get("updated_at"))
        row.synced_at = synced_at
        row.raw = issue.get("raw") or {}
    session.flush()
    return len(issues)


def delete_issues_missing(session, product_id: int, keys: list[str]) -> int:
    """Удаляет из кэша продукта задачи, которых нет в его выборке трекера.

    Полная выборка трекера — источник истины: всё, что не пришло, удалено.
    Список ключей большой (десятки тысяч), поэтому удаляем по частям — лимит параметров SQLite.
    """
    rows = session.query(IssueCache.key).filter(IssueCache.product_id == product_id).all()
    if not keys:
        stale_keys = [row.key for row in rows]
    else:
        keep = set(keys)
        stale_keys = [row.key for row in rows if row.key not in keep]
    deleted = 0
    for start in range(0, len(stale_keys), 500):
        chunk = stale_keys[start : start + 500]
        deleted += session.query(IssueCache).filter(
            IssueCache.product_id == product_id, IssueCache.key.in_(chunk)
        ).delete(synchronize_session=False)
    return deleted
