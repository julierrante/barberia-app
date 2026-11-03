from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import time
from pathlib import Path

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_password, normalize_email
from app.formatting import WEEKDAYS
from app.models import (
    ACTIVE_APPOINTMENT_STATUSES,
    Appointment,
    Barber,
    BarberAccount,
    PortfolioItem,
    Specialty,
    WorkSchedule,
)
from app.timeutils import utc_now

AVATAR_MAX_BYTES = 5 * 1024 * 1024
AVATAR_DIR = Path(__file__).resolve().parent.parent / "static" / "img" / "barbers"
AVATAR_URL_PREFIX = "/static/img/barbers/"

PORTFOLIO_IMAGE_MAX_BYTES = 8 * 1024 * 1024
PORTFOLIO_VIDEO_MAX_BYTES = 25 * 1024 * 1024
PORTFOLIO_MAX_ITEMS = 24
PORTFOLIO_DIR = Path(__file__).resolve().parent.parent / "static" / "media" / "portfolio"
PORTFOLIO_URL_PREFIX = "/static/media/portfolio/"

_email_adapter = TypeAdapter(EmailStr)


class ProfileFormError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__(" ".join(errors))
        self.errors = errors


@dataclass
class BarberProfileData:
    name: str
    tagline: str | None
    bio: str | None
    mp_alias: str | None
    email: str | None
    password: str | None
    active: bool
    specialty_ids: list[int]
    schedules: list[tuple[int, time, time]]
    schedule_rows: list[dict]


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _clean_multiline(value) -> str:
    return str(value or "").strip()


def _parse_time(value) -> time | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return time.fromisoformat(raw)
    except ValueError:
        return None


def slugify(name: str) -> str:
    normalized = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "barbero"


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    candidate = base
    suffix = 2
    while db.scalar(select(Barber.id).where(Barber.slug == candidate)) is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def schedule_rows_from_barber(barber: Barber) -> list[dict]:
    rows: list[dict] = []
    for weekday in range(7):
        blocks = [
            {
                "start": block.start_time.strftime("%H:%M"),
                "end": block.end_time.strftime("%H:%M"),
            }
            for block in barber.schedules
            if block.weekday == weekday
        ]
        while len(blocks) < 2:
            blocks.append({"start": "", "end": ""})
        rows.append(
            {
                "weekday": weekday,
                "name": WEEKDAYS[weekday],
                "blocks": blocks[:2],
            }
        )
    return rows


def schedule_rows_from_form(form) -> list[dict]:
    rows: list[dict] = []
    for weekday in range(7):
        blocks = []
        for block in range(2):
            blocks.append(
                {
                    "start": str(form.get(f"start_{weekday}_{block}") or ""),
                    "end": str(form.get(f"end_{weekday}_{block}") or ""),
                }
            )
        rows.append(
            {
                "weekday": weekday,
                "name": WEEKDAYS[weekday],
                "blocks": blocks,
            }
        )
    return rows


def parse_schedule_rows(rows: list[dict]) -> list[tuple[int, time, time]]:
    schedules: list[tuple[int, time, time]] = []
    errors: list[str] = []

    for row in rows:
        weekday = int(row["weekday"])
        day_name = WEEKDAYS[weekday]
        blocks: list[tuple[time, time]] = []
        for raw in row["blocks"]:
            start_raw = str(raw.get("start") or "").strip()
            end_raw = str(raw.get("end") or "").strip()
            if not start_raw and not end_raw:
                continue
            if not start_raw or not end_raw:
                errors.append(
                    f"Completá el inicio y el fin del bloque de {day_name}."
                )
                continue
            start = _parse_time(start_raw)
            end = _parse_time(end_raw)
            if start is None or end is None:
                errors.append(
                    f"Revisá el formato de hora de {day_name} (HH:MM)."
                )
                continue
            if start >= end:
                errors.append(
                    f"El horario de {day_name} debe terminar después de empezar."
                )
                continue
            blocks.append((start, end))

        blocks.sort()
        for previous, current in zip(blocks, blocks[1:]):
            if previous[1] > current[0]:
                errors.append(f"Los bloques de {day_name} se superponen.")
                break

        schedules.extend((weekday, start, end) for start, end in blocks)

    if errors:
        raise ProfileFormError(errors)
    return schedules


