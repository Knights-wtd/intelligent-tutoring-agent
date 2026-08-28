import codecs
import hashlib
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath
from typing import BinaryIO
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tutor_api.identity.models import User
from tutor_api.knowledge import indexing
from tutor_api.knowledge.access import (
    get_readable_knowledge_base,
    get_writable_knowledge_base,
    require_space_read_access,
    require_space_write_access,
)
from tutor_api.knowledge.indexing import (
    ChunkingConfig,
    EmbeddingAdapter,
    IndexBuildRequest,
    content_sha256,
    prepare_index_build,
)
from tutor_api.knowledge.models import (
    Block,
    BlockKind,
    Chunk,
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    IndexVersion,
    IndexVersionState,
    IngestionJob,
    IngestionJobKind,
    IngestionJobState,
    KnowledgeBase,
    KnowledgeUploadRequest,
    Page,
)
from tutor_api.knowledge.parsers import ParsedBlock, ParsedBlockKind, ParsedDocument
from tutor_api.knowledge.storage import (
    ObjectAlreadyExistsError,
    ObjectStorage,
    build_document_object_key,
    build_page_text_preview_object_key,
)

_KNOWLEDGE_BASE_NAME_CONSTRAINT = "uq_knowledge_base_name_in_space"
_PAGE_PREVIEW_CONTENT_TYPE = "text/plain; charset=utf-8"
_MAX_PAGE_PREVIEW_BYTES = 256 * 1024


def _is_name_conflict(error: IntegrityError) -> bool:
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == _KNOWLEDGE_BASE_NAME_CONSTRAINT:
        return True
    message = str(original)
    return (
        _KNOWLEDGE_BASE_NAME_CONSTRAINT in message
        or "knowledge_bases.space_id, knowledge_bases.name" in message
    )


def create_knowledge_base(
    session: Session,
    user: User,
    space_id: UUID,
    name: str,
) -> KnowledgeBase:
    require_space_write_access(session, user, space_id)
    knowledge_base = KnowledgeBase(
        space_id=space_id,
        owner_user_id=user.id,
        created_by_user_id=user.id,
        name=name,
    )
    try:
        with session.begin_nested():
            session.add(knowledge_base)
            session.flush()
    except IntegrityError as error:
        if _is_name_conflict(error):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="知识库名称已存在",
            ) from None
        raise
    return knowledge_base


def list_knowledge_bases(
    session: Session, user: User, space_id: UUID
) -> list[KnowledgeBase]:
    require_space_read_access(session, user, space_id)
    return list(
        session.scalars(
            select(KnowledgeBase)
            .where(KnowledgeBase.space_id == space_id)
            .order_by(KnowledgeBase.created_at, KnowledgeBase.id)
        )
    )


def get_knowledge_base(
    session: Session, user: User, knowledge_base_id: UUID
) -> KnowledgeBase:
    return get_readable_knowledge_base(session, user, knowledge_base_id)


def get_document_processing_state(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
) -> str:
    knowledge_base = get_readable_knowledge_base(session, user, knowledge_base_id)
    document = session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.knowledge_base_id == knowledge_base.id,
            Document.space_id == knowledge_base.space_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")

    version = session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == document_version_id,
            DocumentVersion.document_id == document.id,
            DocumentVersion.knowledge_base_id == knowledge_base.id,
            DocumentVersion.space_id == knowledge_base.space_id,
        )
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
    if version.state == DocumentVersionState.FAILED:
        return "failed"

    indexed = session.scalar(
        select(Chunk.id)
        .join(IndexVersion, Chunk.index_version_id == IndexVersion.id)
        .where(
            Chunk.document_version_id == version.id,
            Chunk.knowledge_base_id == knowledge_base.id,
            Chunk.space_id == knowledge_base.space_id,
            IndexVersion.knowledge_base_id == knowledge_base.id,
            IndexVersion.space_id == knowledge_base.space_id,
            IndexVersion.state == IndexVersionState.ACTIVE,
        )
        .limit(1)
    )
    if indexed is not None:
        return "searchable"

    # Push the "did any FAILED job target this version" question into SQL
    # instead of streaming every failed job of the knowledge base into Python:
    # ingestion jobs are append-only audit rows, so the old full scan degraded
    # linearly with the knowledge base's failure history.
    version_id_text = str(version.id)
    failed_build_targeting_version = session.scalar(
        select(IngestionJob.id)
        .where(
            IngestionJob.knowledge_base_id == knowledge_base.id,
            IngestionJob.space_id == knowledge_base.space_id,
            IngestionJob.state == IngestionJobState.FAILED,
            IngestionJob.kind == IngestionJobKind.BUILD_INDEX,
            IngestionJob.checkpoint["document_version_ids"].as_string().contains(
                version_id_text
            ),
        )
        .limit(1)
    )
    if failed_build_targeting_version is not None:
        return "failed"
    failed_parse_or_ocr = session.scalar(
        select(IngestionJob.id)
        .where(
            IngestionJob.knowledge_base_id == knowledge_base.id,
            IngestionJob.space_id == knowledge_base.space_id,
            IngestionJob.state == IngestionJobState.FAILED,
            IngestionJob.kind.in_(
                (IngestionJobKind.PARSE_DOCUMENT, IngestionJobKind.OCR_PAGE)
            ),
            IngestionJob.document_id == document.id,
            IngestionJob.document_version_id == version.id,
        )
        .limit(1)
    )
    if failed_parse_or_ocr is not None:
        return "failed"
    return "processing"

