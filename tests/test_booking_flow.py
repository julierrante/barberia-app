from __future__ import annotations

from datetime import time, timedelta

import pytest
from sqlalchemy import func, select

from app.models import Appointment, AppointmentStatus, Client, Payment
from app.timeutils import business_today, local_to_utc
from helpers import booking_payload, find_day_with_slots, parse_dt


def test_home_renders_services_and_barbers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Armá tu" in response.text
    assert "Corte clásico" in response.text
    assert "Mateo Ríos" in response.text


def test_booking_with_deposit_creates_payment_and_ticket(
    client, db, mateo, corte_clasico
):
    day, slots = find_day_with_slots(db, mateo, corte_clasico)
    start_at = slots[0]

    response = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo, service=corte_clasico, start_at=start_at
        ),
    )
    assert response.status_code == 201
    body = response.json()

    assert len(body["public_code"]) == 32
    assert body["status"] == "confirmed"
    assert body["price_cents"] == corte_clasico.price_cents
    assert body["deposit_cents"] == corte_clasico.deposit_cents
    assert body["paid_cents"] == corte_clasico.deposit_cents
    assert body["balance_cents"] == (
        corte_clasico.price_cents - corte_clasico.deposit_cents
    )
    assert parse_dt(body["start_at"]) == start_at
    assert parse_dt(body["end_at"]) == start_at + timedelta(
        minutes=corte_clasico.duration_minutes
    )
    assert len(body["payments"]) == 1
    assert body["payments"][0]["kind"] == "deposit"
    assert body["payments"][0]["method"] == "mock"
    assert body["payments"][0]["status"] == "paid"

    client_row = db.scalar(select(Client).where(Client.phone == "+5491155550101"))
    assert client_row is not None
    assert client_row.first_name == "Lucía"
    assert client_row.email == "lucia@example.com"

    ticket = client.get(f"/reserva/{body['public_code']}")
    assert ticket.status_code == 200
    assert "Comprobante de turno" in ticket.text
    assert "Corte clásico" in ticket.text
    assert "Lucía Fernández" in ticket.text
    assert "Pago online (demo)" in ticket.text
    assert day.strftime("%d/%m/%Y") in ticket.text


def test_full_payment_option_marks_balance_as_zero(client, db, mateo, corte_clasico):
    _, slots = find_day_with_slots(db, mateo, corte_clasico)
    response = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=slots[0],
            payment_option="full",
        ),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["paid_cents"] == corte_clasico.price_cents
    assert body["balance_cents"] == 0
    assert body["payments"][0]["kind"] == "full"


def test_duplicate_slot_is_rejected(client, db, mateo, corte_clasico):
    _, slots = find_day_with_slots(db, mateo, corte_clasico)
    start_at = slots[0]
    first = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo, service=corte_clasico, start_at=start_at
        ),
    )
    assert first.status_code == 201

    duplicate = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=start_at,
            phone="+54 9 11 5555 0202",
            first_name="Otro",
            last_name="Cliente",
        ),
    )
    assert duplicate.status_code == 409
    assert "no está disponible" in duplicate.json()["detail"]
    assert db.scalar(select(func.count(Appointment.id))) == 1


@pytest.mark.parametrize(
    ("offset_days", "expected_message"),
    [(-1, "fechas pasadas"), (46, "45 días adelante")],
)
def test_booking_rejects_dates_outside_window(
    client, mateo, corte_clasico, offset_days, expected_message
):
    day = business_today() + timedelta(days=offset_days)
    response = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=local_to_utc(day, time(12, 0)),
        ),
    )
    assert response.status_code == 400
    assert expected_message in response.json()["detail"]


def test_customer_cancel_checks_phone_and_releases_slot(
    client, db, mateo, corte_clasico
):
    day, slots = find_day_with_slots(db, mateo, corte_clasico)
    start_at = slots[0]
    created = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo, service=corte_clasico, start_at=start_at
        ),
    ).json()
    code = created["public_code"]

    wrong_phone = client.post(
        f"/api/appointments/{code}/cancel",
        json={"phone": "+54 9 11 0000 0000"},
    )
    assert wrong_phone.status_code == 403
    assert "no coincide" in wrong_phone.json()["detail"]

    cancelled = client.post(
        f"/api/appointments/{code}/cancel",
        json={"phone": "+54 9 11 5555 0101"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    db.expire_all()
    row = db.scalar(select(Appointment).where(Appointment.public_code == code))
    assert row.status == AppointmentStatus.cancelled

    availability = client.get(
        "/api/availability",
        params={
            "barber_id": mateo.id,
            "service_id": corte_clasico.id,
            "date": day.isoformat(),
        },
    )
    assert availability.status_code == 200
    available = [parse_dt(slot["start_at"]) for slot in availability.json()["slots"]]
    assert start_at in available

    second_cancel = client.post(
        f"/api/appointments/{code}/cancel",
        json={"phone": "+54 9 11 5555 0101"},
    )
    assert second_cancel.status_code == 409


def test_same_phone_reuses_client_identity(client, db, mateo, corte_clasico):
    _, slots = find_day_with_slots(db, mateo, corte_clasico, minimum=2)
    first = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo, service=corte_clasico, start_at=slots[0]
        ),
    )
    assert first.status_code == 201

    second = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=slots[-1],
            phone="+5491155550101",
            first_name="Lucía",
            last_name="Fernández Ruiz",
        ),
    )
    assert second.status_code == 201

    db.expire_all()
    assert db.scalar(select(func.count(Client.id))) == 1
    client_row = db.scalar(select(Client))
    assert client_row.last_name == "Fernández Ruiz"
    assert db.scalar(select(func.count(Appointment.id))) == 2
    assert db.scalar(select(func.count(Payment.id))) == 2
