from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="barberia-tests-"))

os.environ["APP_NAME"] = "Barbería Test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.db'}"
os.environ["BUSINESS_TIMEZONE"] = "America/Argentina/Buenos_Aires"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["SESSION_SECRET"] = "test-secret"
os.environ["MIN_NOTICE_MINUTES"] = "30"
os.environ["SLOT_GRANULARITY_MINUTES"] = "15"
os.environ["BOOKING_DAYS_AHEAD"] = "45"
os.environ["PAYMENTS_MODE"] = "mock"
os.environ["REMINDER_WORKER_ENABLED"] = "false"
os.environ["DAILY_CLOSE_ENABLED"] = "false"

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (
    Appointment,
    Barber,
    BarberAccount,
    Client,
    DailyClosing,
    Payment,
    Service,
)

SEEDED_BARBER_SLUGS = {"mateo-rios", "thiago-benitez", "camila-duarte"}
from app.seed import seed


@pytest.fixture(scope="session", autouse=True)
def _seeded_database():
    Base.metadata.drop_all(engine)
    seed()
    yield
    engine.dispose()
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_transactions():
    with SessionLocal() as db:
        db.execute(delete(DailyClosing))
        db.execute(delete(Payment))
        db.execute(delete(Appointment))
        db.execute(delete(Client))
        db.execute(delete(BarberAccount))
        db.execute(delete(Barber).where(Barber.slug.notin_(SEEDED_BARBER_SLUGS)))
        db.execute(
            update(Barber)
            .where(Barber.slug.in_(SEEDED_BARBER_SLUGS))
            .values(active=True, deleted_at=None)
        )
        db.commit()
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_client(client):
    response = client.post(
        "/admin/login",
        data={"username": "admin", "password": "test-password"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client


@pytest.fixture
def mateo(db) -> Barber:
    barber = db.scalar(select(Barber).where(Barber.slug == "mateo-rios"))
    assert barber is not None
    return barber


@pytest.fixture
def corte_clasico(db) -> Service:
    service = db.scalar(select(Service).where(Service.name == "Corte clásico"))
    assert service is not None
    return service
