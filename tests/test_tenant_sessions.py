
from app.config import get_settings


def test_owner_session_cannot_access_another_barbershop(admin_client):
    # El propietario puede acceder a su propia barbería.
    own_response = admin_client.get(
        "/admin",
        follow_redirects=False,
    )
    assert own_response.status_code == 200

    # Simulamos una solicitud desde otra barbería.
    other_host = f"barberia-sur.{get_settings().saas_base_domain}"

    foreign_response = admin_client.get(
        "/admin",
        headers={"host": other_host},
        follow_redirects=False,
    )

    # La sesión de Barbería Norte no debe servir en Barbería Sur.
    assert foreign_response.status_code == 303
    assert foreign_response.headers["location"] == "/admin/login"


def test_owner_session_cannot_access_another_barbershop_api(admin_client):
    other_host = f"barberia-sur.{get_settings().saas_base_domain}"

    response = admin_client.get(
        "/api/admin/queue",
        headers={"host": other_host},
        follow_redirects=False,
    )

    assert response.status_code == 401
