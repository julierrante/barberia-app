from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import (
    AppointmentStatus,
    PaymentKind,
    PaymentMethod,
    PaymentStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SpecialtyOut(ORMModel):
    id: int
    name: str


class PortfolioItemOut(ORMModel):
    image_url: str
    media_type: Literal["image", "video"] = "image"
    caption: str | None = None


class WorkScheduleOut(ORMModel):
    weekday: int
    start_time: time
    end_time: time


class ServiceOut(ORMModel):
    id: int
    name: str
    description: str | None = None
    duration_minutes: int
    price_cents: int
    deposit_cents: int


class ServiceBrief(ORMModel):
    id: int
    name: str
    duration_minutes: int


class BarberBrief(ORMModel):
    id: int
    name: str
    slug: str
    avatar_url: str | None = None
    rating_average: float | None = None
    rating_count: int = 0


class BarberOut(BarberBrief):
    tagline: str | None = None
    bio: str | None = None
    specialties: list[SpecialtyOut] = Field(default_factory=list)
    portfolio_items: list[PortfolioItemOut] = Field(default_factory=list)
    schedules: list[WorkScheduleOut] = Field(default_factory=list)


class ClientSummary(ORMModel):
    id: int
    first_name: str
    last_name: str
    phone: str
    email: str | None = None


class ClientCreate(BaseModel):
    first_name: str = Field(min_length=2, max_length=80)
    last_name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=6, max_length=30)
    email: EmailStr | None = None

    @field_validator("first_name", "last_name", "phone", mode="before")
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            return " ".join(value.split())
        return value

    @field_validator("email", mode="before")
    @classmethod
    def empty_email_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("phone")
    @classmethod
    def phone_has_digits(cls, value: str) -> str:
        if len(re.sub(r"\D", "", value)) < 6:
            raise ValueError("El teléfono debe tener al menos 6 dígitos.")
        return value


class BookingCreate(BaseModel):
    barber_id: int
    service_id: int
    start_at: datetime
    payment_option: Literal["deposit", "full", "later"] = "later"
    client: ClientCreate

    @field_validator("start_at")
    @classmethod
    def aware_start_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("La fecha del turno debe incluir zona horaria.")
        return value.astimezone(timezone.utc)


class PaymentOut(ORMModel):
    id: int
    kind: PaymentKind
    method: PaymentMethod
    status: PaymentStatus
    amount_cents: int
    provider: str | None = None
    created_at: datetime
    paid_at: datetime | None = None


class RatingOut(ORMModel):
    score: int
    comment: str | None = None
    created_at: datetime


class RatingCreate(BaseModel):
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("comment", mode="before")
    @classmethod
    def blank_comment_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class AppointmentCoreOut(ORMModel):
    id: int
    public_code: str
    status: AppointmentStatus
    start_at: datetime
    end_at: datetime
    duration_minutes: int
    price_cents: int
    deposit_cents: int
    paid_cents: int
    balance_cents: int
    cancel_reason: str | None = None
    actual_start_at: datetime | None = None
    actual_end_at: datetime | None = None
    client_confirmed_at: datetime | None = None
    barber: BarberBrief
    service: ServiceBrief
    payments: list[PaymentOut] = Field(default_factory=list)
    rating: RatingOut | None = None
    eta_start_at: datetime | None = None
    eta_end_at: datetime | None = None
    delay_minutes: int = 0


class AppointmentPublicOut(AppointmentCoreOut):
    client_first_name: str


class AppointmentAdminOut(AppointmentCoreOut):
    client: ClientSummary
    created_at: datetime


class SlotOut(BaseModel):
    start_at: datetime
    label: str


class CalendarSlotOut(SlotOut):
    status: Literal["available", "occupied", "past"]


class AvailabilityOut(BaseModel):
    barber_id: int
    service_id: int
    date: date
    timezone: str
    slots: list[SlotOut]
    calendar: list[CalendarSlotOut] = Field(default_factory=list)


class CancelIn(BaseModel):
    phone: str = Field(min_length=6, max_length=30)


class QueueItem(BaseModel):
    id: int
    public_code: str
    status: AppointmentStatus
    scheduled_start_at: datetime
    scheduled_end_at: datetime
    eta_start_at: datetime | None = None
    eta_end_at: datetime | None = None
    delay_minutes: int = 0
    client: ClientSummary
    service: ServiceBrief
    price_cents: int
    paid_cents: int
    balance_cents: int
    actual_start_at: datetime | None = None
    actual_end_at: datetime | None = None
    client_confirmed: bool = False
    confirmation_due_soon: bool = False


class QueueOut(BaseModel):
    barber: BarberBrief
    date: date
    timezone: str
    now: datetime
    confirmation_deadline_minutes: int = 45
    items: list[QueueItem]


class StatusUpdate(BaseModel):
    status: Literal["in_progress", "completed", "cancelled", "no_show"]
    reason: str | None = Field(default=None, max_length=300)

    @field_validator("reason", mode="before")
    @classmethod
    def blank_reason_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ManualPaymentCreate(BaseModel):
    amount_cents: int = Field(gt=0)
    method: Literal["cash", "card", "transfer"]
    kind: Literal["deposit", "balance", "full"] = "balance"


class AdvanceOut(BaseModel):
    previous_start_at: datetime
    appointment: AppointmentAdminOut


class RescheduleIn(BaseModel):
    barber_id: int = Field(gt=0)
    start_at: datetime

    @field_validator("start_at")
    @classmethod
    def aware_start_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("La fecha del turno debe incluir zona horaria.")
        return value.astimezone(timezone.utc)


class RescheduleOut(BaseModel):
    previous_start_at: datetime
    previous_barber: BarberBrief
    appointment: AppointmentAdminOut
