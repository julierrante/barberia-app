import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BarberAccount, OwnerAccount
from app.tenancy import obtener_slug_barberia

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000


class LoginRequired(Exception):
    def __init__(self, redirect_url: str = "/admin/login"):
        super().__init__("Se requiere iniciar sesión.")
        self.redirect_url = redirect_url


@dataclass(frozen=True)
class StaffIdentity:
    role: str
    display_name: str
    barberia_id: int
    barber_id: int | None = None

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def is_barber(self) -> bool:
        return self.role == "barber"


def normalize_email(value: str) -> str:
    return value.strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    return (
        f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}$"
        f"{salt}${digest.hex()}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$", 3)
    except (AttributeError, ValueError):
        return False
    if algorithm != PASSWORD_ALGORITHM:
        return False
    try:
        rounds = int(iterations)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        rounds,
    )
    return hmac.compare_digest(digest.hex(), expected)


def authenticate_staff(
    db: Session,
    identifier: str,
    password: str,
    barberia_id: int,
) -> StaffIdentity | None:
    email = normalize_email(identifier)
    if not email:
        return None

    owner = db.scalar(
        select(OwnerAccount).where(
            OwnerAccount.email == email,
            OwnerAccount.barberia_id == barberia_id,
        )
    )
    if owner is not None and verify_password(password, owner.password_hash):
        return StaffIdentity(
            role="owner",
            display_name=owner.email,
            barberia_id=owner.barberia_id,
        )

    account = db.scalar(
        select(BarberAccount)
        .join(BarberAccount.barber)
        .where(
            BarberAccount.email == email,
            BarberAccount.barber.has(
                barberia_id=barberia_id,
                deleted_at=None,
            ),
        )
    )
    if account is None or not verify_password(password, account.password_hash):
        return None
    return StaffIdentity(
        role="barber",
        display_name=account.barber.name,
        barberia_id=barberia_id,
        barber_id=account.barber_id,
    )


def session_matches_tenant(request: Request) -> bool:
    session_slug = request.session.get("barberia_slug")
    session_id = request.session.get("barberia_id")
    if not isinstance(session_slug, str) or not session_slug:
        return False
    if type(session_id) is not int or session_id <= 0:
        return False
    current_slug = obtener_slug_barberia(request.url.hostname or "")
    return session_slug == current_slug


def is_admin(request: Request) -> bool:
    return is_owner(request)


def is_owner(request: Request) -> bool:
    return bool(
        session_matches_tenant(request)
        and request.session.get("role") == "owner"
        and request.session.get("is_admin") is True
    )


def is_barber(request: Request) -> bool:
    barber_id = request.session.get("barber_id")
    return bool(
        session_matches_tenant(request)
        and request.session.get("role") == "barber"
        and type(barber_id) is int
        and barber_id > 0
    )


def is_staff(request: Request) -> bool:
    return is_owner(request) or is_barber(request)


def session_barber_id(request: Request) -> int | None:
    if not is_barber(request):
        return None
    return request.session.get("barber_id")


def display_name(request: Request) -> str:
    return str(request.session.get("admin_username") or "")


def require_admin_page(request: Request) -> None:
    if not is_owner(request):
        raise LoginRequired()


def require_owner_page(request: Request) -> None:
    if not is_owner(request):
        raise LoginRequired()


def require_barber_page(request: Request) -> None:
    if not is_barber(request):
        raise LoginRequired()


def require_staff_page(request: Request) -> None:
    if not is_staff(request):
        raise LoginRequired()


def require_admin_api(request: Request) -> None:
    if not is_staff(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión administrativa requerida.",
        )


def require_owner_api(request: Request) -> None:
    if not is_owner(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo la administración puede realizar esta operación.",
        )
