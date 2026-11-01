from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import Appointment, Barber, Client
from helpers import (
    booking_payload,
    find_day_with_slots,
    find_shared_day,
    parse_dt,
)


def test_admin_pages_and_api_require_login(client, mateo):
    page = client.get("/admin", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "/admin/login"

    api = client.get(
        "/api/admin/queue",
        params={"barber_id": mateo.id, "date": "2026-10-27"},
    )
    assert api.status_code == 401
    assert "Sesión administrativa" in api.json()["detail"]

    reassign = client.post(
        "/api/admin/appointments/1/reschedule",
        json={
            "barber_id": mateo.id,
            "start_at": "2026-10-27T13:00:00+00:00",
        },
    )
    assert reassign.status_code == 401
    assert "Sesión administrativa" in reassign.json()["detail"]

    bad_login = client.post(
        "/admin/login",
        data={"username": "admin", "password": "incorrecta"},
        follow_redirects=False,
    )
    assert bad_login.status_code == 401
    assert "incorrectos" in bad_login.text


def test_admin_login_and_queue(admin_client, db, mateo, corte_clasico):
    day, slots = find_day_with_slots(db, mateo, corte_clasico, minimum=2)
    for slot in (slots[0], slots[-1]):
        response = admin_client.post(
            "/api/appointments",
            json=booking_payload(
                barber=mateo,
                service=corte_clasico,
                start_at=slot,
                payment_option="later",
            ),
        )
        assert response.status_code == 201

    dashboard = admin_client.get("/admin/agenda")
    assert dashboard.status_code == 200
    assert "Turnos del día" in dashboard.text
    assert "Mateo Ríos" in dashboard.text

    queue = admin_client.get(
        "/api/admin/queue",
        params={"barber_id": mateo.id, "date": day.isoformat()},
    )
    assert queue.status_code == 200
    body = queue.json()
    assert body["barber"]["id"] == mateo.id
    assert len(body["items"]) == 2
    starts = [parse_dt(item["scheduled_start_at"]) for item in body["items"]]
    assert starts == sorted(starts)
    assert all(item["status"] == "confirmed" for item in body["items"])
    assert all(item["balance_cents"] == corte_clasico.price_cents for item in body["items"])


def test_cancel_then_advance_uses_freed_slot(admin_client, db, mateo, corte_clasico):
    day, slots = find_day_with_slots(db, mateo, corte_clasico, minimum=2)
    earliest, latest = slots[0], slots[-1]

    first = admin_client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=earliest,
            first_name="Ana",
            last_name="Primera",
            phone="+54 9 11 5555 0404",
        ),
    ).json()
    second = admin_client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=latest,
            first_name="Bruno",
            last_name="Segundo",
            phone="+54 9 11 5555 0505",
        ),
    ).json()

    cancelled = admin_client.patch(
        f"/api/admin/appointments/{first['id']}/status",
        json={"status": "cancelled", "reason": "Liberado por el cliente."},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    advanced = admin_client.post(f"/api/admin/appointments/{second['id']}/advance")
    assert advanced.status_code == 200
    body = advanced.json()
    assert parse_dt(body["previous_start_at"]) == latest
    assert parse_dt(body["appointment"]["start_at"]) == earliest

    db.expire_all()
    row = db.get(Appointment, second["id"])
    assert row.start_at == earliest
    assert row.end_at == earliest + timedelta(minutes=corte_clasico.duration_minutes)

    no_gap = admin_client.post(f"/api/admin/appointments/{second['id']}/advance")
    assert no_gap.status_code == 409
    assert "hueco anterior" in no_gap.json()["detail"]


def test_manual_payment_completion_and_client_history(
    admin_client, db, mateo, corte_clasico
):
    _, slots = find_day_with_slots(db, mateo, corte_clasico)
    created = admin_client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=slots[0],
            first_name="Mateo",
            last_name="Gómez",
            phone="+54 9 11 5555 0202",
        ),
    ).json()
    appointment_id = created["id"]
    balance = created["balance_cents"]

    overpay = admin_client.post(
        f"/api/admin/appointments/{appointment_id}/payments",
        json={
            "amount_cents": balance + 1,
            "method": "cash",
            "kind": "balance",
        },
    )
    assert overpay.status_code == 400
    assert "supera el saldo" in overpay.json()["detail"]

    invalid_status = admin_client.patch(
        f"/api/admin/appointments/{appointment_id}/status",
        json={"status": "completed"},
    )
    assert invalid_status.status_code == 409

    payment = admin_client.post(
        f"/api/admin/appointments/{appointment_id}/payments",
        json={
            "amount_cents": balance,
            "method": "card",
            "kind": "balance",
        },
    )
    assert payment.status_code == 200
    paid = payment.json()
    assert paid["paid_cents"] == corte_clasico.price_cents
    assert paid["balance_cents"] == 0

    started = admin_client.patch(
        f"/api/admin/appointments/{appointment_id}/status",
        json={"status": "in_progress"},
    )
    assert started.status_code == 200
    assert started.json()["actual_start_at"] is not None

    completed = admin_client.patch(
        f"/api/admin/appointments/{appointment_id}/status",
        json={"status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["actual_end_at"] is not None

    db.expire_all()
    client_row = db.scalar(
        select(Client).where(Client.phone == "+5491155550202")
    )
    assert client_row is not None

    history = admin_client.get(f"/admin/clientes/{client_row.id}")
    assert history.status_code == 200
    assert "Mateo Gómez" in history.text
    assert "Corte clásico" in history.text
    assert "completado" in history.text.lower()
    assert "Pago online (demo)" in history.text
    assert "Tarjeta" in history.text
    assert "$ 12.000" in history.text

    ticket = admin_client.get(f"/reserva/{created['public_code']}")
    assert ticket.status_code == 200
    assert "Servicio" in ticket.text
    assert "<em>completado</em>" in ticket.text
    assert "¿Necesitás cancelar?" not in ticket.text


def test_reschedule_to_another_barber_keeps_payments(
    admin_client, db, mateo, corte_clasico
):
    thiago = db.scalar(select(Barber).where(Barber.slug == "thiago-benitez"))
    assert thiago is not None
    day, (mateo_slots, thiago_slots) = find_shared_day(
        db, [mateo, thiago], corte_clasico, minimum=2
    )
    origin, target = mateo_slots[0], thiago_slots[0]

    created = admin_client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=origin,
            payment_option="deposit",
        ),
    ).json()

    slots = admin_client.get(
        f"/api/admin/appointments/{created['id']}/slots",
        params={"barber_id": thiago.id, "date": day.isoformat()},
    )
    assert slots.status_code == 200
    offered = [parse_dt(slot["start_at"]) for slot in slots.json()["slots"]]
    assert target in offered

    response = admin_client.post(
        f"/api/admin/appointments/{created['id']}/reschedule",
        json={"barber_id": thiago.id, "start_at": target.isoformat()},
    )
    assert response.status_code == 200
    body = response.json()
    assert parse_dt(body["previous_start_at"]) == origin
    assert body["previous_barber"]["id"] == mateo.id

    appointment = body["appointment"]
    assert appointment["barber"]["id"] == thiago.id
    assert parse_dt(appointment["start_at"]) == target
    assert parse_dt(appointment["end_at"]) == target + timedelta(
        minutes=corte_clasico.duration_minutes
    )
    assert appointment["price_cents"] == corte_clasico.price_cents
    assert appointment["paid_cents"] == corte_clasico.deposit_cents
    assert appointment["balance_cents"] == (
        corte_clasico.price_cents - corte_clasico.deposit_cents
    )

    db.expire_all()
    row = db.get(Appointment, created["id"])
    assert row.barber_id == thiago.id
    assert row.start_at == target
    assert row.end_at == target + timedelta(minutes=corte_clasico.duration_minutes)

    availability = admin_client.get(
        "/api/availability",
        params={
            "barber_id": mateo.id,
            "service_id": corte_clasico.id,
            "date": day.isoformat(),
        },
    )
    reopened = [
        parse_dt(slot["start_at"]) for slot in availability.json()["slots"]
    ]
    assert origin in reopened

    source_queue = admin_client.get(
        "/api/admin/queue",
        params={"barber_id": mateo.id, "date": day.isoformat()},
    )
    assert all(
        item["id"] != created["id"] for item in source_queue.json()["items"]
    )

    target_queue = admin_client.get(
        "/api/admin/queue",
        params={"barber_id": thiago.id, "date": day.isoformat()},
    )
    assert any(
        item["id"] == created["id"] for item in target_queue.json()["items"]
    )


