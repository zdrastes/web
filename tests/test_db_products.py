"""Стартовые продукты: коды чтения задач трекера и миграция баз с ошибочными alias'ами."""
from sqlalchemy.orm import sessionmaker

from app import db


def products_by_name(engine) -> dict[str, tuple[str, str]]:
    with db.session_factory(engine)() as session:
        return {
            product["name"]: (product["namespace"], product["project_code"])
            for product in db.load_products(session)
        }


def test_default_products_seed_tracker_read_codes(tmp_path):
    engine = db.create_engine("sqlite:///" + (tmp_path / "fresh.db").as_posix())

    db.init_db(engine)

    codes = products_by_name(engine)
    assert codes["DEMO-STORE"] == ("demo-namespace", "DEMO-STORE")
    assert codes["DEMO-TRANS"] == ("demo-namespace", "DEMO-TRANS")
    engine.dispose()


def test_init_db_fixes_legacy_alias_codes(tmp_path):
    """Базы до миграции кодов: в продуктах лежали alias'ы создания задач — задачи не грузились."""
    engine = db.create_engine("sqlite:///" + (tmp_path / "legacy.db").as_posix())
    db.Base.metadata.create_all(engine)
    with db.session_factory(engine)() as session:
        session.add(db.Product(
            name="DEMO-STORE", namespace="legacy-namespace", project_code="legacy-store", sort_order=0,
        ))
        session.add(db.Product(
            name="DEMO-TRANS", namespace="legacy-namespace",
            project_code="legacy-trans", sort_order=1,
        ))
        session.commit()

    db.init_db(engine)

    codes = products_by_name(engine)
    assert codes["DEMO-STORE"] == ("demo-namespace", "DEMO-STORE")
    assert codes["DEMO-TRANS"] == ("demo-namespace", "DEMO-TRANS")
    engine.dispose()


def test_init_db_keeps_custom_codes(tmp_path):
    engine = db.create_engine("sqlite:///" + (tmp_path / "custom.db").as_posix())
    db.Base.metadata.create_all(engine)
    with db.session_factory(engine)() as session:
        session.add(db.Product(name="Свой", namespace="MYNS", project_code="MYPROJ", sort_order=0))
        session.commit()

    db.init_db(engine)

    assert products_by_name(engine)["Свой"] == ("MYNS", "MYPROJ")
    engine.dispose()
