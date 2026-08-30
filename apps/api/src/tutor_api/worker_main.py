"""Process entrypoint for the database-leased ingestion worker."""

from __future__ import annotations

import json
import os
import signal
import socket
import threading
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from tutor_api.core.config import Settings, get_settings
from tutor_api.core.database import create_engine_from_url
from tutor_api.knowledge.embeddings import HashEmbeddingAdapter
from tutor_api.knowledge.formula_evidence import WikipediaFormulaEvidenceProvider
from tutor_api.knowledge.indexing import IndexingError
from tutor_api.knowledge.models import IngestionJobKind
from tutor_api.knowledge.object_deletion import run_object_deletion_once
from tutor_api.knowledge.ocr import (
    OCR_BACKEND_DISABLED,
    DisabledOCRAdapter,
    OCRAdapter,
    PDFiumPageRenderer,
)
from tutor_api.knowledge.storage import ObjectStorage, create_object_storage
from tutor_api.knowledge.worker import (
    DurableJobKind,
    WorkerConfig,
    WorkerHandlers,
    make_build_index_handler,
    make_markdown_draft_handler,
    make_parse_document_handler,
    make_semantic_plan_handler,
    make_vault_project_handler,
    make_vault_scan_handler,
    run_worker_forever,
)
from tutor_api.llm.faro import FaroOpenAICompatibleAdapter
from tutor_api.llm.http_client import create_faro_http_client
from tutor_api.vault.watcher import VaultWatcher, start_vault_watcher_thread


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    """Create the process-owned Session factory without opening a Session at import time."""

    engine = create_engine_from_url(settings.database_url, app_env=settings.app_env)
    return sessionmaker(bind=engine)


def create_ocr_adapter(settings: Settings) -> OCRAdapter:
    """Construct only explicitly supported OCR backends from validated settings."""

    if settings.ocr_backend == OCR_BACKEND_DISABLED:
        return DisabledOCRAdapter()
    raise RuntimeError("ocr_backend_unsupported")


class FaroSemanticPlanner:
    """Adapt the existing Faro Markdown completion port to semantic-plan JSON."""

    provider = "faro"

    def __init__(self, adapter: FaroOpenAICompatibleAdapter, *, model: str) -> None:
        self.adapter = adapter
        self.model = model

    def generate(self, *, prompt: str, source_text: str, source_hash: str) -> object:
        completion = self.adapter.complete_markdown(
            f"{prompt}\nsource_hash={source_hash}\n\n{source_text}"
        )
        try:
            return json.loads(completion.text)
        except json.JSONDecodeError as error:
            raise IndexingError("semantic_plan_invalid") from error


def create_handlers(
    settings: Settings, *, object_storage: ObjectStorage | None = None
) -> WorkerHandlers:
    """Build immutable runtime handlers from validated application settings."""

    adapter = HashEmbeddingAdapter(
        backend=settings.embedding_backend,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )
    object_storage = object_storage or create_object_storage(settings)
    provider_http_client = create_faro_http_client(
        proxy_url=settings.faro_proxy_url,
        timeout_seconds=settings.faro_timeout_seconds,
    )
    llm_adapter = FaroOpenAICompatibleAdapter(
        api_key=settings.faro_api_key.get_secret_value(),
        base_url=settings.faro_api_base_url,
        model=settings.faro_model,
        timeout_seconds=settings.faro_timeout_seconds,
        http_client=provider_http_client,
    )
    semantic_planner = FaroSemanticPlanner(llm_adapter, model=settings.faro_model)
    vault_root = Path(settings.agent_vault_root)
    semantic_sidecars = Path(settings.agent_sidecar_root) / "semantic-plans"
    return {
        IngestionJobKind.PARSE_DOCUMENT: make_parse_document_handler(
            object_storage,
            adapter,
            ocr_adapter=create_ocr_adapter(settings),
            renderer=PDFiumPageRenderer(),
            ocr_languages=settings.ocr_languages,
            max_vault_files=settings.max_vault_files,
            max_vault_uncompressed_bytes=settings.max_vault_uncompressed_bytes,
        ),
        IngestionJobKind.BUILD_INDEX: make_build_index_handler(adapter),
        IngestionJobKind.GENERATE_MARKDOWN: make_markdown_draft_handler(
            llm_adapter,
            max_chars=max(1, settings.faro_context_window // 2),
            max_concurrency=settings.faro_max_concurrency,
            provider="faro",
            model=settings.faro_model,
            formula_evidence_provider=WikipediaFormulaEvidenceProvider(),
        ),
        DurableJobKind.VAULT_SCAN: make_vault_scan_handler(vault_root),
        DurableJobKind.VAULT_PROJECT: make_vault_project_handler(vault_root),
        DurableJobKind.SEMANTIC_PLAN: make_semantic_plan_handler(
            adapter,
            semantic_planner,
            vault_root=vault_root,
            sidecar_root=semantic_sidecars,
        ),
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

    session_factory = create_session_factory(settings)
    watcher = VaultWatcher(
        session_factory,
        Path(settings.agent_vault_root),
        debounce=timedelta(milliseconds=settings.agent_vault_watch_debounce_ms),
        reconcile_interval=timedelta(
            seconds=settings.agent_vault_reconcile_interval_seconds
        ),
    )
    watcher_thread = start_vault_watcher_thread(watcher, stop_event)
    try:
        object_storage = create_object_storage(settings)
        worker_config = WorkerConfig(
            worker_id=default_worker_id(),
            # Minute-level spacing lets provider and object-storage jobs ride out
            # transient reachability windows without a busy retry loop.
            retry_delay=timedelta(minutes=1),
        )
        run_worker_forever(
            session_factory,
            create_handlers(settings, object_storage=object_storage),
            config=worker_config,
            should_stop=stop_event.is_set,
            maintenance=lambda: run_object_deletion_once(
                session_factory,
                object_storage,
                worker_id=worker_config.worker_id,
                lease_duration=worker_config.lease_duration,
                retry_delay=worker_config.retry_delay,
                vault_root=Path(settings.agent_vault_root),
            ),
        )
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


if __name__ == "__main__":
    main()
