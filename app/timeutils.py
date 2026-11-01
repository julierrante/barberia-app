from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings

UTC = timezone.utc


def business_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().business_timezone)


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_business(value: datetime) -> datetime:
    return ensure_utc(value).astimezone(business_tz())


def business_today() -> date:
    return utc_now().astimezone(business_tz()).date()


def day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    tz = business_tz()
    local_start = datetime.combine(day, time.min, tzinfo=tz)
    return local_start.astimezone(UTC), (local_start + timedelta(days=1)).astimezone(UTC)


def local_to_utc(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=business_tz()).astimezone(UTC)
