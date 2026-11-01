from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.formatting import (
    WEEKDAYS,
    PAYMENT_KIND_LABELS,
    PAYMENT_METHOD_LABELS,
    STATUS_LABELS,
    date_input_value,
    format_clock,
    format_date_local,
    format_datetime_local,
    format_duration,
    format_long_date,
    format_money,
    format_time_local,
    payment_kind_label,
    payment_method_label,
    payment_status_label,
    status_label,
    weekday_label,
)
from app.timeutils import business_today

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters.update(
    {
        "money": format_money,
        "clock": format_clock,
        "local_date": format_date_local,
        "long_date": format_long_date,
        "local_time": format_time_local,
        "local_datetime": format_datetime_local,
        "duration": format_duration,
        "date_input": date_input_value,
        "status_label": status_label,
        "payment_kind_label": payment_kind_label,
        "payment_method_label": payment_method_label,
        "payment_status_label": payment_status_label,
        "weekday_label": weekday_label,
    }
)
templates.env.globals.update(
    {
        "app_name": get_settings().app_name,
        "weekdays": WEEKDAYS,
        "status_labels": STATUS_LABELS,
        "payment_kind_labels": PAYMENT_KIND_LABELS,
        "payment_method_labels": PAYMENT_METHOD_LABELS,
        "payments_mode": get_settings().payments_mode,
        "whatsapp_mode": get_settings().whatsapp_mode,
        "business_timezone": get_settings().business_timezone,
        "current_year": business_today().year,
    }
)
