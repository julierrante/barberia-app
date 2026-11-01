from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Appointment, AppointmentReminder
from app.services.booking import confirm_customer_attendance
from app.services.errors import ConflictError
from app.services.reminders import (
    FINAL_NOTICE_OFFSET,
    build_reminder_text,
    process_due_reminders,
)
from app.services.scheduling import build_queue
from helpers import booking_payload, find_day_with_slots, parse_dt


def _book(client, db, mateo, corte_clasico, **kwargs):
    _, slots = find_day_with_slots(db, mateo, corte_clasico)
    response = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=slots[0],
            **kwargs,
        ),
    )
    assert response.status_code == 201
    return response.json()


def test_booking_starts_without_attendance_confirmation(
    client, db, mateo, corte_clasico
):
    created = _book(client, db, mateo, corte_clasico)
    assert created["client_confirmed_at"] is None

    db.expire_all()
    row = db.get(Appointment, created["id"])
    assert row.client_confirmed_at is None


def test_customer_confirms_attendance_from_ticket_link(
    client, admin_client, db, mateo, corte_clasico
):
    day, _ = find_day_with_slots(db, mateo, corte_clasico)
    created = _book(client, db, mateo, corte_clasico)

    ticket = client.get(f"/reserva/{created['public_code']}")
    assert ticket.status_code == 200
    assert 'id="attendance-confirm"' in ticket.text
    assert "Asistencia confirmada" not in ticket.text

    queue = admin_client.get(
        "/api/admin/queue",
        params={"barber_id": mateo.id, "date": day.isoformat()},
    )
    item = next(
        item for item in queue.json()["items"] if item["id"] == created["id"]
    )
    assert item["client_confirmed"] is False

    confirmed = client.post(f"/api/appointments/{created['public_code']}/confirm")
    assert confirmed.status_code == 200
    assert parse_dt(confirmed.json()["client_confirmed_at"]) is not None

    again = client.post(f"/api/appointments/{created['public_code']}/confirm")
    assert again.status_code == 200
    assert (
        again.json()["client_confirmed_at"]
        == confirmed.json()["client_confirmed_at"]
    )

    ticket = client.get(f"/reserva/{created['public_code']}")
    assert "Asistencia confirmada" in ticket.text
    assert 'id="attendance-confirm"' not in ticket.text

    queue = admin_client.get(
        "/api/admin/queue",
        params={"barber_id": mateo.id, "date": day.isoformat()},
    )
    item = next(
        item for item in queue.json()["items"] if item["id"] == created["id"]
    )
    assert item["client_confirmed"] is True

    db.expire_all()
    row = db.get(Appointment, created["id"])
    assert row.client_confirmed_at is not None


def test_confirmation_rejected_once_cancelled_or_started(
    client, db, mateo, corte_clasico
):
    created = _book(client, db, mateo, corte_clasico)

    cancelled = client.post(
        f"/api/appointments/{created['public_code']}/cancel",
        json={"phone": "+54 9 11 5555 0101"},
    )
    assert cancelled.status_code == 200

    response = client.post(f"/api/appointments/{created['public_code']}/confirm")
    assert response.status_code == 409
    assert "no admite confirmación" in response.json()["detail"]

    started = _book(client, db, mateo, corte_clasico)
    appointment = db.scalar(
        select(Appointment).where(Appointment.public_code == started["public_code"])
    )
    with pytest.raises(ConflictError):
        confirm_customer_attendance(
            db,
            started["public_code"],
            now=appointment.start_at + timedelta(minutes=1),
        )


