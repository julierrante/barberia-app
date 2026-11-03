from __future__ import annotations

from datetime import time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app

from app.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    BarberAccount,
    Barberia,
    Client,
    DailyClosing,
    Payment,
    PaymentKind,
    PaymentMethod,
    PaymentStatus,
)
from app.services.barbers import (
    BarberProfileData,
    create_barber_profile,
)
from app.services.closings import (
    close_day,
    ensure_latest_day_closed,
    latest_closable_day,
)
from app.timeutils import business_today, local_to_utc

def _temporary_barber(db, *, name: str = "Barbero Temporal") -> Barber:
    barberia = db.scalar(
        select(Barberia).where(Barberia.slug == "barberia-norte")
    )
    assert barberia is not None

    return create_barber_profile(
        db,
        BarberProfileData(
            name=name,
            tagline="Perfil de prueba",
            bio=None,
            mp_alias=None,
            email="temporal@example.com",
            password="clave-segura-123",
            active=True,
            specialty_ids=[],
            schedules=[(0, time(9, 0), time(10, 0))],
            schedule_rows=[],
        ),
        barberia_id=barberia.id,
    )

def _appointment(
    *,
    person: Client,
    barber: Barber,
    service,
    day,
    clock: time,
    status: AppointmentStatus,
    price_cents: int | None = None,
    payments: list[Payment] | None = None,
) -> Appointment:
    start_at = local_to_utc(day, clock)
    price = service.price_cents if price_cents is None else price_cents
    return Appointment(
        client=person,
        barber=barber,
        service=service,
        status=status,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=service.duration_minutes),
        duration_minutes=service.duration_minutes,
        price_cents=price,
        deposit_cents=0,
        payments=payments or [],
    )


