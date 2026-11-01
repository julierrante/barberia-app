from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    ACTIVE_APPOINTMENT_STATUSES,
    Appointment,
    AppointmentStatus,
    Barber,
)
from app.services.errors import BusinessError, ConflictError
from app.timeutils import (
    UTC,
    business_today,
    day_bounds_utc,
    ensure_utc,
    to_business,
    utc_now,
)


@dataclass
class QueueEntry:
    appointment: Appointment
    eta_start_at: datetime | None
    eta_end_at: datetime | None
    delay_minutes: int
    confirmation_due_soon: bool = False


def validate_booking_day(day: date) -> None:
    today = business_today()
    if day < today:
        raise BusinessError("No se pueden reservar fechas pasadas.")
    if (day - today).days > get_settings().booking_days_ahead:
        raise BusinessError(
            f"La agenda web permite reservar hasta {get_settings().booking_days_ahead} días adelante."
        )


def get_day_appointments(
    db: Session,
    barber_id: int,
    day: date,
    *,
    statuses: tuple[AppointmentStatus, ...] | None = None,
    ignore_appointment_id: int | None = None,
) -> list[Appointment]:
    day_start, day_end = day_bounds_utc(day)
    stmt = select(Appointment).where(
        Appointment.barber_id == barber_id,
        Appointment.start_at < day_end,
        Appointment.end_at > day_start,
    )
    if statuses is not None:
        stmt = stmt.where(Appointment.status.in_(statuses))
    if ignore_appointment_id is not None:
        stmt = stmt.where(Appointment.id != ignore_appointment_id)
    return list(db.scalars(stmt.order_by(Appointment.start_at, Appointment.id)).all())


def _candidate_starts(barber: Barber, duration_minutes: int, day: date) -> list[datetime]:
    tz = to_business(utc_now()).tzinfo
    step = timedelta(minutes=get_settings().slot_granularity_minutes)
    duration = timedelta(minutes=duration_minutes)
    starts: set[datetime] = set()

    for block in barber.schedules:
        if block.weekday != day.weekday():
            continue
        cursor = datetime.combine(day, block.start_time, tzinfo=tz)
        block_end = datetime.combine(day, block.end_time, tzinfo=tz)
        while cursor + duration <= block_end:
            starts.add(cursor.astimezone(UTC))
            cursor += step

    return sorted(starts)


def available_slots(
    db: Session,
    barber: Barber,
    duration_minutes: int,
    day: date,
    *,
    now: datetime | None = None,
    ignore_appointment_id: int | None = None,
    enforce_notice: bool = True,
) -> list[datetime]:
    settings = get_settings()
    now = ensure_utc(now or utc_now())
    earliest = now
    if enforce_notice:
        earliest = now + timedelta(minutes=settings.min_notice_minutes)
    duration = timedelta(minutes=duration_minutes)

    busy = get_day_appointments(
        db,
        barber.id,
        day,
        statuses=ACTIVE_APPOINTMENT_STATUSES,
        ignore_appointment_id=ignore_appointment_id,
    )

    tz = to_business(now).tzinfo
    earliest_local = earliest.astimezone(tz)
    slots: list[datetime] = []

    for candidate_start in _candidate_starts(barber, duration_minutes, day):
        candidate_end = candidate_start + duration
        if candidate_start.astimezone(tz) < earliest_local:
            continue
        if any(
            appointment.start_at < candidate_end
            and appointment.end_at > candidate_start
            for appointment in busy
        ):
            continue
        slots.append(candidate_start)

    return slots


def calendar_slots(
    db: Session,
    barber: Barber,
    duration_minutes: int,
    day: date,
    *,
    now: datetime | None = None,
    ignore_appointment_id: int | None = None,
    enforce_notice: bool = True,
) -> list[tuple[datetime, str]]:
    now = ensure_utc(now or utc_now())
    earliest = now
    if enforce_notice:
        earliest = now + timedelta(minutes=get_settings().min_notice_minutes)
    duration = timedelta(minutes=duration_minutes)

    busy = get_day_appointments(
        db,
        barber.id,
        day,
        statuses=ACTIVE_APPOINTMENT_STATUSES,
        ignore_appointment_id=ignore_appointment_id,
    )

    tz = to_business(now).tzinfo
    earliest_local = earliest.astimezone(tz)
    calendar: list[tuple[datetime, str]] = []

    for candidate_start in _candidate_starts(barber, duration_minutes, day):
        candidate_end = candidate_start + duration
        if candidate_start.astimezone(tz) < earliest_local:
            status = "past"
        elif any(
            appointment.start_at < candidate_end
            and appointment.end_at > candidate_start
            for appointment in busy
        ):
            status = "occupied"
        else:
            status = "available"
        calendar.append((candidate_start, status))

    return calendar


def slot_label(value: datetime) -> str:
    return to_business(value).strftime("%H:%M")


def build_queue(
    db: Session,
    barber: Barber,
    day: date,
    *,
    now: datetime | None = None,
    confirmation_deadline_minutes: int | None = None,
) -> list[QueueEntry]:
    now = ensure_utc(now or utc_now())
    deadline = (
        timedelta(minutes=confirmation_deadline_minutes)
        if confirmation_deadline_minutes is not None
        else None
    )
    appointments = get_day_appointments(db, barber.id, day)
    projected_free_at = now
    entries: list[QueueEntry] = []

    for appointment in appointments:
        duration = timedelta(minutes=appointment.duration_minutes)
        eta_start: datetime | None = None
        eta_end: datetime | None = None
        delay = 0

        if appointment.status == AppointmentStatus.completed:
            eta_start = appointment.actual_start_at or appointment.start_at
            eta_end = appointment.actual_end_at or appointment.end_at
            projected_free_at = max(projected_free_at, eta_end)
            delay = max(0, int((eta_start - appointment.start_at).total_seconds() // 60))
        elif appointment.status == AppointmentStatus.in_progress:
            eta_start = appointment.actual_start_at or now
            eta_end = eta_start + duration
            projected_free_at = max(now, eta_end)
            delay = max(0, int((eta_start - appointment.start_at).total_seconds() // 60))
        elif appointment.status == AppointmentStatus.confirmed:
            eta_start = max(appointment.start_at, projected_free_at)
            eta_end = eta_start + duration
            projected_free_at = eta_end
            delay = max(0, int((eta_start - appointment.start_at).total_seconds() // 60))

        due_soon = (
            deadline is not None
            and appointment.status == AppointmentStatus.confirmed
            and appointment.client_confirmed_at is None
            and appointment.start_at - now <= deadline
        )

        entries.append(
            QueueEntry(
                appointment=appointment,
                eta_start_at=eta_start,
                eta_end_at=eta_end,
                delay_minutes=delay,
                confirmation_due_soon=due_soon,
            )
        )

    return entries


def earliest_advance_slot(
    db: Session,
    appointment: Appointment,
    *,
    now: datetime | None = None,
) -> datetime:
    if appointment.status != AppointmentStatus.confirmed:
        raise ConflictError("Solo se pueden adelantar turnos confirmados.")

    now = ensure_utc(now or utc_now())
    day = to_business(appointment.start_at).date()
    slots = available_slots(
        db,
        appointment.barber,
        appointment.duration_minutes,
        day,
        now=now,
        ignore_appointment_id=appointment.id,
        enforce_notice=False,
    )
    earlier = [slot for slot in slots if slot < appointment.start_at]
    if not earlier:
        raise ConflictError(
            "No hay un hueco anterior disponible para este barbero. "
            "Probá reasignar el turno o esperar una nueva cancelación."
        )
    return earlier[0]