_UPLOAD_SOURCE_KIND = "upload"
_UPLOAD_REQUEST_KEY_CONSTRAINT = "uq_knowledge_upload_request_key"
_UPLOAD_CHUNK_BYTES = 64 * 1024
_MAX_SOURCE_NAME_LENGTH = 255
_IDEMPOTENCY_VALUE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_SUPPORTED_UPLOADS = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".zip": "application/zip",
}


@dataclass(frozen=True)
class PreparedUpload:
    source_name: str
    content_type: str
    content_sha256: str
    temporary_file: BinaryIO


@dataclass(frozen=True)
class KnowledgeUploadResult:
    document: Document
    version: DocumentVersion
    job: IngestionJob


def _is_upload_request_key_conflict(error: IntegrityError) -> bool:
    diagnostic = getattr(error.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == _UPLOAD_REQUEST_KEY_CONSTRAINT:
        return True
    message = str(error.orig)
    return (
        _UPLOAD_REQUEST_KEY_CONSTRAINT in message
        or "knowledge_upload_requests.knowledge_base_id, "
        "knowledge_upload_requests.request_key_hash" in message
    )


def _upload_error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


def _put_upload_object(
    object_storage: ObjectStorage,
    object_key: str,
    data: BinaryIO,
    *,
    content_type: str,
) -> None:
    try:
        object_storage.put_file_if_absent(
            object_key,
            data,
            content_type=content_type,
        )
    except ObjectAlreadyExistsError:
        raise _upload_error(status.HTTP_409_CONFLICT, "不可变对象已存在") from None
    except Exception:
        raise _upload_error(status.HTTP_503_SERVICE_UNAVAILABLE, "上传服务暂不可用") from None


def _normalize_idempotency_key(value: str) -> str:
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        raise _upload_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "无效的幂等键")
    normalized = value.strip()
    if not 1 <= len(normalized) <= 255 or not _IDEMPOTENCY_VALUE.fullmatch(normalized):
        raise _upload_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "无效的幂等键")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_source_name(value: str | None) -> tuple[str, str]:
    if value is None or any(
        unicodedata.category(character) in {"Cc", "Cf"} for character in value
    ):
        raise _upload_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "无效的文件名")
    normalized = unicodedata.normalize("NFC", value.strip())
    if (
        not normalized
        or len(normalized) > _MAX_SOURCE_NAME_LENGTH
        or normalized.startswith(("/", "\\"))
        or "/" in normalized
        or "\\" in normalized
        or ".." in normalized
        or re.match(r"^[A-Za-z]:", normalized)
        or any(unicodedata.category(character) in {"Cc", "Cf"} for character in normalized)
    ):
        raise _upload_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "无效的文件名")
    extension = PurePath(normalized).suffix.casefold()
    if extension not in _SUPPORTED_UPLOADS:
        raise _upload_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "不支持的文件类型")
    return normalized, extension