def blank_form_state() -> dict:
    return {
        "name": "",
        "tagline": "",
        "bio": "",
        "mp_alias": "",
        "email": "",
        "active": True,
        "specialty_ids": [],
        "schedule_rows": [
            {
                "weekday": weekday,
                "name": WEEKDAYS[weekday],
                "blocks": [
                    {"start": "", "end": ""},
                    {"start": "", "end": ""},
                ],
            }
            for weekday in range(7)
        ],
    }


def form_state_from_barber(barber: Barber) -> dict:
    return {
        "name": barber.name,
        "tagline": barber.tagline or "",
        "bio": barber.bio or "",
        "mp_alias": barber.mp_alias or "",
        "email": barber.account.email if barber.account else "",
        "active": barber.active,
        "specialty_ids": [specialty.id for specialty in barber.specialties],
        "schedule_rows": schedule_rows_from_barber(barber),
    }


def form_state_from_form(
    form,
    *,
    existing: Barber | None = None,
    self_service: bool = False,
) -> dict:
    if self_service and existing is not None:
        email = existing.account.email if existing.account else ""
        active = existing.active
    else:
        email = str(form.get("email") or "")
        active = str(form.get("active") or "").lower() in {"on", "true", "1", "yes"}

    specialty_ids: list[int] = []
    for raw in form.getlist("specialty_ids"):
        try:
            specialty_ids.append(int(raw))
        except (TypeError, ValueError):
            continue

    return {
        "name": str(form.get("name") or ""),
        "tagline": str(form.get("tagline") or ""),
        "bio": str(form.get("bio") or ""),
        "mp_alias": str(form.get("mp_alias") or ""),
        "email": email,
        "active": active,
        "specialty_ids": specialty_ids,
        "schedule_rows": schedule_rows_from_form(form),
    }


def parse_profile_form(
    form,
    *,
    existing: Barber | None = None,
    self_service: bool = False,
    require_password: bool = False,
    require_schedule_when_active: bool = False,
) -> BarberProfileData:
    errors: list[str] = []
    schedule_rows = schedule_rows_from_form(form)

    name = _clean(form.get("name"))
    tagline = _clean(form.get("tagline")) or None
    bio = _clean_multiline(form.get("bio")) or None
    raw_alias = _clean(form.get("mp_alias")).lstrip("$").lower()
    mp_alias: str | None = raw_alias or None

    if len(name) < 2:
        errors.append("Ingresá el nombre del barbero.")
    elif len(name) > 120:
        errors.append("El nombre no puede superar los 120 caracteres.")
    if tagline and len(tagline) > 200:
        errors.append("La frase corta no puede superar los 200 caracteres.")
    if bio and len(bio) > 2000:
        errors.append("La descripción no puede superar los 2000 caracteres.")
    if mp_alias and (
        len(mp_alias) < 3
        or len(mp_alias) > 80
        or not re.fullmatch(r"[a-z0-9._-]+", mp_alias)
    ):
        errors.append(
            "El alias de Mercado Pago debe tener entre 3 y 80 caracteres "
            "(letras, números, puntos, guiones o guiones bajos)."
        )

    if self_service and existing is not None:
        email = existing.account.email if existing.account else None
        password = None
        active = existing.active
    else:
        raw_email = _clean(form.get("email"))
        email = None
        if raw_email:
            try:
                email = normalize_email(str(_email_adapter.validate_python(raw_email)))
            except ValidationError:
                errors.append("Ingresá un email válido para el acceso del barbero.")
        password = str(form.get("password") or "").strip() or None
        active = str(form.get("active") or "").lower() in {"on", "true", "1", "yes"}

    has_account = bool(existing and existing.account)

    if not self_service:
        if not email and (require_password or has_account):
            errors.append("Ingresá el email de acceso del barbero.")
        if password:
            if len(password) < 8:
                errors.append("La contraseña debe tener al menos 8 caracteres.")
            elif len(password) > 128:
                errors.append("La contraseña no puede superar los 128 caracteres.")
        elif require_password:
            errors.append("Definí una contraseña inicial para el barbero.")
        if email and not password and not has_account:
            errors.append(
                "Para crear el acceso, definí también una contraseña inicial."
            )
        if password and not email:
            errors.append("El acceso necesita un email además de la contraseña.")

    specialty_ids: list[int] = []
    for raw in form.getlist("specialty_ids"):
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value not in specialty_ids:
            specialty_ids.append(value)

    try:
        schedules = parse_schedule_rows(schedule_rows)
    except ProfileFormError as exc:
        errors.extend(exc.errors)
        schedules = []

    if require_schedule_when_active and active and not schedules:
        errors.append(
            "Para dejar el perfil activo, cargá al menos un día y horario de trabajo."
        )

    if errors:
        raise ProfileFormError(errors)

    return BarberProfileData(
        name=name,
        tagline=tagline,
        bio=bio,
        mp_alias=mp_alias,
        email=email,
        password=password,
        active=active,
        specialty_ids=specialty_ids,
        schedules=schedules,
        schedule_rows=schedule_rows,
    )


