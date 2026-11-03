from __future__ import annotations

import calendar
from datetime import date, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.auth import (
    LoginRequired,
    authenticate_staff,
    is_barber,
    is_owner,
    require_barber_page,
    require_owner_page,
    session_barber_id,
)
from app.config import get_settings
from app.database import get_db
from app.formatting import date_input_value
from app.models import (
    AppointmentStatus,
    Barber,
    Barberia,
    DailyClosing,
    PaymentMethod,
    Service,
    Specialty,
)
from app.services.booking import get_appointment_by_code
from app.services.barbers import (
    ProfileFormError,
    add_portfolio_item,
    blank_form_state,
    create_barber_profile,
    delete_avatar_file,
    delete_barber_profile,
    delete_portfolio_item,
    form_state_from_barber,
    form_state_from_form,
    parse_profile_form,
    store_avatar,
    update_barber_profile,
)
from app.services.clients import calculate_stats, get_client, search_clients
from app.services.closings import close_day
from app.services.errors import NotFoundError
from app.services.scheduling import build_queue
from app.templating import templates
from app.timeutils import business_today, to_business
from app.tenancy import obtener_barberia_actual

router = APIRouter(tags=["Páginas"])


def _not_found(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="not_found.html",
        context={"message": message},
        status_code=404,
    )


def _start_staff_session(
    request: Request,
    *,
    role: str,
    display_name: str,
    barber_id: int | None = None,
) -> None:
    request.session.clear()
    request.session["role"] = role
    request.session["is_admin"] = role == "owner"
    request.session["admin_username"] = display_name
    if barber_id is not None:
        request.session["barber_id"] = barber_id


def _current_barber(request: Request, db: Session) -> Barber:
    barber_id = session_barber_id(request)
    barber = db.get(Barber, barber_id) if barber_id else None
    if barber is None or barber.deleted_at is not None:
        # Sin limpiar la sesión, /mi-agenda y /admin/login se redirigen en bucle.
        request.session.clear()
        raise LoginRequired()
    return barber


MONTH_NAMES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _month_context(raw: str, today: date) -> dict:
    try:
        year_text, month_text = raw.split("-", 1)
        start = date(int(year_text), int(month_text), 1)
    except (AttributeError, TypeError, ValueError):
        start = today.replace(day=1)
    last_day = calendar.monthrange(start.year, start.month)[1]
    end = date(start.year, start.month, last_day)
    return {
        "key": start.strftime("%Y-%m"),
        "start": start,
        "end": end,
        "label": f"{MONTH_NAMES[start.month - 1]} {start.year}",
        "previous": (start - timedelta(days=1)).strftime("%Y-%m"),
        "next": (end + timedelta(days=1)).strftime("%Y-%m"),
    }


def _specialties(db: Session) -> list[Specialty]:
    return list(db.scalars(select(Specialty).order_by(Specialty.name)).all())


def _barber_form_context(
    request: Request,
    *,
    db: Session,
    form_state: dict,
    mode: str,
    action_url: str,
    barber: Barber | None = None,
    errors: list[str] | None = None,
    is_self_service: bool = False,
) -> dict:
    return {
        "form_state": form_state,
        "specialties": _specialties(db),
        "mode": mode,
        "action_url": action_url,
        "barber": barber,
        "errors": errors or [],
        "is_self_service": is_self_service,
        "has_account": bool(barber and barber.account),
        "current_barber": barber if is_self_service else None,
        "business_timezone": get_settings().business_timezone,
    }


def _get_barber_or_404(db: Session, barber_id: int) -> Barber | None:
    barber = db.get(Barber, barber_id)
    if barber is None or barber.deleted_at is not None:
        return None
    return barber


def _portfolio_context(
    request: Request,
    barber: Barber,
    *,
    add_url: str,
    delete_base: str,
) -> dict:
    return {
        "portfolio_items": barber.portfolio_items,
        "portfolio_add_url": add_url,
        "portfolio_delete_base": delete_base,
        "portfolio_added": request.query_params.get("trabajo") == "1",
        "portfolio_deleted": request.query_params.get("trabajo_borrado") == "1",
        "portfolio_error": request.query_params.get("trabajo_error") or "",
    }


