# tests/test_tasks.py

import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, get_db
from app import crud, models, schemas

# ============================================================
# CONFIGURACIÓN DB DE PRUEBAS (SQLite) PARA UNIT + API
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


# Override de la dependencia global de FastAPI
app.dependency_overrides[get_db] = override_get_db


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(autouse=True)
def clean_db():
    """
    Antes de cada test limpiamos la BD de pruebas para que
    no haya basura de otros tests.
    """
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
# 1. PRUEBAS UNITARIAS (directo al CRUD, sin client)
# ============================================================

def _build_task_create(
    title="Test Task",
    description="Descripción de prueba",
    status="pending",
    priority=2,
    due_date=None,
):
    """
    Helper para crear un TaskCreate.
    Ajusta los campos si tu schemas.TaskCreate es diferente.
    """
    return schemas.TaskCreate(
        title=title,
        description=description,
        status=status,
        priority=priority,
        due_date=due_date,
    )


def test_create_task_crud(db_session):
    task_in = _build_task_create()
    task = crud.create_task(db_session, task_in)

    assert task.id is not None
    assert task.title == "Test Task"
    assert task.status == "pending"
    assert task.is_active is True


def test_get_task_crud(db_session):
    task_in = _build_task_create(title="Buscarme")
    created = crud.create_task(db_session, task_in)

    fetched = crud.get_task(db_session, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "Buscarme"


def test_update_task_crud(db_session):
    task_in = _build_task_create()
    created = crud.create_task(db_session, task_in)

    update_data = schemas.TaskUpdate(
        title="Actualizada",
        status="in_progress",
    )

    updated = crud.update_task(db_session, created, update_data)

    assert updated.title == "Actualizada"
    assert updated.status == "in_progress"
    assert updated.updated_at is not None


def test_soft_delete_task_crud(db_session):
    task_in = _build_task_create()
    created = crud.create_task(db_session, task_in)

    crud.soft_delete_task(db_session, created)

    # No debe aparecer al buscar tasks activas
    found = crud.get_task(db_session, created.id)
    assert found is None

    # Pero sigue en la tabla (si lo buscamos sin filtro de is_active)
    raw = (
        db_session.query(models.Task)
        .filter(models.Task.id == created.id)
        .first()
    )
    assert raw is not None
    assert raw.is_active is False


def test_complete_task_crud(db_session):
    task_in = _build_task_create(status="in_progress")
    created = crud.create_task(db_session, task_in)

    done = crud.complete_task(db_session, created)
    assert done.status == "done"


def test_get_tasks_by_status_and_overdue(db_session):
    # Task vencida
    overdue_in = _build_task_create(
        title="Vencida",
        status="in_progress",
        due_date=datetime.utcnow() - timedelta(days=1),
    )
    # Task futura
    future_in = _build_task_create(
        title="Futura",
        status="pending",
        due_date=datetime.utcnow() + timedelta(days=1),
    )
    # Task done (no debe contarse como vencida)
    done_in = _build_task_create(
        title="Hecha",
        status="done",
        due_date=datetime.utcnow() - timedelta(days=1),
    )

    overdue = crud.create_task(db_session, overdue_in)
    future = crud.create_task(db_session, future_in)
    done = crud.create_task(db_session, done_in)

    # Por status
    pending_tasks = crud.get_tasks_by_status(db_session, "pending")
    assert len(pending_tasks) == 1
    assert pending_tasks[0].id == future.id

    # Overdue
    overdue_tasks = crud.get_overdue_tasks(db_session)
    overdue_ids = {t.id for t in overdue_tasks}
    assert overdue.id in overdue_ids
    assert done.id not in overdue_ids  # DONE no cuenta como vencida


# ============================================================
# 2. PRUEBAS DE API (usando TestClient y SQLite)
# ============================================================

def test_create_and_list_tasks_api(client):
    payload = {
        "title": "Task API",
        "description": "Desde API",
        "status": "pending",
        "priority": 1,
        "due_date": None,
    }

    resp = client.post("/tasks", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["id"] is not None
    assert data["title"] == "Task API"

    # Listar
    resp_list = client.get("/tasks")
    assert resp_list.status_code == 200
    tasks = resp_list.json()
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Task API"


def test_update_and_delete_api(client):
    # Crear
    payload = {
        "title": "Original",
        "description": "Desc",
        "status": "pending",
        "priority": 3,
        "due_date": None,
    }
    resp = client.post("/tasks", json=payload)
    task = resp.json()
    task_id = task["id"]

    # Update
    update_payload = {
        "title": "Actualizada API",
        "status": "in_progress",
    }
    resp_upd = client.put(f"/tasks/{task_id}", json=update_payload)
    assert resp_upd.status_code == 200
    updated = resp_upd.json()
    assert updated["title"] == "Actualizada API"
    assert updated["status"] == "in_progress"

    # Delete (soft)
    resp_del = client.delete(f"/tasks/{task_id}")
    assert resp_del.status_code == 204

    # No debería existir como activa
    resp_get = client.get(f"/tasks/{task_id}")
    assert resp_get.status_code == 404


def test_complete_task_api(client):
    payload = {
        "title": "Por completar",
        "description": "Desc",
        "status": "pending",
        "priority": 2,
        "due_date": None,
    }
    resp = client.post("/tasks", json=payload)
    task_id = resp.json()["id"]

    resp_complete = client.patch(f"/tasks/{task_id}/complete")
    assert resp_complete.status_code == 200
    data = resp_complete.json()
    assert data["status"] == "done"


def test_tasks_by_status_and_overdue_api(client):
    # Crea task vencida
    overdue_date = (datetime.utcnow() - timedelta(days=1)).isoformat()
    payload1 = {
        "title": "Overdue API",
        "description": "vencida",
        "status": "in_progress",
        "priority": 2,
        "due_date": overdue_date,
    }
    client.post("/tasks", json=payload1)

    # Crea task pendiente futura
    future_date = (datetime.utcnow() + timedelta(days=1)).isoformat()
    payload2 = {
        "title": "Futura API",
        "description": "futura",
        "status": "pending",
        "priority": 2,
        "due_date": future_date,
    }
    client.post("/tasks", json=payload2)

    # Por status
    resp_status = client.get("/tasks/status/pending")
    assert resp_status.status_code == 200
    tasks_pending = resp_status.json()
    assert len(tasks_pending) == 1
    assert tasks_pending[0]["title"] == "Futura API"

    # Overdue
    resp_overdue = client.get("/tasks/overdue")
    assert resp_overdue.status_code == 200
    tasks_overdue = resp_overdue.json()
    assert len(tasks_overdue) == 1
    assert tasks_overdue[0]["title"] == "Overdue API"


# ============================================================
# 3. PRUEBA DE INTEGRACIÓN CON TESTCONTAINERS (Postgres real)
#    -> requiere: pip install testcontainers[postgresql] psycopg2-binary
# ============================================================

@pytest.mark.integration
def test_integration_with_postgres_testcontainer():
    """
    Integra la app con un Postgres real usando testcontainers.
    Esta prueba es más pesada. Ideal correrla en CI.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers[postgresql] no instalado")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    postgres_image = "postgres:16-alpine"

    with PostgresContainer(postgres_image) as postgres:
        db_url = postgres.get_connection_url()
        engine_pg = create_engine(db_url, future=True)
        TestingSessionPG = sessionmaker(
            autocommit=False, autoflush=False, bind=engine_pg
        )

        # Creamos las tablas en Postgres
        Base.metadata.create_all(bind=engine_pg)

        # Override temporal de get_db para esta prueba
        def override_pg_db():
            db = TestingSessionPG()
            try:
                yield db
            finally:
                db.close()

        old_override = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = override_pg_db

        try:
            client_pg = TestClient(app)

            payload = {
                "title": "Desde Postgres Container",
                "description": "integration test",
                "status": "pending",
                "priority": 1,
                "due_date": None,
            }

            resp = client_pg.post("/tasks", json=payload)
            assert resp.status_code == 201
            data = resp.json()
            assert data["id"] is not None

            resp_list = client_pg.get("/tasks")
            assert resp_list.status_code == 200
            tasks = resp_list.json()
            assert len(tasks) == 1
            assert tasks[0]["title"] == "Desde Postgres Container"
        finally:
            # Restaurar override anterior si existía
            if old_override is not None:
                app.dependency_overrides[get_db] = old_override
            else:
                app.dependency_overrides.pop(get_db, None)


# ============================================================
# 4. PRUEBA E2E CON PLAYWRIGHT
#    -> requiere: pip install playwright pytest-playwright
#    -> luego:   playwright install
#    Esta prueba asume que el backend está corriendo en BASE_URL
# ============================================================

@pytest.mark.e2e
def test_e2e_docs_page(playwright):
    """
    E2E muy básica:
    - Abre la página de /docs de FastAPI
    - Verifica que cargue y que el título contenga el nombre de la API

    Debes tener el backend levantado:
      uvicorn app.main:app --reload
    """
    base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000")

    browser = playwright.chromium.launch()
    page = browser.new_page()

    page.goto(f"{base_url}/docs", wait_until="networkidle")

    title = page.title()
    assert "Task Manager API" in title

    browser.close()


# ============================================================
# 5. PRUEBA DE PERFORMANCE CON PYTEST-BENCHMARK
#    -> requiere: pip install pytest-benchmark
# ============================================================

@pytest.mark.benchmark
def test_performance_list_tasks(client, db_session, benchmark):
    """
    Benchmark simple:
    - Inserta varias tareas
    - Mide el tiempo de respuesta del endpoint /tasks
    """
    # Pre-carga de datos
    for i in range(100):
        task_in = _build_task_create(
            title=f"Tarea {i}",
            status="pending",
            priority=2,
        )
        crud.create_task(db_session, task_in)

    def fetch_tasks():
        resp = client.get("/tasks?skip=0&limit=50")
        assert resp.status_code == 200
        return resp.json()

    result = benchmark(fetch_tasks)

    # Validación básica de que el benchmark no está vacío
    assert isinstance(result, list)
    assert len(result) <= 50  # por el limit
