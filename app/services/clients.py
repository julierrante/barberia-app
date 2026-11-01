from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Appointment,
    AppointmentStatus,
    Client,
    PaymentStatus,
)
from app.services.errors import NotFoundError


@dataclass(frozen=True)
class ClientStats:
    visits_count: int
    last_visit_at: datetime | None
    total_paid_cents: int
    pending_balance_cents: int


def _client_query():
    return select(Client).options(
        selectinload(Client.appointments).selectinload(Appointment.payments)
    )


def calculate_stats(client: Client) -> ClientStats:
    completed = [
        appointment
        for appointment in client.appointments
        if appointment.status == AppointmentStatus.completed
    ]
    last_visit = max(
        (appointment.actual_end_at or appointment.end_at for appointment in completed),
        default=None,
    )
    total_paid = sum(
        payment.amount_cents
        for appointment in client.appointments
        for payment in appointment.payments
        if payment.status == PaymentStatus.paid
    )
    pending = sum(
        appointment.balance_cents
        for appointment in client.appointments
        if appointment.status
        not in (AppointmentStatus.cancelled, AppointmentStatus.no_show)
    )
    return ClientStats(
        visits_count=len(completed),
        last_visit_at=last_visit,
        total_paid_cents=total_paid,
        pending_balance_cents=pending,
    )


def search_clients(
    db: Session,
    query: str | None = None,
    *,
    limit: int = 200,
) -> list[tuple[Client, ClientStats]]:
    stmt = _client_query()
    cleaned = (query or "").strip()
    if cleaned:
        like = f"%{cleaned}%"
        conditions = [
            Client.first_name.ilike(like),
            Client.last_name.ilike(like),
            Client.phone.ilike(like),
        ]
        digits = re.sub(r"\D", "", cleaned)
        if digits:
            conditions.append(Client.phone.ilike(f"%{digits}%"))
        stmt = stmt.where(or_(*conditions))

    stmt = stmt.order_by(Client.last_name, Client.first_name).limit(limit)
    clients = list(db.scalars(stmt).all())
    return [(client, calculate_stats(client)) for client in clients]


def get_client(db: Session, client_id: int) -> Client:
    client = db.scalar(_client_query().where(Client.id == client_id))
    if client is None:
        raise NotFoundError("No encontramos ese cliente.")
    return client
