"""Process entrypoint for the database-leased ingestion worker."""

from __future__ import annotations

import os
import signal
import socket
import threading
from collections.abc import Mapping
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from tutor_api.core.config import Settings, get_settings
from tutor_api.core.database import create_engine_from_url
from tutor_api.knowledge.embeddings import HashEmbeddingAdapter
from tutor_api.knowledge.models import IngestionJobKind
from tutor_api.knowledge.ocr import DisabledOCRAdapter, PDFiumPageRenderer
from tutor_api.knowledge.storage import create_object_storage
from tutor_api.knowledge.worker import (
    JobHandler,
    WorkerConfig,
    make_build_index_handler,
    make_parse_document_handler,
    run_worker_forever,
)


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    """Create the process-owned Session factory without opening a Session at import time."""

    engine = create_engine_from_url(settings.database_url, app_env=settings.app_env)
    return sessionmaker(bind=engine)


def create_handlers(settings: Settings) -> Mapping[IngestionJobKind, JobHandler]:
    """Build immutable runtime handlers from validated application settings."""

    adapter = HashEmbeddingAdapter(
        backend=settings.embedding_backend,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )
    object_storage = create_object_storage(settings)
    return {
        IngestionJobKind.PARSE_DOCUMENT: make_parse_document_handler(
            object_storage,
            adapter,
            ocr_adapter=DisabledOCRAdapter(),
            renderer=PDFiumPageRenderer(),
            ocr_languages=settings.ocr_languages,
            max_vault_files=settings.max_vault_files,
            max_vault_uncompressed_bytes=settings.max_vault_uncompressed_bytes,
        ),
        IngestionJobKind.BUILD_INDEX: make_build_index_handler(adapter),
    }


def default_worker_id() -> str:
    """Return a non-secret process identity suitable for database lease ownership."""

    host = socket.gethostname().strip() or "worker"
    return f"{host}:{os.getpid()}:{uuid4().hex}"[:255]


def main() -> None:
    settings = get_settings()
    production_errors = settings.production_errors()
    if production_errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(production_errors))

    stop_event = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    run_worker_forever(
        create_session_factory(settings),
        create_handlers(settings),
        config=WorkerConfig(worker_id=default_worker_id()),
        should_stop=stop_event.is_set,
    )


if __name__ == "__main__":
    main()
