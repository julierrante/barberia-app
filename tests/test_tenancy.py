
import pytest
from fastapi import HTTPException

from app.tenancy import obtener_slug_barberia


def test_identifica_barberia_por_subdominio():
    assert (
        obtener_slug_barberia("barberia-norte.tuapp.com")
        == "barberia-norte"
    )


def test_identifica_barberia_local():
    assert obtener_slug_barberia("localhost") == "barberia-norte"
    assert obtener_slug_barberia("127.0.0.1") == "barberia-norte"


def test_rechaza_dominio_desconocido():
    with pytest.raises(HTTPException) as exc:
        obtener_slug_barberia("barberia-norte.otrodominio.com")

    assert exc.value.status_code == 404


def test_rechaza_subdominios_anidados():
    with pytest.raises(HTTPException) as exc:
        obtener_slug_barberia("admin.barberia-norte.tuapp.com")

    assert exc.value.status_code == 404


def test_rechaza_dominio_principal():
    with pytest.raises(HTTPException) as exc:
        obtener_slug_barberia("tuapp.com")

    assert exc.value.status_code == 404
