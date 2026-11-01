from __future__ import annotations

from datetime import time, timedelta

from app.database import SessionLocal
from app.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    Client,
    Service,
)
from app.schemas import RescheduleIn
from app.services.booking import reschedule_appointment
from app.services.scheduling import (
    available_slots,
    build_queue,
    earliest_advance_slot,
)
from app.timeutils import local_to_utc
from helpers import booking_payload, find_day_with_slots


def test_available_slots_exclude_booked_overlap(client, db, mateo, corte_clasico):
    day, slots = find_day_with_slots(db, mateo, corte_clasico)
    start_at = slots[0]

    created = client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo, service=corte_clasico, start_at=start_at
        ),
    )
    assert created.status_code == 201

    with SessionLocal() as fresh:
        fresh_barber = fresh.get(Barber, mateo.id)
        fresh_service = fresh.get(Service, corte_clasico.id)
        remaining = available_slots(
            fresh, fresh_barber, fresh_service.duration_minutes, day
        )

    assert start_at not in remaining
    assert start_at + timedelta(minutes=15) not in remaining
    assert start_at + timedelta(minutes=30) in remaining


def test_minimum_notice_filters_early_slots(db, mateo, corte_clasico):
    day, slots = find_day_with_slots(db, mateo, corte_clasico)
    start_at = slots[0]

    included = available_slots(
        db,
        mateo,
        corte_clasico.duration_minutes,
        day,
        now=start_at - timedelta(minutes=31),
    )
    excluded = available_slots(
        db,
        mateo,
        corte_clasico.duration_minutes,
        day,
        now=start_at - timedelta(minutes=29),
    )
    assert start_at in included
    assert start_at not in excluded


def test_earliest_advance_ignores_online_notice(db, mateo, corte_clasico):
    day, _ = find_day_with_slots(db, mateo, corte_clasico)
    person = Client(
        first_name="Cerca", last_name="Cancelación", phone="+5491100006666"
    )
    early_start = local_to_utc(day, time(10, 0))
    later_start = local_to_utc(day, time(11, 0))

    early = Appointment(
        client=person,
        barber=mateo,
        service=corte_clasico,
        status=AppointmentStatus.confirmed,
        start_at=early_start,
        end_at=early_start + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=corte_clasico.price_cents,
        deposit_cents=corte_clasico.deposit_cents,
    )
    later = Appointment(
        client=person,
        barber=mateo,
        service=corte_clasico,
        status=AppointmentStatus.confirmed,
        start_at=later_start,
        end_at=later_start + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=corte_clasico.price_cents,
        deposit_cents=corte_clasico.deposit_cents,
    )
    db.add_all([early, later])
    db.commit()

    early.status = AppointmentStatus.cancelled
    db.commit()

    now = local_to_utc(day, time(9, 50))
    assert earliest_advance_slot(db, later, now=now) == early_start


def test_reschedule_ignores_online_notice(db, mateo, corte_clasico):
    day, _ = find_day_with_slots(db, mateo, corte_clasico)
    person = Client(
        first_name="Mover", last_name="Cerca", phone="+5491100005555"
    )
    target = local_to_utc(day, time(10, 0))
    current = local_to_utc(day, time(12, 0))

    freed = Appointment(
        client=person,
        barber=mateo,
        service=corte_clasico,
        status=AppointmentStatus.confirmed,
        start_at=target,
        end_at=target + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=corte_clasico.price_cents,
        deposit_cents=corte_clasico.deposit_cents,
    )
    moving = Appointment(
        client=person,
        barber=mateo,
        service=corte_clasico,
        status=AppointmentStatus.confirmed,
        start_at=current,
        end_at=current + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=corte_clasico.price_cents,
        deposit_cents=corte_clasico.deposit_cents,
    )
    db.add_all([freed, moving])
    db.commit()

    freed.status = AppointmentStatus.cancelled
    db.commit()

    now = local_to_utc(day, time(9, 50))
    moved, previous_start, previous_barber = reschedule_appointment(
        db,
        moving.id,
        RescheduleIn(barber_id=mateo.id, start_at=target),
        now=now,
    )

    assert previous_start == current
    assert previous_barber.id == mateo.id
    assert moved.start_at == target
    assert moved.end_at == target + timedelta(minutes=corte_clasico.duration_minutes)


