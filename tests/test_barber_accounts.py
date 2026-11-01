from __future__ import annotations

from datetime import time
from urllib.parse import urlencode

from sqlalchemy import select

from app.auth import hash_password, verify_password
from app.models import Barber, BarberAccount
from app.services import barbers as barber_service
from app.timeutils import business_today
from helpers import booking_payload, find_day_with_slots


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"test-image"


def post_form(client, url: str, fields: list[tuple[str, str]], **kwargs):
    return client.post(
        url,
        content=urlencode(fields, doseq=True),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        **kwargs,
    )


def barber_form_payload(
    *,
    name: str,
    email: str,
    password: str,
    specialties: list[int] | None = None,
    schedule_weekdays: tuple[int, ...] = (1, 2),
    active: bool = True,
    tagline: str = "Fade y textura",
) -> list[tuple[str, str]]:
    data: list[tuple[str, str]] = [
        ("name", name),
        ("tagline", tagline),
        ("bio", "Perfil de prueba para el equipo."),
        ("email", email),
        ("password", password),
    ]
    if active:
        data.append(("active", "on"))
    for specialty_id in specialties or []:
        data.append(("specialty_ids", str(specialty_id)))
    for weekday in schedule_weekdays:
        data.extend(
            [
                (f"start_{weekday}_0", "10:00"),
                (f"end_{weekday}_0", "14:00"),
                (f"start_{weekday}_1", "15:00"),
                (f"end_{weekday}_1", "19:00"),
            ]
        )
    return data


