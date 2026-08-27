import hashlib
import threading
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import (
    Block,
    BlockKind,
    CandidateBatchState,
    Document,
    DocumentVersion,
    IngestionJob,
    IngestionJobKind,
    IngestionJobState,
    KnowledgeBase,
    KnowledgeCandidateBatch,
    KnowledgeCandidateLink,
    KnowledgeCandidateNote,
    MarkdownNote,
    Page,
)
from tutor_api.knowledge.worker import fail_job, make_markdown_draft_handler
from tutor_api.llm.ports import LlmCompletion, LlmProviderError, LlmUsage
from tutor_api.spaces.models import Space, SpaceKind


class SequenceAdapter:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def complete_markdown(self, source_text: str) -> LlmCompletion:
        self.prompts.append(source_text)
        return LlmCompletion(
            text=self.responses.pop(0),
            usage=LlmUsage(),
            request_id=f"request-{len(self.prompts)}",
        )


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    active_session = sessionmaker(bind=engine)()
    try:
        yield active_session
    finally:
        active_session.close()
        engine.dispose()


def create_generation_target(
    session: Session,
) -> tuple[KnowledgeCandidateBatch, IngestionJob]:
    owner = User(
        email="worker-candidates@example.com",
        username="worker-candidates",
        password_hash="h",
    )
    session.add(owner)
    session.flush()
    space = Space(owner_id=owner.id, kind=SpaceKind.PERSONAL, name="Candidate worker")
    session.add(space)
    session.flush()
    knowledge_base = KnowledgeBase(
        space_id=space.id,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        name="Wireless",
    )
    session.add(knowledge_base)
    session.flush()
    document = Document(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        owner_user_id=owner.id,
        created_by_user_id=owner.id,
        title="无线通信原理与应用",
        source_kind="upload",
        source_key="wireless.docx",
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        version_number=1,
        content_sha256="a" * 64,
        object_key="knowledge/wireless.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        created_by_user_id=owner.id,
    )
    session.add(version)
    session.flush()
    page_text = "第3章 移动无线传播\n3.1 路径损耗\n路径损耗用于描述接收功率随距离的衰减。"
    page = Page(
        space_id=space.id,
        document_version_id=version.id,
        page_number=1,
        source_pointer="wireless.docx#page=1",
        content_sha256=hashlib.sha256(page_text.encode()).hexdigest(),
    )
    session.add(page)
    session.flush()
    session.add(
        Block(
            space_id=space.id,
            page_id=page.id,
            ordinal=0,
            kind=BlockKind.PARAGRAPH,
            source_pointer="wireless.docx#block=1",
            content_sha256=hashlib.sha256(page_text.encode()).hexdigest(),
            text=page_text,
        )
    )
    batch = KnowledgeCandidateBatch(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        document_version_id=version.id,
        generation_number=1,
        created_by_user_id=owner.id,
    )
    session.add(batch)
    session.flush()
    job = IngestionJob(
        space_id=space.id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        document_version_id=version.id,
        kind=IngestionJobKind.GENERATE_MARKDOWN,
        idempotency_key=f"candidate:{batch.id}",
        checkpoint={"candidate_batch_id": str(batch.id)},
        created_by_user_id=owner.id,
    )
    session.add(job)
    session.flush()
    return batch, job


def test_worker_identifies_structure_then_persists_review_only_candidates(
    session: Session,
) -> None:
    batch, job = create_generation_target(session)
    adapter = SequenceAdapter(
        [
            '{"structures":['
            '{"key":"ch-3","title":"移动无线传播","kind":"chapter","parent_key":null,'
            '"source_pointers":["wireless.docx#block=1"]}]}',
            '{"notes":['
            '{"key":"ch-3","title":"移动无线传播","kind":"chapter","parent_key":null,'
            '"markdown":"# 移动无线传播","source_pointers":["wireless.docx#block=1"]},'
            '{"key":"term-path-loss","title":"路径损耗","kind":"concept","parent_key":"ch-3",'
            '"markdown":"# 路径损耗\\n\\n描述接收功率随距离的衰减。",'
            '"source_pointers":["wireless.docx#block=1"]}],'
            '"links":[{"kind":"structure","relation":"defines","source_key":"ch-3",'
            '"target_key":"term-path-loss","source_pointer":"wireless.docx#block=1",'
            '"occurrence":"路径损耗","context":"本章定义路径损耗"},'
            '{"kind":"term","relation":"mentions","source_key":"ch-3",'
            '"target_key":"term-path-loss","source_pointer":"wireless.docx#block=1",'
            '"occurrence":"路径损耗","context":"术语出现"}]}',
        ]
    )

    make_markdown_draft_handler(adapter, max_chars=10_000)(session, job)
    session.flush()

    assert "只识别章、节、小节" in adapter.prompts[0]
    assert "第一阶段结构" in adapter.prompts[1]
    assert batch.state is CandidateBatchState.NEEDS_REVIEW
    assert session.scalar(select(func.count()).select_from(KnowledgeCandidateNote)) == 2
    assert session.scalar(select(func.count()).select_from(KnowledgeCandidateLink)) == 2
    assert session.scalar(select(func.count()).select_from(MarkdownNote)) == 0
    assert job.checkpoint["candidate_batch_id"] == str(batch.id)
    assert job.checkpoint["candidate_note_count"] == 2
    assert job.checkpoint["candidate_link_count"] == 2