def _normalize_upload_content_type(value: str | None, extension: str) -> str:
    if value is None or any(
        unicodedata.category(character) in {"Cc", "Cf"} for character in value
    ):
        raise _upload_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "不支持的文件类型")
    parts = [part.strip() for part in value.split(";")]
    media_type = parts[0].casefold()
    expected = _SUPPORTED_UPLOADS[extension]
    if media_type != expected:
        raise _upload_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "不支持的文件类型")
    if len(parts) > 1:
        if extension != ".md" or len(parts) != 2 or parts[1].casefold() != "charset=utf-8":
            raise _upload_error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "不支持的文件类型")
    return expected


def _valid_signature(extension: str, prefix: bytes) -> bool:
    if extension == ".pdf":
        return prefix.startswith(b"%PDF-")
    if extension == ".png":
        return prefix.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {".jpg", ".jpeg"}:
        return prefix.startswith(b"\xff\xd8")
    if extension in {".zip", ".docx"}:
        return prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    return extension == ".md"


async def _prepare_upload(upload: UploadFile, max_bytes: int) -> PreparedUpload:
    source_name, extension = _normalize_source_name(upload.filename)
    content_type = _normalize_upload_content_type(upload.content_type, extension)
    temporary_file = tempfile.SpooledTemporaryFile(max_size=min(max_bytes, 1024 * 1024), mode="w+b")
    digest = hashlib.sha256()
    size = 0
    prefix = bytearray()
    decoder = codecs.getincrementaldecoder("utf-8")() if extension == ".md" else None
    try:
        while chunk := await upload.read(_UPLOAD_CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise _upload_error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件超过大小限制")
            if len(prefix) < 8:
                prefix.extend(chunk[: 8 - len(prefix)])
            if decoder is not None:
                if b"\x00" in chunk:
                    raise _upload_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件内容无效")
                try:
                    decoder.decode(chunk)
                except UnicodeDecodeError:
                    raise _upload_error(
                        status.HTTP_422_UNPROCESSABLE_ENTITY, "文件内容无效"
                    ) from None
            digest.update(chunk)
            temporary_file.write(chunk)
        if size == 0:
            raise _upload_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件不能为空")
        if decoder is not None:
            try:
                decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                raise _upload_error(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, "文件内容无效"
                ) from None
        if not _valid_signature(extension, bytes(prefix)):
            raise _upload_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件内容无效")
        temporary_file.seek(0)
        return PreparedUpload(source_name, content_type, digest.hexdigest(), temporary_file)
    except BaseException:
        temporary_file.close()
        raise


def _load_upload_result(session: Session, request: KnowledgeUploadRequest) -> KnowledgeUploadResult:
    document = session.get(Document, request.document_id)
    version = session.get(DocumentVersion, request.document_version_id)
    job = session.get(IngestionJob, request.ingestion_job_id)
    if document is None or version is None or job is None:
        raise RuntimeError("upload idempotency graph is incomplete")
    return KnowledgeUploadResult(document=document, version=version, job=job)


def _add_upload_request(
    session: Session,
    *,
    knowledge_base: KnowledgeBase,
    request_key_hash: str,
    prepared: PreparedUpload,
    document: Document,
    version: DocumentVersion,
    job: IngestionJob,
) -> KnowledgeUploadRequest:
    request = KnowledgeUploadRequest(
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        request_key_hash=request_key_hash,
        source_name=prepared.source_name,
        content_sha256=prepared.content_sha256,
        document_id=document.id,
        document_version_id=version.id,
        ingestion_job_id=job.id,
    )
    session.add(request)
    return request


def upload_prepared_knowledge_document(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    prepared: PreparedUpload,
    idempotency_key: str,
    object_storage: ObjectStorage,
) -> KnowledgeUploadResult:
    authorized_knowledge_base = get_writable_knowledge_base(
        session, user, knowledge_base_id
    )
    knowledge_base = session.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.id == authorized_knowledge_base.id)
        .with_for_update()
    )
    if knowledge_base is None:
        raise _upload_error(status.HTTP_404_NOT_FOUND, "资源不存在")
    request_key_hash = _normalize_idempotency_key(idempotency_key)
    replay = session.scalar(
        select(KnowledgeUploadRequest).where(
            KnowledgeUploadRequest.knowledge_base_id == knowledge_base.id,
            KnowledgeUploadRequest.request_key_hash == request_key_hash,
        )
    )
    if replay is not None:
        if (
            replay.source_name != prepared.source_name
            or replay.content_sha256 != prepared.content_sha256
        ):
            raise _upload_error(status.HTTP_409_CONFLICT, "幂等请求冲突")
        return _load_upload_result(session, replay)

    document = session.scalar(
        select(Document).where(
            Document.knowledge_base_id == knowledge_base.id,
            Document.source_kind == _UPLOAD_SOURCE_KIND,
            Document.source_key == prepared.source_name,
        )
    )
    new_document = document is None
    if document is None:
        document = Document(
            id=uuid4(),
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            owner_user_id=user.id,
            created_by_user_id=user.id,
            title=prepared.source_name,
            source_kind=_UPLOAD_SOURCE_KIND,
            source_key=prepared.source_name,
            state=DocumentState.ACTIVE,
        )

    existing_version = None if new_document else session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.content_sha256 == prepared.content_sha256,
        )
    )
    if existing_version is not None:
        existing_job = session.scalar(
            select(IngestionJob).where(
                IngestionJob.document_version_id == existing_version.id,
                IngestionJob.kind == IngestionJobKind.PARSE_DOCUMENT,
            )
        )
        if existing_job is None:
            raise RuntimeError("uploaded version has no parse job")
        try:
            with session.begin_nested():
                _add_upload_request(
                    session,
                    knowledge_base=knowledge_base,
                    request_key_hash=request_key_hash,
                    prepared=prepared,
                    document=document,
                    version=existing_version,
                    job=existing_job,
                )
                session.flush()
        except IntegrityError as error:
            if not _is_upload_request_key_conflict(error):
                raise
            replay = session.scalar(
                select(KnowledgeUploadRequest).where(
                    KnowledgeUploadRequest.knowledge_base_id == knowledge_base.id,
                    KnowledgeUploadRequest.request_key_hash == request_key_hash,
                )
            )
            if replay is None:
                raise
            if (
                replay.source_name != prepared.source_name
                or replay.content_sha256 != prepared.content_sha256
            ):
                raise _upload_error(status.HTTP_409_CONFLICT, "幂等请求冲突") from None
            return _load_upload_result(session, replay)
        return KnowledgeUploadResult(document, existing_version, existing_job)

    next_version = 1 if new_document else (
        session.scalar(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.document_id == document.id
            )
        )
        or 0
    ) + 1
    version = DocumentVersion(
        id=uuid4(),
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        version_number=next_version,
        content_sha256=prepared.content_sha256,
        object_key="pending",
        content_type=prepared.content_type,
        state=DocumentVersionState.UPLOADED,
        created_by_user_id=user.id,
    )
    version.object_key = build_document_object_key(
        knowledge_base.space_id, document.id, version.id, prepared.source_name
    )
    job = IngestionJob(
        id=uuid4(),
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        document_version_id=version.id,
        kind=IngestionJobKind.PARSE_DOCUMENT,
        state=IngestionJobState.QUEUED,
        idempotency_key=f"upload:{request_key_hash}",
        checkpoint={},
        created_by_user_id=user.id,
    )
    try:
        with session.begin_nested():
            if new_document:
                session.add(document)
            session.add_all([version, job])
            _add_upload_request(
                session,
                knowledge_base=knowledge_base,
                request_key_hash=request_key_hash,
                prepared=prepared,
                document=document,
                version=version,
                job=job,
            )
            session.flush()
            prepared.temporary_file.seek(0)
            _put_upload_object(
                object_storage,
                version.object_key,
                prepared.temporary_file,
                content_type=prepared.content_type,
            )
    except HTTPException:
        raise
    except IntegrityError as error:
        if not _is_upload_request_key_conflict(error):
            raise
        replay = session.scalar(
            select(KnowledgeUploadRequest).where(
                KnowledgeUploadRequest.knowledge_base_id == knowledge_base.id,
                KnowledgeUploadRequest.request_key_hash == request_key_hash,
            )
        )
        if replay is None:
            raise
        if (
            replay.source_name != prepared.source_name
            or replay.content_sha256 != prepared.content_sha256
        ):
            raise _upload_error(status.HTTP_409_CONFLICT, "幂等请求冲突") from None
        return _load_upload_result(session, replay)
    except Exception:
        raise _upload_error(status.HTTP_503_SERVICE_UNAVAILABLE, "上传服务暂不可用") from None
    return KnowledgeUploadResult(document, version, job)


