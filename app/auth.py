import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import BarberAccount

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


def credentials_valid(username: str, password: str) -> bool:
    settings = get_settings()
    user_ok = secrets.compare_digest(username, settings.admin_username)
    password_ok = secrets.compare_digest(password, settings.admin_password)
    return user_ok and password_ok


def authenticate_staff(
    db: Session, identifier: str, password: str
) -> StaffIdentity | None:
    if credentials_valid(identifier, password):
        return StaffIdentity(
            role="owner",
            display_name=get_settings().admin_username,
        )

    email = normalize_email(identifier)
    if not email:
        return None
    account = db.scalar(
        select(BarberAccount).where(BarberAccount.email == email)
    )
    if (
        account is None
        or account.barber.deleted_at is not None
        or not verify_password(password, account.password_hash)
    ):
        return None
    return StaffIdentity(
        role="barber",
        display_name=account.barber.name,
        barber_id=account.barber_id,
    )


def is_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


def is_owner(request: Request) -> bool:
    return is_admin(request)


def is_barber(request: Request) -> bool:
    return bool(
        request.session.get("role") == "barber"
        and request.session.get("barber_id")
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
