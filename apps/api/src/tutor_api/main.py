from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tutor_api.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    production_errors = active_settings.production_errors()
    if production_errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(production_errors))
    app = FastAPI(title="Textbook Tutor API", version="0.1.0")
    app.state.settings = active_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[active_settings.web_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "textbook-tutor-api"}

    return app


app = create_app()
