from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, UTCDateTime
from app.timeutils import utc_now


class AppointmentStatus(str, enum.Enum):
    confirmed = "confirmed"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class PaymentKind(str, enum.Enum):
    deposit = "deposit"
    full = "full"
    balance = "balance"


class PaymentMethod(str, enum.Enum):
    mock = "mock"
    cash = "cash"
    card = "card"
    transfer = "transfer"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"
    refunded = "refunded"


class ReminderStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    cancelled = "cancelled"
    skipped = "skipped"


class MediaType(str, enum.Enum):
    image = "image"
    video = "video"


ACTIVE_APPOINTMENT_STATUSES = (
    AppointmentStatus.confirmed,
    AppointmentStatus.in_progress,
)


def _enum(enum_class, name: str):
    return SAEnum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
        length=30,
    )


barber_specialties = Table(
    "barber_specialties",
    Base.metadata,
    Column("barber_id", ForeignKey("barbers.id", ondelete="CASCADE"), primary_key=True),
    Column("specialty_id", ForeignKey("specialties.id", ondelete="CASCADE"), primary_key=True),
)


class Barberia(Base):
    __tablename__ = "barberias"

    id: Mapped[int] = mapped_column(primary_key=True)

    nombre: Mapped[str] = mapped_column(
        String(120),
        nullable=False
    )

    slug: Mapped[str] = mapped_column(
        String(140),
        unique=True,
        index=True,
        nullable=False
    )

    descripcion: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    logo_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )

    color_primario: Mapped[str] = mapped_column(
        String(7),
        default="#000000",
        nullable=False
    )

    activa: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False
    )

    creada_en: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        nullable=False
    )

    barberos: Mapped[list[Barber]] = relationship(
        back_populates="barberia"
    )


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )

    appointments: Mapped[list[Appointment]] = relationship(
        back_populates="client",
        order_by="Appointment.start_at.desc()",
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Specialty(Base):
    __tablename__ = "specialties"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)

    barbers: Mapped[list[Barber]] = relationship(
        secondary=barber_specialties,
        back_populates="specialties",
    )


