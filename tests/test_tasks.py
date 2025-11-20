# tests/test_tasks.py

import os
import shutil
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ============================================================
# FIX IMPORT: asegurar que backend/app/ siempre existe en PATH
# ============================================================
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.main import app
from app.database import Base, get_db
from app import crud, models, schemas


# ============================================================
# MARCADORES DE PYTEST (para eliminar warnings)
# ============================================================
def pytest_configure(config):
    config.addinivalue_line("markers", "integration: test de integración con Docker/TestContainers")
    config.addinivalue_line("markers", "e2e: test end-to-end usando Playwright")
    config.addinivalue_line("markers", "benchmark: pruebas de rendimiento")


# ============================================================
# CONFIGURACIÓN DE BD (SQLite) PARA UNIT + API
# ============================================================

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_tasks.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)

Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Override global de FastAPI
app.dependency_overrides[get_db] = override_get_db


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(autouse=True)
def clean_db():
    """Reinicia la BD antes de cada test para evitar contaminación."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    return TestClient(app)


# ============================================================
# HELPERS
# ============================================================

def _build_task_create(
    title="Test Task",
    description="Descripción de prueba",
    status="pending",
    priority=2,
    due_date=None,
):
    return schemas.TaskCreate(
        title=title,
        description=description,
        status=status,
        priority=priority,
        due_date=due_date,
    )


# ============================================================
# 1. PRUEBAS UNITARIAS (CRUD directo)
# ============================================================

def test_create_task_crud(db_session):
    task = crud.create_task(db_session, _build_task_create())
    assert task.id is not None
    assert task.title == "Test Task"
    assert task.status == "pending"


def test_get_task_crud(db_session):
    created = crud.create_task(db_session, _build_task_create(title="Buscarme"))
    fetched = crud.get_task(db_session, created.id)
    assert fetched is not None
    assert fetched.title == "Buscarme"


def test_update_task_crud(db_session):
    created = crud.create_task(db_session, _build_task_create())
    updated = crud.update_task(
        db_session,
        created,
        schemas.TaskUpdate(title="Actualizada", status="in_progress"),
    )
    assert updated.title == "Actualizada"
    assert updated.status == "in_progress"


def test_soft_delete_task_crud(db_session):
    created = crud.create_task(db_session, _build_task_create())
    crud.soft_delete_task(db_session, created)
    assert crud.get_task(db_session, created.id) is None


def test_complete_task_crud(db_session):
    created = crud.create_task(
        db_session,
        _build_task_create(status="in_progress")
    )
    done = crud.complete_task(db_session, created)
    assert done.status == "done"


def test_get_tasks_by_status_and_overdue(db_session):
    overdue = crud.create_task(
        db_session,
        _build_task_create(
            title="Vencida",
            status="in_progress",
            due_date=datetime.utcnow() - timedelta(days=1),
        )
    )

    future = crud.create_task(
        db_session,
        _build_task_create(
            title="Futura",
            status="pending",
            due_date=datetime.utcnow() + timedelta(days=1),
        )
    )

    done = crud.create_task(
        db_session,
        _build_task_create(
            title="Hecha",
            status="done",
            due_date=datetime.utcnow() - timedelta(days=1),
        )
    )

    # Status
    pending = crud.get_tasks_by_status(db_session, "pending")
    assert pending[0].id == future.id

    # Overdue
    overdue_tasks = crud.get_overdue_tasks(db_session)
    overdue_ids = {t.id for t in overdue_tasks}
    assert overdue.id in overdue_ids
    assert done.id not in overdue_ids


# ============================================================
# 2. PRUEBAS API (TestClient)
# ============================================================

def test_create_and_list_tasks_api(client):
    resp = client.post("/tasks", json={
        "title": "Task API",
        "description": "Desde API",
        "status": "pending",
        "priority": 1,
        "due_date": None
    })
    assert resp.status_code == 201

    resp_list = client.get("/tasks")
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1


def test_update_and_delete_api(client):
    new = client.post("/tasks", json={
        "title": "Original",
        "description": "Desc",
        "status": "pending",
        "priority": 2,
        "due_date": None
    }).json()

    uid = new["id"]

    upd = client.put(f"/tasks/{uid}", json={
        "title": "Actualizada API",
        "status": "in_progress"
    })
    assert upd.status_code == 200
    assert upd.json()["title"] == "Actualizada API"

    del_res = client.delete(f"/tasks/{uid}")
    assert del_res.status_code == 204

    res_404 = client.get(f"/tasks/{uid}")
    assert res_404.status_code == 404


def test_complete_task_api(client):
    new = client.post("/tasks", json={
        "title": "Por completar",
        "description": "Desc",
        "status": "pending",
        "priority": 2,
        "due_date": None
    }).json()

    uid = new["id"]

    complete = client.patch(f"/tasks/{uid}/complete")
    assert complete.json()["status"] == "done"


def test_tasks_by_status_and_overdue_api(client):
    overdue_date = (datetime.utcnow() - timedelta(days=1)).isoformat() + "Z"
    future_date = (datetime.utcnow() + timedelta(days=1)).isoformat() + "Z"

    client.post("/tasks", json={
        "title": "Overdue API",
        "description": "vencida",
        "status": "in_progress",
        "priority": 2,
        "due_date": overdue_date
    })

    client.post("/tasks", json={
        "title": "Futura API",
        "description": "futura",
        "status": "pending",
        "priority": 2,
        "due_date": future_date
    })

    pending_res = client.get("/tasks/status/pending")
    assert pending_res.status_code == 200
    assert pending_res.json()[0]["title"] == "Futura API"

    overdue_res = client.get("/tasks/overdue")
    assert overdue_res.status_code == 200
    assert overdue_res.json()[0]["title"] == "Overdue API"


# ============================================================
# 3. TEST DE INTEGRACIÓN (Docker/TestContainers)
# ============================================================

@pytest.mark.integration
def test_integration_with_postgres_testcontainer():
    """Se salta automáticamente si Docker no está disponible."""
    if shutil.which("docker") is None:
        pytest.skip("Docker no instalado, se omite test de integración.")

    try:
        from testcontainers.postgres import PostgresContainer
    except:
        pytest.skip("testcontainers no instalado.")

    # Si Docker no corre, también saltará
    try:
        container = PostgresContainer("postgres:16-alpine")
    except Exception:
        pytest.skip("Docker no está corriendo, skip.")

    with container as postgres:
        db_url = postgres.get_connection_url()

        engine_pg = create_engine(db_url, future=True)
        TestingSessionPG = sessionmaker(
            autocommit=False, autoflush=False, bind=engine_pg
        )

        Base.metadata.create_all(bind=engine_pg)

        def override_pg():
            db = TestingSessionPG()
            try:
                yield db
            finally:
                db.close()

        old = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = override_pg

        client_pg = TestClient(app)

        resp = client_pg.post("/tasks", json={
            "title": "Desde Postgres",
            "description": "test",
            "status": "pending",
            "priority": 1,
            "due_date": None
        })
        assert resp.status_code == 201

        app.dependency_overrides[get_db] = old


# ============================================================
# 4. TEST E2E (Playwright)
# ============================================================

@pytest.mark.e2e
def test_e2e_docs_page(playwright):
    """Se salta automáticamente si Playwright no tiene navegadores."""
    browsers_path = os.path.join(
        os.environ["USERPROFILE"],
        "AppData", "Local", "ms-playwright"
    )
    if not os.path.exists(browsers_path):
        pytest.skip("Playwright no tiene navegadores instalados (falta 'playwright install').")

    base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000")

    browser = playwright.chromium.launch()
    page = browser.new_page()
    page.goto(f"{base_url}/docs", wait_until="networkidle")

    assert "Task Manager API" in page.title()
    browser.close()


# ============================================================
# 5. BENCHMARK
# ============================================================

@pytest.mark.benchmark
def test_performance_list_tasks(client, db_session, benchmark):
    for i in range(100):
        crud.create_task(
            db_session,
            _build_task_create(title=f"Tarea {i}")
        )

    def fetch_tasks():
        r = client.get("/tasks?skip=0&limit=50")
        return r.json()

    result = benchmark(fetch_tasks)
    assert isinstance(result, list)
