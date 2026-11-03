from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Barber, Barberia, Service
from app.schemas import (
    AppointmentPublicOut,
    AvailabilityOut,
    BarberOut,
    BookingCreate,
    CalendarSlotOut,
    CancelIn,
    RatingCreate,
    RatingOut,
    ServiceOut,
    SlotOut,
)
from app.services.booking import (
    cancel_customer_booking,
    confirm_customer_attendance,
    create_booking,
    get_appointment_by_code,
    get_barber,
    get_service,
    rate_appointment,
)
from app.services.scheduling import (
    available_slots,
    build_queue,
    calendar_slots,
    slot_label,
    validate_booking_day,
)
from app.services.errors import NotFoundError
from app.timeutils import to_business, utc_now
from app.tenancy import obtener_barberia_actual

router = APIRouter(prefix="/api", tags=["Público"])


def _require_appointment_for_barberia(
    db: Session, public_code: str, barberia: Barberia
):
    appointment = get_appointment_by_code(db, public_code)
    if (
        appointment.barber.barberia_id != barberia.id
        or appointment.service.barberia_id != barberia.id
    ):
        raise NotFoundError("No encontramos ese turno.")
    return appointment


def _queue_entry(db: Session, appointment):
    day = to_business(appointment.start_at).date()
    entries = build_queue(db, appointment.barber, day)
    return next(
        (entry for entry in entries if entry.appointment.id == appointment.id), None
    )


def _public_out(appointment, entry=None) -> AppointmentPublicOut:
    result = AppointmentPublicOut.model_validate(appointment)
    if entry is not None:
        result = result.model_copy(
            update={
                "eta_start_at": entry.eta_start_at,
                "eta_end_at": entry.eta_end_at,
                "delay_minutes": entry.delay_minutes,
            }
        )
    return result


@router.get("/services", response_model=list[ServiceOut])
def list_services(
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    return list(
        db.scalars(
            select(Service)
            .where(Service.active.is_(True), Service.barberia_id == barberia.id)
            .order_by(Service.price_cents)
        ).all()
    )


@router.get("/barbers", response_model=list[BarberOut])
def list_barbers(
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    return list(
        db.scalars(
            select(Barber)
            .where(Barber.active.is_(True), Barber.barberia_id == barberia.id)
            .order_by(Barber.name)
        ).all()
    )


@router.get("/barbers/{slug}", response_model=BarberOut)
def get_barber_profile(
    slug: str,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    barber = db.scalar(
        select(Barber).where(
            Barber.slug == slug, Barber.active.is_(True),
            Barber.barberia_id == barberia.id,
        )
    )
    if barber is None:
        raise NotFoundError("No encontramos ese barbero.")
    return barber


@router.get("/availability", response_model=AvailabilityOut)
def get_availability(
    barber_id: int,
    service_id: int,
    booking_date: date = Query(alias="date"),
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    service = get_service(db, service_id)
    barber = get_barber(db, barber_id)
    if service.barberia_id != barberia.id or barber.barberia_id != barberia.id:
        raise NotFoundError("El servicio o barbero no está disponible.")
    validate_booking_day(booking_date)
    slots = available_slots(db, barber, service.duration_minutes, booking_date)
    calendar = calendar_slots(db, barber, service.duration_minutes, booking_date)
    return AvailabilityOut(
        barber_id=barber.id,
        service_id=service.id,
        date=booking_date,
        timezone=to_business(utc_now()).tzname() or "local",
        slots=[SlotOut(start_at=slot, label=slot_label(slot)) for slot in slots],
        calendar=[
            CalendarSlotOut(
                start_at=start, label=slot_label(start), status=status
            )
            for start, status in calendar
        ],
    )


@router.post(
    "/appointments",
    response_model=AppointmentPublicOut,
    status_code=201,
)
def book_appointment(
    payload: BookingCreate,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    service = get_service(db, payload.service_id)
    barber = get_barber(db, payload.barber_id)
    if service.barberia_id != barberia.id or barber.barberia_id != barberia.id:
        raise NotFoundError("El servicio o barbero no está disponible.")
    appointment = create_booking(db, payload)
    return _public_out(appointment, _queue_entry(db, appointment))


@router.get("/appointments/{public_code}", response_model=AppointmentPublicOut)
def get_appointment(
    public_code: str,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    appointment = _require_appointment_for_barberia(db, public_code, barberia)
    return _public_out(appointment, _queue_entry(db, appointment))


@router.post(
    "/appointments/{public_code}/cancel",
    response_model=AppointmentPublicOut,
)
def cancel_appointment(
    public_code: str,
    payload: CancelIn,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    _require_appointment_for_barberia(db, public_code, barberia)
    appointment = cancel_customer_booking(db, public_code, payload.phone)
    return _public_out(appointment, _queue_entry(db, appointment))


@router.post(
    "/appointments/{public_code}/confirm",
    response_model=AppointmentPublicOut,
)
def confirm_appointment_attendance(
    public_code: str,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    _require_appointment_for_barberia(db, public_code, barberia)
    appointment = confirm_customer_attendance(db, public_code)
    return _public_out(appointment, _queue_entry(db, appointment))


@router.post(
    "/appointments/{public_code}/rating",
    response_model=RatingOut,
    status_code=201,
)
def rate_served_appointment(
    public_code: str,
    payload: RatingCreate,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    _require_appointment_for_barberia(db, public_code, barberia)
    return rate_appointment(db, public_code, payload)
