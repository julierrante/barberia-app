
from __future__ import annotations

import ipaddress

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Barberia


def obtener_slug_barberia(host: str) -> str:
    """Identifica la barbería utilizando el dominio solicitado."""

    settings = get_settings()

    host = host.strip().lower().rstrip(".")

    # Desarrollo local: localhost o IP de loopback.
    if host == "localhost":
        return settings.saas_local_barberia_slug

    try:
        if ipaddress.ip_address(host).is_loopback:
            return settings.saas_local_barberia_slug
    except ValueError:
        pass

    dominio = settings.saas_base_domain.lower().strip(".")

    sufijo = f".{dominio}"

    if not host.endswith(sufijo):
        raise HTTPException(
            status_code=404,
            detail="No encontramos esta barbería.",
        )

    slug = host[: -len(sufijo)]

    # Solo se acepta un subdominio.
    if not slug or "." in slug:
        raise HTTPException(
            status_code=404,
            detail="No encontramos esta barbería.",
        )

    return slug


def obtener_barberia_actual(
    request: Request,
    db: Session = Depends(get_db),
) -> Barberia:
    """Resuelve la barbería activa para la solicitud HTTP."""

    # request.url.hostname excluye el puerto.
    host = request.url.hostname or ""

    slug = obtener_slug_barberia(host)

    barberia = db.scalar(
        select(Barberia).where(
            Barberia.slug == slug,
            Barberia.activa.is_(True),
        )
    )

    if barberia is None:
        raise HTTPException(
            status_code=404,
            detail="No encontramos esta barbería.",
        )

    return barberia
