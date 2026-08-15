from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.billing.router import admin_router, router as billing_router
from tutor_api.classrooms.router import router as classrooms_router
from tutor_api.core.config import Settings, get_settings
from tutor_api.core.database import create_engine_from_url
from tutor_api.identity.router import router as identity_router
from tutor_api.providers.router import router as providers_router
from tutor_api.providers.service import synchronize_provider_profiles
from tutor_api.spaces.router import router as spaces_router


def create_app(
    settings: Settings | None = None, session_factory: sessionmaker[Session] | None = None
) -> FastAPI:
    active_settings = settings or get_settings()
    production_errors = active_settings.production_errors()
    if production_errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(production_errors))
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if app.state.session_factory is not None:
            with app.state.session_factory.begin() as session:
                synchronize_provider_profiles(session, active_settings.provider_profiles)
        yield

    app = FastAPI(title="Textbook Tutor API", version="0.1.0", lifespan=lifespan)
    app.state.settings = active_settings
    if session_factory is not None:
        app.state.session_factory = session_factory
    elif active_settings.app_env == "test" or active_settings.database_url.startswith(
        "postgresql+psycopg://"
    ):
        engine = create_engine_from_url(
            active_settings.database_url, app_env=active_settings.app_env
        )
        app.state.session_factory = sessionmaker(bind=engine)
    else:
        app.state.session_factory = None

    @app.exception_handler(RequestValidationError)
    async def redact_validation_passwords(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        del request
        errors = [
            {key: field_error[key] for key in ("type", "loc", "msg") if key in field_error}
            for field_error in error.errors()
        ]
        return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errors}))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[active_settings.web_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(identity_router)
    app.include_router(spaces_router)
    app.include_router(classrooms_router)
    app.include_router(providers_router)
    app.include_router(billing_router)
    app.include_router(admin_router)

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "textbook-tutor-api"}

    return app


app = create_app()
