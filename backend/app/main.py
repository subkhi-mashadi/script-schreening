import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import audit_logs, auth, dashboard, manuscripts, quick_check, review, rules, screenings, users, versions
from app.core import errors
from app.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    errors.install(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    api = APIRouter(prefix="/api/v1")
    for r in (auth.router, users.router, dashboard.router, manuscripts.router, versions.router, quick_check.router, screenings.router, review.router, rules.router, audit_logs.router):
        api.include_router(r)

    @api.get("/health", tags=["ops"])
    def health() -> dict:
        return {"status": "ok"}

    @api.get("/settings", tags=["ops"])
    def public_settings() -> dict:
        """Pengaturan yang memengaruhi tampilan (tanpa rahasia)."""
        return {"auto_mode": get_settings().auto_mode}

    app.include_router(api)
    return app


app = create_app()