def _persisted_block_kind(block: ParsedBlock) -> BlockKind:
    return {
        ParsedBlockKind.HEADING: BlockKind.TITLE,
        ParsedBlockKind.PARAGRAPH: BlockKind.PARAGRAPH,
        ParsedBlockKind.TABLE: BlockKind.TABLE,
    }[block.kind]


def _parsed_page_groups(
    parsed_document: ParsedDocument,
) -> list[tuple[int, tuple[ParsedBlock, ...]]]:
    if parsed_document.pages:
        return [(page.page_number, page.blocks) for page in parsed_document.pages]
    return [(1, parsed_document.blocks)]


def _validate_existing_parsed_graph(
    session: Session,
    version: DocumentVersion,
    parsed_document: ParsedDocument,
) -> None:
    pages = list(
        session.scalars(
            select(Page).where(Page.document_version_id == version.id).order_by(Page.page_number)
        )
    )
    expected_pages = _parsed_page_groups(parsed_document)
    if len(pages) != len(expected_pages):
        raise RuntimeError("parsed_document_restart_conflict")
    for page, (page_number, parsed_blocks) in zip(pages, expected_pages, strict=True):
        expected_hash = content_sha256("\n".join(block.text for block in parsed_blocks))
        expected_pointer = f"{parsed_document.source_name}#page={page_number}"
        if (
            page.space_id != version.space_id
            or page.page_number != page_number
            or page.source_pointer != expected_pointer
            or page.content_sha256 != expected_hash
        ):
            raise RuntimeError("parsed_document_restart_conflict")
        blocks = list(
            session.scalars(select(Block).where(Block.page_id == page.id).order_by(Block.ordinal))
        )
        if len(blocks) != len(parsed_blocks):
            raise RuntimeError("parsed_document_restart_conflict")
        for ordinal, (stored, parsed) in enumerate(zip(blocks, parsed_blocks, strict=True)):
            if (
                stored.space_id != version.space_id
                or stored.ordinal != ordinal
                or stored.kind is not _persisted_block_kind(parsed)
                or stored.source_pointer != parsed.source_pointer
                or stored.content_sha256 != content_sha256(parsed.text)
                or stored.text != parsed.text
            ):
                raise RuntimeError("parsed_document_restart_conflict")


