from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Semaphore

import httpx
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.billing.router import admin_router
from tutor_api.billing.router import router as billing_router
from tutor_api.classrooms.router import router as classrooms_router
from tutor_api.core.config import Settings, get_settings
from tutor_api.core.database import create_engine_from_url
from tutor_api.identity.rate_limit import LoginRateLimiter
from tutor_api.identity.router import router as identity_router
from tutor_api.knowledge.embeddings import HashEmbeddingAdapter
from tutor_api.knowledge.router import router as knowledge_router
from tutor_api.knowledge.storage import ObjectStorage, create_object_storage
from tutor_api.llm.faro import FaroOpenAICompatibleAdapter
from tutor_api.llm.ports import TutorChatAdapter
from tutor_api.providers.router import router as providers_router
from tutor_api.providers.service import synchronize_provider_profiles
from tutor_api.question_bank.router import router as question_bank_router
from tutor_api.spaces.router import router as spaces_router
from tutor_api.tutor.router import router as tutor_router


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
    object_storage: ObjectStorage | None = None,
    tutor_adapter: TutorChatAdapter | None = None,
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
    app.state.login_rate_limiter = LoginRateLimiter(
        max_attempts=active_settings.login_max_attempts,
        lockout_seconds=active_settings.login_lockout_seconds,
    )
    # Counts every registration attempt per client IP; successes do not reset the
    # window so bulk account creation cannot slide past the cap.
    app.state.register_rate_limiter = LoginRateLimiter(
        max_attempts=active_settings.register_max_attempts,
        lockout_seconds=active_settings.register_lockout_seconds,
    )
    # A shared client keeps TLS connections pooled; when FARO_PROXY_URL is set the
    # explicit proxy is honored while trust_env stays off (no ambient env leaks).
    # A shared client keeps TLS connections pooled; transport-level retries ride
    # out TLS handshake flaps on constrained networks. When FARO_PROXY_URL is set
    # the explicit proxy is honored while trust_env stays off (no env leaks).
    if active_settings.faro_proxy_url:
        transport = httpx.HTTPTransport(
            proxy=active_settings.faro_proxy_url,
            retries=2,
            local_address="0.0.0.0",
        )
    else:
        # Pin IPv4: Docker Desktop hands out an unreachable AAAA for host-gateway
        # aliases and httpx does not fall back across address families.
        transport = httpx.HTTPTransport(retries=2, local_address="0.0.0.0")
    provider_http_client = httpx.Client(
        transport=transport,
        timeout=active_settings.faro_timeout_seconds,
        trust_env=False,
    )
    app.state.tutor_adapter = tutor_adapter or FaroOpenAICompatibleAdapter(
        api_key=active_settings.faro_api_key.get_secret_value(),
        base_url=active_settings.faro_api_base_url,
        model=active_settings.faro_model,
        timeout_seconds=active_settings.faro_timeout_seconds,
        http_client=provider_http_client,
    )
    # Bounds concurrent tutor provider calls (chat path). Guards the LLM
    # endpoint against unbounded fan-out when many learners chat at once.
    app.state.tutor_semaphore = Semaphore(active_settings.faro_max_concurrency)
    app.state.embedding_adapter = HashEmbeddingAdapter(
        backend=active_settings.embedding_backend,
        model=active_settings.embedding_model,
        dimension=active_settings.embedding_dimension,
    )
    app.state.object_storage = (
        object_storage
        if object_storage is not None or active_settings.app_env == "test"
        else create_object_storage(active_settings)
    )
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
    app.include_router(knowledge_router)
    app.include_router(tutor_router)
    app.include_router(providers_router)
    app.include_router(question_bank_router)
    app.include_router(billing_router)
    app.include_router(admin_router)

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "textbook-tutor-api"}

    return app


app = create_app()
