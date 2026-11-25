"""Синхронизация кэша по каждому продукту со своей выборкой трекера."""
import pytest
from sqlalchemy.orm import sessionmaker

from app import db
from app.sync_service import perform_sync
from app.sync_service import SyncNotConfigured


class FakeSettings:
    tracker_configured = True
    tracker_base_url = "https://tracker.test"
    tracker_status_ids = ()


class FakeClient:
    """Клиент одного продукта: выборка задаётся по названию продукта."""

    def __init__(self, samples: dict[str, list[dict]], product: dict, failures: set[str] = ()):
        self.samples = samples
        self.product = product
        self.failures = failures

    def get_all_issues(self):
        if self.product["name"] in self.failures:
            raise RuntimeError("трекер недоступен")
        return self.samples.get(self.product["name"], [])

    def close(self):
        pass


def make_session_factory(engine):
    db.init_db(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


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


def test_perform_sync_fills_cache_per_product(tmp_path):
    engine = db.create_engine("sqlite:///" + (tmp_path / "sync.db").as_posix())
    factory = make_session_factory(engine)
    with factory() as session:
        products = {p["name"]: p["id"] for p in db.load_products(session)}

    def make_client(product):
        return FakeClient({"SPL": [issue("SPL-1", "первая")], "WMS": [issue("WMS-1", "своя")]}, product)

    result = perform_sync(FakeSettings(), factory, make_client)
    assert result["fetched"] == 2
    assert result["stored"] == 2

    with factory() as session:
        rows = {(row.product_id, row.key) for row in session.query(db.IssueCache).all()}
        assert (products["SPL"], "SPL-1") in rows
        assert (products["WMS"], "WMS-1") in rows
    engine.dispose()


def test_perform_sync_without_namespace_raises(tmp_path):
    engine = db.create_engine("sqlite:///" + (tmp_path / "sync.db").as_posix())
    factory = make_session_factory(engine)
    with factory() as session:
        for product in session.query(db.Product).all():
            product.namespace = ""
            product.project_code = ""
        session.commit()

    with pytest.raises(SyncNotConfigured):
        perform_sync(FakeSettings(), factory, lambda product: None)
    engine.dispose()