def _bounded_page_preview_bytes(parsed_blocks: tuple[ParsedBlock, ...]) -> bytes:
    raw = "\n".join(block.text for block in parsed_blocks).encode("utf-8")
    if len(raw) <= _MAX_PAGE_PREVIEW_BYTES:
        return raw
    marker = b"\n[preview truncated]"
    retained = raw[: _MAX_PAGE_PREVIEW_BYTES - len(marker)]
    return retained.decode("utf-8", errors="ignore").encode("utf-8") + marker


def _persist_page_preview(
    object_storage: ObjectStorage,
    *,
    version: DocumentVersion,
    page_number: int,
    content_sha256: str,
    data: bytes,
) -> str:
    key = build_page_text_preview_object_key(
        version.space_id, version.id, page_number, content_sha256
    )
    try:
        object_storage.put_if_absent(
            key,
            data,
            content_type=_PAGE_PREVIEW_CONTENT_TYPE,
        )
    except ObjectAlreadyExistsError:
        # The key includes the immutable version and full page digest, so a retry can reuse it.
        pass
    except Exception:
        raise RuntimeError("page_preview_storage_unavailable") from None
    return key


def _persist_parsed_graph(
    session: Session,
    version: DocumentVersion,
    parsed_document: ParsedDocument,
    object_storage: ObjectStorage,
) -> None:
    existing_page = session.scalar(
        select(Page.id).where(Page.document_version_id == version.id).limit(1)
    )
    if existing_page is not None:
        _validate_existing_parsed_graph(session, version, parsed_document)
        return
    for page_number, parsed_blocks in _parsed_page_groups(parsed_document):
        page_content_sha256 = content_sha256("\n".join(block.text for block in parsed_blocks))
        page = Page(
            space_id=version.space_id,
            document_version_id=version.id,
            page_number=page_number,
            source_pointer=f"{parsed_document.source_name}#page={page_number}",
            content_sha256=page_content_sha256,
            text_object_key=_persist_page_preview(
                object_storage,
                version=version,
                page_number=page_number,
                content_sha256=page_content_sha256,
                data=_bounded_page_preview_bytes(parsed_blocks),
            ),
            source_metadata={},
        )
        session.add(page)
        session.flush()
        session.add_all(
            [
                Block(
                    space_id=version.space_id,
                    page_id=page.id,
                    ordinal=ordinal,
                    kind=_persisted_block_kind(block),
                    source_pointer=block.source_pointer,
                    content_sha256=content_sha256(block.text),
                    text=block.text,
                )
                for ordinal, block in enumerate(parsed_blocks)
            ]
        )
    session.flush()