def test_admin_can_delete_barber_and_history_is_kept(
    admin_client, client, db, mateo, corte_clasico
):
    barber = _temporary_barber(db)
    day = business_today() - timedelta(days=3)

    person = Client(
        first_name="Baja",
        last_name="Programada",
        phone="+5491100030303",
    )
    appointment = _appointment(
        person=person,
        barber=barber,
        service=corte_clasico,
        day=day,
        clock=time(9, 0),
        status=AppointmentStatus.confirmed,
    )
    db.add_all([person, appointment])
    db.commit()

    blocked = admin_client.post(
        f"/admin/barberos/{barber.id}/eliminar",
        follow_redirects=False,
    )
    assert blocked.status_code == 303
    assert "error=turnos-pendientes" in blocked.headers["location"]

    db.expire_all()
    still_there = db.get(Barber, barber.id)
    assert still_there is not None
    assert still_there.deleted_at is None
    assert still_there.account is not None

    appointment = db.get(Appointment, appointment.id)
    appointment.status = AppointmentStatus.cancelled
    db.commit()
    close_day(db, day)

    deleted = admin_client.post(
        f"/admin/barberos/{barber.id}/eliminar",
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert "eliminado=1" in deleted.headers["location"]

    db.expire_all()
    archived = db.get(Barber, barber.id)
    assert archived is not None
    assert archived.deleted_at is not None
    assert archived.active is False
    assert db.scalar(
        select(BarberAccount).where(BarberAccount.barber_id == barber.id)
    ) is None

    closing = db.scalar(
        select(DailyClosing).where(
            DailyClosing.barber_id == barber.id,
            DailyClosing.business_date == day,
        )
    )
    assert closing is not None
    assert closing.barber_name == barber.name

    listing = admin_client.get("/admin/barberos?eliminado=1")
    assert listing.status_code == 200
    assert "El perfil se eliminó" in listing.text
    assert barber.name not in listing.text

    failed_login = client.post(
        "/admin/login",
        data={"username": "temporal@example.com", "password": "clave-segura-123"},
        follow_redirects=False,
    )
    assert failed_login.status_code == 401


def test_owner_profile_centralizes_team_actions_and_blocks_barbers(
    admin_client, client, db, mateo
):
    page = admin_client.get("/admin/mi-perfil")
    assert page.status_code == 200
    assert "Mi perfil" in page.text
    assert "Acciones sobre el equipo" in page.text
    assert "Agregar barbero" in page.text
    assert "Administradora" in page.text
    assert mateo.name in page.text
    assert "/admin/barberos/nuevo" in page.text
    assert "Eliminar" in page.text

    barber = _temporary_barber(db)
    login = client.post(
        "/admin/login",
        data={"username": "temporal@example.com", "password": "clave-segura-123"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/mi-agenda"

    blocked = client.get("/admin/mi-perfil", follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/admin/login"

    blocked_agenda = client.get("/admin/agenda", follow_redirects=False)
    assert blocked_agenda.status_code == 303
    assert blocked_agenda.headers["location"] == "/admin/login"

    blocked_delete = client.post(
        f"/admin/barberos/{barber.id}/eliminar",
        data={"origin": "perfil"},
        follow_redirects=False,
    )
    assert blocked_delete.status_code == 303
    assert blocked_delete.headers["location"] == "/admin/login"


def test_team_actions_from_owner_profile_return_to_profile(admin_client, db):
    barber = _temporary_barber(db)
    barber.active = False
    db.commit()

    approved = admin_client.post(
        f"/admin/barberos/{barber.id}/estado",
        data={"active": "1", "origin": "perfil"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    assert approved.headers["location"] == "/admin/mi-perfil?actualizado=1"

    deleted = admin_client.post(
        f"/admin/barberos/{barber.id}/eliminar",
        data={"origin": "perfil"},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/admin/mi-perfil?eliminado=1"

    db.expire_all()
    archived = db.get(Barber, barber.id)
    assert archived.deleted_at is not None
    assert archived.active is False

    page = admin_client.get("/admin/mi-perfil?eliminado=1")
    assert "El perfil se eliminó" in page.text
    assert barber.name not in page.text


def test_owner_home_is_a_barber_gallery_not_the_agenda(admin_client, mateo):
    home = admin_client.get("/admin")
    assert home.status_code == 200
    assert "en primera plana" in home.text
    assert "Ver acciones" in home.text
    assert mateo.name in home.text
    assert mateo.avatar_url in home.text
    assert f'data-agenda-url="/admin/agenda?barber_id={mateo.id}"' in home.text
    assert f'data-edit-url="/admin/barberos/{mateo.id}"' in home.text
    assert f'data-delete-url="/admin/barberos/{mateo.id}/eliminar"' in home.text
    assert 'id="owner-actions-dialog"' in home.text
    assert "Turnos del día" not in home.text

    agenda = admin_client.get("/admin/agenda")
    assert agenda.status_code == 200
    assert "Turnos del día" in agenda.text
    assert 'id="admin-barber"' in agenda.text


def test_owner_agenda_preselects_the_chosen_barber(admin_client, mateo):
    page = admin_client.get(
        "/admin/agenda",
        params={"barber_id": mateo.id},
    )
    assert page.status_code == 200
    assert f'value="{mateo.id}" selected' in page.text


def test_owner_home_actions_return_to_home(admin_client, db, mateo):
    mateo.active = False
    db.commit()

    approved = admin_client.post(
        f"/admin/barberos/{mateo.id}/estado",
        data={"active": "1", "origin": "home"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    assert approved.headers["location"] == "/admin?actualizado=1"

    page = admin_client.get("/admin?actualizado=1")
    assert "El estado del barbero se actualizó" in page.text

    barber = _temporary_barber(db)
    deleted = admin_client.post(
        f"/admin/barberos/{barber.id}/eliminar",
        data={"origin": "home"},
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/admin?eliminado=1"

    page = admin_client.get("/admin?eliminado=1")
    assert "El perfil se eliminó" in page.text


def test_deleted_barber_session_does_not_loop_on_login(admin_client, db):
    barber = _temporary_barber(db)
    with TestClient(app) as barber_client:
        login = barber_client.post(
            "/admin/login",
            data={
                "username": "temporal@example.com",
                "password": "clave-segura-123",
            },
            follow_redirects=False,
        )
        assert login.status_code == 303
        assert login.headers["location"] == "/mi-agenda"

        deleted = admin_client.post(
            f"/admin/barberos/{barber.id}/eliminar",
            data={"origin": "home"},
            follow_redirects=False,
        )
        assert deleted.status_code == 303

        agenda = barber_client.get("/mi-agenda", follow_redirects=False)
        assert agenda.status_code == 303
        assert agenda.headers["location"] == "/admin/login"

        login_page = barber_client.get("/admin/login", follow_redirects=False)
        assert login_page.status_code == 200


def test_close_day_records_each_barber_and_can_be_recalculated(
    admin_client, db, mateo, corte_clasico
):
    day = business_today() - timedelta(days=2)
    person = Client(
        first_name="Cierre",
        last_name="Diario",
        phone="+5491100040404",
    )
    completed = _appointment(
        person=person,
        barber=mateo,
        service=corte_clasico,
        day=day,
        clock=time(10, 0),
        status=AppointmentStatus.completed,
        payments=[
            Payment(
                kind=PaymentKind.deposit,
                method=PaymentMethod.mock,
                status=PaymentStatus.paid,
                amount_cents=400_000,
            )
        ],
    )
    cancelled = _appointment(
        person=person,
        barber=mateo,
        service=corte_clasico,
        day=day,
        clock=time(11, 0),
        status=AppointmentStatus.cancelled,
        payments=[
            Payment(
                kind=PaymentKind.deposit,
                method=PaymentMethod.mock,
                status=PaymentStatus.paid,
                amount_cents=400_000,
            )
        ],
    )
    no_show = _appointment(
        person=person,
        barber=mateo,
        service=corte_clasico,
        day=day,
        clock=time(12, 0),
        status=AppointmentStatus.no_show,
    )
    db.add_all([person, completed, cancelled, no_show])
    db.commit()

    rows = close_day(db, day)
    assert len(rows) == 3

    mateo_row = next(row for row in rows if row.barber_id == mateo.id)
    assert mateo_row.appointments_count == 3
    assert mateo_row.completed_count == 1
    assert mateo_row.cancelled_count == 1
    assert mateo_row.no_show_count == 1
    assert mateo_row.service_revenue_cents == corte_clasico.price_cents
    assert mateo_row.collected_cents == 800_000
    assert mateo_row.pending_cents == corte_clasico.price_cents - 400_000

    zero_rows = [row for row in rows if row.barber_id != mateo.id]
    assert len(zero_rows) == 2
    assert all(row.appointments_count == 0 for row in zero_rows)
    assert all(row.service_revenue_cents == 0 for row in zero_rows)
    assert all(row.collected_cents == 0 for row in zero_rows)
    assert all(row.pending_cents == 0 for row in zero_rows)

    extra = _appointment(
        person=person,
        barber=mateo,
        service=corte_clasico,
        day=day,
        clock=time(15, 0),
        status=AppointmentStatus.completed,
        price_cents=800_000,
        payments=[
            Payment(
                kind=PaymentKind.full,
                method=PaymentMethod.cash,
                status=PaymentStatus.paid,
                amount_cents=800_000,
            )
        ],
    )
    db.add(extra)
    db.commit()

    close_day(db, day)
    assert db.scalar(
        select(func.count(DailyClosing.id)).where(
            DailyClosing.business_date == day
        )
    ) == 3
    db.expire_all()
    mateo_row = db.scalar(
        select(DailyClosing).where(
            DailyClosing.barber_id == mateo.id,
            DailyClosing.business_date == day,
        )
    )
    assert mateo_row.completed_count == 2
    assert mateo_row.service_revenue_cents == corte_clasico.price_cents + 800_000
    assert mateo_row.collected_cents == 1_600_000

    page = admin_client.get(
        "/admin/cierres",
        params={"month": day.strftime("%Y-%m")},
    )
    assert page.status_code == 200
    assert mateo.name in page.text
    assert "$ 16.000" in page.text
    assert "Cobrado" in page.text
    assert "$ 0" in page.text


def test_manual_close_creates_zero_rows_and_rejects_future(admin_client, db):
    day = business_today() - timedelta(days=1)

    response = admin_client.post(
        "/admin/cierres",
        data={"date": day.isoformat()},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert f"month={day.strftime('%Y-%m')}" in response.headers["location"]
    assert "guardado=1" in response.headers["location"]

    db.expire_all()
    rows = list(
        db.scalars(
            select(DailyClosing).where(DailyClosing.business_date == day)
        ).all()
    )
    assert len(rows) == 3
    assert all(row.appointments_count == 0 for row in rows)
    assert all(row.service_revenue_cents == 0 for row in rows)
    assert all(row.pending_cents == 0 for row in rows)

    future = admin_client.post(
        "/admin/cierres",
        data={"date": (business_today() + timedelta(days=1)).isoformat()},
        follow_redirects=False,
    )
    assert future.status_code == 303
    assert "error=fecha-futura" in future.headers["location"]


def test_latest_closable_day_and_automatic_close(db):
    day = business_today() - timedelta(days=4)

    assert (
        latest_closable_day(now=local_to_utc(day, time(23, 45))) == day
    )
    assert (
        latest_closable_day(now=local_to_utc(day, time(22, 0)))
        == day - timedelta(days=1)
    )

    created = ensure_latest_day_closed(
        db, now=local_to_utc(day, time(23, 45))
    )
    assert created == day
    assert db.scalar(
        select(func.count(DailyClosing.id)).where(
            DailyClosing.business_date == day
        )
    ) == 3

    repeated = ensure_latest_day_closed(
        db, now=local_to_utc(day, time(23, 45))
    )
    assert repeated is None


def test_automatic_close_updates_an_early_manual_close(db):
    day = business_today() - timedelta(days=5)
    close_day(db, day, now=local_to_utc(day, time(10, 0)))

    closed = ensure_latest_day_closed(
        db, now=local_to_utc(day, time(23, 45))
    )
    assert closed == day

    db.expire_all()
    stamps = db.scalars(
        select(DailyClosing.closed_at).where(
            DailyClosing.business_date == day
        )
    ).all()
    assert min(stamps) >= local_to_utc(day, time(23, 30))

    repeated = ensure_latest_day_closed(
        db, now=local_to_utc(day, time(23, 45))
    )
    assert repeated is None
