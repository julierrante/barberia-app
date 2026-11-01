from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    Appointment,
    AppointmentReminder,
    AppointmentStatus,
    ReminderStatus,
)
from app.timeutils import ensure_utc, to_business, utc_now

REMINDER_OFFSETS = (90, 60)
FINAL_NOTICE_OFFSET = 45
ALL_REMINDER_OFFSETS = REMINDER_OFFSETS + (FINAL_NOTICE_OFFSET,)
TERMINAL_STATUSES = {
    AppointmentStatus.completed,
    AppointmentStatus.cancelled,
    AppointmentStatus.no_show,
}
LEAD_LABELS = {90: "en 1 hora y media", 60: "en 1 hora"}

logger = logging.getLogger("barberia.reminders")


class ReminderDeliveryError(Exception):
    pass


@dataclass
class DeliveryResult:
    provider: str
    reference: str | None = None


def sync_appointment_reminders(
    db: Session,
    appointment: Appointment,
    *,
    now=None,
) -> None:
    if appointment.status != AppointmentStatus.confirmed:
        return

    now = ensure_utc(now or utc_now())
    existing = {
        reminder.offset_minutes: reminder for reminder in appointment.reminders
    }

    for offset in ALL_REMINDER_OFFSETS:
        scheduled_at = appointment.start_at - timedelta(minutes=offset)
        reminder = existing.get(offset)

        if reminder is not None and reminder.status == ReminderStatus.sent:
            continue

        if scheduled_at <= now:
            if reminder is None:
                appointment.reminders.append(
                    AppointmentReminder(
                        offset_minutes=offset,
                        scheduled_at=scheduled_at,
                        status=ReminderStatus.skipped,
                    )
                )
            else:
                reminder.scheduled_at = scheduled_at
                reminder.status = ReminderStatus.skipped
                reminder.sent_at = None
                reminder.error = None
            continue

        if reminder is None:
            appointment.reminders.append(
                AppointmentReminder(
                    offset_minutes=offset,
                    scheduled_at=scheduled_at,
                )
            )
        else:
            reminder.scheduled_at = scheduled_at
            reminder.status = ReminderStatus.pending
            reminder.sent_at = None
            reminder.provider = None
            reminder.provider_reference = None
            reminder.error = None


def cancel_appointment_reminders(appointment: Appointment) -> None:
    for reminder in appointment.reminders:
        if reminder.status == ReminderStatus.pending:
            reminder.status = ReminderStatus.cancelled


def _whatsapp_number(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("54"):
        return digits
    if len(digits) == 10:
        return f"549{digits}"
    return digits


def confirmation_url(appointment: Appointment) -> str:
    base = get_settings().app_base_url.rstrip("/")
    return f"{base}/reserva/{appointment.public_code}"


def build_reminder_text(appointment: Appointment, offset_minutes: int) -> str:
    local_start = to_business(appointment.start_at)
    link = confirmation_url(appointment)
    if offset_minutes == FINAL_NOTICE_OFFSET:
        return (
            f"Hola {appointment.client.first_name}, tu turno de "
            f"{appointment.service.name} con {appointment.barber.name} es a las "
            f"{local_start.strftime('%H:%M')} y todavía no confirmamos tu asistencia. "
            f"Confirmá ahora desde este enlace, o el horario podría quedar liberado: {link}"
        )
    lead = LEAD_LABELS.get(offset_minutes, f"en {offset_minutes} minutos")
    if appointment.client_confirmed_at is None:
        return (
            f"Hola {appointment.client.first_name}, te recordamos que tu turno de "
            f"{appointment.service.name} con {appointment.barber.name} es {lead}, "
            f"el {local_start.strftime('%d/%m/%Y')} a las {local_start.strftime('%H:%M')}. "
            f"Confirmá tu asistencia desde este enlace: {link}"
        )
    return (
        f"Hola {appointment.client.first_name}, te recordamos que tu turno de "
        f"{appointment.service.name} con {appointment.barber.name} es {lead}, "
        f"el {local_start.strftime('%d/%m/%Y')} a las {local_start.strftime('%H:%M')}. "
        f"Asistencia confirmada. Código de reserva: "
        f"{appointment.public_code[:8].upper()}."
    )


def _cloud_payload(appointment: Appointment, offset_minutes: int) -> dict:
    settings = get_settings()
    local_start = to_business(appointment.start_at)
    if settings.whatsapp_template_name:
        return {
            "messaging_product": "whatsapp",
            "to": _whatsapp_number(appointment.client.phone),
            "type": "template",
            "template": {
                "name": settings.whatsapp_template_name,
                "language": {"code": settings.whatsapp_template_language},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": appointment.client.first_name},
                            {"type": "text", "text": appointment.service.name},
                            {"type": "text", "text": appointment.barber.name},
                            {"type": "text", "text": local_start.strftime("%d/%m/%Y")},
                            {"type": "text", "text": local_start.strftime("%H:%M")},
                            {"type": "text", "text": confirmation_url(appointment)},
                        ],
                    }
                ],
            },
        }

    return {
        "messaging_product": "whatsapp",
        "to": _whatsapp_number(appointment.client.phone),
        "type": "text",
        "text": {"preview_url": False, "body": build_reminder_text(appointment, offset_minutes)},
    }


