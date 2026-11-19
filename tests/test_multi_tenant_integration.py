"""Pruebas integrales de dos barberías independientes."""

import pytest
from sqlalchemy import select

from app.models import (
    Appointment,
    AppointmentStatus,
    Barber,
    Client,
    Service,
    WorkSchedule,
)
from helpers import booking_payload, find_day_with_slots, find_shared_day

def test_dos_propietarios_acceden_a_sus_propias_barberias(
    admin_client,
    admin_client_sur,
):
    # Propietario de Barbería Norte.
    norte = admin_client.get(
        "/admin/barberos",
        follow_redirects=False,
    )

    # Propietario de Barbería Sur.
    sur = admin_client_sur.get(
        "/admin/barberos",
        follow_redirects=False,
    )

    # Ambos propietarios deben poder acceder.
    assert norte.status_code == 200
    assert sur.status_code == 200

    # Mateo pertenece únicamente a Barbería Norte.
    assert "Mateo Ríos" in norte.text
    assert "Mateo Ríos" not in sur.text


@pytest.fixture
def equipo_sur(db, barberia_sur, mateo):
    barbero = Barber(
        name="Lucas Barbería Sur",
        slug="lucas-barberia-sur-test",
        barberia_id=barberia_sur.id,
        active=True,
        schedules=[
            WorkSchedule(
                weekday=horario.weekday,
                start_time=horario.start_time,
                end_time=horario.end_time,
            )
            for horario in mateo.schedules
        ],
    )

    servicio = Service(
        name="Corte Exclusivo Sur",
        barberia_id=barberia_sur.id,
        duration_minutes=30,
        price_cents=2500000,
        deposit_cents=0,
        active=True,
    )

    db.add_all([barbero, servicio])
    db.commit()

    yield barbero, servicio

    # Eliminar turnos antes que sus recursos asociados.
    turnos = db.scalars(
        select(Appointment).where(
            Appointment.barber_id == barbero.id
        )
    ).all()

    for turno in turnos:
        db.delete(turno)

    db.flush()

    db.delete(servicio)
    db.delete(barbero)
    db.commit()


def test_dos_barberias_reservan_mismo_horario_sin_mezclar_turnos(
    admin_client,
    admin_client_sur,
    db,
    mateo,
    corte_clasico,
    equipo_sur,
):
    barbero_sur, servicio_sur = equipo_sur

    day, slots = find_shared_day(
        db,
        [mateo, barbero_sur],
        corte_clasico,
    )

    horarios_comunes = set(slots[0]) & set(slots[1])
    assert horarios_comunes

    inicio = min(horarios_comunes)

    turnos_creados = []
    telefonos = [
        "+5491198765471",
        "+5491198765472",
    ]

    try:
        # Norte reserva con Mateo.
        norte = admin_client.post(
            "/api/appointments",
            json=booking_payload(
                barber=mateo,
                service=corte_clasico,
                start_at=inicio,
                phone=telefonos[0],
                first_name="ClienteNorte",
                payment_option="later",
            ),
        )

        assert norte.status_code == 201
        turnos_creados.append(norte.json()["id"])

        # Sur reserva exactamente en el mismo horario.
        sur = admin_client_sur.post(
            "/api/appointments",
            json=booking_payload(
                barber=barbero_sur,
                service=servicio_sur,
                start_at=inicio,
                phone=telefonos[1],
                first_name="ClienteSur",
                payment_option="later",
            ),
        )

        assert sur.status_code == 201
        turnos_creados.append(sur.json()["id"])

        assert norte.json()["id"] != sur.json()["id"]

        # Cada barbería consulta su propio turno.
        consulta_norte = admin_client.get(
            f"/api/appointments/{norte.json()['public_code']}"
        )

        consulta_sur = admin_client_sur.get(
            f"/api/appointments/{sur.json()['public_code']}"
        )

        assert consulta_norte.status_code == 200
        assert consulta_sur.status_code == 200

        # Ninguna puede consultar el turno de la otra.
        cruce_norte = admin_client.get(
            f"/api/appointments/{sur.json()['public_code']}"
        )

        cruce_sur = admin_client_sur.get(
            f"/api/appointments/{norte.json()['public_code']}"
        )

        assert cruce_norte.status_code == 404
        assert cruce_sur.status_code == 404

        # Cada propietario ve únicamente su propia cola.
        cola_norte = admin_client.get(
            "/api/admin/queue",
            params={
                "barber_id": mateo.id,
                "date": day.isoformat(),
            },
        )

        cola_sur = admin_client_sur.get(
            "/api/admin/queue",
            params={
                "barber_id": barbero_sur.id,
                "date": day.isoformat(),
            },
        )

        assert cola_norte.status_code == 200
        assert cola_sur.status_code == 200

        ids_norte = {
            item["id"] for item in cola_norte.json()["items"]
        }
        ids_sur = {
            item["id"] for item in cola_sur.json()["items"]
        }

        assert norte.json()["id"] in ids_norte
        assert sur.json()["id"] not in ids_norte

        assert sur.json()["id"] in ids_sur
        assert norte.json()["id"] not in ids_sur

    finally:
        # Limpiar turnos antes de eliminar el equipo de Sur.
        for appointment_id in turnos_creados:
            appointment = db.get(Appointment, appointment_id)
            if appointment is not None:
                db.delete(appointment)

        db.flush()

        for telefono in telefonos:
            cliente = db.scalar(
                select(Client).where(Client.phone == telefono)
            )
            if cliente is not None:
                db.delete(cliente)

        db.commit()