def test_reschedule_resets_attendance_confirmation(
    admin_client, db, mateo, corte_clasico
):
    _, slots = find_day_with_slots(db, mateo, corte_clasico, minimum=2)
    created = admin_client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=slots[0],
        ),
    ).json()

    confirmed = admin_client.post(
        f"/api/appointments/{created['public_code']}/confirm"
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["client_confirmed_at"] is not None

    moved = admin_client.post(
        f"/api/admin/appointments/{created['id']}/reschedule",
        json={"barber_id": mateo.id, "start_at": slots[1].isoformat()},
    )
    assert moved.status_code == 200
    assert moved.json()["appointment"]["client_confirmed_at"] is None

    db.expire_all()
    row = db.get(Appointment, created["id"])
    assert row.client_confirmed_at is None


def test_reminder_text_requests_confirmation_with_link(
    client, db, mateo, corte_clasico
):
    created = _book(client, db, mateo, corte_clasico)
    appointment = db.scalar(
        select(Appointment).where(Appointment.public_code == created["public_code"])
    )

    text = build_reminder_text(appointment, 90)
    assert f"/reserva/{appointment.public_code}" in text
    assert "Confirmá tu asistencia" in text

    confirm_customer_attendance(db, created["public_code"])
    db.expire_all()
    appointment = db.scalar(
        select(Appointment).where(Appointment.public_code == created["public_code"])
    )
    text = build_reminder_text(appointment, 60)
    assert "Asistencia confirmada" in text
    assert "Confirmá tu asistencia" not in text


def test_final_notice_urges_confirmation_when_unconfirmed(
    client, db, mateo, corte_clasico
):
    created = _book(client, db, mateo, corte_clasico)
    appointment = db.scalar(
        select(Appointment).where(Appointment.public_code == created["public_code"])
    )

    text = build_reminder_text(appointment, FINAL_NOTICE_OFFSET)
    assert "podría quedar liberado" in text
    assert f"/reserva/{appointment.public_code}" in text

    sent = asyncio.run(
        process_due_reminders(now=appointment.start_at - timedelta(minutes=30))
    )
    assert sent == 3

    db.expire_all()
    reminders = {
        item.offset_minutes: item
        for item in db.scalars(
            select(AppointmentReminder).where(
                AppointmentReminder.appointment_id == appointment.id
            )
        )
    }
    assert all(item.status == "sent" for item in reminders.values())


def test_final_notice_skipped_once_customer_confirms(
    client, db, mateo, corte_clasico
):
    created = _book(client, db, mateo, corte_clasico)
    appointment = db.scalar(
        select(Appointment).where(Appointment.public_code == created["public_code"])
    )

    confirm_customer_attendance(db, created["public_code"])

    sent = asyncio.run(
        process_due_reminders(now=appointment.start_at - timedelta(minutes=30))
    )
    assert sent == 3

    db.expire_all()
    reminders = {
        item.offset_minutes: item
        for item in db.scalars(
            select(AppointmentReminder).where(
                AppointmentReminder.appointment_id == appointment.id
            )
        )
    }
    assert reminders[FINAL_NOTICE_OFFSET].status == "skipped"
    assert reminders[90].status == "sent"
    assert reminders[60].status == "sent"


def test_queue_marks_unconfirmed_turnos_due_soon(client, db, mateo, corte_clasico):
    day, slots = find_day_with_slots(db, mateo, corte_clasico)
    created = _book(client, db, mateo, corte_clasico)

    entries = build_queue(
        db,
        mateo,
        day,
        now=slots[0] - timedelta(minutes=30),
        confirmation_deadline_minutes=45,
    )
    entry = next(item for item in entries if item.appointment.id == created["id"])
    assert entry.confirmation_due_soon is True

    entries = build_queue(
        db,
        mateo,
        day,
        now=slots[0] - timedelta(hours=2),
        confirmation_deadline_minutes=45,
    )
    entry = next(item for item in entries if item.appointment.id == created["id"])
    assert entry.confirmation_due_soon is False

    confirm_customer_attendance(db, created["public_code"])
    entries = build_queue(
        db,
        mateo,
        day,
        now=slots[0] - timedelta(minutes=30),
        confirmation_deadline_minutes=45,
    )
    entry = next(item for item in entries if item.appointment.id == created["id"])
    assert entry.confirmation_due_soon is False