def _latest_ready_version_ids(session: Session, knowledge_base_id: UUID) -> tuple[UUID, ...]:
    versions = session.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.knowledge_base_id == knowledge_base_id,
            DocumentVersion.state == DocumentVersionState.READY,
        )
        .order_by(DocumentVersion.document_id, DocumentVersion.version_number.desc())
    )
    latest: dict[UUID, UUID] = {}
    for version in versions:
        latest.setdefault(version.document_id, version.id)
    return tuple(sorted(latest.values(), key=str))


def enqueue_index_build(
    session: Session,
    *,
    request: IndexBuildRequest,
    embedding_adapter: EmbeddingAdapter,
    knowledge_base_locked: bool = False,
) -> IngestionJob:
    """Create or reuse the build job for one immutable index target."""

    index = prepare_index_build(
        session, request, embedding_adapter, knowledge_base_locked=knowledge_base_locked
    )
    idempotency_key = f"build:{index.index_signature}"
    existing = session.scalar(
        select(IngestionJob).where(
            IngestionJob.knowledge_base_id == request.knowledge_base_id,
            IngestionJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    job = IngestionJob(
        space_id=request.space_id,
        knowledge_base_id=request.knowledge_base_id,
        index_version_id=index.id,
        kind=IngestionJobKind.BUILD_INDEX,
        state=IngestionJobState.QUEUED,
        idempotency_key=idempotency_key,
        checkpoint={
            "document_version_ids": [str(value) for value in request.document_version_ids],
            "parser_signature": request.parser_signature,
            "ocr_signature": request.ocr_signature,
            "chunk_max_chars": request.chunking.max_chars,
            "chunk_overlap_chars": request.chunking.overlap_chars,
        },
        created_by_user_id=request.created_by_user_id,
    )
    session.add(job)
    session.flush()
    return job


def persist_parsed_document_and_enqueue_build(
    session: Session,
    *,
    document_version_id: UUID,
    parsed_document: ParsedDocument,
    parser_signature: str,
    ocr_signature: str,
    chunking: ChunkingConfig,
    embedding_adapter: EmbeddingAdapter,
    object_storage: ObjectStorage,
) -> IngestionJob:
    """Persist immutable parser output and enqueue exactly one matching index build."""

    version = session.get(DocumentVersion, document_version_id)
    if version is None:
        raise RuntimeError("document_version_not_found")
    if version.state not in (DocumentVersionState.PARSING, DocumentVersionState.READY):
        raise RuntimeError("document_version_not_parsing")
    _persist_parsed_graph(session, version, parsed_document, object_storage)
    version.state = DocumentVersionState.READY
    session.flush()
    indexing._lock_knowledge_base(session, version.knowledge_base_id)
    request = IndexBuildRequest(
        space_id=version.space_id,
        knowledge_base_id=version.knowledge_base_id,
        created_by_user_id=version.created_by_user_id,
        document_version_ids=_latest_ready_version_ids(session, version.knowledge_base_id),
        parser_signature=parser_signature,
        ocr_signature=ocr_signature,
        chunking=chunking,
    )
    return enqueue_index_build(
        session,
        request=request,
        embedding_adapter=embedding_adapter,
        knowledge_base_locked=True,
    )
