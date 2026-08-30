from threading import Lock
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Header, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from tutor_api.core.database import session_scope
from tutor_api.identity.models import User
from tutor_api.identity.router import CurrentUser, _session_factory
from tutor_api.knowledge.access import get_writable_knowledge_base
from tutor_api.knowledge.candidate_service import (
    confirm_candidate_batch,
    create_candidate_generation,
)
from tutor_api.knowledge.graph import load_knowledge_graph
from tutor_api.knowledge.models import (
    KnowledgeCandidateBatch,
    KnowledgeCandidateLink,
    KnowledgeCandidateNote,
)
from tutor_api.knowledge.retrieval import (
    SourcePreview,
    parse_preview_range,
    read_cited_page_preview,
    read_cited_source_preview,
    search_knowledge,
)
from tutor_api.knowledge.schemas import (
    ConfirmKnowledgeCandidateBatchRequest,
    CreateKnowledgeBaseRequest,
    CreateKnowledgeCandidateBatchRequest,
    KnowledgeBaseResponse,
    KnowledgeCandidateBatchResponse,
    KnowledgeCandidateLinkResponse,
    KnowledgeCandidateNoteResponse,
    KnowledgeCitationResponse,
    KnowledgeDocumentChunkResponse,
    KnowledgeDocumentResponse,
    KnowledgeDocumentStatusResponse,
    KnowledgeGraphEdgeResponse,
    KnowledgeGraphNodeResponse,
    KnowledgeGraphResponse,
    KnowledgeNoteDetailResponse,
    KnowledgeNoteReferenceResponse,
    KnowledgeNoteSummaryResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSearchResultResponse,
    KnowledgeUploadResponse,
    KnowledgeWorkspaceDocumentResponse,
    KnowledgeWorkspaceResponse,
)
from tutor_api.knowledge.service import (
    PreparedUpload,
    _prepare_upload,
    create_knowledge_base,
    delete_knowledge_base,
    get_document_processing_state,
    get_knowledge_base,
    list_document_chunks,
    list_knowledge_bases,
    list_knowledge_documents,
    upload_prepared_knowledge_document,
)
from tutor_api.knowledge.storage import ObjectStorage
from tutor_api.knowledge.workspace import load_knowledge_workspace, load_published_note

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


def _citation_secret(request: Request) -> str:
    # Must match the secret used to mint tutor-chat citations; a mismatch makes
    # tutor citations 404 on preview while search citations keep working.
    return request.app.state.settings.effective_citation_hmac_secret


def _preview_response(preview: SourcePreview) -> Response:
    end = preview.start + len(preview.data) - 1
    return Response(
        content=preview.data,
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=preview.content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {preview.start}-{end}/{preview.total_size}",
            "Content-Length": str(len(preview.data)),
            "X-Content-Type-Options": "nosniff",
        },
    )


def _preview_storage(request: Request) -> ObjectStorage:
    storage = request.app.state.object_storage
    if storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="来源预览暂不可用",
        )
    return storage


def _require_upload_access(
    session_factory: sessionmaker[Session],
    user_id: UUID,
    knowledge_base_id: UUID,
) -> None:
    with session_factory() as session:
        get_writable_knowledge_base(session, _load_upload_user(session, user_id), knowledge_base_id)


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
                source_name=result.document.source_key,
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