def _portfolio_redirect(
    target: str,
    *,
    added: bool = False,
    deleted: bool = False,
    error: str = "",
) -> RedirectResponse:
    params = []
    if added:
        params.append("trabajo=1")
    if deleted:
        params.append("trabajo_borrado=1")
    if error:
        params.append(f"trabajo_error={quote(error)}")
    query = "&".join(params)
    url = f"{target}?{query}#trabajos" if query else f"{target}#trabajos"
    return RedirectResponse(url=url, status_code=303)


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    settings = get_settings()

    services = list(
        db.scalars(
            select(Service)
            .where(
                Service.active.is_(True),
                Service.barberia_id == barberia.id,
            )
            .order_by(Service.price_cents)
        ).all()
    )

    barbers = list(
        db.scalars(
            select(Barber)
            .where(
                Barber.active.is_(True),
                Barber.barberia_id == barberia.id,
            )
            .order_by(Barber.name)
        ).all()
    )

    today = business_today()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "services": services,
            "barbers": barbers,
            "today": today.isoformat(),
            "max_day": (
                today + timedelta(days=settings.booking_days_ahead)
            ).isoformat(),
            "min_notice_minutes": settings.min_notice_minutes,
            "payments_mode": settings.payments_mode,
            "business_timezone": settings.business_timezone,
        },
    )


