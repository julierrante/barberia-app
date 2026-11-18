
from app.models import Barber
from app.timeutils import business_today

from datetime import datetime, timedelta, timezone

from app.models import Appointment, AppointmentStatus, Client, Service

from app.database import SessionLocal
from app.services.clients import calculate_stats, get_client

from sqlalchemy import select

from app.models import DailyClosing
from app.services.closings import close_day
from app.timeutils import business_today

from app.models import Payment, PaymentKind, PaymentMethod, PaymentStatus


def test_owner_cannot_access_another_barbershop_queue(
    admin_client,
    db,
    barberia_sur,
):
    # Creamos un barbero perteneciente a Barbería Sur.
    barber_sur = Barber(
        name="Barbero del Sur",
        slug="barbero-del-sur-test",
        barberia_id=barberia_sur.id,
        active=True,
    )

    db.add(barber_sur)
    db.commit()
    db.refresh(barber_sur)

    # El propietario de Barbería Norte intenta consultar su agenda.
    response = admin_client.get(
        "/api/admin/queue",
        params={
            "barber_id": barber_sur.id,
            "date": business_today().isoformat(),
        },
    )

    # La API debe rechazar el acceso a otra barbería.
    assert response.status_code == 403



def test_owner_cannot_manage_another_barbershop_barber(
    admin_client,
    db,
    barberia_sur,
):
    barber_sur = Barber(
        name="Barbero Sur Protegido",
        slug="barbero-sur-protegido-test",
        barberia_id=barberia_sur.id,
        active=True,
    )
    db.add(barber_sur)
    db.commit()
    db.refresh(barber_sur)

    # Norte intenta abrir el formulario de edición de un barbero de Sur.
    response = admin_client.get(
        f"/admin/barberos/{barber_sur.id}",
        follow_redirects=False,
    )
    assert response.status_code == 404

    # Norte intenta desactivar al barbero de Sur.
    response = admin_client.post(
        f"/admin/barberos/{barber_sur.id}/estado",
        data={"active": "0"},
        follow_redirects=False,
    )
    assert response.status_code == 404

    # Verificamos que el barbero de Sur siga activo.
    db.refresh(barber_sur)
    assert barber_sur.active is True


def test_owner_cannot_see_clients_from_another_barbershop(
    admin_client,
    db,
    barberia_sur,
):
    # Creamos un barbero de Barbería Sur.
    barber_sur = Barber(
        name="Barbero Clientes Sur",
        slug="barbero-clientes-sur-test",
        barberia_id=barberia_sur.id,
        active=True,
    )

    # Creamos un servicio exclusivo de Sur.
    service_sur = Service(
        name="Corte Sur Test",
        barberia_id=barberia_sur.id,
        duration_minutes=30,
        price_cents=15000,
        deposit_cents=0,
        active=True,
    )

    client_sur = Client(
        first_name="ClienteExclusivo",
        last_name="SurTest",
        phone="+5491198765432",
    )

    start_at = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)

    appointment_sur = Appointment(
        client=client_sur,
        barber=barber_sur,
        service=service_sur,
        status=AppointmentStatus.confirmed,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=15000,
        deposit_cents=0,
    )

    db.add_all([
        barber_sur,
        service_sur,
        client_sur,
        appointment_sur,
    ])
    db.commit()

    try:
        # Norte busca un cliente que solo pertenece a Sur.
        response = admin_client.get(
            "/admin/clientes",
            params={"q": "ClienteExclusivo"},
        )

        assert response.status_code == 200
        assert "SurTest" not in response.text

        # Norte intenta entrar directamente a su ficha.
        response = admin_client.get(
            f"/admin/clientes/{client_sur.id}",
            follow_redirects=False,
        )

        assert response.status_code == 404

    finally:
        # Limpiamos los datos creados para este test.
        db.delete(appointment_sur)
        db.flush()
        db.delete(client_sur)
        db.delete(service_sur)
        db.delete(barber_sur)
        db.commit()


