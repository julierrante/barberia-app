from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select

import app.services.barbers as barbers_service
from app.models import (
    Appointment,
    AppointmentReminder,
    AppointmentStatus,
    PortfolioItem,
    ReminderStatus,
)
from app.services.reminders import process_due_reminders
from helpers import booking_payload, find_day_with_slots, parse_dt


def test_availability_calendar_marks_available_and_occupied(
    client, db, mateo, corte_clasico
):
    day, slots = find_day_with_slots(db, mateo, corte_clasico)
    booked = slots[0]

    response = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo, service=corte_clasico, start_at=booked
        ),
    )
    assert response.status_code == 201

    availability = client.get(
        "/api/availability",
        params={
            "barber_id": mateo.id,
            "service_id": corte_clasico.id,
            "date": day.isoformat(),
        },
    )
    assert availability.status_code == 200
    data = availability.json()

    calendar = {parse_dt(item["start_at"]): item["status"] for item in data["calendar"]}
    assert calendar[booked] == "occupied"
    assert any(status == "available" for status in calendar.values())

    available = {parse_dt(item["start_at"]) for item in data["slots"]}
    assert booked not in available
    assert all(
        parse_dt(item["start_at"]) in available
        for item in data["calendar"]
        if item["status"] == "available"
    )


def test_client_can_rate_completed_appointment_once(
    client, db, mateo, corte_clasico
):
    _, slots = find_day_with_slots(db, mateo, corte_clasico)
    created = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo, service=corte_clasico, start_at=slots[0]
        ),
    ).json()
    code = created["public_code"]

    early = client.post(f"/api/appointments/{code}/rating", json={"score": 5})
    assert early.status_code == 409

    db.expire_all()
    appointment = db.scalar(
        select(Appointment).where(Appointment.public_code == code)
    )
    appointment.status = AppointmentStatus.completed
    db.commit()

    rated = client.post(
        f"/api/appointments/{code}/rating",
        json={"score": 5, "comment": "Excelente corte."},
    )
    assert rated.status_code == 201
    assert rated.json()["score"] == 5
    assert rated.json()["comment"] == "Excelente corte."

    duplicate = client.post(
        f"/api/appointments/{code}/rating", json={"score": 3}
    )
    assert duplicate.status_code == 409

    ticket = client.get(f"/reserva/{code}")
    assert ticket.status_code == 200
    assert "★★★★★" in ticket.text
    assert "Excelente corte." in ticket.text
    assert 'id="rating-form" hidden' in ticket.text

    profile = client.get("/api/barbers")
    assert profile.status_code == 200
    mateo_out = next(item for item in profile.json() if item["id"] == mateo.id)
    assert mateo_out["rating_average"] == 5.0
    assert mateo_out["rating_count"] == 1


def test_ticket_shows_mercado_pago_alias_for_tips(
    client, db, mateo, corte_clasico
):
    mateo.mp_alias = "mateo.rios.mp"
    db.commit()

    _, slots = find_day_with_slots(db, mateo, corte_clasico)
    created = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo, service=corte_clasico, start_at=slots[0]
        ),
    ).json()

    ticket = client.get(f"/reserva/{created['public_code']}")
    assert ticket.status_code == 200
    assert "mateo.rios.mp" in ticket.text
    assert "Copiar alias" in ticket.text
    assert "Propina" in ticket.text


def test_works_page_and_public_links_use_gallery(
    client, db, mateo, corte_clasico
):
    mateo.portfolio_items = [
        PortfolioItem(
            image_url="/static/media/portfolio/foto.jpg",
            media_type="image",
            caption="Fade clásico",
            sort_order=1,
        ),
        PortfolioItem(
            image_url="/static/media/portfolio/video.mp4",
            media_type="video",
            caption="Diseño a máquina",
            sort_order=2,
        ),
    ]
    db.commit()

    works = client.get(f"/barberos/{mateo.slug}/trabajos")
    assert works.status_code == 200
    assert "Fade clásico" in works.text
    assert "Diseño a máquina" in works.text
    assert "<video" in works.text
    assert "Trabajos realizados" in works.text

    team = client.get("/barberos")
    assert team.status_code == 200
    assert "Ver trabajos realizados de Mateo Ríos" in team.text