def test_queue_projects_delay_from_running_appointment(db, mateo, corte_clasico):
    day, _ = find_day_with_slots(db, mateo, corte_clasico)

    person = Client(
        first_name="Prueba",
        last_name="Demora",
        phone="+5491100009999",
        email="demora@example.com",
    )
    first_start = local_to_utc(day, time(10, 0))
    second_start = local_to_utc(day, time(10, 30))
    actual_start = local_to_utc(day, time(10, 30))
    now = local_to_utc(day, time(10, 35))

    first = Appointment(
        client=person,
        barber=mateo,
        service=corte_clasico,
        status=AppointmentStatus.in_progress,
        start_at=first_start,
        end_at=first_start + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=corte_clasico.price_cents,
        deposit_cents=corte_clasico.deposit_cents,
        actual_start_at=actual_start,
    )
    second = Appointment(
        client=person,
        barber=mateo,
        service=corte_clasico,
        status=AppointmentStatus.confirmed,
        start_at=second_start,
        end_at=second_start + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=corte_clasico.price_cents,
        deposit_cents=corte_clasico.deposit_cents,
    )
    db.add_all([first, second])
    db.commit()

    entries = build_queue(db, mateo, day, now=now)
    assert len(entries) == 2

    running, waiting = entries
    assert running.delay_minutes == 30
    assert running.eta_start_at == actual_start
    assert running.eta_end_at == actual_start + timedelta(minutes=30)

    assert waiting.delay_minutes == 30
    assert waiting.eta_start_at == actual_start + timedelta(minutes=30)
    assert waiting.eta_end_at == actual_start + timedelta(minutes=60)


def test_queue_keeps_schedule_when_on_time(db, mateo, corte_clasico):
    day, _ = find_day_with_slots(db, mateo, corte_clasico)

    person = Client(
        first_name="Puntual",
        last_name="Cliente",
        phone="+5491100008888",
    )
    start_at = local_to_utc(day, time(15, 0))
    appointment = Appointment(
        client=person,
        barber=mateo,
        service=corte_clasico,
        status=AppointmentStatus.confirmed,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=corte_clasico.price_cents,
        deposit_cents=corte_clasico.deposit_cents,
    )
    db.add(appointment)
    db.commit()

    entries = build_queue(
        db, mateo, day, now=local_to_utc(day, time(9, 0))
    )
    entry = entries[0]
    assert entry.delay_minutes == 0
    assert entry.eta_start_at == start_at
    assert entry.eta_end_at == start_at + timedelta(minutes=30)


def test_client_stats_use_completed_and_active_appointments(db, mateo, corte_clasico):
    from app.services.clients import calculate_stats

    day, _ = find_day_with_slots(db, mateo, corte_clasico)
    person = Client(first_name="Stats", last_name="Test", phone="+5491100007777")
    db.add(person)
    db.flush()

    completed = Appointment(
        client=person,
        barber=mateo,
        service=corte_clasico,
        status=AppointmentStatus.completed,
        start_at=local_to_utc(day, time(11, 0)),
        end_at=local_to_utc(day, time(11, 30)),
        duration_minutes=30,
        price_cents=corte_clasico.price_cents,
        deposit_cents=corte_clasico.deposit_cents,
        actual_start_at=local_to_utc(day, time(11, 5)),
        actual_end_at=local_to_utc(day, time(11, 35)),
    )
    confirmed = Appointment(
        client=person,
        barber=mateo,
        service=corte_clasico,
        status=AppointmentStatus.confirmed,
        start_at=local_to_utc(day, time(12, 0)),
        end_at=local_to_utc(day, time(12, 30)),
        duration_minutes=30,
        price_cents=corte_clasico.price_cents,
        deposit_cents=corte_clasico.deposit_cents,
    )
    db.add_all([completed, confirmed])
    db.commit()

    stats = calculate_stats(person)
    assert stats.visits_count == 1
    assert stats.last_visit_at == completed.actual_end_at
    assert stats.total_paid_cents == 0
    assert stats.pending_balance_cents == corte_clasico.price_cents * 2
