from threading import Lock
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from tutor_api.core.database import session_scope
from tutor_api.identity.models import User
from tutor_api.identity.router import CurrentUser, _session_factory
from tutor_api.knowledge.access import get_writable_knowledge_base
from tutor_api.knowledge.schemas import (
    CreateKnowledgeBaseRequest,
    KnowledgeBaseResponse,
    KnowledgeUploadResponse,
)
from tutor_api.knowledge.service import (
    PreparedUpload,
    _prepare_upload,
    create_knowledge_base,
    get_knowledge_base,
    list_knowledge_bases,
    upload_prepared_knowledge_document,
)
from tutor_api.knowledge.storage import ObjectStorage

router = APIRouter(tags=["knowledge bases"])


class _PreparedUploadLease:
    def __init__(self, prepared: PreparedUpload) -> None:
        self._prepared = prepared
        self._lock = Lock()
        self._worker_owned = False
        self._closed = False

    def claim_for_worker(self) -> PreparedUpload:
        with self._lock:
            if self._closed:
                raise RuntimeError("prepared upload is no longer available")
            self._worker_owned = True
            return self._prepared

    def close_if_route_owned(self) -> None:
        with self._lock:
            if self._worker_owned or self._closed:
                return
            self._closed = True
        self._prepared.temporary_file.close()

    def close_from_worker(self) -> None:
        with self._lock:
            if not self._worker_owned or self._closed:
                return
            self._closed = True
        self._prepared.temporary_file.close()


def _load_upload_user(session: Session, user_id: UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证失败")
    return user


def _require_upload_access(
    session_factory: sessionmaker[Session],
    user_id: UUID,
    knowledge_base_id: UUID,
) -> None:
    with session_factory() as session:
        get_writable_knowledge_base(
            session, _load_upload_user(session, user_id), knowledge_base_id
        )


def _commit_knowledge_upload(
    session_factory: sessionmaker[Session],
    user_id: UUID,
    knowledge_base_id: UUID,
    upload_lease: _PreparedUploadLease,
    idempotency_key: str,
    object_storage: ObjectStorage,
) -> KnowledgeUploadResponse:
    prepared = upload_lease.claim_for_worker()
    try:
        with session_scope(session_factory) as session:
            result = upload_prepared_knowledge_document(
                session,
                _load_upload_user(session, user_id),
                knowledge_base_id,
                prepared,
                idempotency_key,
                object_storage,
            )
            return KnowledgeUploadResponse(
                document_id=result.document.id,
                document_version_id=result.version.id,
                ingestion_job_id=result.job.id,
                space_id=result.document.space_id,
                knowledge_base_id=result.document.knowledge_base_id,
                source_name=result.document.source_key,
                version_number=result.version.version_number,
                content_sha256=result.version.content_sha256,
                content_type=result.version.content_type,
                document_state=result.document.state,
                version_state=result.version.state,
                job_state=result.job.state,
                created_at=result.version.created_at,
            )
    finally:
        upload_lease.close_from_worker()


@router.post(
    "/api/v1/spaces/{space_id}/knowledge-bases",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_knowledge_base(
    space_id: UUID,
    payload: CreateKnowledgeBaseRequest,
    request: Request,
    current_user: CurrentUser,
) -> KnowledgeBaseResponse:
    with session_scope(_session_factory(request)) as session:
        knowledge_base = create_knowledge_base(session, current_user, space_id, payload.name)
        return KnowledgeBaseResponse.model_validate(knowledge_base)


@router.get(
    "/api/v1/spaces/{space_id}/knowledge-bases",
    response_model=list[KnowledgeBaseResponse],
)
def get_space_knowledge_bases(
    space_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> list[KnowledgeBaseResponse]:
    with session_scope(_session_factory(request)) as session:
        return [
            KnowledgeBaseResponse.model_validate(knowledge_base)
            for knowledge_base in list_knowledge_bases(session, current_user, space_id)
        ]


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}",
    response_model=KnowledgeBaseResponse,
)
def get_knowledge_base_detail(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> KnowledgeBaseResponse:
    with session_scope(_session_factory(request)) as session:
        return KnowledgeBaseResponse.model_validate(
            get_knowledge_base(session, current_user, knowledge_base_id)
        )


@router.post(
    "/api/v1/knowledge-bases/{knowledge_base_id}/documents",
    response_model=KnowledgeUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_knowledge_document(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> KnowledgeUploadResponse:
    prepared: PreparedUpload | None = None
    upload_lease: _PreparedUploadLease | None = None
    session_factory = _session_factory(request)
    try:
        await run_in_threadpool(
            _require_upload_access,
            session_factory,
            current_user.id,
            knowledge_base_id,
        )
        object_storage = request.app.state.object_storage
        if object_storage is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="上传服务暂不可用",
            )
        prepared = await _prepare_upload(
            file, request.app.state.settings.knowledge_upload_max_bytes
        )
        upload_lease = _PreparedUploadLease(prepared)
        return await run_in_threadpool(
            _commit_knowledge_upload,
            session_factory,
            current_user.id,
            knowledge_base_id,
            upload_lease,
            idempotency_key,
            object_storage,
        )
    finally:
        if upload_lease is not None:
            upload_lease.close_if_route_owned()
        elif prepared is not None:
            prepared.temporary_file.close()
        await file.close()
