import json
import math
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4
from weakref import ref

from sqlalchemy import (
    DDL,
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.mutable import Mutable, MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, UserDefinedType

from tutor_api.core.database import Base


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda values: [member.value for member in values],
    )


def _sha256_check(column_name: str) -> str:
    stripped = column_name
    for character in "0123456789abcdef":
        stripped = f"replace({stripped}, '{character}', '')"
    return f"length({column_name}) = 64 AND {stripped} = ''"


class _PostgreSQLVector(UserDefinedType):
    """Compile to pgvector's unbounded VECTOR type without a runtime dependency."""

    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "VECTOR"


class EmbeddingVector(TypeDecorator[list[float]]):
    """Use pgvector on PostgreSQL and strict JSON arrays in SQLite tests."""

    impl = JSON
    cache_ok = True

    @property
    def python_type(self) -> type[list[float]]:
        return list

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PostgreSQLVector())
        return dialect.type_descriptor(JSON())

    @staticmethod
    def _normalize(value: object, *, allow_tuple: bool = False) -> list[float]:
        accepted_root = (list, tuple) if allow_tuple else (list,)
        if not isinstance(value, accepted_root):
            raise TypeError("embedding must be a list of finite numbers")
        normalized: list[float] = []
        for component in value:
            if isinstance(component, bool) or not isinstance(component, (int, float)):
                raise TypeError("embedding components must be finite int or float values")
            normalized_component = float(component)
            if not math.isfinite(normalized_component):
                raise ValueError("embedding components must be finite")
            normalized.append(normalized_component)
        return normalized

    def process_bind_param(
        self, value: list[float] | None, dialect: Dialect
    ) -> list[float] | str:
        normalized = self._normalize(value)
        if dialect.name != "postgresql":
            return normalized
        return "[" + ",".join(format(component, ".17g") for component in normalized) + "]"

    def process_result_value(self, value: object, dialect: Dialect) -> list[float]:
        if dialect.name == "postgresql":
            if isinstance(value, memoryview):
                value = value.tobytes()
            if isinstance(value, bytes):
                try:
                    value = value.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValueError("embedding bytes must be valid UTF-8") from error
            if isinstance(value, str):
                try:
                    value = json.loads(
                        value,
                        parse_constant=lambda constant: (_ for _ in ()).throw(
                            ValueError(f"invalid embedding constant: {constant}")
                        ),
                    )
                except json.JSONDecodeError as error:
                    raise ValueError("embedding result must be a JSON-style vector") from error
            return self._normalize(value, allow_tuple=True)
        return self._normalize(value)