@router.get("/barberos", response_class=HTMLResponse)
def barbers_page(
    request: Request,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    barbers = list(
        db.scalars(
            select(Barber)
            .where(
                Barber.active.is_(True),
                Barber.barberia_id == barberia.id,
            )
            .order_by(Barber.name)
        ).all()
    )

    return templates.TemplateResponse(
        request=request,
        name="barbers.html",
        context={"barbers": barbers},
    )


@router.get("/barberos/{slug}/trabajos", response_class=HTMLResponse)
def barber_works_page(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    barber = db.scalar(
        select(Barber).where(
            Barber.slug == slug,
            Barber.active.is_(True),
            Barber.barberia_id == barberia.id,
        )
    )

    if barber is None:
        return _not_found(request, "No encontramos ese barbero.")

    return templates.TemplateResponse(
        request=request,
        name="barber_works.html",
        context={"barber": barber},
    )


@router.get("/reserva/{public_code}", response_class=HTMLResponse)
def reservation_page(
    request: Request,
    public_code: str,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    try:
        appointment = get_appointment_by_code(db, public_code)

        if (
            appointment.barber.barberia_id != barberia.id
            or appointment.service.barberia_id != barberia.id
        ):
            raise NotFoundError("No encontramos ese turno.")

    except NotFoundError as exc:
        return _not_found(request, exc.message)

    day = to_business(appointment.start_at).date()
    entries = build_queue(db, appointment.barber, day)

    entry = next(
        (
            item for item in entries
            if item.appointment.id == appointment.id
        ),
        None,
    )

    has_mock_payment = any(
        payment.method == PaymentMethod.mock
        for payment in appointment.payments
    )

    return templates.TemplateResponse(
        request=request,
        name="confirmation.html",
        context={
            "appointment": appointment,
            "queue_entry": entry,
            "cancellable": (
                appointment.status == AppointmentStatus.confirmed
            ),
            "has_mock_payment": has_mock_payment,
            "business_timezone": get_settings().business_timezone,
        },
    )


@router.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request):
    if is_owner(request):
        return RedirectResponse(url="/admin", status_code=303)
    if is_barber(request):
        return RedirectResponse(url="/mi-agenda", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="admin/login.html",
        context={},
    )


@router.post("/admin/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    identity = authenticate_staff(db, username, password)
    if identity is None:
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"error": "Usuario o contraseña incorrectos."},
            status_code=401,
        )

    _start_staff_session(
        request,
        role=identity.role,
        display_name=identity.display_name,
        barber_id=identity.barber_id,
    )
    target = "/admin" if identity.is_owner else "/mi-agenda"
    return RedirectResponse(url=target, status_code=303)


@router.post("/admin/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("/admin", response_class=HTMLResponse)
def admin_home(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    barbers = list(
        db.scalars(
            select(Barber)
            .where(Barber.deleted_at.is_(None))
            .order_by(Barber.active.desc(), Barber.name)
        ).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/home.html",
        context={
            "barbers": barbers,
            "updated": request.query_params.get("actualizado") == "1",
            "deleted": request.query_params.get("eliminado") == "1",
            "error": request.query_params.get("error"),
            "admin_username": request.session.get("admin_username", "admin"),
            "business_timezone": get_settings().business_timezone,
        },
    )


@router.get("/admin/agenda", response_class=HTMLResponse)
def admin_agenda(
    request: Request,
    barber_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    barbers = list(
        db.scalars(
            select(Barber).where(Barber.active.is_(True)).order_by(Barber.name)
        ).all()
    )
    selected = next(
        (barber for barber in barbers if barber.id == barber_id), None
    )
    if selected is None and barbers:
        selected = barbers[0]
    today = business_today()
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "barbers": barbers,
            "selected_barber_id": selected.id if selected else None,
            "today": date_input_value(today),
            "max_day": date_input_value(
                today + timedelta(days=get_settings().booking_days_ahead)
            ),
            "is_owner": True,
            "can_reschedule": True,
            "client_detail": True,
            "current_barber": None,
            "admin_username": request.session.get("admin_username", "admin"),
            "business_timezone": get_settings().business_timezone,
        },
    )


@router.get("/admin/clientes", response_class=HTMLResponse)
def admin_clients(
    request: Request,
    q: str = Query(default=""),
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    rows = search_clients(db, q)
    return templates.TemplateResponse(
        request=request,
        name="admin/clients.html",
        context={
            "rows": rows,
            "query": q,
            "admin_username": request.session.get("admin_username", "admin"),
        },
    )


@router.get("/admin/clientes/{client_id}", response_class=HTMLResponse)
def admin_client_detail(
    request: Request,
    client_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    try:
        client = get_client(db, client_id)
    except NotFoundError as exc:
        return _not_found(request, exc.message)

    return templates.TemplateResponse(
        request=request,
        name="admin/client_detail.html",
        context={
            "client": client,
            "stats": calculate_stats(client),
            "admin_username": request.session.get("admin_username", "admin"),
        },
    )


# ---------- Owner: barber management ----------


@router.get("/admin/barberos", response_class=HTMLResponse)
def admin_barbers(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    barbers = list(
        db.scalars(
            select(Barber)
            .where(Barber.deleted_at.is_(None))
            .order_by(Barber.active.desc(), Barber.name)
        ).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/barbers.html",
        context={
            "barbers": barbers,
            "created": request.query_params.get("creado") == "1",
            "updated": request.query_params.get("actualizado") == "1",
            "deleted": request.query_params.get("eliminado") == "1",
            "status_error": request.query_params.get("error"),
            "admin_username": request.session.get("admin_username", "admin"),
        },
    )


@router.get("/admin/mi-perfil", response_class=HTMLResponse)
def admin_owner_profile(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    barbers = list(
        db.scalars(
            select(Barber)
            .where(Barber.deleted_at.is_(None))
            .order_by(Barber.active.desc(), Barber.name)
        ).all()
    )
    owner_username = get_settings().admin_username
    return templates.TemplateResponse(
        request=request,
        name="admin/owner_profile.html",
        context={
            "barbers": barbers,
            "metrics": {
                "team": len(barbers),
                "active": sum(1 for barber in barbers if barber.active),
                "pending": sum(1 for barber in barbers if not barber.active),
                "with_access": sum(
                    1 for barber in barbers if barber.account is not None
                ),
            },
            "created": request.query_params.get("creado") == "1",
            "updated": request.query_params.get("actualizado") == "1",
            "deleted": request.query_params.get("eliminado") == "1",
            "status_error": request.query_params.get("error"),
            "owner_username": owner_username,
            "business_timezone": get_settings().business_timezone,
            "admin_username": owner_username,
        },
    )


@router.get("/admin/barberos/nuevo", response_class=HTMLResponse)
def admin_barber_new(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    context = _barber_form_context(
        request,
        db=db,
        form_state=blank_form_state(),
        mode="create",
        action_url="/admin/barberos/nuevo",
    )
    context["admin_username"] = request.session.get("admin_username", "admin")
    return templates.TemplateResponse(
        request=request,
        name="admin/barber_form.html",
        context=context,
    )


@router.post("/admin/barberos/nuevo", response_class=HTMLResponse)
async def admin_barber_create(
    request: Request,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
    _: None = Depends(require_owner_page),
):
    form = await request.form()
    form_state = form_state_from_form(form)
    stored_avatar_url: str | None = None

    try:
        data = parse_profile_form(
            form,
            require_password=True,
            require_schedule_when_active=True,
        )
        upload = form.get("avatar")
        if isinstance(upload, UploadFile) and upload.filename:
            stored_avatar_url = store_avatar(await upload.read())
        barber = create_barber_profile(
    db,
    data,
    barberia_id=barberia.id,
    avatar_url=stored_avatar_url,
)
    except ProfileFormError as exc:
        delete_avatar_file(stored_avatar_url)
        context = _barber_form_context(
            request,
            db=db,
            form_state=form_state,
            mode="create",
            action_url="/admin/barberos/nuevo",
            errors=exc.errors,
        )
        context["admin_username"] = request.session.get(
            "admin_username", "admin"
        )
        return templates.TemplateResponse(
            request=request,
            name="admin/barber_form.html",
            context=context,
            status_code=400,
        )

    return RedirectResponse(url="/admin/barberos?creado=1", status_code=303)


@router.get("/admin/barberos/{barber_id}", response_class=HTMLResponse)
def admin_barber_edit(
    request: Request,
    barber_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    barber = _get_barber_or_404(db, barber_id)
    if barber is None:
        return _not_found(request, "No encontramos ese barbero.")

    context = _barber_form_context(
        request,
        db=db,
        form_state=form_state_from_barber(barber),
        mode="edit",
        action_url=f"/admin/barberos/{barber.id}",
        barber=barber,
    )
    context["admin_username"] = request.session.get("admin_username", "admin")
    context["saved"] = request.query_params.get("guardado") == "1"
    context.update(
        _portfolio_context(
            request,
            barber,
            add_url=f"/admin/barberos/{barber.id}/trabajos",
            delete_base=f"/admin/barberos/{barber.id}/trabajos",
        )
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/barber_form.html",
        context=context,
    )


@router.post("/admin/barberos/{barber_id}", response_class=HTMLResponse)
async def admin_barber_update(
    request: Request,
    barber_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    barber = _get_barber_or_404(db, barber_id)
    if barber is None:
        return _not_found(request, "No encontramos ese barbero.")

    form = await request.form()
    form_state = form_state_from_form(form, existing=barber)
    stored_avatar_url: str | None = None
    previous_avatar_url = barber.avatar_url

    try:
        data = parse_profile_form(
            form,
            existing=barber,
            require_schedule_when_active=True,
        )
        upload = form.get("avatar")
        if isinstance(upload, UploadFile) and upload.filename:
            stored_avatar_url = store_avatar(await upload.read())
        remove_avatar = str(form.get("remove_avatar") or "").lower() in {
            "on",
            "true",
            "1",
            "yes",
        }
        update_barber_profile(
            db,
            barber,
            data,
            avatar_url=stored_avatar_url,
            remove_avatar=remove_avatar and not stored_avatar_url,
        )
    except ProfileFormError as exc:
        delete_avatar_file(stored_avatar_url)
        context = _barber_form_context(
            request,
            db=db,
            form_state=form_state,
            mode="edit",
            action_url=f"/admin/barberos/{barber.id}",
            barber=barber,
            errors=exc.errors,
        )
        context["admin_username"] = request.session.get(
            "admin_username", "admin"
        )
        context.update(
            _portfolio_context(
                request,
                barber,
                add_url=f"/admin/barberos/{barber.id}/trabajos",
                delete_base=f"/admin/barberos/{barber.id}/trabajos",
            )
        )
        return templates.TemplateResponse(
            request=request,
            name="admin/barber_form.html",
            context=context,
            status_code=400,
        )

    if stored_avatar_url or previous_avatar_url != barber.avatar_url:
        delete_avatar_file(previous_avatar_url)
    return RedirectResponse(
        url=f"/admin/barberos/{barber.id}?guardado=1", status_code=303
    )


@router.post("/admin/barberos/{barber_id}/trabajos")
async def admin_barber_portfolio_add(
    request: Request,
    barber_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    barber = _get_barber_or_404(db, barber_id)
    if barber is None:
        return _not_found(request, "No encontramos ese barbero.")

    form = await request.form()
    upload = form.get("media")
    try:
        if not isinstance(upload, UploadFile) or not upload.filename:
            raise ProfileFormError(
                ["Elegí una foto o un video para agregar a la galería."]
            )
        add_portfolio_item(
            db,
            barber,
            data=await upload.read(),
            caption=str(form.get("caption") or ""),
        )
    except ProfileFormError as exc:
        return _portfolio_redirect(
            f"/admin/barberos/{barber.id}", error=" ".join(exc.errors)
        )
    return _portfolio_redirect(f"/admin/barberos/{barber.id}", added=True)


@router.post("/admin/barberos/{barber_id}/trabajos/{item_id}/eliminar")
def admin_barber_portfolio_delete(
    request: Request,
    barber_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    barber = _get_barber_or_404(db, barber_id)
    if barber is None:
        return _not_found(request, "No encontramos ese barbero.")
    try:
        delete_portfolio_item(db, barber, item_id)
    except ProfileFormError as exc:
        return _portfolio_redirect(
            f"/admin/barberos/{barber.id}", error=" ".join(exc.errors)
        )
    return _portfolio_redirect(f"/admin/barberos/{barber.id}", deleted=True)


@router.post("/admin/barberos/{barber_id}/estado")
def admin_barber_status(
    request: Request,
    barber_id: int,
    active: str = Form(...),
    origin: str = Form(default=""),
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    barber = _get_barber_or_404(db, barber_id)
    if barber is None:
        return _not_found(request, "No encontramos ese barbero.")

    base_url = {
        "home": "/admin",
        "perfil": "/admin/mi-perfil",
    }.get(origin, "/admin/barberos")
    target_active = active == "1"
    if target_active and not barber.schedules:
        return RedirectResponse(
            url=f"{base_url}?error=sin-horarios", status_code=303
        )
    barber.active = target_active
    db.commit()
    return RedirectResponse(url=f"{base_url}?actualizado=1", status_code=303)


@router.post("/admin/barberos/{barber_id}/eliminar")
def admin_barber_delete(
    request: Request,
    barber_id: int,
    origin: str = Form(default=""),
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    barber = _get_barber_or_404(db, barber_id)
    if barber is None:
        return _not_found(request, "No encontramos ese barbero.")

    base_url = {
        "home": "/admin",
        "perfil": "/admin/mi-perfil",
    }.get(origin, "/admin/barberos")
    try:
        delete_barber_profile(db, barber)
    except ProfileFormError:
        return RedirectResponse(
            url=f"{base_url}?error=turnos-pendientes", status_code=303
        )
    return RedirectResponse(url=f"{base_url}?eliminado=1", status_code=303)


# ---------- Owner: daily closings ----------


@router.get("/admin/cierres", response_class=HTMLResponse)
def admin_closings(
    request: Request,
    month: str = Query(default=""),
    barber_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    today = business_today()
    period = _month_context(month, today)

    statement = select(DailyClosing).where(
        DailyClosing.business_date >= period["start"],
        DailyClosing.business_date <= period["end"],
    )
    if barber_id is not None:
        statement = statement.where(DailyClosing.barber_id == barber_id)
    rows = list(
        db.scalars(
            statement.order_by(
                DailyClosing.business_date.desc(), DailyClosing.barber_name
            )
        ).all()
    )

    barbers = list(db.scalars(select(Barber).order_by(Barber.name)).all())
    totals = {
        "appointments": sum(row.appointments_count for row in rows),
        "completed": sum(row.completed_count for row in rows),
        "revenue": sum(row.service_revenue_cents for row in rows),
        "collected": sum(row.collected_cents for row in rows),
        "pending": sum(row.pending_cents for row in rows),
    }
    return templates.TemplateResponse(
        request=request,
        name="admin/closings.html",
        context={
            "rows": rows,
            "period": period,
            "barbers": barbers,
            "selected_barber_id": barber_id,
            "totals": totals,
            "today": today.isoformat(),
            "saved": request.query_params.get("guardado") == "1",
            "recalculated": request.query_params.get("recalculado") == "1",
            "error": request.query_params.get("error"),
            "closing_enabled": get_settings().daily_close_enabled,
            "closing_time": (
                f"{get_settings().daily_close_hour:02d}:"
                f"{get_settings().daily_close_minute:02d}"
            ),
            "admin_username": request.session.get("admin_username", "admin"),
        },
    )


@router.get("/admin/reportes", response_class=HTMLResponse)
def admin_reports(
    request: Request,
    month: str = Query(default=""),
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    today = business_today()
    period = _month_context(month, today)
    rows = list(
        db.scalars(
            select(DailyClosing)
            .where(
                DailyClosing.business_date >= period["start"],
                DailyClosing.business_date <= period["end"],
            )
            .order_by(DailyClosing.business_date)
        ).all()
    )

    by_barber: dict[int, dict] = {}
    by_day: dict[date, int] = {}
    for row in rows:
        bucket = by_barber.setdefault(
            row.barber_id,
            {
                "barber_id": row.barber_id,
                "name": row.barber_name,
                "revenue": 0,
                "collected": 0,
                "pending": 0,
                "completed": 0,
                "cancelled": 0,
                "no_show": 0,
                "appointments": 0,
                "days": 0,
            },
        )
        bucket["revenue"] += row.service_revenue_cents
        bucket["collected"] += row.collected_cents
        bucket["pending"] += row.pending_cents
        bucket["completed"] += row.completed_count
        bucket["cancelled"] += row.cancelled_count
        bucket["no_show"] += row.no_show_count
        bucket["appointments"] += row.appointments_count
        bucket["days"] += 1
        by_day[row.business_date] = (
            by_day.get(row.business_date, 0) + row.service_revenue_cents
        )

    barber_rows = sorted(
        by_barber.values(), key=lambda item: item["revenue"], reverse=True
    )
    max_revenue = max((item["revenue"] for item in barber_rows), default=0)
    for item in barber_rows:
        item["share"] = (
            round(100 * item["revenue"] / max_revenue) if max_revenue else 0
        )

    last_day = calendar.monthrange(period["start"].year, period["start"].month)[1]
    trend = [
        {
            "date": date(period["start"].year, period["start"].month, day_num),
            "revenue": by_day.get(
                date(period["start"].year, period["start"].month, day_num), 0
            ),
        }
        for day_num in range(1, last_day + 1)
    ]
    max_day_revenue = max((item["revenue"] for item in trend), default=0)
    active_days = sum(1 for item in trend if item["revenue"] > 0)

    totals = {
        "appointments": sum(item["appointments"] for item in barber_rows),
        "completed": sum(item["completed"] for item in barber_rows),
        "cancelled": sum(item["cancelled"] for item in barber_rows),
        "no_show": sum(item["no_show"] for item in barber_rows),
        "revenue": sum(item["revenue"] for item in barber_rows),
        "collected": sum(item["collected"] for item in barber_rows),
        "pending": sum(item["pending"] for item in barber_rows),
        "active_days": active_days,
    }
    totals["no_show_rate"] = (
        round(100 * totals["no_show"] / totals["appointments"])
        if totals["appointments"]
        else 0
    )

    return templates.TemplateResponse(
        request=request,
        name="admin/reports.html",
        context={
            "period": period,
            "totals": totals,
            "barber_rows": barber_rows,
            "trend": trend,
            "max_day_revenue": max_day_revenue,
            "last_day": last_day,
            "admin_username": request.session.get("admin_username", "admin"),
            "business_timezone": get_settings().business_timezone,
        },
    )


@router.post("/admin/cierres")
def admin_close_day(
    request: Request,
    closing_date: str = Form(..., alias="date"),
    db: Session = Depends(get_db),
    _: None = Depends(require_owner_page),
):
    try:
        day = date.fromisoformat(closing_date)
    except ValueError:
        return RedirectResponse(
            url="/admin/cierres?error=fecha-invalida", status_code=303
        )

    if day > business_today():
        return RedirectResponse(
            url="/admin/cierres?error=fecha-futura", status_code=303
        )

    existed = (
        db.scalar(
            select(DailyClosing.id)
            .where(DailyClosing.business_date == day)
            .limit(1)
        )
        is not None
    )
    rows = close_day(db, day)
    if not rows:
        return RedirectResponse(
            url="/admin/cierres?error=sin-barberos", status_code=303
        )

    month = day.strftime("%Y-%m")
    suffix = "recalculado=1" if existed else "guardado=1"
    return RedirectResponse(
        url=f"/admin/cierres?month={month}&{suffix}", status_code=303
    )


# ---------- Team access: registration and barber self-service ----------


@router.get("/equipo/registro", response_class=HTMLResponse)
def barber_register_page(request: Request, db: Session = Depends(get_db)):
    if is_owner(request):
        return RedirectResponse(url="/admin", status_code=303)
    if is_barber(request):
        return RedirectResponse(url="/mi-agenda", status_code=303)

    context = _barber_form_context(
        request,
        db=db,
        form_state=blank_form_state(),
        mode="register",
        action_url="/equipo/registro",
        is_self_service=False,
    )
    context["form_state"]["active"] = False
    return templates.TemplateResponse(
        request=request,
        name="admin/barber_register.html",
        context=context,
    )


@router.post("/equipo/registro", response_class=HTMLResponse)
async def barber_register(
    request: Request,
    db: Session = Depends(get_db),
    barberia: Barberia = Depends(obtener_barberia_actual),
):
    form = await request.form()
    form_state = form_state_from_form(form)
    stored_avatar_url: str | None = None

    try:
        data = parse_profile_form(form, require_password=True)
        data.active = False
        upload = form.get("avatar")
        if isinstance(upload, UploadFile) and upload.filename:
            stored_avatar_url = store_avatar(await upload.read())
        barber = create_barber_profile(
        db,
        data,
        barberia_id=barberia.id,
        avatar_url=stored_avatar_url,
)
    except ProfileFormError as exc:
        delete_avatar_file(stored_avatar_url)
        context = _barber_form_context(
            request,
            db=db,
            form_state=form_state,
            mode="register",
            action_url="/equipo/registro",
            errors=exc.errors,
        )
        context["form_state"]["active"] = False
        return templates.TemplateResponse(
            request=request,
            name="admin/barber_register.html",
            context=context,
            status_code=400,
        )

    _start_staff_session(
        request,
        role="barber",
        display_name=barber.name,
        barber_id=barber.id,
    )
    return RedirectResponse(url="/mi-perfil?bienvenido=1", status_code=303)


@router.get("/mi-agenda", response_class=HTMLResponse)
def barber_agenda(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_barber_page),
):
    barber = _current_barber(request, db)
    today = business_today()
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "barbers": [barber],
            "selected_barber_id": barber.id,
            "today": date_input_value(today),
            "max_day": date_input_value(
                today + timedelta(days=get_settings().booking_days_ahead)
            ),
            "is_owner": False,
            "can_reschedule": False,
            "client_detail": False,
            "current_barber": barber,
            "admin_username": barber.name,
            "business_timezone": get_settings().business_timezone,
        },
    )


@router.get("/mi-perfil", response_class=HTMLResponse)
def barber_profile_page(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_barber_page),
):
    barber = _current_barber(request, db)
    context = _barber_form_context(
        request,
        db=db,
        form_state=form_state_from_barber(barber),
        mode="self",
        action_url="/mi-perfil",
        barber=barber,
        is_self_service=True,
    )
    context.update(
        {
            "admin_username": barber.name,
            "saved": request.query_params.get("guardado") == "1",
            "welcome": request.query_params.get("bienvenido") == "1",
        }
    )
    context.update(
        _portfolio_context(
            request,
            barber,
            add_url="/mi-perfil/trabajos",
            delete_base="/mi-perfil/trabajos",
        )
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/barber_profile.html",
        context=context,
    )


@router.post("/mi-perfil", response_class=HTMLResponse)
async def barber_profile_update(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_barber_page),
):
    barber = _current_barber(request, db)
    form = await request.form()
    form_state = form_state_from_form(form, existing=barber, self_service=True)
    stored_avatar_url: str | None = None
    previous_avatar_url = barber.avatar_url

    try:
        data = parse_profile_form(form, existing=barber, self_service=True)
        upload = form.get("avatar")
        if isinstance(upload, UploadFile) and upload.filename:
            stored_avatar_url = store_avatar(await upload.read())
        remove_avatar = str(form.get("remove_avatar") or "").lower() in {
            "on",
            "true",
            "1",
            "yes",
        }
        update_barber_profile(
            db,
            barber,
            data,
            avatar_url=stored_avatar_url,
            remove_avatar=remove_avatar and not stored_avatar_url,
            self_service=True,
        )
    except ProfileFormError as exc:
        delete_avatar_file(stored_avatar_url)
        context = _barber_form_context(
            request,
            db=db,
            form_state=form_state,
            mode="self",
            action_url="/mi-perfil",
            barber=barber,
            errors=exc.errors,
            is_self_service=True,
        )
        context["admin_username"] = barber.name
        context.update(
            _portfolio_context(
                request,
                barber,
                add_url="/mi-perfil/trabajos",
                delete_base="/mi-perfil/trabajos",
            )
        )
        return templates.TemplateResponse(
            request=request,
            name="admin/barber_profile.html",
            context=context,
            status_code=400,
        )

    if stored_avatar_url or previous_avatar_url != barber.avatar_url:
        delete_avatar_file(previous_avatar_url)
    return RedirectResponse(url="/mi-perfil?guardado=1", status_code=303)


@router.post("/mi-perfil/trabajos")
async def barber_portfolio_add(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_barber_page),
):
    barber = _current_barber(request, db)
    form = await request.form()
    upload = form.get("media")
    try:
        if not isinstance(upload, UploadFile) or not upload.filename:
            raise ProfileFormError(
                ["Elegí una foto o un video para agregar a la galería."]
            )
        add_portfolio_item(
            db,
            barber,
            data=await upload.read(),
            caption=str(form.get("caption") or ""),
        )
    except ProfileFormError as exc:
        return _portfolio_redirect("/mi-perfil", error=" ".join(exc.errors))
    return _portfolio_redirect("/mi-perfil", added=True)


@router.post("/mi-perfil/trabajos/{item_id}/eliminar")
def barber_portfolio_delete(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_barber_page),
):
    barber = _current_barber(request, db)
    try:
        delete_portfolio_item(db, barber, item_id)
    except ProfileFormError as exc:
        return _portfolio_redirect("/mi-perfil", error=" ".join(exc.errors))
    return _portfolio_redirect("/mi-perfil", deleted=True)