def test_reschedule_rejects_busy_slot_and_non_confirmed(
    admin_client, db, mateo, corte_clasico
):
    thiago = db.scalar(select(Barber).where(Barber.slug == "thiago-benitez"))
    assert thiago is not None
    day, (mateo_slots, thiago_slots) = find_shared_day(
        db, [mateo, thiago], corte_clasico, minimum=2
    )

    created = admin_client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=mateo_slots[0],
        ),
    ).json()

    occupied = thiago_slots[0]
    busy_booking = admin_client.post(
        "/api/appointments",
        json=booking_payload(
            barber=thiago,
            service=corte_clasico,
            start_at=occupied,
            first_name="Otro",
            last_name="Cliente",
            phone="+54 9 11 5555 0606",
        ),
    )
    assert busy_booking.status_code == 201

    conflict = admin_client.post(
        f"/api/admin/appointments/{created['id']}/reschedule",
        json={"barber_id": thiago.id, "start_at": occupied.isoformat()},
    )
    assert conflict.status_code == 409
    assert "ya no está disponible" in conflict.json()["detail"]

    started = admin_client.patch(
        f"/api/admin/appointments/{created['id']}/status",
        json={"status": "in_progress"},
    )
    assert started.status_code == 200

    blocked = admin_client.post(
        f"/api/admin/appointments/{created['id']}/reschedule",
        json={"barber_id": thiago.id, "start_at": thiago_slots[1].isoformat()},
    )
    assert blocked.status_code == 409
    assert "confirmados" in blocked.json()["detail"]


def test_cannot_charge_cancelled_appointment(admin_client, db, mateo, corte_clasico):
    _, slots = find_day_with_slots(db, mateo, corte_clasico)
    created = admin_client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=slots[0],
            payment_option="later",
        ),
    ).json()

    cancelled = admin_client.patch(
        f"/api/admin/appointments/{created['id']}/status",
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200

    payment = admin_client.post(
        f"/api/admin/appointments/{created['id']}/payments",
        json={
            "amount_cents": 1000,
            "method": "cash",
            "kind": "balance",
        },
    )
    assert payment.status_code == 409
    assert "cancelado" in payment.json()["detail"]