async def send_whatsapp_reminder(
    appointment: Appointment,
    offset_minutes: int,
) -> DeliveryResult:
    settings = get_settings()
    message = build_reminder_text(appointment, offset_minutes)

    if settings.whatsapp_mode == "mock":
        logger.info(
            "Recordatorio simulado (%s min) para el turno %s: %s",
            offset_minutes,
            appointment.public_code[:8],
            message,
        )
        return DeliveryResult("mock", f"mock-{uuid.uuid4().hex[:12]}")

    if settings.whatsapp_mode != "cloud":
        raise ReminderDeliveryError(
            "WHATSAPP_MODE debe ser 'mock' o 'cloud'."
        )
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise ReminderDeliveryError(
            "Faltan WHATSAPP_ACCESS_TOKEN o WHATSAPP_PHONE_NUMBER_ID para enviar por WhatsApp."
        )

    url = (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            url,
            json=_cloud_payload(appointment, offset_minutes),
            headers={
                "Authorization": f"Bearer {settings.whatsapp_access_token}",
                "Content-Type": "application/json",
            },
        )

    if response.status_code >= 400:
        detail = response.text[:300]
        raise ReminderDeliveryError(
            f"WhatsApp rechazó el envío ({response.status_code}): {detail}"
        )

    try:
        data = response.json()
    except ValueError:
        data = {}
    reference = (
        data.get("messages", [{}])[0].get("id")
        if isinstance(data.get("messages"), list) and data["messages"]
        else None
    )
    return DeliveryResult("whatsapp_cloud", reference)


async def process_due_reminders(*, now=None) -> int:
    now = ensure_utc(now or utc_now())
    processed = 0

    with SessionLocal() as db:
        due = list(
            db.scalars(
                select(AppointmentReminder)
                .where(
                    AppointmentReminder.status == ReminderStatus.pending,
                    AppointmentReminder.scheduled_at <= now,
                )
                .order_by(AppointmentReminder.scheduled_at)
                .limit(25)
            ).all()
        )

        for reminder in due:
            appointment = reminder.appointment
            if appointment.status != AppointmentStatus.confirmed:
                reminder.status = ReminderStatus.cancelled
                db.commit()
                processed += 1
                continue

            if (
                reminder.offset_minutes == FINAL_NOTICE_OFFSET
                and appointment.client_confirmed_at is not None
            ):
                reminder.status = ReminderStatus.skipped
                reminder.sent_at = None
                db.commit()
                processed += 1
                continue

            try:
                result = await send_whatsapp_reminder(
                    appointment, reminder.offset_minutes
                )
            except Exception as exc:
                logger.warning(
                    "Falló el recordatorio del turno %s: %s",
                    appointment.public_code[:8],
                    exc,
                )
                reminder.status = ReminderStatus.failed
                reminder.error = str(exc)[:500]
            else:
                reminder.status = ReminderStatus.sent
                reminder.sent_at = utc_now()
                reminder.provider = result.provider
                reminder.provider_reference = result.reference
                reminder.error = None
            db.commit()
            processed += 1

    return processed


async def reminder_worker(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(5, settings.reminder_worker_interval_seconds)
    logger.info("Recordatorios activos en modo %s cada %s s.", settings.whatsapp_mode, interval)

    while not stop_event.is_set():
        try:
            await process_due_reminders()
        except Exception:
            logger.exception("Error al procesar recordatorios")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            continue