class KnowledgeBaseState(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class DocumentState(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class DocumentVersionState(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    READY = "ready"
    FAILED = "failed"


class BlockKind(StrEnum):
    TITLE = "title"
    PARAGRAPH = "paragraph"
    FORMULA = "formula"
    TABLE = "table"
    IMAGE_CAPTION = "image_caption"
    EXAMPLE = "example"
    QUESTION = "question"
    ANSWER = "answer"


class IndexVersionState(StrEnum):
    BUILDING = "building"
    READY = "ready"
    ACTIVE = "active"
    FAILED = "failed"
    RETIRED = "retired"


class IngestionJobKind(StrEnum):
    PARSE_DOCUMENT = "parse_document"
    OCR_PAGE = "ocr_page"
    BUILD_INDEX = "build_index"


class IngestionJobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("id", "space_id", name="uq_knowledge_base_id_space"),
        UniqueConstraint("space_id", "name", name="uq_knowledge_base_name_in_space"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    state: Mapped[KnowledgeBaseState] = mapped_column(
        _enum(KnowledgeBaseState, "knowledge_base_state"),
        nullable=False,
        default=KnowledgeBaseState.ACTIVE,
        server_default=KnowledgeBaseState.ACTIVE.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("id", "space_id", name="uq_document_id_space"),
        UniqueConstraint("id", "knowledge_base_id", "space_id", name="uq_document_id_kb_space"),
        UniqueConstraint(
            "knowledge_base_id",
            "source_kind",
            "source_key",
            name="uq_document_source_in_knowledge_base",
        ),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_document_knowledge_base_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    state: Mapped[DocumentState] = mapped_column(
        _enum(DocumentState, "document_state"),
        nullable=False,
        default=DocumentState.ACTIVE,
        server_default=DocumentState.ACTIVE.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("id", "space_id", name="uq_document_version_id_space"),
        UniqueConstraint(
            "id", "knowledge_base_id", "space_id", name="uq_document_version_id_kb_space"
        ),
        UniqueConstraint(
            "id",
            "document_id",
            "knowledge_base_id",
            "space_id",
            name="uq_document_version_id_document_kb_space",
        ),
        UniqueConstraint("document_id", "version_number", name="uq_document_version_number"),
        UniqueConstraint("document_id", "content_sha256", name="uq_document_content_hash"),
        UniqueConstraint("object_key", name="uq_document_version_object_key"),
        CheckConstraint("version_number > 0", name="ck_document_version_number_positive"),
        CheckConstraint(_sha256_check("content_sha256"), name="ck_document_version_sha256"),
        ForeignKeyConstraint(
            ["document_id", "knowledge_base_id", "space_id"],
            ["documents.id", "documents.knowledge_base_id", "documents.space_id"],
            name="fk_document_version_document_kb_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[DocumentVersionState] = mapped_column(
        _enum(DocumentVersionState, "document_version_state"),
        nullable=False,
        default=DocumentVersionState.UPLOADED,
        server_default=DocumentVersionState.UPLOADED.value,
        index=True,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("id", "space_id", name="uq_page_id_space"),
        UniqueConstraint("id", "document_version_id", "space_id", name="uq_page_id_version_space"),
        UniqueConstraint("document_version_id", "page_number", name="uq_page_number"),
        UniqueConstraint("document_version_id", "source_pointer", name="uq_page_source_pointer"),
        CheckConstraint("page_number > 0", name="ck_page_number_positive"),
        CheckConstraint(_sha256_check("content_sha256"), name="ck_page_sha256"),
        ForeignKeyConstraint(
            ["document_version_id", "space_id"],
            ["document_versions.id", "document_versions.space_id"],
            name="fk_page_document_version_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_pointer: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    text_object_key: Mapped[str | None] = mapped_column(String(1024))
    image_object_key: Mapped[str | None] = mapped_column(String(1024))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Block(Base):
    __tablename__ = "blocks"
    __table_args__ = (
        UniqueConstraint("id", "space_id", name="uq_block_id_space"),
        UniqueConstraint("id", "page_id", "space_id", name="uq_block_id_page_space"),
        UniqueConstraint("page_id", "ordinal", name="uq_block_ordinal"),
        UniqueConstraint("page_id", "source_pointer", name="uq_block_source_pointer"),
        CheckConstraint("ordinal >= 0", name="ck_block_ordinal_nonnegative"),
        CheckConstraint(_sha256_check("content_sha256"), name="ck_block_sha256"),
        ForeignKeyConstraint(
            ["page_id", "space_id"],
            ["pages.id", "pages.space_id"],
            name="fk_block_page_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[BlockKind] = mapped_column(_enum(BlockKind, "block_kind"), nullable=False)
    source_pointer: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    text: Mapped[str | None] = mapped_column(Text)
    bounding_box: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IndexVersion(Base):
    __tablename__ = "index_versions"
    __table_args__ = (
        UniqueConstraint("id", "space_id", name="uq_index_version_id_space"),
        UniqueConstraint(
            "id", "knowledge_base_id", "space_id", name="uq_index_version_id_kb_space"
        ),
        UniqueConstraint(
            "id",
            "knowledge_base_id",
            "space_id",
            "embedding_dimension",
            "index_signature",
            name="uq_index_embedding_contract",
        ),
        UniqueConstraint("knowledge_base_id", "version_number", name="uq_index_version_number"),
        UniqueConstraint("knowledge_base_id", "index_signature", name="uq_index_signature"),
        CheckConstraint("version_number > 0", name="ck_index_version_number_positive"),
        CheckConstraint(
            "embedding_dimension BETWEEN 8 AND 4096",
            name="ck_index_embedding_dimension_range",
        ),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_index_knowledge_base_space",
            ondelete="CASCADE",
        ),
        Index(
            "uq_active_index_per_knowledge_base",
            "knowledge_base_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
            sqlite_where=text("state = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[IndexVersionState] = mapped_column(
        _enum(IndexVersionState, "index_version_state"),
        nullable=False,
        default=IndexVersionState.BUILDING,
        server_default=IndexVersionState.BUILDING.value,
        index=True,
    )
    parser_signature: Mapped[str] = mapped_column(String(255), nullable=False)
    ocr_signature: Mapped[str] = mapped_column(String(255), nullable=False)
    chunking_signature: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_backend: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    index_signature: Mapped[str] = mapped_column(String(512), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("id", "space_id", name="uq_chunk_id_space"),
        UniqueConstraint("index_version_id", "ordinal", name="uq_chunk_ordinal"),
        UniqueConstraint("index_version_id", "source_pointer", name="uq_chunk_source_pointer"),
        CheckConstraint("ordinal >= 0", name="ck_chunk_ordinal_nonnegative"),
        CheckConstraint(_sha256_check("content_sha256"), name="ck_chunk_sha256"),
        CheckConstraint(
            "block_id IS NULL OR page_id IS NOT NULL", name="ck_chunk_block_requires_page"
        ),
        ForeignKeyConstraint(
            [
                "index_version_id",
                "knowledge_base_id",
                "space_id",
                "embedding_dimension",
                "index_signature",
            ],
            [
                "index_versions.id",
                "index_versions.knowledge_base_id",
                "index_versions.space_id",
                "index_versions.embedding_dimension",
                "index_versions.index_signature",
            ],
            name="fk_chunk_index_embedding_contract",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "knowledge_base_id", "space_id"],
            [
                "document_versions.id",
                "document_versions.knowledge_base_id",
                "document_versions.space_id",
            ],
            name="fk_chunk_document_version_kb_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["page_id", "document_version_id", "space_id"],
            ["pages.id", "pages.document_version_id", "pages.space_id"],
            name="fk_chunk_page_version_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["block_id", "page_id", "space_id"],
            ["blocks.id", "blocks.page_id", "blocks.space_id"],
            name="fk_chunk_block_page_space",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "json_valid(embedding) AND json_type(embedding) = 'array' "
            "AND json_array_length(embedding) = embedding_dimension",
            name="ck_chunk_embedding_dimension_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "vector_dims(embedding) = embedding_dimension",
            name="ck_chunk_embedding_dimension_postgresql",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    index_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    document_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    page_id: Mapped[UUID | None] = mapped_column(index=True)
    block_id: Mapped[UUID | None] = mapped_column(index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_pointer: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    lexical_terms: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
        server_default="[]",
    )
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    index_signature: Mapped[str] = mapped_column(String(512), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


_SQLITE_EMBEDDING_INSERT_TRIGGER = DDL(
    """
    CREATE TRIGGER trg_chunks_validate_embedding_insert
    BEFORE INSERT ON chunks
    WHEN EXISTS (
        SELECT 1 FROM json_each(NEW.embedding)
        WHERE type NOT IN ('integer', 'real')
           OR value != value
           OR abs(CAST(value AS REAL)) > 1.7976931348623157e308
    )
    BEGIN
        SELECT RAISE(ABORT, 'invalid embedding element');
    END
    """
).execute_if(dialect="sqlite")
_SQLITE_EMBEDDING_UPDATE_TRIGGER = DDL(
    """
    CREATE TRIGGER trg_chunks_validate_embedding_update
    BEFORE UPDATE OF embedding, embedding_dimension ON chunks
    WHEN EXISTS (
        SELECT 1 FROM json_each(NEW.embedding)
        WHERE type NOT IN ('integer', 'real')
           OR value != value
           OR abs(CAST(value AS REAL)) > 1.7976931348623157e308
    )
    BEGIN
        SELECT RAISE(ABORT, 'invalid embedding element');
    END
    """
).execute_if(dialect="sqlite")
event.listen(Chunk.__table__, "after_create", _SQLITE_EMBEDDING_INSERT_TRIGGER)
event.listen(Chunk.__table__, "after_create", _SQLITE_EMBEDDING_UPDATE_TRIGGER)


_CHECKPOINT_TYPE = JSON().with_variant(JSONB(), "postgresql")


class _NestedMutable:
    _container_parent_ref: Any = None

    def _container_parent(self) -> Any:
        if self._container_parent_ref is None:
            return None
        return self._container_parent_ref()

    def _set_container_parent(self, parent: Any) -> None:
        self._container_parent_ref = ref(parent)

    def _clear_container_parent(self, parent: Any) -> None:
        if self._container_parent() is parent:
            self._container_parent_ref = None

    def changed(self) -> None:
        parent = self._container_parent()
        if parent is not None:
            parent.changed()
            return
        Mutable.changed(self)


_MISSING = object()


class MutableJSONDict(_NestedMutable, MutableDict):
    """Mutable JSON object that propagates changes from nested containers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        dict.__init__(self)
        for key, value in dict(*args, **kwargs).items():
            dict.__setitem__(self, key, _mutable_json_value(value, self))

    @classmethod
    def coerce(cls, key: str, value: Any) -> "MutableJSONDict | None":
        if isinstance(value, cls):
            return cls(value)
        if isinstance(value, dict):
            return cls(value)
        return Mutable.coerce(key, value)

    def __deepcopy__(self, memo: dict[int, Any]) -> "MutableJSONDict":
        copied = type(self)(self)
        memo[id(self)] = copied
        return copied

    def __setitem__(self, key: Any, value: Any) -> None:
        wrapped = _mutable_json_value(value, self)
        old_value = dict.get(self, key, _MISSING)
        dict.__setitem__(self, key, wrapped)
        if old_value is not _MISSING:
            _detach_mutable_json_value(old_value, self)
        self.changed()

    def __delitem__(self, key: Any) -> None:
        old_value = dict.__getitem__(self, key)
        dict.__delitem__(self, key)
        _detach_mutable_json_value(old_value, self)
        self.changed()

    def setdefault(self, key: Any, value: Any = None) -> Any:
        if key in self:
            return dict.__getitem__(self, key)
        self[key] = value
        return dict.__getitem__(self, key)

    def update(self, *args: Any, **kwargs: Any) -> None:
        values = dict(*args, **kwargs)
        for key, value in values.items():
            wrapped = _mutable_json_value(value, self)
            old_value = dict.get(self, key, _MISSING)
            dict.__setitem__(self, key, wrapped)
            if old_value is not _MISSING:
                _detach_mutable_json_value(old_value, self)
        if values:
            self.changed()

    def __ior__(self, value: Any) -> "MutableJSONDict":
        self.update(value)
        return self

    def pop(self, key: Any, default: Any = _MISSING) -> Any:
        if key not in self:
            if default is _MISSING:
                raise KeyError(key)
            return default
        old_value = dict.pop(self, key)
        _detach_mutable_json_value(old_value, self)
        self.changed()
        return old_value

    def popitem(self) -> tuple[Any, Any]:
        key, old_value = dict.popitem(self)
        _detach_mutable_json_value(old_value, self)
        self.changed()
        return key, old_value

    def clear(self) -> None:
        old_values = list(dict.values(self))
        dict.clear(self)
        for old_value in old_values:
            _detach_mutable_json_value(old_value, self)
        if old_values:
            self.changed()


class MutableJSONList(_NestedMutable, MutableList):
    """Mutable JSON array that propagates changes to its root object."""

    def __init__(self, values: Any = ()) -> None:
        list.__init__(self)
        list.extend(self, (_mutable_json_value(value, self) for value in values))

    def __deepcopy__(self, memo: dict[int, Any]) -> "MutableJSONList":
        copied = type(self)(self)
        memo[id(self)] = copied
        return copied

    def __setitem__(self, index: Any, value: Any) -> None:
        if isinstance(index, slice):
            old_values = list.__getitem__(self, index)
            wrapped = [_mutable_json_value(item, self) for item in value]
        else:
            old_values = [list.__getitem__(self, index)]
            wrapped = _mutable_json_value(value, self)
        list.__setitem__(self, index, wrapped)
        for old_value in old_values:
            _detach_mutable_json_value(old_value, self)
        self.changed()

    def __delitem__(self, index: Any) -> None:
        if isinstance(index, slice):
            old_values = list.__getitem__(self, index)
        else:
            old_values = [list.__getitem__(self, index)]
        list.__delitem__(self, index)
        for old_value in old_values:
            _detach_mutable_json_value(old_value, self)
        self.changed()

    def append(self, value: Any) -> None:
        list.append(self, _mutable_json_value(value, self))
        self.changed()

    def extend(self, values: Any) -> None:
        wrapped = [_mutable_json_value(value, self) for value in values]
        if wrapped:
            list.extend(self, wrapped)
            self.changed()

    def insert(self, index: int, value: Any) -> None:
        list.insert(self, index, _mutable_json_value(value, self))
        self.changed()

    def pop(self, index: int = -1) -> Any:
        old_value = list.pop(self, index)
        _detach_mutable_json_value(old_value, self)
        self.changed()
        return old_value

    def remove(self, value: Any) -> None:
        self.pop(self.index(value))

    def clear(self) -> None:
        old_values = list(self)
        list.clear(self)
        for old_value in old_values:
            _detach_mutable_json_value(old_value, self)
        if old_values:
            self.changed()


def _mutable_json_value(value: Any, parent: Any) -> Any:
    if isinstance(value, MutableJSONDict):
        value = MutableJSONDict(value)
    elif isinstance(value, MutableJSONList):
        value = MutableJSONList(value)
    elif isinstance(value, dict):
        value = MutableJSONDict(value)
    elif isinstance(value, list):
        value = MutableJSONList(value)
    else:
        return value
    value._set_container_parent(parent)
    return value


def _detach_mutable_json_value(value: Any, parent: Any) -> None:
    if isinstance(value, (MutableJSONDict, MutableJSONList)):
        value._clear_container_parent(parent)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        UniqueConstraint("id", "space_id", name="uq_ingestion_job_id_space"),
        UniqueConstraint(
            "id",
            "document_version_id",
            "document_id",
            "knowledge_base_id",
            "space_id",
            name="uq_ingestion_job_id_version_document_kb_space",
        ),
        UniqueConstraint(
            "knowledge_base_id", "idempotency_key", name="uq_ingestion_job_idempotency"
        ),
        CheckConstraint("attempt_count >= 0", name="ck_ingestion_attempt_nonnegative"),
        CheckConstraint("max_attempts > 0", name="ck_ingestion_max_attempts_positive"),
        CheckConstraint("attempt_count <= max_attempts", name="ck_ingestion_attempt_within_limit"),
        CheckConstraint(
            "state <> 'retry_wait' OR attempt_count > 0",
            name="ck_ingestion_retry_wait_has_attempt",
        ),
        CheckConstraint(
            "(state = 'running' AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'running' AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_ingestion_lease_matches_state",
        ),
        CheckConstraint(
            "(state IN ('completed', 'failed', 'cancelled') "
            "AND completed_at IS NOT NULL) OR "
            "(state NOT IN ('completed', 'failed', 'cancelled') "
            "AND completed_at IS NULL)",
            name="ck_ingestion_completed_at_matches_state",
        ),
        CheckConstraint(
            "(state = 'queued' AND started_at IS NULL) OR "
            "(state IN ('running', 'retry_wait', 'completed', 'failed') "
            "AND started_at IS NOT NULL) OR state = 'cancelled'",
            name="ck_ingestion_started_at_matches_state",
        ),
        CheckConstraint(
            "(kind = 'parse_document' AND document_id IS NOT NULL "
            "AND document_version_id IS NOT NULL AND page_id IS NULL "
            "AND index_version_id IS NULL) OR "
            "(kind = 'ocr_page' AND document_id IS NOT NULL "
            "AND document_version_id IS NOT NULL AND page_id IS NOT NULL "
            "AND index_version_id IS NULL) OR "
            "(kind = 'build_index' AND document_id IS NULL "
            "AND document_version_id IS NULL AND page_id IS NULL "
            "AND index_version_id IS NOT NULL)",
            name="ck_ingestion_target_matches_kind",
        ),
        CheckConstraint(
            "json_type(checkpoint) = 'object'",
            name="ck_ingestion_checkpoint_object_sqlite",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "jsonb_typeof(checkpoint) = 'object'",
            name="ck_ingestion_checkpoint_object_postgresql",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_ingestion_knowledge_base_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_id", "knowledge_base_id", "space_id"],
            ["documents.id", "documents.knowledge_base_id", "documents.space_id"],
            name="fk_ingestion_document_kb_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "document_id", "knowledge_base_id", "space_id"],
            [
                "document_versions.id",
                "document_versions.document_id",
                "document_versions.knowledge_base_id",
                "document_versions.space_id",
            ],
            name="fk_ingestion_version_document_kb_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["page_id", "document_version_id", "space_id"],
            ["pages.id", "pages.document_version_id", "pages.space_id"],
            name="fk_ingestion_page_version_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["index_version_id", "knowledge_base_id", "space_id"],
            [
                "index_versions.id",
                "index_versions.knowledge_base_id",
                "index_versions.space_id",
            ],
            name="fk_ingestion_index_kb_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    document_id: Mapped[UUID | None] = mapped_column(index=True)
    document_version_id: Mapped[UUID | None] = mapped_column(index=True)
    page_id: Mapped[UUID | None] = mapped_column(index=True)
    index_version_id: Mapped[UUID | None] = mapped_column(index=True)
    kind: Mapped[IngestionJobKind] = mapped_column(
        _enum(IngestionJobKind, "ingestion_job_kind"), nullable=False, index=True
    )
    state: Mapped[IngestionJobState] = mapped_column(
        _enum(IngestionJobState, "ingestion_job_state"),
        nullable=False,
        default=IngestionJobState.QUEUED,
        server_default=IngestionJobState.QUEUED.value,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        MutableJSONDict.as_mutable(_CHECKPOINT_TYPE), nullable=False, default=dict
    )
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_detail: Mapped[str | None] = mapped_column(String(1000))
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class KnowledgeUploadRequest(Base):
    __tablename__ = "knowledge_upload_requests"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id", "request_key_hash", name="uq_knowledge_upload_request_key"
        ),
        CheckConstraint(_sha256_check("request_key_hash"), name="ck_upload_request_key_hash"),
        CheckConstraint(_sha256_check("content_sha256"), name="ck_upload_request_content_hash"),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_upload_request_knowledge_base_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "document_id", "knowledge_base_id", "space_id"],
            [
                "document_versions.id",
                "document_versions.document_id",
                "document_versions.knowledge_base_id",
                "document_versions.space_id",
            ],
            name="fk_upload_request_version_document_kb_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            [
                "ingestion_job_id",
                "document_version_id",
                "document_id",
                "knowledge_base_id",
                "space_id",
            ],
            [
                "ingestion_jobs.id",
                "ingestion_jobs.document_version_id",
                "ingestion_jobs.document_id",
                "ingestion_jobs.knowledge_base_id",
                "ingestion_jobs.space_id",
            ],
            name="fk_upload_request_job_version_document_kb_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    request_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_name: Mapped[str] = mapped_column(String(500), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    document_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ingestion_job_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