def _load_specialties(db: Session, specialty_ids: list[int]) -> list[Specialty]:
    if not specialty_ids:
        return []
    specialties = list(
        db.scalars(
            select(Specialty).where(Specialty.id.in_(specialty_ids))
        ).all()
    )
    if len({specialty.id for specialty in specialties}) != len(specialty_ids):
        raise ProfileFormError(
            ["Una de las especialidades seleccionadas ya no existe."]
        )
    return specialties


def _account_email_taken(
    db: Session, email: str, *, exclude_barber_id: int | None = None
) -> bool:
    stmt = select(BarberAccount.id).where(BarberAccount.email == email)
    if exclude_barber_id is not None:
        stmt = stmt.where(BarberAccount.barber_id != exclude_barber_id)
    return db.scalar(stmt) is not None



def create_barber_profile(
    db: Session,
    data: BarberProfileData,
    *,
    barberia_id: int,
    avatar_url: str | None = None,
) -> Barber:
    if not data.email or not data.password:
        raise ProfileFormError(
            ["El perfil necesita un email y una contraseña de acceso."]
        )

    if _account_email_taken(db, data.email):
        raise ProfileFormError(
            ["Ya existe una cuenta con ese email."]
        )

    specialties = _load_specialties(db, data.specialty_ids)

    barber = Barber(
        barberia_id=barberia_id,
        name=data.name,
        slug=unique_slug(db, data.name),
        tagline=data.tagline,
        bio=data.bio,
        mp_alias=data.mp_alias,
        avatar_url=avatar_url,
        active=data.active,
        specialties=specialties,
        schedules=[
            WorkSchedule(
                weekday=weekday,
                start_time=start,
                end_time=end,
            )
            for weekday, start, end in data.schedules
        ],
    )

    BarberAccount(
        email=data.email,
        password_hash=hash_password(data.password),
        barber=barber,
    )

    db.add(barber)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ProfileFormError(
            ["No pudimos guardar el perfil: revisá el email y los horarios."]
        ) from None

    return barber

def update_barber_profile(
    db: Session,
    barber: Barber,
    data: BarberProfileData,
    *,
    avatar_url: str | None = None,
    remove_avatar: bool = False,
    self_service: bool = False,
) -> Barber:
    if not self_service:
        if data.email:
            if _account_email_taken(
                db, data.email, exclude_barber_id=barber.id
            ):
                raise ProfileFormError(["Ya existe una cuenta con ese email."])
            if barber.account is None:
                if not data.password:
                    raise ProfileFormError(
                        ["Definí una contraseña inicial para crear el acceso."]
                    )
                account = BarberAccount(
                    email=data.email,
                    password_hash=hash_password(data.password),
                    barber=barber,
                )
                db.add(account)
            else:
                barber.account.email = data.email
                if data.password:
                    barber.account.password_hash = hash_password(data.password)
        elif barber.account is not None:
            raise ProfileFormError(
                ["El perfil tiene acceso activo: ingresá su email."]
            )

    specialties = _load_specialties(db, data.specialty_ids)
    barber.name = data.name
    barber.tagline = data.tagline
    barber.bio = data.bio
    barber.mp_alias = data.mp_alias
    barber.active = data.active
    barber.specialties = specialties

    barber.schedules.clear()
    db.flush()
    barber.schedules.extend(
        WorkSchedule(weekday=weekday, start_time=start, end_time=end)
        for weekday, start, end in data.schedules
    )

    if avatar_url:
        barber.avatar_url = avatar_url
    elif remove_avatar:
        barber.avatar_url = None

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ProfileFormError(
            ["No pudimos guardar los cambios: revisá el email y los horarios."]
        ) from None
    return barber


