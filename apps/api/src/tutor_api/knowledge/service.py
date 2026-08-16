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
from tutor_api.knowledge.access import (
    get_readable_knowledge_base,
    get_writable_knowledge_base,
    require_space_read_access,
    require_space_write_access,
)
from tutor_api.knowledge.models import (
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    IngestionJob,
    IngestionJobKind,
    IngestionJobState,
    KnowledgeBase,
    KnowledgeUploadRequest,
)
from tutor_api.knowledge.storage import (
    ObjectAlreadyExistsError,
    ObjectStorage,
    build_document_object_key,
)

_KNOWLEDGE_BASE_NAME_CONSTRAINT = "uq_knowledge_base_name_in_space"


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
    except Exception:
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


async def upload_knowledge_document(
    session: Session,
    user: User,
    knowledge_base_id: UUID,
    upload: UploadFile,
    idempotency_key: str,
    object_storage: ObjectStorage | None,
    max_bytes: int,
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
    if object_storage is None:
        raise _upload_error(status.HTTP_503_SERVICE_UNAVAILABLE, "上传服务暂不可用")
    request_key_hash = _normalize_idempotency_key(idempotency_key)
    prepared = await _prepare_upload(upload, max_bytes)
    try:
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
    finally:
        prepared.temporary_file.close()
