"""Кэш задач: upsert/удаление по продукту — составной ключ (product_id, key)."""
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app import db
from app.db import utcnow


def make_session(engine):
    db.init_db(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def issue(key: str, summary: str = "", labels: list[str] | None = None) -> dict:
    return {
        "key": key,
        "summary": summary,
        "status": "Открыта",
        "labels": labels or [],
        "created_at": None,
        "updated_at": None,
        "raw": {},
    }


def test_upsert_creates_updates_and_keeps_count(tmp_path):
    engine = db.create_engine("sqlite:///" + (tmp_path / "cache.db").as_posix())
    synced_at = utcnow()
    with make_session(engine) as session:
        spl_id = session.query(db.Product).first().id
        first = [issue("DEMO-1", "первая", ["ls_a"]), issue("DEMO-2", "вторая", [])]
        assert db.upsert_issues(session, spl_id, first, synced_at) == 2
        session.commit()

        second = [issue("DEMO-1", "обновлённая", ["ls_b"]), issue("DEMO-3", "новая", [])]
        assert db.upsert_issues(session, spl_id, second, synced_at) == 2
        session.commit()

        rows = {row.key: row for row in session.query(db.IssueCache).all()}
        assert set(rows) == {"DEMO-1", "DEMO-2", "DEMO-3"}
        assert rows["DEMO-1"].summary == "обновлённая"
        assert rows["DEMO-1"].labels == ["ls_b"]
        assert rows["DEMO-2"].summary == "вторая"
    engine.dispose()


def test_upsert_keeps_products_apart(tmp_path):
    """Одинаковые ключи у разных продуктов — разные строки (составной ключ)."""
    engine = db.create_engine("sqlite:///" + (tmp_path / "cache.db").as_posix())
    synced_at = utcnow()
    with make_session(engine) as session:
        products = session.query(db.Product).order_by(db.Product.sort_order).all()
        db.upsert_issues(session, products[0].id, [issue("X-1", "DEMO версия")], synced_at)
        db.upsert_issues(session, products[1].id, [issue("X-1", "DEMO-STORE версия")], synced_at)
        session.commit()

        spl_row = session.get(db.IssueCache, (products[0].id, "X-1"))
        wms_row = session.get(db.IssueCache, (products[1].id, "X-1"))
        assert spl_row.summary == "DEMO версия"
        assert wms_row.summary == "DEMO-STORE версия"
    engine.dispose()


def test_delete_issues_missing_removes_rows_not_in_tracker(tmp_path):
    engine = db.create_engine("sqlite:///" + (tmp_path / "cache.db").as_posix())
    with make_session(engine) as session:
        spl_id = session.query(db.Product).first().id
        db.upsert_issues(session, spl_id, [issue("DEMO-1"), issue("DEMO-2"), issue("DEMO-3")], utcnow())
        session.commit()

        removed = db.delete_issues_missing(session, spl_id, ["DEMO-1", "DEMO-3"])
        session.commit()
        assert removed == 1
        keys = {row.key for row in session.query(db.IssueCache).all()}
        assert keys == {"DEMO-1", "DEMO-3"}
    engine.dispose()


def test_delete_issues_missing_scoped_to_product(tmp_path):
    """Удаление по выборке одного продукта не трогает кэш других продуктов."""
    engine = db.create_engine("sqlite:///" + (tmp_path / "cache.db").as_posix())
    with make_session(engine) as session:
        products = session.query(db.Product).order_by(db.Product.sort_order).all()
        db.upsert_issues(session, products[0].id, [issue("DEMO-1")], utcnow())
        db.upsert_issues(session, products[1].id, [issue("DEMO-STORE-1")], utcnow())
        session.commit()

        db.delete_issues_missing(session, products[0].id, [])
        session.commit()

        keys = {(row.product_id, row.key) for row in session.query(db.IssueCache).all()}
        assert keys == {(products[1].id, "DEMO-STORE-1")}
    engine.dispose()


def test_replace_label_notes_round_trip(tmp_path):
    engine = db.create_engine("sqlite:///" + (tmp_path / "notes.db").as_posix())
    with make_session(engine) as session:
        db.replace_label_notes(session, {"ls_a": "Первая", "ls_b": ""})
        session.commit()
        assert db.load_label_notes(session) == {"ls_a": "Первая", "ls_b": ""}

        db.replace_label_notes(session, {"ls_c": "Третья"})
        session.commit()
        assert db.load_label_notes(session) == {"ls_c": "Третья"}
    engine.dispose()
