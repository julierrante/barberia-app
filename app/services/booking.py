from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    Client,
    Rating,
    Service,
)
from app.schemas import (
    BookingCreate,
    ClientCreate,
    ManualPaymentCreate,
    RatingCreate,
    RescheduleIn,
    StatusUpdate,
)
from app.services.errors import (
    BusinessError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.services.payments import add_manual_payment, add_online_payment
from app.services.reminders import (
    cancel_appointment_reminders,
    sync_appointment_reminders,
)
from app.services.scheduling import (
    available_slots,
    earliest_advance_slot,
    validate_booking_day,
)
from app.timeutils import UTC, ensure_utc, to_business, utc_now


def normalize_phone(value: str) -> str:
    stripped = value.strip()
    prefix = "+" if stripped.startswith("+") else ""
    return prefix + re.sub(r"\D", "", stripped)


def get_service(db: Session, service_id: int) -> Service:
    service = db.get(Service, service_id)
    if service is None or not service.active:
        raise NotFoundError("El servicio seleccionado no está disponible.")
    return service


def get_barber(db: Session, barber_id: int) -> Barber:
    barber = db.get(Barber, barber_id)
    if barber is None or not barber.active:
        raise NotFoundError("El barbero seleccionado no está disponible.")
    return barber


def get_appointment_by_code(db: Session, public_code: str) -> Appointment:
    appointment = db.scalar(
        select(Appointment).where(Appointment.public_code == public_code)
    )
    if appointment is None:
        raise NotFoundError("No encontramos ese turno.")
    return appointment


def get_appointment(db: Session, appointment_id: int) -> Appointment:
    appointment = db.get(Appointment, appointment_id)
    if appointment is None:
        raise NotFoundError("No encontramos ese turno.")
    return appointment


def upsert_client(db: Session, data: ClientCreate) -> Client:
    phone = normalize_phone(data.phone)
    client = db.scalar(select(Client).where(Client.phone == phone))
    email = str(data.email).lower() if data.email else None

    if client is not None:
        client.first_name = data.first_name
        client.last_name = data.last_name
        if email:
            client.email = email
        return client

    client = Client(
        first_name=data.first_name,
        last_name=data.last_name,
        phone=phone,
        email=email,
    )
    db.add(client)
    return client


def create_booking(
    db: Session,
    payload: BookingCreate,
    *,
    now: datetime | None = None,
) -> Appointment:
    now = ensure_utc(now or utc_now())
    service = get_service(db, payload.service_id)
    barber = get_barber(db, payload.barber_id)

    start_at = payload.start_at.astimezone(UTC).replace(microsecond=0)
    day = to_business(start_at).date()
    validate_booking_day(day)

    slots = available_slots(db, barber, service.duration_minutes, day, now=now)
    if start_at not in slots:
        raise ConflictError("Ese horario ya no está disponible. Elegí otro turno.")

    client = upsert_client(db, payload.client)
    appointment = Appointment(
        client=client,
        barber=barber,
        service=service,
        status=AppointmentStatus.confirmed,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=service.duration_minutes),
        duration_minutes=service.duration_minutes,
        price_cents=service.price_cents,
        deposit_cents=service.deposit_cents,
    )
    db.add(appointment)
    db.flush()

    add_online_payment(appointment, payload.payment_option, now=now)
    sync_appointment_reminders(db, appointment, now=now)
    db.commit()
    return appointment


def cancel_customer_booking(
    db: Session,
    public_code: str,
    phone: str,
) -> Appointment:
    appointment = get_appointment_by_code(db, public_code)
    if normalize_phone(phone) != normalize_phone(appointment.client.phone):
        raise ForbiddenError("El teléfono no coincide con el titular del turno.")
    if appointment.status == AppointmentStatus.cancelled:
        raise ConflictError("Este turno ya fue cancelado.")
    if appointment.status != AppointmentStatus.confirmed:
        raise ConflictError("Este turno ya no se puede cancelar online.")

    appointment.status = AppointmentStatus.cancelled
    appointment.cancel_reason = "Cancelado por el cliente desde la web."
    cancel_appointment_reminders(appointment)
    db.commit()
    return appointment


def confirm_customer_attendance(
    db: Session,
    public_code: str,
    *,
    now: datetime | None = None,
) -> Appointment:
    appointment = get_appointment_by_code(db, public_code)
    if appointment.client_confirmed_at is not None:
        return appointment
    now = ensure_utc(now or utc_now())
    if appointment.status != AppointmentStatus.confirmed:
        raise ConflictError("Este turno ya no admite confirmación de asistencia.")
    if appointment.start_at <= now:
        raise ConflictError("Este turno ya comenzó; no hace falta confirmarlo.")
    appointment.client_confirmed_at = now
    db.commit()
    return appointment


