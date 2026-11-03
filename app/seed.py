from __future__ import annotations

from datetime import time

from sqlalchemy import select

from app.database import SessionLocal, create_tables
from app.models import (
    Barber,
    Barberia,
    PortfolioItem,
    Service,
    Specialty,
    WorkSchedule,
)



BARBERIA_INICIAL_SLUG = "barberia-norte"
BARBEROS_DEMO = ("mateo-rios", "thiago-benitez", "camila-duarte")
SERVICIOS_DEMO = (
    "Corte clásico", "Corte + barba", "Barba y perfilado",
    "Fade + diseño", "Corte niño",
)


def seed() -> None:
    create_tables()
    with SessionLocal() as db:
        barberia = db.scalar(
            select(Barberia).where(Barberia.slug == BARBERIA_INICIAL_SLUG)
        )
        if barberia is None:
            barberia = Barberia(
                nombre="Barbería Norte",
                slug=BARBERIA_INICIAL_SLUG,
                descripcion="Barbería de demostración",
                color_primario="#000000",
                activa=True,
            )
            db.add(barberia)
            db.flush()

        if db.scalar(select(Service.id).limit(1)) is not None:
            barberos_existentes = db.scalars(
                select(Barber).where(
                    Barber.slug.in_(BARBEROS_DEMO),
                    Barber.barberia_id.is_(None),
                )
            ).all()
            for barbero in barberos_existentes:
                barbero.barberia = barberia

            # Solo vinculamos los servicios conocidos del demo, no datos ajenos.
            servicios_existentes = db.scalars(
                select(Service).where(
                    Service.name.in_(SERVICIOS_DEMO),
                    Service.barberia_id.is_(None),
                )
            ).all()
            for servicio in servicios_existentes:
                servicio.barberia = barberia

            db.commit()
            print("La base ya contiene datos.")
            print("Barberos de demostración asociados:", len(barberos_existentes))
            print("Servicios de demostración asociados:", len(servicios_existentes))
            return

        specialties = {
            name: Specialty(name=name)
            for name in (
                "Fade",
                "Corte clásico",
                "Barba y afeitado",
                "Corte texturizado",
                "Diseño de corte",
            )
        }
        db.add_all(specialties.values())

        services = [
            Service(
                barberia=barberia,
                name="Corte clásico",
                description="Asesoramiento, lavado y corte a tijera o máquina.",
                duration_minutes=30,
                price_cents=1_200_000,
                deposit_cents=400_000,
            ),
            Service(
                barberia=barberia,
                name="Corte + barba",
                description="Corte a medida y perfilado de barba con toalla caliente.",
                duration_minutes=45,
                price_cents=1_800_000,
                deposit_cents=600_000,
            ),
            Service(
                barberia=barberia,
                name="Barba y perfilado",
                description="Diseño de barba, afeitado de contornos y bálsamo.",
                duration_minutes=20,
                price_cents=800_000,
                deposit_cents=300_000,
            ),
            Service(
                barberia=barberia,
                name="Fade + diseño",
                description="Degradado personalizado con líneas y terminación a navaja.",
                duration_minutes=45,
                price_cents=1_600_000,
                deposit_cents=500_000,
            ),
            Service(
                barberia=barberia,
                name="Corte niño",
                description="Corte con paciencia para los más chicos, hasta 12 años.",
                duration_minutes=30,
                price_cents=1_000_000,
                deposit_cents=300_000,
            ),
        ]
        db.add_all(services)

        mateo = Barber(
            barberia=barberia,
            name="Mateo Ríos",
            slug="mateo-rios",
            tagline="Fades limpios, detalles precisos.",
            bio=(
                "Barbero desde 2015. Me formé en cortes clásicos y degradados, "
                "siempre con una lectura atenta de la forma de la cara y la rutina "
                "de cada cliente. Si querés un corte prolijo que aguante la semana, "
                "este es tu lugar."
            ),
            avatar_url="/static/img/barber-mateo.jpg",
            specialties=[
                specialties["Fade"],
                specialties["Corte clásico"],
                specialties["Diseño de corte"],
            ],
            portfolio_items=[
                PortfolioItem(
                    image_url="/static/img/work-mateo.jpg",
                    caption="Fade medio con línea",
                    sort_order=1,
                ),
            ],
            schedules=[
                WorkSchedule(weekday=weekday, start_time=start, end_time=end)
                for weekday in (1, 2, 3, 4, 5)
                for start, end in (
                    (time(10, 0), time(13, 0)),
                    (time(14, 0), time(20, 0)),
                )
            ],
        )
        thiago = Barber(
            barberia=barberia,
            name="Thiago Benítez",
            slug="thiago-benitez",
            tagline="Barba, navaja y ritual.",
            bio=(
                "Especialista en barba y afeitado tradicional. Trabajo el detalle "
                "con toalla caliente, aceites y una navaja que no negocia. También "
                "hago cortes clásicos y fades con mucha textura."
            ),
            avatar_url="/static/img/barber-thiago.jpg",
            specialties=[
                specialties["Barba y afeitado"],
                specialties["Corte clásico"],
                specialties["Fade"],
            ],
            portfolio_items=[
                PortfolioItem(
                    image_url="/static/img/work-thiago.jpg",
                    caption="Barba perfilada + corte clásico",
                    sort_order=1,
                ),
            ],
            schedules=[
                WorkSchedule(weekday=weekday, start_time=start, end_time=end)
                for weekday in (0, 1, 2, 3, 4)
                for start, end in (
                    (time(9, 0), time(13, 0)),
                    (time(14, 0), time(18, 0)),
                )
            ],
        )
        camila = Barber(
            barberia=barberia,
            name="Camila Duarte",
            slug="camila-duarte",
            tagline="Textura, forma y movimiento.",
            bio=(
                "Me gusta trabajar texturas, capas y cortes con movimiento. "
                "Cada visita empieza con una charla sobre cómo te peinás y termina "
                "con un acabado fácil de mantener en casa."
            ),
            avatar_url="/static/img/barber-camila.jpg",
            specialties=[
                specialties["Corte texturizado"],
                specialties["Diseño de corte"],
                specialties["Fade"],
            ],
            portfolio_items=[
                PortfolioItem(
                    image_url="/static/img/work-camila.jpg",
                    caption="Texturizado con flequillo",
                    sort_order=1,
                ),
            ],
            schedules=[
                WorkSchedule(weekday=weekday, start_time=start, end_time=end)
                for weekday in (2, 3, 4, 5, 6)
                for start, end in (
                    (time(11, 0), time(15, 0)),
                    (time(16, 0), time(20, 0)),
                )
            ],
        )

        db.add_all([mateo, thiago, camila])
        db.commit()

        print("Datos iniciales cargados.")
        print(f"  Barbería: {barberia.nombre}")
        print("  Servicios: 5")
        print("  Barberos: 3")
        print("  Especialidades: 5")


if __name__ == "__main__":
    seed()
