from collections.abc import Generator
from datetime import datetime, timezone

from sqlalchemy import DateTime, TypeDecorator, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class UTCDateTime(TypeDecorator):
    """Guarda UTC sin zona en SQLite y siempre lo devuelve con tzinfo."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_missing_sqlite_columns() -> None:
    if not _is_sqlite:
        return
    inspector = inspect(engine)
    additions = (
        ("barbers", "mp_alias", "ALTER TABLE barbers ADD COLUMN mp_alias VARCHAR(80)"),
        (
            "portfolio_items",
            "media_type",
            "ALTER TABLE portfolio_items ADD COLUMN media_type "
            "VARCHAR(10) NOT NULL DEFAULT 'image'",
        ),
        (
            "barbers",
            "deleted_at",
            "ALTER TABLE barbers ADD COLUMN deleted_at DATETIME",
        ),
        (
            "appointments",
            "client_confirmed_at",
            "ALTER TABLE appointments ADD COLUMN client_confirmed_at DATETIME",
        ),
    )
    with engine.begin() as connection:
        for table, column, statement in additions:
            existing = {item["name"] for item in inspector.get_columns(table)}
            if column not in existing:
                connection.execute(text(statement))


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
    _add_missing_sqlite_columns()