def _login_barber(client, email: str, password: str):
    response = client.post(
        "/admin/login",
        data={"username": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/mi-agenda"


def test_password_hash_roundtrip():
    stored = hash_password("una-clave-segura")
    assert stored != "una-clave-segura"
    assert verify_password("una-clave-segura", stored)
    assert not verify_password("otra-clave", stored)


def test_owner_creates_barber_and_barber_gets_own_scoped_panel(
    admin_client, client, db, mateo
):
    specialty = mateo.specialties[0]
    response = post_form(
        admin_client,
        "/admin/barberos/nuevo",
        barber_form_payload(
            name="Nico Prueba",
            email="nico@example.com",
            password="secreto123",
            specialties=[specialty.id],
        ),
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/barberos?creado=1"

    db.expire_all()
    barber = db.scalar(select(Barber).where(Barber.slug == "nico-prueba"))
    assert barber is not None
    assert barber.active is True
    assert len(barber.schedules) == 4
    assert barber.account is not None
    assert barber.account.email == "nico@example.com"
    assert barber.account.password_hash != "secreto123"
    assert verify_password("secreto123", barber.account.password_hash)

    public_page = client.get("/barberos")
    assert "Nico Prueba" in public_page.text

    admin_client.post("/admin/logout", follow_redirects=False)
    _login_barber(admin_client, "nico@example.com", "secreto123")

    agenda = admin_client.get("/mi-agenda")
    assert agenda.status_code == 200
    assert "Mi agenda" in agenda.text
    assert "Nico Prueba" in agenda.text
    assert 'id="admin-barber"' not in agenda.text

    owner_page = admin_client.get("/admin", follow_redirects=False)
    assert owner_page.status_code == 303
    assert owner_page.headers["location"] == "/admin/login"

    own_queue = admin_client.get(
        "/api/admin/queue",
        params={"barber_id": barber.id, "date": business_today().isoformat()},
    )
    assert own_queue.status_code == 200
    assert own_queue.json()["barber"]["id"] == barber.id

    other_queue = admin_client.get(
        "/api/admin/queue",
        params={"barber_id": mateo.id, "date": business_today().isoformat()},
    )
    assert other_queue.status_code == 403


def test_barber_cannot_operate_on_another_barbers_appointment(
    admin_client, db, mateo, corte_clasico
):
    _, slots = find_day_with_slots(db, mateo, corte_clasico)
    booking = admin_client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=slots[0],
            payment_option="later",
        ),
    )
    assert booking.status_code == 201
    appointment_id = booking.json()["id"]

    response = post_form(
        admin_client,
        "/admin/barberos/nuevo",
        barber_form_payload(
            name="Otro Barbero",
            email="otro@example.com",
            password="secreto123",
        ),
        follow_redirects=False,
    )
    assert response.status_code == 303

    admin_client.post("/admin/logout", follow_redirects=False)
    _login_barber(admin_client, "otro@example.com", "secreto123")

    patch = admin_client.patch(
        f"/api/admin/appointments/{appointment_id}/status",
        json={"status": "in_progress"},
    )
    assert patch.status_code == 403

    reschedule = admin_client.post(
        f"/api/admin/appointments/{appointment_id}/reschedule",
        json={
            "barber_id": mateo.id,
            "start_at": slots[-1].isoformat(),
        },
    )
    assert reschedule.status_code == 403


def test_barber_edits_profile_photo_and_schedule(
    admin_client, db, monkeypatch, tmp_path
):
    monkeypatch.setattr(barber_service, "AVATAR_DIR", tmp_path)

    create = post_form(
        admin_client,
        "/admin/barberos/nuevo",
        barber_form_payload(
            name="Perfil Editable",
            email="editable@example.com",
            password="secreto123",
            schedule_weekdays=(1,),
        ),
        follow_redirects=False,
    )
    assert create.status_code == 303

    db.expire_all()
    barber = db.scalar(
        select(Barber).where(Barber.slug == "perfil-editable")
    )
    assert barber is not None
    before_avatar = barber.avatar_url

    admin_client.post("/admin/logout", follow_redirects=False)
    _login_barber(admin_client, "editable@example.com", "secreto123")

    update_data = {
        "name": "Perfil Editado",
        "tagline": "Nueva frase",
        "bio": "Descripción actualizada desde mi perfil.",
        "start_3_0": "09:00",
        "end_3_0": "12:00",
        "start_3_1": "13:00",
        "end_3_1": "18:00",
    }
    response = admin_client.post(
        "/mi-perfil",
        data=update_data,
        files={"avatar": ("foto.png", PNG_BYTES, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/mi-perfil?guardado=1"

    db.expire_all()
    barber = db.get(Barber, barber.id)
    assert barber.name == "Perfil Editado"
    assert barber.tagline == "Nueva frase"
    assert "Descripción actualizada" in barber.bio
    assert [(block.weekday, block.start_time, block.end_time) for block in barber.schedules] == [
        (3, time(9, 0), time(12, 0)),
        (3, time(13, 0), time(18, 0)),
    ]
    assert barber.avatar_url.startswith("/static/img/barbers/")
    assert barber.avatar_url != before_avatar
    saved_file = tmp_path / barber.avatar_url.rsplit("/", 1)[-1]
    assert saved_file.is_file()

    profile_page = admin_client.get("/mi-perfil")
    assert profile_page.status_code == 200
    assert "Nueva frase" in profile_page.text


def test_self_registration_stays_pending_until_owner_approves(
    client, db, mateo
):
    data = barber_form_payload(
        name="Barbero Nuevo",
        email="nuevo@example.com",
        password="secreto123",
        specialties=[mateo.specialties[0].id],
        schedule_weekdays=(4,),
        active=False,
    )
    registration = post_form(
        client,
        "/equipo/registro",
        data,
        follow_redirects=False,
    )
    assert registration.status_code == 303
    assert registration.headers["location"] == "/mi-perfil?bienvenido=1"

    db.expire_all()
    barber = db.scalar(
        select(Barber).where(Barber.slug == "barbero-nuevo")
    )
    assert barber is not None
    assert barber.active is False
    assert barber.account is not None

    assert "Barbero Nuevo" not in client.get("/barberos").text
    profile = client.get("/mi-perfil")
    assert profile.status_code == 200
    assert "pendiente de aprobación" in profile.text

    client.post("/admin/logout", follow_redirects=False)
    login = client.post(
        "/admin/login",
        data={"username": "admin", "password": "test-password"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    approve = client.post(
        f"/admin/barberos/{barber.id}/estado",
        data={"active": "1"},
        follow_redirects=False,
    )
    assert approve.status_code == 303
    assert approve.headers["location"] == "/admin/barberos?actualizado=1"

    db.expire_all()
    assert db.get(Barber, barber.id).active is True
    assert "Barbero Nuevo" in client.get("/barberos").text


def test_owner_attaches_access_to_existing_seeded_barber(
    admin_client, db, mateo
):
    data: list[tuple[str, str]] = [
        ("name", mateo.name),
        ("tagline", mateo.tagline or ""),
        ("bio", mateo.bio or ""),
        ("email", "mateo@example.com"),
        ("password", "secreto123"),
        ("active", "on"),
    ]
    for specialty in mateo.specialties:
        data.append(("specialty_ids", str(specialty.id)))

    blocks_by_day: dict[int, list] = {}
    for block in mateo.schedules:
        blocks_by_day.setdefault(block.weekday, []).append(block)
    for weekday, blocks in blocks_by_day.items():
        for index, block in enumerate(blocks[:2]):
            data.append(
                (f"start_{weekday}_{index}", block.start_time.strftime("%H:%M"))
            )
            data.append(
                (f"end_{weekday}_{index}", block.end_time.strftime("%H:%M"))
            )

    response = post_form(
        admin_client,
        f"/admin/barberos/{mateo.id}",
        data,
        follow_redirects=False,
    )
    assert response.status_code == 303

    db.expire_all()
    barber = db.get(Barber, mateo.id)
    assert barber.account is not None
    assert barber.account.email == "mateo@example.com"
    assert verify_password("secreto123", barber.account.password_hash)

    admin_client.post("/admin/logout", follow_redirects=False)
    _login_barber(admin_client, "mateo@example.com", "secreto123")
    assert admin_client.get("/mi-agenda").status_code == 200


def test_overlapping_schedule_is_rejected(client, db, mateo):
    response = client.post(
        "/admin/login",
        data={"username": "admin", "password": "test-password"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    data = barber_form_payload(
        name="Horario Roto",
        email="roto@example.com",
        password="secreto123",
        schedule_weekdays=(),
    )
    data.extend(
        [
            ("start_1_0", "10:00"),
            ("end_1_0", "15:00"),
            ("start_1_1", "14:00"),
            ("end_1_1", "18:00"),
        ]
    )
    broken = post_form(
        client,
        "/admin/barberos/nuevo",
        data,
        follow_redirects=False,
    )
    assert broken.status_code == 400
    assert "se superponen" in broken.text

    assert db.scalar(select(Barber.id).where(Barber.slug == "horario-roto")) is None