def test_shared_client_history_is_isolated_by_barbershop(
    admin_client,
    db,
    barberia_sur,
    mateo,
    corte_clasico,
):
    # Un cliente que reserva en dos barberías.
    shared_client = Client(
        first_name="ClienteCompartido",
        last_name="DosBarberias",
        phone="+5491198765433",
    )

    barber_sur = Barber(
        name="Barbero Historial Sur",
        slug="barbero-historial-sur-test",
        barberia_id=barberia_sur.id,
        active=True,
    )

    service_sur = Service(
        name="Servicio Exclusivo Sur",
        barberia_id=barberia_sur.id,
        duration_minutes=30,
        price_cents=27000,
        deposit_cents=0,
        active=True,
    )

    start_at = datetime(
        2026, 11, 10, 14, 0, tzinfo=timezone.utc
    )

    appointment_norte = Appointment(
        client=shared_client,
        barber=mateo,
        service=corte_clasico,
        status=AppointmentStatus.confirmed,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=12000,
        deposit_cents=0,
    )

    appointment_sur = Appointment(
        client=shared_client,
        barber=barber_sur,
        service=service_sur,
        status=AppointmentStatus.confirmed,
        start_at=start_at + timedelta(days=1),
        end_at=start_at + timedelta(days=1, minutes=30),
        duration_minutes=30,
        price_cents=27000,
        deposit_cents=0,
    )

    db.add_all([
        shared_client,
        barber_sur,
        service_sur,
        appointment_norte,
        appointment_sur,
    ])
    db.commit()


    try:
        # El propietario de Norte abre la ficha compartida.
        response = admin_client.get(
            f"/admin/clientes/{shared_client.id}"
        )

        assert response.status_code == 200

        # El cliente es visible porque reservó en Norte.
        assert "ClienteCompartido" in response.text

        # Solamente debe figurar el turno de Norte.
        assert "1 registros" in response.text

        # No debe aparecer el servicio de Barbería Sur.
        assert "Servicio Exclusivo Sur" not in response.text
        assert "Barbero Historial Sur" not in response.text

        # Verificamos las estadísticas usando una sesión limpia.
        with SessionLocal() as fresh_db:
            client_norte = get_client(
                fresh_db,
                shared_client.id,
                barberia_id=mateo.barberia_id,
            )

            stats = calculate_stats(client_norte)

            assert len(client_norte.appointments) == 1
            assert stats.pending_balance_cents == 12000
            assert stats.total_paid_cents == 0


        # Primero cargamos los turnos de ambas barberías
        # dentro de la misma sesión.
        db.expire(shared_client, ["appointments"])
        assert len(shared_client.appointments) == 2

        # Ahora consultamos el cliente como propietario de Norte.
        # SQLAlchemy debe reemplazar el historial cargado
        # por los turnos correspondientes a Norte.
        client_norte = get_client(
            db,
            shared_client.id,
            barberia_id=mateo.barberia_id,
        )

        assert len(client_norte.appointments) == 1

        stats = calculate_stats(client_norte)
        assert stats.pending_balance_cents == 12000
        assert stats.total_paid_cents == 0


    finally:
        # Limpiamos los datos creados por el test.
        db.delete(appointment_norte)
        db.delete(appointment_sur)
        db.flush()

        db.delete(shared_client)
        db.delete(service_sur)
        db.delete(barber_sur)
        db.commit()


def test_manual_closing_does_not_modify_another_barbershop(
    db,
    barberia_sur,
    mateo,
):
    day = business_today() - timedelta(days=10)

    barber_sur = Barber(
        name="Barbero Cierre Sur",
        slug="barbero-cierre-sur-test",
        barberia_id=barberia_sur.id,
        active=True,
    )
    db.add(barber_sur)
    db.commit()

    try:
        # Primero cerramos la caja de Sur.
        close_day(
            db,
            day,
            barberia_id=barberia_sur.id,
        )

        cierre_sur = db.scalar(
            select(DailyClosing).where(
                DailyClosing.barber_id == barber_sur.id,
                DailyClosing.business_date == day,
            )
        )

        assert cierre_sur is not None
        fecha_cierre_sur = cierre_sur.closed_at

        # Ahora el propietario de Norte cierra su propia caja.
        cierres_norte = close_day(
            db,
            day,
            barberia_id=mateo.barberia_id,
        )

        # Todos los cierres generados deben pertenecer a Norte.
        assert cierres_norte
        assert all(
            cierre.barber.barberia_id == mateo.barberia_id
            for cierre in cierres_norte
        )

        # El cierre de Sur no debe modificarse.
        db.refresh(cierre_sur)
        assert cierre_sur.closed_at == fecha_cierre_sur

    finally:
        # Limpiamos los cierres de este día.
        db.query(DailyClosing).filter(
            DailyClosing.business_date == day
        ).delete(synchronize_session=False)

        db.commit()
        db.delete(barber_sur)
        db.commit()


