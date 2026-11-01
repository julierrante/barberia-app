from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth import (
    require_admin_api,
    require_owner_api,
    session_barber_id,
)
from app.config import get_settings
from app.database import get_db
from app.models import AppointmentStatus, Barber
from app.schemas import (
    AdvanceOut,
    AppointmentAdminOut,
    AvailabilityOut,
    BarberBrief,
    ClientSummary,
    ManualPaymentCreate,
    QueueItem,
    QueueOut,
    RescheduleIn,
    RescheduleOut,
    ServiceBrief,
    SlotOut,
    StatusUpdate,
)
from app.services.booking import (
    advance_appointment,
    change_status,
    get_appointment,
    get_barber,
    register_manual_payment,
    reschedule_appointment,
)
from app.services.errors import ConflictError, ForbiddenError
from app.services.scheduling import (
    available_slots,
    build_queue,
    slot_label,
    validate_booking_day,
)
from app.timeutils import to_business, utc_now

router = APIRouter(
    prefix="/api/admin",
    tags=["Administración"],
    dependencies=[Depends(require_admin_api)],
)


def _ensure_barber_scope(request: Request, db: Session, barber_id: int) -> None:
    scoped_barber_id = session_barber_id(request)
    if scoped_barber_id is None:
        return
    if scoped_barber_id != barber_id:
        raise ForbiddenError("No podés operar sobre la agenda de otro barbero.")
    barber = db.get(Barber, barber_id)
    if barber is None or barber.deleted_at is not None:
        raise ForbiddenError("El perfil de este barbero ya no está disponible.")


def _ensure_appointment_scope(
    request: Request, db: Session, appointment_id: int
) -> None:
    scoped_barber_id = session_barber_id(request)
    if scoped_barber_id is None:
        return
    appointment = get_appointment(db, appointment_id)
    if appointment.barber_id != scoped_barber_id:
        raise ForbiddenError("Ese turno pertenece a otro barbero.")
    if appointment.barber.deleted_at is not None:
        raise ForbiddenError("El perfil de este barbero ya no está disponible.")


@router.get("/queue", response_model=QueueOut)
def get_queue(
    request: Request,
    barber_id: int,
    day: date = Query(alias="date"),
    db: Session = Depends(get_db),
):
    _ensure_barber_scope(request, db, barber_id)
    barber = get_barber(db, barber_id)
    now = utc_now()
    settings = get_settings()
    entries = build_queue(
        db,
        barber,
        day,
        now=now,
        confirmation_deadline_minutes=settings.confirmation_deadline_minutes,
    )

    items = [
        QueueItem(
            id=entry.appointment.id,
            public_code=entry.appointment.public_code,
            status=entry.appointment.status,
            scheduled_start_at=entry.appointment.start_at,
            scheduled_end_at=entry.appointment.end_at,
            eta_start_at=entry.eta_start_at,
            eta_end_at=entry.eta_end_at,
            delay_minutes=entry.delay_minutes,
            client=ClientSummary.model_validate(entry.appointment.client),
            service=ServiceBrief.model_validate(entry.appointment.service),
            price_cents=entry.appointment.price_cents,
            paid_cents=entry.appointment.paid_cents,
            balance_cents=entry.appointment.balance_cents,
            actual_start_at=entry.appointment.actual_start_at,
            actual_end_at=entry.appointment.actual_end_at,
            client_confirmed=entry.appointment.client_confirmed_at is not None,
            confirmation_due_soon=entry.confirmation_due_soon,
        )
        for entry in entries
    ]

    return QueueOut(
        barber=BarberBrief.model_validate(barber),
        date=day,
        timezone=to_business(now).tzname() or "local",
        now=now,
        confirmation_deadline_minutes=settings.confirmation_deadline_minutes,
        items=items,
    )


@router.patch(
    "/appointments/{appointment_id}/status",
    response_model=AppointmentAdminOut,
)
def update_appointment_status(
    request: Request,
    appointment_id: int,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
):
    _ensure_appointment_scope(request, db, appointment_id)
    return change_status(db, appointment_id, payload)


@router.post(
    "/appointments/{appointment_id}/advance",
    response_model=AdvanceOut,
)
def advance_appointment_endpoint(
    request: Request,
    appointment_id: int,
    db: Session = Depends(get_db),
):
    _ensure_appointment_scope(request, db, appointment_id)
    appointment, previous_start = advance_appointment(db, appointment_id)
    return AdvanceOut(
        previous_start_at=previous_start,
        appointment=AppointmentAdminOut.model_validate(appointment),
    )


@router.get(
    "/appointments/{appointment_id}/slots",
    response_model=AvailabilityOut,
    dependencies=[Depends(require_owner_api)],
)
def list_reschedule_slots(
    appointment_id: int,
    barber_id: int,
    day: date = Query(alias="date"),
    db: Session = Depends(get_db),
):
    appointment = get_appointment(db, appointment_id)
    if appointment.status != AppointmentStatus.confirmed:
        raise ConflictError("Solo se pueden reasignar turnos confirmados.")

    barber = get_barber(db, barber_id)
    validate_booking_day(day)
    slots = available_slots(
        db,
        barber,
        appointment.duration_minutes,
        day,
        ignore_appointment_id=appointment.id,
        enforce_notice=False,
    )
    return AvailabilityOut(
        barber_id=barber.id,
        service_id=appointment.service_id,
        date=day,
        timezone=get_settings().business_timezone,
        slots=[SlotOut(start_at=slot, label=slot_label(slot)) for slot in slots],
    )


@router.post(
    "/appointments/{appointment_id}/reschedule",
    response_model=RescheduleOut,
    dependencies=[Depends(require_owner_api)],
)
def reschedule_appointment_endpoint(
    appointment_id: int,
    payload: RescheduleIn,
    db: Session = Depends(get_db),
):
    appointment, previous_start, previous_barber = reschedule_appointment(
        db, appointment_id, payload
    )
    return RescheduleOut(
        previous_start_at=previous_start,
        previous_barber=BarberBrief.model_validate(previous_barber),
        appointment=AppointmentAdminOut.model_validate(appointment),
    )


@router.post(
    "/appointments/{appointment_id}/payments",
    response_model=AppointmentAdminOut,
)
def add_payment(
    request: Request,
    appointment_id: int,
    payload: ManualPaymentCreate,
    db: Session = Depends(get_db),
):
    _ensure_appointment_scope(request, db, appointment_id)
    appointment = register_manual_payment(db, appointment_id, payload)
    return AppointmentAdminOut.model_validate(appointment)
