
"""Pruebas de aislamiento de las rutas públicas entre barberías."""

from datetime import timedelta

import pytest
from sqlalchemy import delete, select

from app.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    Barberia,
    Client,
    Service,
)
from app.timeutils import utc_now


@pytest.fixture
def barberia_sur(db):
    barberia = Barberia(
        nombre="Barbería Sur",
        slug="barberia-sur",
    )

    barbero = Barber(
        name="Barbero Sur",
        slug="barbero-sur",
        barberia=barberia,
    )

    servicio = Service(
        name="Servicio Sur",
        duration_minutes=30,
        price_cents=2000000,
        deposit_cents=0,
        barberia=barberia,
    )

    db.add_all([barberia, barbero, servicio])
    db.commit()

    try:
        yield barberia, barbero, servicio
    finally:
        # Eliminar primero los turnos creados por las pruebas.
        # Los turnos tienen claves foráneas obligatorias.
        db.execute(
            delete(Appointment).where(
                Appointment.barber_id == barbero.id
            )
        )

        db.flush()

        db.delete(servicio)
        db.delete(barbero)
        db.delete(barberia)
        db.commit()


def test_servicios_filtrados_por_barberia(client, barberia_sur):
    _, _, servicio_sur = barberia_sur

    norte = client.get(
        "/api/services",
        headers={"host": "localhost"},
    )

    sur = client.get(
        "/api/services",
        headers={"host": "barberia-sur.tuapp.com"},
    )

    assert norte.status_code == 200
    assert sur.status_code == 200

    assert servicio_sur.id not in {
        item["id"] for item in norte.json()
    }

    assert {item["id"] for item in sur.json()} == {
        servicio_sur.id
    }


def test_barberos_filtrados_por_barberia(client, barberia_sur):
    _, barbero_sur, _ = barberia_sur

    norte = client.get(
        "/api/barbers",
        headers={"host": "localhost"},
    )

    sur = client.get(
        "/api/barbers",
        headers={"host": "barberia-sur.tuapp.com"},
    )

    assert norte.status_code == 200
    assert sur.status_code == 200

    assert barbero_sur.id not in {
        item["id"] for item in norte.json()
    }

    assert {item["id"] for item in sur.json()} == {
        barbero_sur.id
    }


def test_perfil_de_barbero_ajeno_no_es_visible(
    client,
    barberia_sur,
):
    response = client.get(
        "/api/barbers/barbero-sur",
        headers={"host": "localhost"},
    )

    assert response.status_code == 404


def test_disponibilidad_con_recursos_ajenos_se_rechaza(
    client,
    barberia_sur,
):
    _, barbero_sur, servicio_sur = barberia_sur

    response = client.get(
        "/api/availability",
        params={
            "barber_id": barbero_sur.id,
            "service_id": servicio_sur.id,
            "date": "2026-11-10",
        },
        headers={"host": "localhost"},
    )

    assert response.status_code == 404


def test_home_no_muestra_servicios_ajenos(
    client,
    barberia_sur,
):
    response = client.get(
        "/",
        headers={"host": "localhost"},
    )

    assert response.status_code == 200
    assert "Servicio Sur" not in response.text


def test_barberia_inexistente_se_rechaza(client):
    response = client.get(
        "/api/services",
        headers={"host": "inexistente.tuapp.com"},
    )

    assert response.status_code == 404


def test_no_permite_operar_sobre_turno_de_otra_barberia(
    client,
    db,
    barberia_sur,
):
    _, barbero_sur, servicio_sur = barberia_sur

    cliente = Client(
        first_name="Cliente",
        last_name="Sur",
        phone="+5491199998888",
    )

    inicio = utc_now() + timedelta(days=2)

    turno = Appointment(
        client=cliente,
        barber=barbero_sur,
        service=servicio_sur,
        status=AppointmentStatus.confirmed,
        start_at=inicio,
        end_at=inicio + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=servicio_sur.price_cents,
        deposit_cents=0,
    )

    db.add(turno)
    db.commit()

    codigo = turno.public_code
    headers = {"host": "localhost"}

    consulta = client.get(
        f"/api/appointments/{codigo}",
        headers=headers,
    )
    assert consulta.status_code == 404

    cancelacion = client.post(
        f"/api/appointments/{codigo}/cancel",
        json={"phone": cliente.phone},
        headers=headers,
    )
    assert cancelacion.status_code == 404

    confirmacion = client.post(
        f"/api/appointments/{codigo}/confirm",
        headers=headers,
    )
    assert confirmacion.status_code == 404

    calificacion = client.post(
        f"/api/appointments/{codigo}/rating",
        json={
            "score": 5,
            "comment": "Excelente",
        },
        headers=headers,
    )
    assert calificacion.status_code == 404

    db.expire_all()

    turno_guardado = db.scalar(
        select(Appointment).where(
            Appointment.public_code == codigo
        )
    )

    assert turno_guardado is not None
    assert turno_guardado.status == AppointmentStatus.confirmed
    assert turno_guardado.client_confirmed_at is None
    assert turno_guardado.rating is None