class Barber(Base):
    __tablename__ = "barbers"

    id: Mapped[int] = mapped_column(primary_key=True)
    barberia_id: Mapped[int | None] = mapped_column(
        ForeignKey("barberias.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    barberia: Mapped[Barberia | None] = relationship(
        back_populates="barberos"
    )
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    tagline: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mp_alias: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    specialties: Mapped[list[Specialty]] = relationship(
        secondary=barber_specialties,
        back_populates="barbers",
        order_by="Specialty.name",
        lazy="selectin",
    )
    portfolio_items: Mapped[list[PortfolioItem]] = relationship(
        back_populates="barber",
        cascade="all, delete-orphan",
        order_by="PortfolioItem.sort_order, PortfolioItem.id",
        lazy="selectin",
    )
    schedules: Mapped[list[WorkSchedule]] = relationship(
        back_populates="barber",
        cascade="all, delete-orphan",
        order_by="WorkSchedule.weekday, WorkSchedule.start_time",
        lazy="selectin",
    )
    appointments: Mapped[list[Appointment]] = relationship(back_populates="barber")
    ratings: Mapped[list[Rating]] = relationship(
        back_populates="barber",
        cascade="all, delete-orphan",
        order_by="Rating.created_at.desc()",
        lazy="selectin",
    )
    account: Mapped[BarberAccount | None] = relationship(
        back_populates="barber",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    daily_closings: Mapped[list[DailyClosing]] = relationship(
        back_populates="barber",
        order_by="DailyClosing.business_date.desc()",
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def rating_average(self) -> float | None:
        if not self.ratings:
            return None
        return round(sum(rating.score for rating in self.ratings) / len(self.ratings), 1)

    @property
    def rating_count(self) -> int:
        return len(self.ratings)


class BarberAccount(Base):
    __tablename__ = "barber_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_id: Mapped[int] = mapped_column(
        ForeignKey("barbers.id", ondelete="CASCADE"), unique=True, index=True
    )
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )

    barber: Mapped[Barber] = relationship(back_populates="account")


class PortfolioItem(Base):
    __tablename__ = "portfolio_items"
    __table_args__ = (
        CheckConstraint("media_type IN ('image', 'video')", name="ck_portfolio_media_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_id: Mapped[int] = mapped_column(
        ForeignKey("barbers.id", ondelete="CASCADE"), index=True
    )
    image_url: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(
        String(10), default=MediaType.image.value, server_default=text("'image'")
    )
    caption: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    barber: Mapped[Barber] = relationship(back_populates="portfolio_items")

    @property
    def is_video(self) -> bool:
        return self.media_type == MediaType.video.value


class WorkSchedule(Base):
    __tablename__ = "work_schedules"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_schedule_weekday"),
        CheckConstraint("start_time < end_time", name="ck_schedule_times"),
        UniqueConstraint(
            "barber_id", "weekday", "start_time", "end_time", name="uq_schedule_block"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_id: Mapped[int] = mapped_column(
        ForeignKey("barbers.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    barber: Mapped[Barber] = relationship(back_populates="schedules")


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_service_duration"),
        CheckConstraint("price_cents >= 0", name="ck_service_price"),
        CheckConstraint(
            "deposit_cents >= 0 AND deposit_cents <= price_cents",
            name="ck_service_deposit",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)
    deposit_cents: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    appointments: Mapped[list[Appointment]] = relationship(back_populates="service")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_appointment_times"),
        CheckConstraint("duration_minutes > 0", name="ck_appointment_duration"),
        CheckConstraint("price_cents >= 0", name="ck_appointment_price"),
        Index("ix_appointments_barber_start", "barber_id", "start_at"),
        Index("ix_appointments_client_start", "client_id", "start_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, default=lambda: uuid.uuid4().hex
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), index=True
    )
    barber_id: Mapped[int] = mapped_column(
        ForeignKey("barbers.id", ondelete="RESTRICT"), index=True
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), index=True
    )

    status: Mapped[AppointmentStatus] = mapped_column(
        _enum(AppointmentStatus, "appointment_status"),
        default=AppointmentStatus.confirmed,
    )
    start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    end_at: Mapped[datetime] = mapped_column(UTCDateTime())
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(Integer)
    deposit_cents: Mapped[int] = mapped_column(Integer, default=0)

    cancel_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    actual_start_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    actual_end_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    client_confirmed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )

    client: Mapped[Client] = relationship(back_populates="appointments", lazy="selectin")
    barber: Mapped[Barber] = relationship(back_populates="appointments", lazy="selectin")
    service: Mapped[Service] = relationship(back_populates="appointments", lazy="selectin")
    payments: Mapped[list[Payment]] = relationship(
        back_populates="appointment",
        cascade="all, delete-orphan",
        order_by="Payment.id",
        lazy="selectin",
    )
    rating: Mapped[Rating | None] = relationship(
        back_populates="appointment",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    reminders: Mapped[list[AppointmentReminder]] = relationship(
        back_populates="appointment",
        cascade="all, delete-orphan",
        order_by="AppointmentReminder.offset_minutes.desc()",
    )

    @property
    def client_first_name(self) -> str:
        return self.client.first_name

    @property
    def paid_cents(self) -> int:
        return sum(
            payment.amount_cents
            for payment in self.payments
            if payment.status == PaymentStatus.paid
        )

    @property
    def balance_cents(self) -> int:
        return max(0, self.price_cents - self.paid_cents)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="ck_payment_amount"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[PaymentKind] = mapped_column(_enum(PaymentKind, "payment_kind"))
    method: Mapped[PaymentMethod] = mapped_column(_enum(PaymentMethod, "payment_method"))
    status: Mapped[PaymentStatus] = mapped_column(
        _enum(PaymentStatus, "payment_status"),
        default=PaymentStatus.paid,
    )
    amount_cents: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    appointment: Mapped[Appointment] = relationship(back_populates="payments")


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (CheckConstraint("score >= 1 AND score <= 5", name="ck_rating_score"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), unique=True, index=True
    )
    barber_id: Mapped[int] = mapped_column(
        ForeignKey("barbers.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    appointment: Mapped[Appointment] = relationship(back_populates="rating")
    barber: Mapped[Barber] = relationship(back_populates="ratings")
    client: Mapped[Client] = relationship()

    @property
    def stars(self) -> str:
        return "★" * self.score + "☆" * (5 - self.score)


class DailyClosing(Base):
    __tablename__ = "daily_closings"
    __table_args__ = (
        UniqueConstraint(
            "barber_id", "business_date", name="uq_daily_closing_barber_date"
        ),
        Index("ix_daily_closings_date", "business_date"),
        CheckConstraint(
            "completed_count >= 0 AND cancelled_count >= 0 AND no_show_count >= 0",
            name="ck_daily_closing_counts",
        ),
        CheckConstraint(
            "service_revenue_cents >= 0 AND collected_cents >= 0 AND pending_cents >= 0",
            name="ck_daily_closing_amounts",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    barber_id: Mapped[int] = mapped_column(
        ForeignKey("barbers.id", ondelete="RESTRICT"), index=True
    )
    business_date: Mapped[date] = mapped_column(Date)
    barber_name: Mapped[str] = mapped_column(String(120))
    appointments_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_count: Mapped[int] = mapped_column(Integer, default=0)
    no_show_count: Mapped[int] = mapped_column(Integer, default=0)
    service_revenue_cents: Mapped[int] = mapped_column(Integer, default=0)
    collected_cents: Mapped[int] = mapped_column(Integer, default=0)
    pending_cents: Mapped[int] = mapped_column(Integer, default=0)
    closed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )

    barber: Mapped[Barber] = relationship(back_populates="daily_closings")


class AppointmentReminder(Base):
    __tablename__ = "appointment_reminders"
    __table_args__ = (
        UniqueConstraint(
            "appointment_id", "offset_minutes", name="uq_reminder_appointment_offset"
        ),
        Index("ix_reminders_status_scheduled", "status", "scheduled_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), index=True
    )
    offset_minutes: Mapped[int] = mapped_column(Integer)
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[ReminderStatus] = mapped_column(
        _enum(ReminderStatus, "reminder_status"),
        default=ReminderStatus.pending,
    )
    channel: Mapped[str] = mapped_column(String(20), default="whatsapp")
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    appointment: Mapped[Appointment] = relationship(back_populates="reminders")
