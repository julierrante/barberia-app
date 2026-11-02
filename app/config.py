from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Barbería Norte"
    app_base_url: str = "http://127.0.0.1:8000"
    saas_base_domain: str = "tuapp.com"
    saas_local_barberia_slug: str = "barberia-norte"

    database_url: str = "sqlite:///./barberia.db"
    business_timezone: str = "America/Argentina/Buenos_Aires"

    admin_username: str = "admin"
    admin_password: str = "cambiar-esta-clave"
    session_secret: str = "clave-de-desarrollo-cambiar-en-produccion"

    min_notice_minutes: int = 30
    slot_granularity_minutes: int = 15
    booking_days_ahead: int = 45
    payments_mode: str = "mock"

    whatsapp_mode: str = "mock"
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_template_name: str = "recordatorio_turno"
    whatsapp_template_language: str = "es_AR"
    whatsapp_api_version: str = "v21.0"
    reminder_worker_enabled: bool = True
    reminder_worker_interval_seconds: int = 30
    # Minutos antes del turno a partir de los cuales un turno sin confirmar
    # se considera "por vencer": dispara el último aviso al cliente y la
    # alerta destacada en la agenda.
    confirmation_deadline_minutes: int = 45

    daily_close_enabled: bool = True
    daily_close_hour: int = 23
    daily_close_minute: int = 30
    closing_worker_interval_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
