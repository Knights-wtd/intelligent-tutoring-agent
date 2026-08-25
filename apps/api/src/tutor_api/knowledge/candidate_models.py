"""Tenant-scoped persistence for review-only knowledge candidates."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from tutor_api.core.database import Base
from tutor_api.knowledge.candidates import CandidateLinkKind, CandidateNoteKind


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda values: [member.value for member in values],
    )


class CandidateBatchState(StrEnum):
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    FAILED = "failed"


class CandidateReviewState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class KnowledgeCandidateBatch(Base):
    __tablename__ = "knowledge_candidate_batches"
    __table_args__ = (
        UniqueConstraint(
            "id", "knowledge_base_id", "space_id", name="uq_candidate_batch_id_kb_space"
        ),
        UniqueConstraint(
            "document_version_id",
            "generation_number",
            name="uq_candidate_batch_version_generation",
        ),
        CheckConstraint("generation_number > 0", name="ck_candidate_batch_generation_positive"),
        ForeignKeyConstraint(
            ["knowledge_base_id", "space_id"],
            ["knowledge_bases.id", "knowledge_bases.space_id"],
            name="fk_candidate_batch_knowledge_base_space",
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
            name="fk_candidate_batch_source_version_document_kb_space",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    document_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[CandidateBatchState] = mapped_column(
        _enum(CandidateBatchState, "candidate_batch_state"),
        nullable=False,
        default=CandidateBatchState.PROCESSING,
        server_default=CandidateBatchState.PROCESSING.value,
        index=True,
    )
    generation_provider: Mapped[str | None] = mapped_column(String(100))
    generation_model: Mapped[str | None] = mapped_column(String(255))
    generation_request_id: Mapped[str | None] = mapped_column(String(255))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class KnowledgeCandidateNote(Base):
    __tablename__ = "knowledge_candidate_notes"
    __table_args__ = (
        UniqueConstraint("batch_id", "ordinal", name="uq_candidate_note_batch_ordinal"),
        UniqueConstraint("batch_id", "candidate_key", name="uq_candidate_note_batch_key"),
        CheckConstraint("ordinal >= 0", name="ck_candidate_note_ordinal_nonnegative"),
        CheckConstraint("length(candidate_key) > 0", name="ck_candidate_note_key_nonempty"),
        ForeignKeyConstraint(
            ["batch_id", "knowledge_base_id", "space_id"],
            [
                "knowledge_candidate_batches.id",
                "knowledge_candidate_batches.knowledge_base_id",
                "knowledge_candidate_batches.space_id",
            ],
            name="fk_candidate_note_batch_kb_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["batch_id", "parent_key"],
            ["knowledge_candidate_notes.batch_id", "knowledge_candidate_notes.candidate_key"],
            name="fk_candidate_note_parent_in_batch",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    batch_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_key: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    kind: Mapped[CandidateNoteKind] = mapped_column(
        _enum(CandidateNoteKind, "candidate_note_kind"), nullable=False, index=True
    )
    parent_key: Mapped[str | None] = mapped_column(String(200))
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    source_pointers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    review_state: Mapped[CandidateReviewState] = mapped_column(
        _enum(CandidateReviewState, "candidate_note_review_state"),
        nullable=False,
        default=CandidateReviewState.PENDING,
        server_default=CandidateReviewState.PENDING.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class KnowledgeCandidateLink(Base):
    __tablename__ = "knowledge_candidate_links"
    __table_args__ = (
        UniqueConstraint("batch_id", "ordinal", name="uq_candidate_link_batch_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_candidate_link_ordinal_nonnegative"),
        CheckConstraint(
            "kind <> 'term' OR occurrence IS NOT NULL",
            name="ck_candidate_term_link_occurrence",
        ),
        ForeignKeyConstraint(
            ["batch_id", "knowledge_base_id", "space_id"],
            [
                "knowledge_candidate_batches.id",
                "knowledge_candidate_batches.knowledge_base_id",
                "knowledge_candidate_batches.space_id",
            ],
            name="fk_candidate_link_batch_kb_space",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["batch_id", "source_key"],
            ["knowledge_candidate_notes.batch_id", "knowledge_candidate_notes.candidate_key"],
            name="fk_candidate_link_source_in_batch",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["batch_id", "target_key"],
            ["knowledge_candidate_notes.batch_id", "knowledge_candidate_notes.candidate_key"],
            name="fk_candidate_link_target_in_batch",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    batch_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[CandidateLinkKind] = mapped_column(
        _enum(CandidateLinkKind, "candidate_link_kind"), nullable=False, index=True
    )
    relation: Mapped[str] = mapped_column(String(100), nullable=False)
    source_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    target_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_pointer: Mapped[str] = mapped_column(String(1024), nullable=False)
    occurrence: Mapped[str | None] = mapped_column(String(500))
    context: Mapped[str] = mapped_column(Text, nullable=False)
    review_state: Mapped[CandidateReviewState] = mapped_column(
        _enum(CandidateReviewState, "candidate_link_review_state"),
        nullable=False,
        default=CandidateReviewState.PENDING,
        server_default=CandidateReviewState.PENDING.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