def test_propietario_no_puede_modificar_turno_de_otra_barberia(
    admin_client,
    admin_client_sur,
    db,
    equipo_sur,
):
    barbero_sur, servicio_sur = equipo_sur

    _, horarios = find_day_with_slots(
        db,
        barbero_sur,
        servicio_sur,
    )

    telefono = "+5491198765483"
    turno_id = None

    try:
        # Sur crea una reserva válida.
        respuesta = admin_client_sur.post(
            "/api/appointments",
            json=booking_payload(
                barber=barbero_sur,
                service=servicio_sur,
                start_at=horarios[0],
                phone=telefono,
                first_name="ClienteSeguridadSur",
                payment_option="later",
            ),
        )

        assert respuesta.status_code == 201
        turno_id = respuesta.json()["id"]

        # Norte intenta cambiar el estado del turno de Sur.
        cambio_estado = admin_client.patch(
            f"/api/admin/appointments/{turno_id}/status",
            json={"status": "in_progress"},
        )

        assert cambio_estado.status_code == 403

        # Norte intenta registrar un pago en ese turno.
        pago = admin_client.post(
            f"/api/admin/appointments/{turno_id}/payments",
            json={
                "amount_cents": 1000,
                "method": "cash",
                "kind": "balance",
            },
        )

        assert pago.status_code == 403

        # Norte intenta adelantar el turno de Sur.
        adelantar = admin_client.post(
            f"/api/admin/appointments/{turno_id}/advance"
        )

        assert adelantar.status_code == 403

        # Verificamos que ninguna operación lo haya alterado.
        turno = db.get(Appointment, turno_id)
        db.refresh(turno)

        assert turno.status == AppointmentStatus.confirmed
        assert len(turno.payments) == 0

        # Sur sigue pudiendo consultar su turno.
        consulta_sur = admin_client_sur.get(
            f"/api/appointments/{respuesta.json()['public_code']}"
        )

        assert consulta_sur.status_code == 200

    finally:
        if turno_id is not None:
            turno = db.get(Appointment, turno_id)
            if turno is not None:
                db.delete(turno)
                db.flush()

        cliente = db.scalar(
            select(Client).where(Client.phone == telefono)
        )

        if cliente is not None:
            db.delete(cliente)

        db.commit()


def test_no_permite_reprogramar_turno_a_barbero_de_otra_barberia(
    admin_client,
    db,
    mateo,
    corte_clasico,
    equipo_sur,
):
    barbero_sur, _ = equipo_sur

    _, horarios = find_day_with_slots(
        db,
        mateo,
        corte_clasico,
    )

    inicio = horarios[0]
    telefono = "+5491198765485"
    turno_id = None

    try:
        # Norte crea un turno válido con Mateo.
        respuesta = admin_client.post(
            "/api/appointments",
            json=booking_payload(
                barber=mateo,
                service=corte_clasico,
                start_at=inicio,
                phone=telefono,
                first_name="ClienteReprogramacion",
                payment_option="later",
            ),
        )

        assert respuesta.status_code == 201
        turno_id = respuesta.json()["id"]

        # Norte intenta moverlo a un barbero de Sur.
        reprogramacion = admin_client.post(
            f"/api/admin/appointments/{turno_id}/reschedule",
            json={
                "barber_id": barbero_sur.id,
                "start_at": inicio.isoformat(),
            },
        )

        assert reprogramacion.status_code == 403

        # El turno debe conservar su barbero y horario.
        turno = db.get(Appointment, turno_id)
        db.refresh(turno)

        assert turno.barber_id == mateo.id
        assert turno.start_at == inicio
        assert turno.status == AppointmentStatus.confirmed

    finally:
        if turno_id is not None:
            turno = db.get(Appointment, turno_id)
            if turno is not None:
                db.delete(turno)
                db.flush()

        cliente = db.scalar(
            select(Client).where(Client.phone == telefono)
        )

        if cliente is not None:
            db.delete(cliente)

        db.commit()