def delete_barber_profile(db: Session, barber: Barber) -> None:
    pending = db.scalar(
        select(Appointment.id)
        .where(
            Appointment.barber_id == barber.id,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
        )
        .limit(1)
    )
    if pending is not None:
        raise ProfileFormError(
            [
                "El barbero tiene turnos pendientes. Resolvelos (completar, "
                "cancelar o marcar ausencia) antes de eliminar su perfil."
            ]
        )

    if barber.account is not None:
        db.delete(barber.account)
    barber.deleted_at = utc_now()
    barber.active = False
    db.commit()


def _image_extension(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def store_avatar(data: bytes) -> str:
    if not data:
        raise ProfileFormError(["La foto está vacía. Elegí otra imagen."])
    if len(data) > AVATAR_MAX_BYTES:
        raise ProfileFormError(["La foto no puede superar los 5 MB."])
    extension = _image_extension(data)
    if extension is None:
        raise ProfileFormError(["La foto debe ser JPG, PNG o WebP."])

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{extension}"
    (AVATAR_DIR / filename).write_bytes(data)
    return f"{AVATAR_URL_PREFIX}{filename}"


def delete_avatar_file(avatar_url: str | None) -> None:
    if not avatar_url or not avatar_url.startswith(AVATAR_URL_PREFIX):
        return
    filename = avatar_url.removeprefix(AVATAR_URL_PREFIX)
    if not filename or "/" in filename or "\\" in filename:
        return
    path = AVATAR_DIR / filename
    if path.is_file():
        path.unlink()


_MP4_BRANDS = {
    b"isom",
    b"iso2",
    b"iso4",
    b"iso5",
    b"mp41",
    b"mp42",
    b"avc1",
    b"M4V ",
    b"dash",
    b"mmp4",
    b"MSNV",
}


def _video_extension(data: bytes) -> str | None:
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _MP4_BRANDS:
        return "mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    return None


def store_portfolio_media(data: bytes) -> tuple[str, str]:
    if not data:
        raise ProfileFormError(["El archivo está vacío. Elegí otra foto o video."])

    image_extension = _image_extension(data)
    if image_extension:
        if len(data) > PORTFOLIO_IMAGE_MAX_BYTES:
            raise ProfileFormError(["La foto no puede superar los 8 MB."])
        media_type, extension = "image", image_extension
    else:
        video_extension = _video_extension(data)
        if video_extension is None:
            raise ProfileFormError(
                ["Formato no admitido. Subí JPG, PNG, WebP, MP4 o WebM."]
            )
        if len(data) > PORTFOLIO_VIDEO_MAX_BYTES:
            raise ProfileFormError(["El video no puede superar los 25 MB."])
        media_type, extension = "video", video_extension

    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{extension}"
    (PORTFOLIO_DIR / filename).write_bytes(data)
    return media_type, f"{PORTFOLIO_URL_PREFIX}{filename}"


def delete_portfolio_file(media_url: str | None) -> None:
    if not media_url or not media_url.startswith(PORTFOLIO_URL_PREFIX):
        return
    filename = media_url.removeprefix(PORTFOLIO_URL_PREFIX)
    if not filename or "/" in filename or "\\" in filename:
        return
    path = PORTFOLIO_DIR / filename
    if path.is_file():
        path.unlink()


def add_portfolio_item(
    db: Session,
    barber: Barber,
    *,
    data: bytes,
    caption: str = "",
) -> PortfolioItem:
    if len(barber.portfolio_items) >= PORTFOLIO_MAX_ITEMS:
        raise ProfileFormError(
            [f"La galería admite hasta {PORTFOLIO_MAX_ITEMS} trabajos. Quitá alguno para sumar otro."]
        )

    media_type, media_url = store_portfolio_media(data)
    clean_caption = _clean(caption)[:160] or None
    sort_order = max(
        (item.sort_order for item in barber.portfolio_items), default=0
    ) + 1
    item = PortfolioItem(
        barber=barber,
        image_url=media_url,
        media_type=media_type,
        caption=clean_caption,
        sort_order=sort_order,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        delete_portfolio_file(media_url)
        raise ProfileFormError(
            ["No pudimos guardar el trabajo. Intentá de nuevo."]
        ) from None
    return item


def delete_portfolio_item(db: Session, barber: Barber, item_id: int) -> None:
    item = next((entry for entry in barber.portfolio_items if entry.id == item_id), None)
    if item is None:
        raise ProfileFormError(["No encontramos ese trabajo en la galería."])
    media_url = item.image_url
    db.delete(item)
    db.commit()
    delete_portfolio_file(media_url)