def rate_appointment(
    db: Session,
    public_code: str,
    payload: RatingCreate,
) -> Rating:
    appointment = get_appointment_by_code(db, public_code)
    if appointment.status != AppointmentStatus.completed:
        raise ConflictError("Podés calificar el turno una vez que esté completado.")
    if appointment.rating is not None:
        raise ConflictError("Ya calificaste este turno.")

    rating = Rating(
        appointment=appointment,
        barber_id=appointment.barber_id,
        client_id=appointment.client_id,
        score=payload.score,
        comment=payload.comment,
    )
    db.add(rating)
    db.commit()
    return rating


def change_status(
    db: Session,
    appointment_id: int,
    payload: StatusUpdate,
    *,
    now: datetime | None = None,
) -> Appointment:
    appointment = get_appointment(db, appointment_id)
    target = AppointmentStatus(payload.status)
    now = ensure_utc(now or utc_now())

    allowed = {
        AppointmentStatus.confirmed: {
            AppointmentStatus.in_progress,
            AppointmentStatus.cancelled,
            AppointmentStatus.no_show,
        },
        AppointmentStatus.in_progress: {AppointmentStatus.completed},
    }
    if target not in allowed.get(appointment.status, set()):
        raise ConflictError(
            f"No se puede pasar de '{appointment.status.value}' a '{target.value}'."
        )

    if target == AppointmentStatus.in_progress:
        appointment.actual_start_at = now
    elif target == AppointmentStatus.completed:
        appointment.actual_end_at = now
    elif target == AppointmentStatus.cancelled:
        appointment.cancel_reason = payload.reason or "Cancelado por el personal."
    elif target == AppointmentStatus.no_show:
        appointment.cancel_reason = payload.reason or "El cliente no se presentó."

    appointment.status = target
    if target in (
        AppointmentStatus.completed,
        AppointmentStatus.cancelled,
        AppointmentStatus.no_show,
    ):
        cancel_appointment_reminders(appointment)
    db.commit()
    return appointment


def advance_appointment(
    db: Session,
    appointment_id: int,
    *,
    now: datetime | None = None,
) -> tuple[Appointment, datetime]:
    appointment = get_appointment(db, appointment_id)
    previous_start = appointment.start_at
    new_start = earliest_advance_slot(db, appointment, now=now)

    appointment.start_at = new_start
    appointment.end_at = new_start + timedelta(minutes=appointment.duration_minutes)
    appointment.client_confirmed_at = None
    sync_appointment_reminders(db, appointment, now=now)
    db.commit()
    return appointment, previous_start


def reschedule_appointment(
    db: Session,
    appointment_id: int,
    payload: RescheduleIn,
    *,
    now: datetime | None = None,
) -> tuple[Appointment, datetime, Barber]:
    appointment = get_appointment(db, appointment_id)
    if appointment.status != AppointmentStatus.confirmed:
        raise ConflictError("Solo se pueden reasignar turnos confirmados.")

    now = ensure_utc(now or utc_now())
    target_barber = get_barber(db, payload.barber_id)
    new_start = payload.start_at.astimezone(UTC).replace(microsecond=0)
    day = to_business(new_start).date()
    validate_booking_day(day)

    slots = available_slots(
        db,
        target_barber,
        appointment.duration_minutes,
        day,
        now=now,
        ignore_appointment_id=appointment.id,
        enforce_notice=False,
    )
    if new_start not in slots:
        raise ConflictError(
            "Ese horario ya no está disponible para el barbero elegido. "
            "Elegí otro turno."
        )

    previous_start = appointment.start_at
    previous_barber = appointment.barber
    appointment.barber = target_barber
    appointment.start_at = new_start
    appointment.end_at = new_start + timedelta(minutes=appointment.duration_minutes)
    appointment.client_confirmed_at = None
    sync_appointment_reminders(db, appointment, now=now)
    db.commit()
    return appointment, previous_start, previous_barber


def register_manual_payment(
    db: Session,
    appointment_id: int,
    payload: ManualPaymentCreate,
    *,
    now: datetime | None = None,
) -> Appointment:
    appointment = get_appointment(db, appointment_id)
    add_manual_payment(
        appointment,
        amount_cents=payload.amount_cents,
        method=payload.method,
        kind=payload.kind,
        now=now,
    )
    db.commit()
    return appointment
