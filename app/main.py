from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import LoginRequired
from app.config import get_settings
from app.database import create_tables
from app.routers import admin_api, pages, public_api
from app.services.closings import closing_worker
from app.services.errors import BusinessError
from app.services.reminders import reminder_worker

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_tables()
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task] = []
    if settings.reminder_worker_enabled:
        tasks.append(asyncio.create_task(reminder_worker(stop_event)))
    if settings.daily_close_enabled:
        tasks.append(asyncio.create_task(closing_worker(stop_event)))
    try:
        yield
    finally:
        if tasks:
            stop_event.set()
            await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(
    title=settings.app_name,
    description="MVP de gestión de turnos, barberos, pagos y clientes.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="barberia_session",
    max_age=60 * 60 * 12,
    same_site="lax",
    https_only=False,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.exception_handler(BusinessError)
async def business_error_handler(_request: Request, exc: BusinessError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


@app.exception_handler(LoginRequired)
async def login_required_handler(_request: Request, exc: LoginRequired):
    return RedirectResponse(url=exc.redirect_url, status_code=303)


app.include_router(public_api.router)
app.include_router(admin_api.router)
app.include_router(pages.router)


@app.get("/health", tags=["Sistema"])
def healthcheck():
    return {"status": "ok"}