@router.delete(
    "/api/v1/knowledge-bases/{knowledge_base_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_knowledge_base(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> Response:
    with session_scope(_session_factory(request)) as session:
        delete_knowledge_base(session, current_user, knowledge_base_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/graph",
    response_model=KnowledgeGraphResponse,
)
def get_knowledge_graph(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> KnowledgeGraphResponse:
    with session_scope(_session_factory(request)) as session:
        graph = load_knowledge_graph(session, current_user, knowledge_base_id)
    return KnowledgeGraphResponse(
        knowledge_base_id=graph.knowledge_base_id,
        nodes=[
            KnowledgeGraphNodeResponse(
                id=node.id,
                note_id=node.note_id,
                title=node.title,
                kind=node.kind,
                source_pointers=list(node.source_pointers),
            )
            for node in graph.nodes
        ],
        edges=[
            KnowledgeGraphEdgeResponse(
                id=edge.id,
                source_id=edge.source_id,
                target_id=edge.target_id,
                kind=edge.kind,
                relation=edge.relation,
                source_pointer=edge.source_pointer,
            )
            for edge in graph.edges
        ],
    )


@router.post(
    "/api/v1/knowledge-bases/{knowledge_base_id}/search",
    response_model=KnowledgeSearchResponse,
)
def post_knowledge_search(
    knowledge_base_id: UUID,
    payload: KnowledgeSearchRequest,
    request: Request,
    current_user: CurrentUser,
) -> KnowledgeSearchResponse:
    embedding_adapter = request.app.state.embedding_adapter
    if embedding_adapter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="检索服务暂不可用",
        )
    with session_scope(_session_factory(request)) as session:
        hits = search_knowledge(
            session,
            current_user,
            knowledge_base_id,
            query=payload.query,
            limit=payload.limit,
            embedding_adapter=embedding_adapter,
            citation_secret=_citation_secret(request),
            full_content=payload.full,
        )
    return KnowledgeSearchResponse(
        results=[
            KnowledgeSearchResultResponse(
                excerpt=hit.excerpt,
                citation=KnowledgeCitationResponse(
                    id=hit.citation.id,
                    source_name=hit.citation.source_name,
                    page_number=hit.citation.page_number,
                ),
            )
            for hit in hits
        ]
    )


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/documents",
    response_model=list[KnowledgeDocumentResponse],
)
def get_knowledge_documents(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> list[KnowledgeDocumentResponse]:
    with session_scope(_session_factory(request)) as session:
        return [
            KnowledgeDocumentResponse(
                document_id=summary.document_id,
                document_version_id=summary.document_version_id,
                source_name=summary.source_name,
                processing_state=summary.processing_state,
                created_at=summary.created_at,
            )
            for summary in list_knowledge_documents(session, current_user, knowledge_base_id)
        ]


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}/chunks",
    response_model=list[KnowledgeDocumentChunkResponse],
)
def get_knowledge_document_chunks(
    knowledge_base_id: UUID,
    document_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> list[KnowledgeDocumentChunkResponse]:
    with session_scope(_session_factory(request)) as session:
        chunks = list_document_chunks(
            session,
            current_user,
            knowledge_base_id,
            document_id,
        )
        return [
            KnowledgeDocumentChunkResponse(
                ordinal=chunk.ordinal,
                content=chunk.content,
                page_number=chunk.page_number,
            )
            for chunk in chunks
        ]


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/documents/{document_id}/versions/"
    "{document_version_id}/status",
    response_model=KnowledgeDocumentStatusResponse,
)
def get_knowledge_document_status(
    knowledge_base_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> KnowledgeDocumentStatusResponse:
    with session_scope(_session_factory(request)) as session:
        processing_state = get_document_processing_state(
            session,
            current_user,
            knowledge_base_id,
            document_id,
            document_version_id,
        )
    return KnowledgeDocumentStatusResponse(
        document_id=document_id,
        document_version_id=document_version_id,
        processing_state=processing_state,
    )


@router.get("/api/v1/knowledge-bases/{knowledge_base_id}/citations/{citation_id}/source")
def get_cited_source_preview(
    knowledge_base_id: UUID,
    citation_id: str,
    request: Request,
    current_user: CurrentUser,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    try:
        offset, length = parse_preview_range(range_header)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            detail="请求范围无效",
        ) from None
    with session_scope(_session_factory(request)) as session:
        preview = read_cited_source_preview(
            session,
            current_user,
            knowledge_base_id,
            citation_id,
            offset=offset,
            length=length,
            storage=_preview_storage(request),
            citation_secret=_citation_secret(request),
        )
    return _preview_response(preview)


@router.get("/api/v1/knowledge-bases/{knowledge_base_id}/citations/{citation_id}/page")
def get_cited_page_preview(
    knowledge_base_id: UUID,
    citation_id: str,
    request: Request,
    current_user: CurrentUser,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    try:
        offset, length = parse_preview_range(range_header)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            detail="请求范围无效",
        ) from None
    with session_scope(_session_factory(request)) as session:
        preview = read_cited_page_preview(
            session,
            current_user,
            knowledge_base_id,
            citation_id,
            offset=offset,
            length=length,
            storage=_preview_storage(request),
            citation_secret=_citation_secret(request),
        )
    return _preview_response(preview)


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


def _candidate_batch_response(
    session: Session,
    batch: KnowledgeCandidateBatch,
) -> KnowledgeCandidateBatchResponse:
    notes = list(
        session.scalars(
            select(KnowledgeCandidateNote)
            .where(KnowledgeCandidateNote.batch_id == batch.id)
            .order_by(KnowledgeCandidateNote.ordinal)
        )
    )
    links = list(
        session.scalars(
            select(KnowledgeCandidateLink)
            .where(KnowledgeCandidateLink.batch_id == batch.id)
            .order_by(KnowledgeCandidateLink.ordinal)
        )
    )
    return KnowledgeCandidateBatchResponse(
        id=batch.id,
        document_id=batch.document_id,
        document_version_id=batch.document_version_id,
        generation_number=batch.generation_number,
        state=batch.state,
        failure_code=batch.failure_code,
        notes=[KnowledgeCandidateNoteResponse.model_validate(note) for note in notes],
        links=[KnowledgeCandidateLinkResponse.model_validate(link) for link in links],
        created_at=batch.created_at,
        updated_at=batch.updated_at,
    )


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/workspace",
    response_model=KnowledgeWorkspaceResponse,
)
def get_knowledge_workspace_snapshot(
    knowledge_base_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> KnowledgeWorkspaceResponse:
    with session_scope(_session_factory(request)) as session:
        snapshot = load_knowledge_workspace(session, current_user, knowledge_base_id)
        return KnowledgeWorkspaceResponse(
            knowledge_base_id=snapshot.knowledge_base_id,
            documents=[
                KnowledgeWorkspaceDocumentResponse(
                    document_id=item.document_id,
                    document_version_id=item.document_version_id,
                    source_name=item.source_name,
                    content_type=item.content_type,
                    processing_state=item.processing_state,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
                for item in snapshot.documents
            ],
            candidate_batch=(
                _candidate_batch_response(session, snapshot.candidate_batch)
                if snapshot.candidate_batch is not None
                else None
            ),
            notes=[
                KnowledgeNoteSummaryResponse(
                    id=item.id,
                    title=item.title,
                    kind=item.kind,
                    parent_id=item.parent_id,
                    source_document_id=item.source_document_id,
                    updated_at=item.updated_at,
                )
                for item in snapshot.notes
            ],
        )


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/notes/{note_id}",
    response_model=KnowledgeNoteDetailResponse,
)
def get_published_knowledge_note(
    knowledge_base_id: UUID,
    note_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> KnowledgeNoteDetailResponse:
    with session_scope(_session_factory(request)) as session:
        note = load_published_note(session, current_user, knowledge_base_id, note_id)
        return KnowledgeNoteDetailResponse(
            id=note.id,
            title=note.title,
            kind=note.kind,
            markdown=note.markdown,
            source_markers=list(note.source_markers),
            source_document_id=note.source_document_id,
            source_name=note.source_name,
            parent=(
                KnowledgeNoteReferenceResponse(id=note.parent.id, title=note.parent.title)
                if note.parent is not None
                else None
            ),
            children=[
                KnowledgeNoteReferenceResponse(id=child.id, title=child.title)
                for child in note.children
            ],
            updated_at=note.updated_at,
        )


@router.post(
    "/api/v1/knowledge-bases/{knowledge_base_id}/candidate-batches",
    response_model=KnowledgeCandidateBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_knowledge_candidate_batch(
    knowledge_base_id: UUID,
    payload: CreateKnowledgeCandidateBatchRequest,
    request: Request,
    current_user: CurrentUser,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> KnowledgeCandidateBatchResponse:
    with session_scope(_session_factory(request)) as session:
        batch, _ = create_candidate_generation(
            session,
            current_user,
            knowledge_base_id,
            payload.document_version_id,
            idempotency_key=idempotency_key,
        )
        return _candidate_batch_response(session, batch)


@router.get(
    "/api/v1/knowledge-bases/{knowledge_base_id}/candidate-batches/{batch_id}",
    response_model=KnowledgeCandidateBatchResponse,
)
def get_knowledge_candidate_batch(
    knowledge_base_id: UUID,
    batch_id: UUID,
    request: Request,
    current_user: CurrentUser,
) -> KnowledgeCandidateBatchResponse:
    with session_scope(_session_factory(request)) as session:
        knowledge_base = get_writable_knowledge_base(
            session,
            current_user,
            knowledge_base_id,
        )
        batch = session.scalar(
            select(KnowledgeCandidateBatch).where(
                KnowledgeCandidateBatch.id == batch_id,
                KnowledgeCandidateBatch.knowledge_base_id == knowledge_base.id,
                KnowledgeCandidateBatch.space_id == knowledge_base.space_id,
            )
        )
        if batch is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="资源不存在",
            )
        return _candidate_batch_response(session, batch)


@router.post(
    "/api/v1/knowledge-bases/{knowledge_base_id}/candidate-batches/{batch_id}/confirm",
    response_model=KnowledgeCandidateBatchResponse,
)
def post_confirm_knowledge_candidate_batch(
    knowledge_base_id: UUID,
    batch_id: UUID,
    payload: ConfirmKnowledgeCandidateBatchRequest,
    request: Request,
    current_user: CurrentUser,
) -> KnowledgeCandidateBatchResponse:
    with session_scope(_session_factory(request)) as session:
        batch = confirm_candidate_batch(
            session,
            current_user,
            knowledge_base_id,
            batch_id,
            accepted_note_ids=set(payload.accepted_note_ids),
            accepted_link_ids=set(payload.accepted_link_ids),
        )
        return _candidate_batch_response(session, batch)
