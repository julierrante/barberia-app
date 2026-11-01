from __future__ import annotations

from app.services.closings import close_day
from helpers import booking_payload, find_day_with_slots


def test_owner_views_monthly_billing_report(admin_client, db, mateo, corte_clasico):
    day, slots = find_day_with_slots(db, mateo, corte_clasico)
    created = admin_client.post(
        "/api/appointments",
        json=booking_payload(
            barber=mateo,
            service=corte_clasico,
            start_at=slots[0],
            payment_option="later",
        ),
    ).json()

    payment = admin_client.post(
        f"/api/admin/appointments/{created['id']}/payments",
        json={
            "amount_cents": corte_clasico.price_cents,
            "method": "cash",
            "kind": "balance",
        },
    )
    assert payment.status_code == 200
    admin_client.patch(
        f"/api/admin/appointments/{created['id']}/status",
        json={"status": "in_progress"},
    )
    admin_client.patch(
        f"/api/admin/appointments/{created['id']}/status",
        json={"status": "completed"},
    )

    rows = close_day(db, day)
    assert len(rows) >= 1

    month = day.strftime("%Y-%m")
    report = admin_client.get(f"/admin/reportes?month={month}")
    assert report.status_code == 200
    assert "El mes" in report.text
    assert "Facturación por barbero" in report.text
    assert "Mateo Ríos" in report.text
    assert "$ 12.000" in report.text
    assert "report-chart" in report.text
    assert "0%" in report.text

    previous = admin_client.get(
        f"/admin/reportes?month={month}", follow_redirects=False
    )
    assert previous.status_code == 200


def test_report_page_requires_owner_login(client):
    response = client.get("/admin/reportes", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_report_empty_month_shows_hint(admin_client):
    report = admin_client.get("/admin/reportes?month=2030-01")
    assert report.status_code == 200
    assert "No hay cierres guardados" in report.text