def test_barber_can_upload_and_remove_portfolio_media(
    client, db, mateo, corte_clasico, tmp_path, monkeypatch
):
    monkeypatch.setattr(barbers_service, "PORTFOLIO_DIR", tmp_path)
    monkeypatch.setattr(
        barbers_service, "PORTFOLIO_URL_PREFIX", "/static/media/portfolio/"
    )

    from app.database import SessionLocal

    login = client.post(
        "/admin/login",
        data={"username": "admin", "password": "test-password"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    tiny_png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
        b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    uploaded = client.post(
        f"/admin/barberos/{mateo.id}/trabajos",
        data={"caption": "Trabajo nuevo"},
        files={"media": ("corte.png", tiny_png, "image/png")},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303

    with SessionLocal() as fresh:
        item = fresh.scalar(
            select(PortfolioItem).where(
                PortfolioItem.barber_id == mateo.id,
                PortfolioItem.caption == "Trabajo nuevo",
            )
        )
        assert item is not None
        assert item.media_type == "image"
        stored_files = list(tmp_path.iterdir())
        assert len(stored_files) == 1
        assert stored_files[0].read_bytes() == tiny_png
        item_id = item.id

        removed = client.post(
            f"/admin/barberos/{mateo.id}/trabajos/{item_id}/eliminar",
            follow_redirects=False,
        )
        assert removed.status_code == 303
        fresh.expire_all()
        assert (
            fresh.scalar(
                select(PortfolioItem.id).where(PortfolioItem.id == item_id)
            )
            is None
        )

    assert list(tmp_path.iterdir()) == []


def test_booking_schedules_two_whatsapp_reminders_and_cancels_them(
    client, db, mateo, corte_clasico
):
    _, slots = find_day_with_slots(db, mateo, corte_clasico)
    created = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo, service=corte_clasico, start_at=slots[0]
        ),
    ).json()

    db.expire_all()
    appointment = db.scalar(
        select(Appointment).where(Appointment.public_code == created["public_code"])
    )
    reminders = sorted(appointment.reminders, key=lambda item: item.offset_minutes)
    assert [item.offset_minutes for item in reminders] == [45, 60, 90]
    assert all(item.status == ReminderStatus.pending for item in reminders)
    by_offset = {item.offset_minutes: item for item in reminders}
    assert by_offset[45].scheduled_at == appointment.start_at - timedelta(minutes=45)
    assert by_offset[60].scheduled_at == appointment.start_at - timedelta(minutes=60)
    assert by_offset[90].scheduled_at == appointment.start_at - timedelta(minutes=90)

    cancelled = client.post(
        f"/api/appointments/{created['public_code']}/cancel",
        json={"phone": "+54 9 11 5555 0101"},
    )
    assert cancelled.status_code == 200

    db.expire_all()
    appointment = db.scalar(
        select(Appointment).where(Appointment.public_code == created["public_code"])
    )
    assert all(
        item.status == ReminderStatus.cancelled for item in appointment.reminders
    )


def test_reminder_worker_sends_due_mock_messages(
    client, db, mateo, corte_clasico
):
    _, slots = find_day_with_slots(db, mateo, corte_clasico)
    created = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo, service=corte_clasico, start_at=slots[0]
        ),
    ).json()

    appointment = db.scalar(
        select(Appointment).where(Appointment.public_code == created["public_code"])
    )
    sent = asyncio.run(
        process_due_reminders(now=appointment.start_at + timedelta(minutes=1))
    )
    assert sent == 3

    db.expire_all()
    reminders = db.scalars(
        select(AppointmentReminder).where(
            AppointmentReminder.appointment_id == appointment.id
        )
    ).all()
    assert all(item.status == ReminderStatus.sent for item in reminders)
    assert all(item.provider == "mock" for item in reminders)
    assert all(item.sent_at is not None for item in reminders)
