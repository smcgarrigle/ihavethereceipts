import os

import pytest
from fastapi.testclient import TestClient

# Use in-memory SQLite for testing BEFORE importing app
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["TESTING"] = "1"

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

# Create a testing engine
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


@event.listens_for(engine, "connect")
def do_connect(dbapi_connection, _connection_record):
    dbapi_connection.isolation_level = None


@event.listens_for(engine, "begin")
def do_begin(conn):
    conn.exec_driver_sql("BEGIN")


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def _isolate_feature_flags(tmp_path, monkeypatch):
    """Keep tests out of the repository's tracked data/feature_flags.json.

    It is runtime-mutable state that happens to be committed, so a test that
    flips a flag would otherwise dirty the working tree. A missing file loads
    the same defaults, so this changes nothing a test can observe.
    """
    from app.api import settings_router

    monkeypatch.setattr(settings_router, "FEATURE_FLAGS_PATH", tmp_path / "feature_flags.json")


@pytest.fixture(autouse=True)
def _no_background_workers(request, monkeypatch):
    """Keep the app's background workers from running during tests.

    Three pieces of background work open sessions on ``app.database``'s own
    in-memory engine from threads that outlive the request or test that
    started them:

    - the BulkProcessor poll loop, started by the app lifespan on every
      ``TestClient`` entry and never joined on exit;
    - the NutritionEnricher batch, started by a reviewed-items save when
      nutrition coverage is below threshold;
    - ``enrich_db_item_task``, scheduled per new item by the same save.

    That engine pools SQLite connections per thread and closes them from
    whichever thread triggers cleanup, so a still-running worker had its
    connection closed underneath it: "Cannot operate on a closed database",
    and intermittently a segfault that killed the whole pytest process.
    None of this work is observable to a test (it queries a database with no
    tables), so it is turned off here. Tests that exercise one of these
    pieces directly call its method rather than going through these entry
    points; mark a test ``real_background_work`` to keep the real ones.
    """
    if request.node.get_closest_marker("real_background_work"):
        return

    from app.services import fdc_service
    from app.services.bulk_processor import BulkProcessor
    from app.services.nutrition_enricher import NutritionEnricher

    monkeypatch.setattr(BulkProcessor, "start", lambda _self: None)
    monkeypatch.setattr(NutritionEnricher, "start", lambda _self, **_kwargs: None)
    monkeypatch.setattr(fdc_service, "enrich_db_item_task", lambda _item_id: False)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