def test_financial_reports_only_show_own_barbershop(
    admin_client,
    db,
    barberia_sur,
    mateo,
):
    day = business_today() - timedelta(days=8)

    barber_sur = Barber(
        name="Barbero Reporte Sur",
        slug="barbero-reporte-sur-test",
        barberia_id=barberia_sur.id,
        active=True,
    )

    db.add(barber_sur)
    db.commit()

    # Generamos cierres para ambas barberías.
    close_day(db, day, barberia_id=mateo.barberia_id)
    close_day(db, day, barberia_id=barberia_sur.id)

    try:
        # Norte consulta sus cierres.
        response = admin_client.get(
            "/admin/cierres",
            params={"month": day.strftime("%Y-%m")},
        )

        assert response.status_code == 200
        assert "Barbero Reporte Sur" not in response.text

        # Norte consulta sus reportes.
        response = admin_client.get(
            "/admin/reportes",
            params={"month": day.strftime("%Y-%m")},
        )

        assert response.status_code == 200
        assert "Barbero Reporte Sur" not in response.text

    finally:
        db.query(DailyClosing).filter(
            DailyClosing.business_date == day
        ).delete(synchronize_session=False)

        db.commit()
        db.delete(barber_sur)
        db.commit()


def test_closing_amounts_are_isolated_by_barbershop(
    db,
    barberia_sur,
    mateo,
    corte_clasico,
):
    day = business_today() - timedelta(days=20)
    start_at = datetime(
        day.year, day.month, day.day, 14, 0,
        tzinfo=timezone.utc,
    )

    barber_sur = Barber(
        name="Barbero Pagos Sur",
        slug="barbero-pagos-sur-test",
        barberia_id=barberia_sur.id,
        active=True,
    )

    service_sur = Service(
        name="Servicio Pagos Sur",
        barberia_id=barberia_sur.id,
        duration_minutes=30,
        price_cents=27000,
        deposit_cents=0,
        active=True,
    )

    client_norte = Client(
        first_name="PagoNorte",
        last_name="Prueba",
        phone="+5491198765440",
    )

    client_sur = Client(
        first_name="PagoSur",
        last_name="Prueba",
        phone="+5491198765441",
    )

    appointment_norte = Appointment(
        client=client_norte,
        barber=mateo,
        service=corte_clasico,
        status=AppointmentStatus.completed,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=12000,
        deposit_cents=0,
        payments=[
            Payment(
                kind=next(iter(PaymentKind)),
                method=next(iter(PaymentMethod)),
                status=PaymentStatus.paid,
                amount_cents=9000,
            )
        ],
    )

    appointment_sur = Appointment(
        client=client_sur,
        barber=barber_sur,
        service=service_sur,
        status=AppointmentStatus.completed,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
        duration_minutes=30,
        price_cents=27000,
        deposit_cents=0,
        payments=[
            Payment(
                kind=next(iter(PaymentKind)),
                method=next(iter(PaymentMethod)),
                status=PaymentStatus.paid,
                amount_cents=21000,
            )
        ],
    )

    db.add_all([
        barber_sur,
        service_sur,
        client_norte,
        client_sur,
        appointment_norte,
        appointment_sur,
    ])
    db.commit()

    cierres_norte = []
    cierres_sur = []

    try:
        cierres_norte = close_day(
            db, day, barberia_id=mateo.barberia_id
        )
        cierres_sur = close_day(
            db, day, barberia_id=barberia_sur.id
        )

        assert sum(
            row.service_revenue_cents for row in cierres_norte
        ) == 12000
        assert sum(
            row.collected_cents for row in cierres_norte
        ) == 9000
        assert sum(
            row.pending_cents for row in cierres_norte
        ) == 3000

        assert sum(
            row.service_revenue_cents for row in cierres_sur
        ) == 27000
        assert sum(
            row.collected_cents for row in cierres_sur
        ) == 21000
        assert sum(
            row.pending_cents for row in cierres_sur
        ) == 6000

    finally:
        for cierre in cierres_norte + cierres_sur:
            db.delete(cierre)

        db.flush()

        db.delete(appointment_norte)
        db.delete(appointment_sur)
        db.flush()

        db.delete(client_norte)
        db.delete(client_sur)
        db.delete(service_sur)
        db.delete(barber_sur)
        db.commit()
