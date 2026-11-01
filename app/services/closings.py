from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    DailyClosing,
    PaymentStatus,
)
from app.timeutils import (
    day_bounds_utc,
    ensure_utc,
    local_to_utc,
    to_business,
    utc_now,
)

logger = logging.getLogger("barberia.closings")


def _cutoff_time() -> time:
    settings = get_settings()
    return time(
        min(max(settings.daily_close_hour, 0), 23),
        min(max(settings.daily_close_minute, 0), 59),
    )


def latest_closable_day(*, now: datetime | None = None) -> date:
    local = to_business(ensure_utc(now or utc_now()))
    if local.time() >= _cutoff_time():
        return local.date()
    return local.date() - timedelta(days=1)


def close_day(
    db: Session,
    day: date,
    *,
    now: datetime | None = None,
) -> list[DailyClosing]:
    start_at, end_at = day_bounds_utc(day)
    appointments = list(
        db.scalars(
            select(Appointment).where(
                Appointment.start_at >= start_at,
                Appointment.start_at < end_at,
            )
        ).all()
    )

    by_barber: dict[int, list[Appointment]] = defaultdict(list)
    for appointment in appointments:
        by_barber[appointment.barber_id].append(appointment)

    existing = {
        row.barber_id: row
        for row in db.scalars(
            select(DailyClosing).where(DailyClosing.business_date == day)
        ).all()
    }

    barbers: dict[int, Barber] = {
        barber.id: barber
        for barber in db.scalars(
            select(Barber).where(Barber.deleted_at.is_(None))
        ).all()
    }
    for barber_id in set(by_barber) | set(existing):
        if barber_id not in barbers:
            barber = db.get(Barber, barber_id)
            if barber is not None:
                barbers[barber_id] = barber

    closed_at = ensure_utc(now or utc_now())
    rows: list[DailyClosing] = []

    for barber in sorted(barbers.values(), key=lambda item: item.name):
        day_appointments = by_barber.get(barber.id, [])
        completed = [
            appointment
            for appointment in day_appointments
            if appointment.status == AppointmentStatus.completed
        ]
        service_revenue = sum(appointment.price_cents for appointment in completed)
        collected = sum(
            payment.amount_cents
            for appointment in day_appointments
            for payment in appointment.payments
            if payment.status == PaymentStatus.paid
        )
        completed_collected = sum(
            payment.amount_cents
            for appointment in completed
            for payment in appointment.payments
            if payment.status == PaymentStatus.paid
        )

        row = existing.get(barber.id)
        if row is None:
            row = DailyClosing(
                barber_id=barber.id,
                business_date=day,
                barber_name=barber.name,
            )
            db.add(row)
            existing[barber.id] = row

        row.closed_at = closed_at
        row.barber_name = barber.name
        row.appointments_count = len(day_appointments)
        row.completed_count = len(completed)
        row.cancelled_count = sum(
            1
            for appointment in day_appointments
            if appointment.status == AppointmentStatus.cancelled
        )
        row.no_show_count = sum(
            1
            for appointment in day_appointments
            if appointment.status == AppointmentStatus.no_show
        )
        row.service_revenue_cents = service_revenue
        row.collected_cents = collected
        row.pending_cents = max(0, service_revenue - completed_collected)
        rows.append(row)

    db.commit()
    return rows


def ensure_latest_day_closed(
    db: Session,
    *,
    now: datetime | None = None,
) -> date | None:
    day = latest_closable_day(now=now)
    cutoff_at = local_to_utc(day, _cutoff_time())
    closed_at = db.scalars(
        select(DailyClosing.closed_at).where(
            DailyClosing.business_date == day
        )
    ).all()
    if closed_at and max(closed_at) >= cutoff_at:
        return None

    rows = close_day(db, day, now=now)
    if not rows:
        return None
    logger.info("Cierre diario guardado para el %s (%s barberos).", day, len(rows))
    return day


async def closing_worker(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(10, settings.closing_worker_interval_seconds)
    logger.info(
        "Cierres automáticos activos a las %02d:%02d (%s).",
        settings.daily_close_hour,
        settings.daily_close_minute,
        settings.business_timezone,
    )

    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                ensure_latest_day_closed(db)
        except Exception:
            logger.exception("Error al guardar el cierre diario")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            continue
