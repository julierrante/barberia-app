from __future__ import annotations

from datetime import datetime, timedelta

from app.models import Barber, Service
from app.services.scheduling import available_slots
from app.timeutils import business_today


def find_day_with_slots(
    db,
    barber: Barber,
    service: Service,
    *,
    minimum: int = 1,
) -> tuple:
    day = business_today() + timedelta(days=1)
    for _ in range(45):
        slots = available_slots(db, barber, service.duration_minutes, day)
        if len(slots) >= minimum:
            return day, slots
        day += timedelta(days=1)
    raise AssertionError("No se encontró un día con disponibilidad suficiente.")


def find_shared_day(
    db,
    barbers: list[Barber],
    service: Service,
    *,
    minimum: int = 1,
) -> tuple:
    day = business_today() + timedelta(days=1)
    for _ in range(45):
        slots = [
            available_slots(db, barber, service.duration_minutes, day)
            for barber in barbers
        ]
        if all(len(candidate) >= minimum for candidate in slots):
            return day, slots
        day += timedelta(days=1)
    raise AssertionError("No se encontró un día compartido con disponibilidad.")


def booking_payload(
    *,
    barber: Barber,
    service: Service,
    start_at: datetime,
    phone: str = "+54 9 11 5555 0101",
    first_name: str = "Lucía",
    last_name: str = "Fernández",
    payment_option: str = "deposit",
) -> dict:
    return {
        "barber_id": barber.id,
        "service_id": service.id,
        "start_at": start_at.isoformat(),
        "payment_option": payment_option,
        "client": {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "email": "lucia@example.com",
        },
    }


def parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