def test_terminal_provider_failure_marks_candidate_batch_failed(session: Session) -> None:
    batch, job = create_generation_target(session)
    now = datetime(2026, 8, 24, tzinfo=UTC)
    job.state = IngestionJobState.RUNNING
    job.attempt_count = 1
    job.max_attempts = 1
    job.lease_owner = "candidate-worker"
    job.lease_expires_at = now + timedelta(minutes=1)
    job.started_at = now
    session.flush()

    fail_job(
        session,
        job_id=job.id,
        worker_id="candidate-worker",
        error=LlmProviderError("llm_provider_unavailable"),
        now=now,
    )

    assert job.state is IngestionJobState.FAILED
    assert job.last_error_code == "llm_provider_unavailable"
    assert batch.state is CandidateBatchState.FAILED
    assert batch.failure_code == "llm_provider_unavailable"


def test_worker_uses_bounded_parallel_llm_calls_for_multiple_chunks(
    session: Session,
) -> None:
    _, job = create_generation_target(session)

    class ParallelAdapter:
        def __init__(self) -> None:
            self.active = 0
            self.maximum_active = 0
            self.lock = threading.Lock()
            self.two_active = threading.Event()

        def complete_markdown(self, source_text: str) -> LlmCompletion:
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                if self.active >= 2:
                    self.two_active.set()
            self.two_active.wait(timeout=2)
            with self.lock:
                self.active -= 1
            if "只识别章、节、小节" in source_text:
                text = (
                    '{"structures":[{"key":"ch-3","title":"移动无线传播",'
                    '"kind":"chapter","parent_key":null,'
                    '"source_pointers":["wireless.docx#block=1"]}]}'
                )
            else:
                text = (
                    '{"notes":[{"key":"ch-3","title":"移动无线传播",'
                    '"kind":"chapter","parent_key":null,'
                    '"markdown":"# 移动无线传播",'
                    '"source_pointers":["wireless.docx#block=1"]}],"links":[]}'
                )
            return LlmCompletion(text=text, usage=LlmUsage())

    adapter = ParallelAdapter()
    make_markdown_draft_handler(
        adapter,
        max_chars=10,
        max_concurrency=2,
    )(session, job)


def test_worker_collects_external_formula_evidence_and_persists_verification(
    session: Session,
) -> None:
    _, job = create_generation_target(session)
    block = session.scalar(select(Block))
    assert block is not None
    block.text = "Free-space model\nP_r(d)=P_t/L(d)"

    class EvidenceProvider:
        def __init__(self) -> None:
            self.sources: list[str] = []

        def collect(self, source_text: str) -> tuple[dict[str, str], ...]:
            self.sources.append(source_text)
            return (
                {
                    "title": "Free-space path loss",
                    "url": "https://en.wikipedia.org/wiki/Free-space_path_loss",
                    "source_type": "encyclopedia",
                    "excerpt": "<math>FSPL=(4\\pi d/\\lambda)^2</math>",
                },
            )

    evidence_provider = EvidenceProvider()
    adapter = SequenceAdapter(
        [
            '{"structures":[{"key":"ch-1","title":"Propagation","kind":"chapter",'
            '"parent_key":null,"source_pointers":["wireless.docx#block=1"]}]}',
            '{"notes":['
            '{"key":"ch-1","title":"Propagation","kind":"chapter","parent_key":null,'
            '"markdown":"# Propagation","source_pointers":["wireless.docx#block=1"]},'
            '{"key":"formula-fspl","title":"Free-space formula","kind":"formula",'
            '"parent_key":"ch-1","markdown":"# Formula\\n\\nP_r(d)=P_t/L(d)",'
            '"source_pointers":["wireless.docx#block=1"],'
            '"formula_verification":{"status":"verified",'
            '"textbook_expression":"P_r(d)=P_t/L(d)",'
            '"normalized_expression":"P_r(d)=P_t/L(d)",'
            '"variable_mapping":[{"textbook_symbol":"P_r(d)",'
            '"external_symbol":"P_R","meaning":"received power","unit":"W"}]},'
            '"external_sources":[{"title":"Free-space path loss",'
            '"url":"https://en.wikipedia.org/wiki/Free-space_path_loss",'
            '"source_type":"encyclopedia",'
            '"excerpt":"<math>FSPL=(4\\\\pi d/\\\\lambda)^2</math>"}]}],'
            '"links":[{"kind":"structure","relation":"uses_formula",'
            '"source_key":"ch-1","target_key":"formula-fspl",'
            '"source_pointer":"wireless.docx#block=1","occurrence":"P_r(d)",'
            '"context":"Formula used by the chapter"}]}',
        ]
    )

    make_markdown_draft_handler(
        adapter,
        max_chars=10_000,
        formula_evidence_provider=evidence_provider,
    )(session, job)
    session.flush()

    assert evidence_provider.sources == [
        "[source:wireless.docx#block=1]\nFree-space model\nP_r(d)=P_t/L(d)"
    ]
    assert "https://en.wikipedia.org/wiki/Free-space_path_loss" in adapter.prompts[1]
    formula = session.scalar(
        select(KnowledgeCandidateNote).where(KnowledgeCandidateNote.candidate_key == "formula-fspl")
    )
    assert formula is not None
    assert formula.formula_verification["status"] == "verified"
    assert formula.formula_verification["normalized_expression"] == "P_r(d)=P_t/L(d)"
    assert formula.external_sources[0]["source_type"] == "encyclopedia"
