from __future__ import annotations

from datetime import date, datetime, time

from app.models import (
    AppointmentStatus,
    PaymentKind,
    PaymentMethod,
    PaymentStatus,
)
from app.timeutils import to_business

WEEKDAYS = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}

STATUS_LABELS = {
    AppointmentStatus.confirmed: "Confirmado",
    AppointmentStatus.in_progress: "En curso",
    AppointmentStatus.completed: "Completado",
    AppointmentStatus.cancelled: "Cancelado",
    AppointmentStatus.no_show: "No se presentó",
}

PAYMENT_KIND_LABELS = {
    PaymentKind.deposit: "Seña",
    PaymentKind.full: "Pago total",
    PaymentKind.balance: "Saldo",
}

PAYMENT_METHOD_LABELS = {
    PaymentMethod.mock: "Pago online (demo)",
    PaymentMethod.cash: "Efectivo",
    PaymentMethod.card: "Tarjeta",
    PaymentMethod.transfer: "Transferencia",
}

PAYMENT_STATUS_LABELS = {
    PaymentStatus.pending: "Pendiente",
    PaymentStatus.paid: "Pagado",
    PaymentStatus.failed: "Fallido",
    PaymentStatus.refunded: "Reembolsado",
}


def _key(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def status_label(value) -> str:
    return STATUS_LABELS.get(value, _key(value))


def payment_kind_label(value) -> str:
    return PAYMENT_KIND_LABELS.get(value, _key(value))


def payment_method_label(value) -> str:
    return PAYMENT_METHOD_LABELS.get(value, _key(value))


def payment_status_label(value) -> str:
    return PAYMENT_STATUS_LABELS.get(value, _key(value))


def format_money(cents: int | None) -> str:
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    absolute = abs(cents)
    whole, remainder = divmod(absolute, 100)
    body = f"{whole:,}".replace(",", ".")
    if remainder:
        body += f",{remainder:02d}"
    return f"{sign}$ {body}"


def format_clock(value: datetime | time | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = to_business(value).time()
    return value.strftime("%H:%M")


def format_date_local(value: datetime | date | None, pattern: str = "%d/%m/%Y") -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = to_business(value).date()
    return value.strftime(pattern)


def format_long_date(value: datetime | date | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = to_business(value).date()
    return f"{WEEKDAYS.get(value.weekday(), '')} {value.strftime('%d/%m/%Y')}"


def format_time_local(value: datetime | None) -> str:
    if value is None:
        return "—"
    return to_business(value).strftime("%H:%M")


def format_datetime_local(value: datetime | None, pattern: str = "%d/%m/%Y · %H:%M") -> str:
    if value is None:
        return "—"
    return to_business(value).strftime(pattern)


def format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours} h"
    return f"{hours} h {rest} min"


def date_input_value(value: datetime | date | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = to_business(value).date()
    return value.isoformat()


def weekday_label(value: int) -> str:
    return WEEKDAYS.get(value, "")
