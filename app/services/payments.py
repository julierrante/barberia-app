from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.config import get_settings
from app.models import (
    Appointment,
    AppointmentStatus,
    Payment,
    PaymentKind,
    PaymentMethod,
    PaymentStatus,
)
from app.services.errors import BusinessError, ConflictError
from app.timeutils import utc_now


@dataclass(frozen=True)
class ChargeResult:
    approved: bool
    reference: str | None
    provider: str


class MockGateway:
    name = "mock"

    def charge(self, amount_cents: int, description: str) -> ChargeResult:
        return ChargeResult(
            approved=True,
            reference=f"mock_{uuid.uuid4().hex[:16]}",
            provider=self.name,
        )


def get_gateway() -> MockGateway:
    mode = get_settings().payments_mode
    if mode == "mock":
        return MockGateway()
    raise BusinessError(
        f"El modo de pagos '{mode}' no está implementado. Configurá PAYMENTS_MODE=mock."
    )


def add_online_payment(
    appointment: Appointment,
    option: str,
    *,
    now: datetime | None = None,
) -> Payment | None:
    """Simula la aprobación del cobro.

    En producción se debe crear un pago pendiente y confirmarlo por webhook del
    proveedor; el navegador nunca debe ser la fuente de verdad del pago.
    """
    if option == "later":
        return None

    now = now or utc_now()
    if option == "deposit":
        amount = appointment.deposit_cents
        kind = PaymentKind.deposit
        if amount <= 0:
            raise BusinessError("Este servicio no requiere seña. Elegí otro medio.")
    elif option == "full":
        amount = appointment.price_cents
        kind = PaymentKind.full
        if amount <= 0:
            return None
    else:
        raise BusinessError("Opción de pago inválida.")

    result = get_gateway().charge(amount, f"Turno #{appointment.public_code[:8]}")
    if not result.approved:
        raise BusinessError("El pago no fue aprobado. Probá con otro medio.")

    payment = Payment(
        kind=kind,
        method=PaymentMethod.mock,
        status=PaymentStatus.paid,
        amount_cents=amount,
        provider=result.provider,
        provider_reference=result.reference,
        paid_at=now,
    )
    appointment.payments.append(payment)
    return payment


def add_manual_payment(
    appointment: Appointment,
    *,
    amount_cents: int,
    method: str,
    kind: str,
    now: datetime | None = None,
) -> Payment:
    if appointment.status in (
        AppointmentStatus.cancelled,
        AppointmentStatus.no_show,
    ):
        raise ConflictError("No se pueden registrar pagos de un turno cancelado.")
    if amount_cents <= 0:
        raise BusinessError("El monto debe ser mayor a cero.")
    if amount_cents > appointment.balance_cents:
        raise BusinessError(
            "El monto supera el saldo pendiente del turno."
        )

    now = now or utc_now()
    payment = Payment(
        kind=PaymentKind(kind),
        method=PaymentMethod(method),
        status=PaymentStatus.paid,
        amount_cents=amount_cents,
        provider="manual",
        paid_at=now,
    )
    appointment.payments.append(payment)
    return payment
