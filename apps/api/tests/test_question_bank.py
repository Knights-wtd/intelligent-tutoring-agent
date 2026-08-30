import hashlib
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import sessionmaker

import tutor_api.question_bank.service as question_bank_service
from tutor_api.classrooms.models import ClassroomRole
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.models import (
    Chunk,
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    IndexVersion,
    IndexVersionState,
    KnowledgeBase,
)
from tutor_api.knowledge.retrieval import citation_id_for_chunk
from tutor_api.main import create_app
from tutor_api.question_bank.models import (
    Question,
    QuestionAttempt,
    QuestionAttemptAssessment,
    QuestionType,
    QuestionVersion,
)
from tutor_api.question_bank.schemas import CreateAttemptRequest
from tutor_api.question_bank.service import get_question, list_questions

QUESTION_RESPONSE_FIELDS = {
    "id",
    "question_version_id",
    "knowledge_base_id",
    "space_id",
    "version_number",
    "question_type",
    "prompt",
    "choices",
    "difficulty",
    "created_at",
}
ATTEMPT_RESPONSE_FIELDS = {
    "id",
    "question_version_id",
    "created_at",
    "correct",
    "score_basis_points",
    "error_type",
    "needs_review",
    "mastery_basis_points",
    "mastery_evidence_count",
    "review_due_at",
    "review_interval_days",
    "grading_contract_version",
    "mastery_contract_version",
    "review_policy_version",
    # 交卷后揭示的正确答案与解析。
    "expected_answer",
    "explanation",
}

REVIEW_ITEM_FIELDS = {
    "question_id",
    "question_version_id",
    "question_type",
    "prompt",
    "attempted_at",
    "correct",
    "score_basis_points",
    "error_type",
    "needs_review",
    "mastery_basis_points",
    "mastery_evidence_count",
    "review_due_at",
    "review_interval_days",
    "grading_contract_version",
    "mastery_contract_version",
    "review_policy_version",
}
REVIEW_ITEM_PRIVATE_FIELDS = {
    "answer",
    "expected_answer",
    "expected_keywords",
    "source_chunk_id",
    "source_chunk_ordinal",
    "source_pointer",
    "source_content_sha256",
    "source_index_signature",
    "document_version_id",
    "user_id",
    "space_id",
    "owner_user_id",
    "created_by_user_id",
    "request_key_hash",
    "attempt_id",
    "assessment_id",
    "prior_correct_streak",
    "next_correct_streak",
}
ATTEMPT_PRIVATE_FIELDS = {
    "answer",
    "expected_keywords",
    "source_chunk_id",
    "source_chunk_ordinal",
    "source_pointer",
    "source_content_sha256",
    "source_index_signature",
    "user_id",
    "request_key_hash",
    # expected_answer 不在此列：作答后的响应必须揭示正确答案（新契约）。
}

PRIVATE_MARKERS = {
    "expected_answer",
    "expected_keywords",
    "source_chunk_id",
    "source_chunk_ordinal",
    "source_pointer",
    "source_content_sha256",
    "source_index_signature",
    "created_by_user_id",
    "owner_user_id",
}


def make_client(*, raise_server_exceptions: bool = True) -> tuple[TestClient, object]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(engine)
    app = create_app(Settings(app_env="test"), sessionmaker(bind=engine))
    return TestClient(app, raise_server_exceptions=raise_server_exceptions), engine


def register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{username}@example.com",
            "username": username,
            "password": "Correct horse battery staple 9",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def post_knowledge_base(client: TestClient, space_id: str, name: str) -> dict:
    response = client.post(f"/api/v1/spaces/{space_id}/knowledge-bases", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def seed_active_source(
    engine: object, knowledge_base_id: str, user_id: str, suffix: str
) -> dict[str, str]:
    content = f"Private source content {suffix}"
    source_pointer = f"page:1/block:0/chunk:{suffix}"
    with sessionmaker(bind=engine)() as session:
        knowledge_base = session.get(KnowledgeBase, UUID(knowledge_base_id))
        assert knowledge_base is not None
        document = Document(
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            owner_user_id=UUID(user_id),
            created_by_user_id=UUID(user_id),
            title=f"{suffix}.pdf",
            source_kind="upload",
            source_key=f"{suffix}.pdf",
            state=DocumentState.ACTIVE,
        )
        session.add(document)
        session.flush()
        document_version = DocumentVersion(
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            version_number=1,
            content_sha256=hashlib.sha256(f"document-{suffix}".encode()).hexdigest(),
            object_key=f"spaces/{knowledge_base.space_id}/documents/{document.id}/source.pdf",
            content_type="application/pdf",
            state=DocumentVersionState.READY,
            created_by_user_id=UUID(user_id),
        )
        index = IndexVersion(
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            version_number=1,
            state=IndexVersionState.ACTIVE,
            parser_signature=f"parser-{suffix}",
            ocr_signature=f"ocr-{suffix}",
            chunking_signature=f"chunking-{suffix}",
            embedding_backend="hash",
            embedding_model="test",
            embedding_dimension=8,
            embedding_contract_signature=f"embedding-contract-{suffix}",
            index_signature=f"index-signature-{suffix}",
            created_by_user_id=UUID(user_id),
        )
        session.add_all([document_version, index])
        session.flush()
        chunk = Chunk(
            space_id=knowledge_base.space_id,
            knowledge_base_id=knowledge_base.id,
            index_version_id=index.id,
            document_version_id=document_version.id,
            page_id=None,
            block_id=None,
            ordinal=0,
            source_pointer=source_pointer,
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            content=content,
            lexical_terms=[],
            embedding_dimension=8,
            index_signature=index.index_signature,
            embedding=[0.0] * 8,
        )
        session.add(chunk)
        session.commit()
        return {
            "chunk_id": str(chunk.id),
            "document_version_id": str(document_version.id),
            "content": content,
            "content_sha256": chunk.content_sha256,
            "source_pointer": source_pointer,
            "index_signature": index.index_signature,
            "document_id": str(document.id),
            "index_version_id": str(index.id),
        }


def question_payload(citation_id: str) -> dict:
    return {
        "source_citation_id": citation_id,
        "question_type": "short",
        "prompt": "  State the theorem.  ",
        "expected_answer": "  private expected answer  ",
        "expected_keywords": [" theorem ", "", "theorem", "proof "],
    }


def test_question_bank_routes_require_authentication() -> None:
    client, engine = make_client()
    knowledge_base_id = uuid4()
    question_id = uuid4()
    question_version_id = uuid4()

    assert client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/questions",
        json=question_payload("cite_invalid"),
    ).status_code == 401
    assert client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}/questions").status_code == 401
    assert client.get(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/questions/{question_id}"
    ).status_code == 401
    assert client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/question-versions/{question_version_id}/attempts",
        json={"answer": "my answer"},
    ).status_code == 401
    assert client.get(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/review-items"
    ).status_code == 401
    assert client.get(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/question-versions/"
        f"{question_version_id}/attempt-history"
    ).status_code == 401
    engine.dispose()


def test_personal_owner_creates_question_from_scoped_citation_with_safe_responses() -> None:
    client, engine = make_client()
    registration = register(client, "question-personal-owner")
    knowledge_base = post_knowledge_base(client, registration["personal_space"]["id"], "Math")
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "personal"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )

    created_response = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions",
        json=question_payload(citation_id),
    )

    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert set(created) == QUESTION_RESPONSE_FIELDS
    assert created["knowledge_base_id"] == knowledge_base["id"]
    assert created["space_id"] == knowledge_base["space_id"]
    assert created["version_number"] == 1
    assert created["question_type"] == "short"
    assert created["prompt"] == "State the theorem."
    assert not (PRIVATE_MARKERS & set(created))
    for marker in (
        "private expected answer",
        source["content"],
        source["content_sha256"],
        source["source_pointer"],
        source["index_signature"],
    ):
        assert marker not in created_response.text

    listed_response = client.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions")
    detail_response = client.get(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions/{created['id']}"
    )
    assert listed_response.status_code == detail_response.status_code == 200
    assert listed_response.json() == [created]
    assert detail_response.json() == created

    forged = question_payload(citation_id) | {"owner_user_id": str(uuid4())}
    assert client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions", json=forged
    ).status_code == 422

    with sessionmaker(bind=engine)() as session:
        question = session.get(Question, UUID(created["id"]))
        assert question is not None
        assert question.owner_user_id == UUID(registration["user"]["id"])
        assert question.created_by_user_id == UUID(registration["user"]["id"])
        version = session.get(QuestionVersion, UUID(created["question_version_id"]))
        assert version is not None
        assert version.question_id == question.id
        assert version.document_version_id == UUID(source["document_version_id"])
        assert version.question_type == QuestionType.SHORT
        assert version.expected_answer == "private expected answer"
        assert version.expected_keywords == ["theorem", "proof"]
        assert version.source_chunk_id == UUID(source["chunk_id"])
        assert version.source_chunk_ordinal == 0
        assert version.source_pointer == source["source_pointer"]
        assert version.source_content_sha256 == source["content_sha256"]
        assert version.source_index_signature == source["index_signature"]
        assert session.scalars(select(Question)).all() == [question]
    engine.dispose()


def test_invalid_forged_or_cross_knowledge_base_citations_do_not_write_questions() -> None:
    client, engine = make_client()
    registration = register(client, "question-citation-owner")
    space_id = registration["personal_space"]["id"]
    first_knowledge_base = post_knowledge_base(client, space_id, "First")
    second_knowledge_base = post_knowledge_base(client, space_id, "Second")
    first_source = seed_active_source(
        engine, first_knowledge_base["id"], registration["user"]["id"], "first"
    )
    second_source = seed_active_source(
        engine, second_knowledge_base["id"], registration["user"]["id"], "second"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    valid_citation = citation_id_for_chunk(
        UUID(first_source["chunk_id"]), UUID(first_knowledge_base["id"]), secret
    )
    forged_citation = (
        valid_citation[:-2]
        + ("a" if valid_citation[-2] != "a" else "b")
        + valid_citation[-1]
    )
    cross_knowledge_base_citation = citation_id_for_chunk(
        UUID(second_source["chunk_id"]), UUID(second_knowledge_base["id"]), secret
    )

    for citation_id in (
        "cite_invalid",
        "cite_" + ("x" * 1_000),
        forged_citation,
        cross_knowledge_base_citation,
    ):
        response = client.post(
            f"/api/v1/knowledge-bases/{first_knowledge_base['id']}/questions",
            json=question_payload(citation_id),
        )
        assert response.status_code == 404, response.text

    with sessionmaker(bind=engine)() as session:
        assert session.scalars(select(Question)).all() == []
    engine.dispose()


def test_question_authoring_schema_forbids_server_fields_and_requires_expected_content() -> None:
    client, engine = make_client()
    registration = register(client, "question-validation-owner")
    knowledge_base = post_knowledge_base(client, registration["personal_space"]["id"], "Math")
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "validation"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )

    invalid_payloads = [
        question_payload(citation_id) | {"question_type": "choice", "expected_answer": "   "},
        question_payload(citation_id) | {"question_type": "short", "expected_answer": None},
        question_payload(citation_id)
        | {"question_type": "open", "expected_answer": " ", "expected_keywords": [" "]},
        question_payload(citation_id) | {"question_type": "unknown"},
        question_payload(citation_id) | {"document_version_id": str(uuid4())},
        question_payload(citation_id) | {"prompt": "bad\u0000prompt"},
    ]
    for payload in invalid_payloads:
        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions", json=payload
        )
        assert response.status_code == 422, response.text

    open_response = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions",
        json={
            "source_citation_id": citation_id,
            "question_type": "open",
            "prompt": " Explain the result. ",
            "expected_keywords": [" proof ", "proof", " explanation "],
        },
    )
    assert open_response.status_code == 201, open_response.text
    with sessionmaker(bind=engine)() as session:
        version = session.get(QuestionVersion, UUID(open_response.json()["question_version_id"]))
        assert version is not None
        assert version.expected_answer is None
        assert version.expected_keywords == ["proof", "explanation"]
    engine.dispose()




def test_question_keyword_resource_limits_reject_without_writes() -> None:
    client, engine = make_client()
    registration = register(client, "question-keyword-limits-owner")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Keyword Limits"
    )
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "keyword-limits"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    too_many_keywords = [f"keyword-{index}" for index in range(51)]
    too_many_keyword_characters = [f"{index:03d}{'x' * 252}" for index in range(17)]

    for expected_keywords in (too_many_keywords, too_many_keyword_characters):
        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions",
            json={
                "source_citation_id": citation_id,
                "question_type": "open",
                "prompt": "Explain the source.",
                "expected_keywords": expected_keywords,
            },
        )
        assert response.status_code == 422, response.text

    with sessionmaker(bind=engine)() as session:
        assert session.scalars(select(Question)).all() == []
    engine.dispose()


def test_public_question_reads_defer_private_orm_columns() -> None:
    client, engine = make_client()
    registration = register(client, "question-read-columns-owner")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Read Columns"
    )
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "read-columns"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    created = post_question(client, knowledge_base, citation_id)

    with sessionmaker(bind=engine)() as session:
        user = session.get(User, UUID(registration["user"]["id"]))
        assert user is not None
        results = [
            *list_questions(session, user, UUID(knowledge_base["id"])),
            get_question(session, user, UUID(knowledge_base["id"]), UUID(created["id"])),
        ]
        assert len(results) == 2
        for result in results:
            assert not {
                "id",
                "knowledge_base_id",
                "space_id",
                "created_at",
            } & inspect(result.question).unloaded
            assert {"owner_user_id", "created_by_user_id"} <= inspect(result.question).unloaded
            assert not {"id", "version_number", "question_type", "prompt"} & inspect(
                result.version
            ).unloaded
            assert {
                "knowledge_base_id",
                "space_id",
                "question_id",
                "document_version_id",
                "expected_answer",
                "expected_keywords",
                "source_chunk_id",
                "source_chunk_ordinal",
                "source_pointer",
                "source_content_sha256",
                "source_index_signature",
                "created_by_user_id",
                "created_at",
            } <= inspect(result.version).unloaded
    engine.dispose()

def create_classroom(client: TestClient, name: str = "Algebra") -> dict:
    response = client.post("/api/v1/classrooms", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def add_classroom_member(
    owner: TestClient, classroom: dict, username: str, role: ClassroomRole
) -> tuple[TestClient, dict]:
    member = TestClient(owner.app)
    registration = register(member, username)
    invite = owner.post(
        f"/api/v1/classrooms/{classroom['id']}/invites",
        json={"expires_in_hours": 24, "max_uses": 1},
    )
    assert invite.status_code == 201, invite.text
    joined = member.post("/api/v1/classrooms/join", json={"code": invite.json()["code"]})
    assert joined.status_code == 200, joined.text
    if role == ClassroomRole.TEACHER:
        promoted = owner.patch(
            f"/api/v1/classrooms/{classroom['id']}/members/{registration['user']['id']}",
            json={"role": "teacher"},
        )
        assert promoted.status_code == 200, promoted.text
    return member, registration


def post_question(client: TestClient, knowledge_base: dict, citation_id: str) -> dict:
    response = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions",
        json=question_payload(citation_id),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_classroom_owner_and_teacher_can_author_while_students_read_and_outsiders_are_hidden(
) -> None:
    owner, engine = make_client()
    owner_registration = register(owner, "question-classroom-owner")
    classroom = create_classroom(owner)
    knowledge_base = post_knowledge_base(owner, classroom["space"]["id"], "Class Math")
    source = seed_active_source(
        engine, knowledge_base["id"], owner_registration["user"]["id"], "classroom"
    )
    secret = owner.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    owner_question = post_question(owner, knowledge_base, citation_id)
    teacher, teacher_registration = add_classroom_member(
        owner, classroom, "question-classroom-teacher", ClassroomRole.TEACHER
    )
    teacher_question = post_question(teacher, knowledge_base, citation_id)
    student, _student_registration = add_classroom_member(
        owner, classroom, "question-classroom-student", ClassroomRole.STUDENT
    )
    outsider = TestClient(owner.app)
    register(outsider, "question-classroom-outsider")

    assert student.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions",
        json=question_payload(citation_id),
    ).status_code == 403
    listed = student.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions")
    detail = student.get(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions/{teacher_question['id']}"
    )
    assert listed.status_code == detail.status_code == 200
    assert {item["id"] for item in listed.json()} == {owner_question["id"], teacher_question["id"]}
    assert detail.json() == teacher_question

    assert (
        outsider.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions").status_code
        == 404
    )
    assert outsider.get(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions/{owner_question['id']}"
    ).status_code == 404
    assert outsider.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions",
        json=question_payload(citation_id),
    ).status_code == 404
    with sessionmaker(bind=engine)() as session:
        outsider_attempt_count = len(session.scalars(select(QuestionAttempt)).all())
        outsider_assessment_count = len(
            session.scalars(select(QuestionAttemptAssessment)).all()
        )
    assert outsider.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{owner_question['question_version_id']}/attempts",
        headers={"Idempotency-Key": "outsider-attempt-key"},
        json={"answer": "must remain hidden"},
    ).status_code == 404
    with sessionmaker(bind=engine)() as session:
        assert len(session.scalars(select(QuestionAttempt)).all()) == outsider_attempt_count
        assert (
            len(session.scalars(select(QuestionAttemptAssessment)).all())
            == outsider_assessment_count
        )
    assert teacher_registration["user"]["id"] != owner_registration["user"]["id"]
    engine.dispose()


def test_question_attempts_are_private_idempotent_and_tenant_scoped() -> None:
    owner, engine = make_client()
    owner_registration = register(owner, "attempt-classroom-owner")
    classroom = create_classroom(owner, "Attempt Class")
    knowledge_base = post_knowledge_base(owner, classroom["space"]["id"], "Attempts")
    source = seed_active_source(
        engine, knowledge_base["id"], owner_registration["user"]["id"], "attempt"
    )
    secret = owner.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    question = post_question(owner, knowledge_base, citation_id)
    student, student_registration = add_classroom_member(
        owner, classroom, "attempt-student", ClassroomRole.STUDENT
    )
    second_student, second_student_registration = add_classroom_member(
        owner, classroom, "attempt-second-student", ClassroomRole.STUDENT
    )
    second_knowledge_base = post_knowledge_base(owner, classroom["space"]["id"], "Other Attempts")
    attempt_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempts"
    )

    assert student.post(attempt_url, json={"answer": "missing key"}).status_code == 422
    assert student.post(
        attempt_url,
        headers={"Idempotency-Key": "attempt-key"},
        json={
            "answer": "forged",
            "user_id": student_registration["user"]["id"],
            "correct": True,
            "score_basis_points": 10_000,
        },
    ).status_code == 422

    first = student.post(
        attempt_url,
        headers={"Idempotency-Key": "  attempt-key  "},
        json={"answer": "PRIVATE   expected ANSWER"},
    )
    assert first.status_code == 201, first.text
    first_payload = first.json()
    assert set(first_payload) == ATTEMPT_RESPONSE_FIELDS
    assert first_payload | {} == first_payload
    assert first_payload["question_version_id"] == question["question_version_id"]
    assert first_payload["correct"] is True
    assert first_payload["score_basis_points"] == 10_000
    assert first_payload["error_type"] == "none"
    assert first_payload["needs_review"] is False
    assert first_payload["mastery_basis_points"] == 10_000
    assert first_payload["mastery_evidence_count"] == 1
    assert first_payload["review_interval_days"] == 7
    # 交卷后响应必须揭示正确答案与解析（若有）。
    assert first_payload["expected_answer"] == "private expected answer"
    assert not (ATTEMPT_PRIVATE_FIELDS & set(first_payload))
    for marker in (
        "PRIVATE   expected ANSWER",
        "attempt-key",
        source["content"],
    ):
        assert marker not in first.text

    wrong = student.post(
        attempt_url,
        headers={"Idempotency-Key": "wrong-key"},
        json={"answer": "wrong answer"},
    )
    assert wrong.status_code == 201, wrong.text
    wrong_payload = wrong.json()
    assert wrong_payload["correct"] is False
    assert wrong_payload["score_basis_points"] == 0
    assert wrong_payload["error_type"] == "application"
    assert wrong_payload["needs_review"] is True
    assert wrong_payload["mastery_basis_points"] == 5_000
    assert wrong_payload["mastery_evidence_count"] == 2
    assert wrong_payload["review_interval_days"] == 1

    replay = student.post(
        attempt_url,
        headers={"Idempotency-Key": "attempt-key"},
        json={"answer": "replacement private answer"},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == first_payload

    second_user = second_student.post(
        attempt_url,
        headers={"Idempotency-Key": "attempt-key"},
        json={"answer": "second private answer"},
    )
    assert second_user.status_code == 201, second_user.text
    assert second_user.json()["id"] != first_payload["id"]
    assert second_user.json()["mastery_evidence_count"] == 1

    cross_knowledge_base = second_student.post(
        f"/api/v1/knowledge-bases/{second_knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempts",
        headers={"Idempotency-Key": "cross-key"},
        json={"answer": "must not write"},
    )
    assert cross_knowledge_base.status_code == 404

    with sessionmaker(bind=engine)() as session:
        unknown_version_attempt_count = len(session.scalars(select(QuestionAttempt)).all())
        unknown_version_assessment_count = len(
            session.scalars(select(QuestionAttemptAssessment)).all()
        )
    unknown_version = student.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/{uuid4()}/attempts",
        headers={"Idempotency-Key": "unknown-version-key"},
        json={"answer": "must not write"},
    )
    assert unknown_version.status_code == 404
    with sessionmaker(bind=engine)() as session:
        assert len(session.scalars(select(QuestionAttempt)).all()) == unknown_version_attempt_count
        assert (
            len(session.scalars(select(QuestionAttemptAssessment)).all())
            == unknown_version_assessment_count
        )

    with sessionmaker(bind=engine)() as session:
        attempts = session.scalars(select(QuestionAttempt).order_by(QuestionAttempt.id)).all()
        assessments = session.scalars(
            select(QuestionAttemptAssessment).order_by(QuestionAttemptAssessment.created_at)
        ).all()
        assert len(attempts) == len(assessments) == 3
        first_attempt = session.get(QuestionAttempt, UUID(first_payload["id"]))
        assert first_attempt is not None
        assert first_attempt.answer == "PRIVATE   expected ANSWER"
        assert first_attempt.request_key_hash == hashlib.sha256(b"attempt-key").hexdigest()
        assert first_attempt.user_id == UUID(student_registration["user"]["id"])
        first_assessment = session.scalar(
            select(QuestionAttemptAssessment).where(
                QuestionAttemptAssessment.question_attempt_id == first_attempt.id
            )
        )
        assert first_assessment is not None
        assert first_assessment.correct is True
        assert first_assessment.prior_correct_streak == 0
        assert first_assessment.next_correct_streak == 1
        wrong_assessment = session.scalar(
            select(QuestionAttemptAssessment).where(
                QuestionAttemptAssessment.question_attempt_id == UUID(wrong_payload["id"])
            )
        )
        assert wrong_assessment is not None
        assert wrong_assessment.prior_correct_streak == 1
        assert wrong_assessment.next_correct_streak == 0
        assert {attempt.user_id for attempt in attempts} == {
            UUID(student_registration["user"]["id"]),
            UUID(second_student_registration["user"]["id"]),
        }
        assert {attempt.question_version_id for attempt in attempts} == {
            UUID(question["question_version_id"])
        }
    engine.dispose()


def test_open_attempts_use_server_keywords_for_partial_and_full_scores() -> None:
    client, engine = make_client()
    registration = register(client, "open-attempt-owner")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Open Attempts"
    )
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "open-attempt"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    payload = question_payload(citation_id) | {
        "question_type": "open",
        "expected_answer": None,
        "expected_keywords": ["theorem", "proof"],
    }
    created = client.post(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions", json=payload
    )
    assert created.status_code == 201, created.text
    attempt_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{created.json()['question_version_id']}/attempts"
    )

    partial = client.post(
        attempt_url,
        headers={"Idempotency-Key": "open-partial"},
        json={"answer": "The theorem is useful."},
    )
    assert partial.status_code == 201, partial.text
    assert partial.json()["correct"] is False
    assert partial.json()["score_basis_points"] == 5_000
    assert partial.json()["error_type"] == "application"
    assert partial.json()["review_interval_days"] == 3

    full = client.post(
        attempt_url,
        headers={"Idempotency-Key": "open-full"},
        json={"answer": "A theorem needs a proof."},
    )
    assert full.status_code == 201, full.text
    assert full.json()["correct"] is True
    assert full.json()["score_basis_points"] == 10_000
    assert full.json()["review_interval_days"] == 7
    engine.dispose()


def test_attempt_failure_after_attempt_flush_rolls_back_attempt_and_assessment(
    monkeypatch: object,
) -> None:
    client, engine = make_client(raise_server_exceptions=False)
    registration = register(client, "attempt-rollback-owner")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Rollback"
    )
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "rollback"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    question = post_question(client, knowledge_base, citation_id)
    attempt_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempts"
    )

    def fail_assessment(**_: object) -> object:
        raise RuntimeError("injected assessment failure")

    monkeypatch.setattr(question_bank_service, "_new_attempt_assessment", fail_assessment)
    response = client.post(
        attempt_url,
        headers={"Idempotency-Key": "rollback-key"},
        json={"answer": "private rollback answer"},
    )
    assert response.status_code == 500
    with sessionmaker(bind=engine)() as session:
        assert session.scalars(select(QuestionAttempt)).all() == []
        assert session.scalars(select(QuestionAttemptAssessment)).all() == []
    engine.dispose()


def test_legacy_attempt_replay_without_assessment_is_not_rewritten() -> None:
    client, engine = make_client()
    registration = register(client, "legacy-attempt-owner")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Legacy"
    )
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "legacy"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    question = post_question(client, knowledge_base, citation_id)
    request_key_hash = hashlib.sha256(b"legacy-key").hexdigest()
    with sessionmaker(bind=engine)() as session:
        knowledge_base_row = session.get(KnowledgeBase, UUID(knowledge_base["id"]))
        assert knowledge_base_row is not None
        legacy_attempt = QuestionAttempt(
            space_id=knowledge_base_row.space_id,
            knowledge_base_id=knowledge_base_row.id,
            question_version_id=UUID(question["question_version_id"]),
            user_id=UUID(registration["user"]["id"]),
            request_key_hash=request_key_hash,
            answer="legacy private answer",
        )
        session.add(legacy_attempt)
        session.commit()
    attempt_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempts"
    )
    response = client.post(
        attempt_url,
        headers={"Idempotency-Key": "legacy-key"},
        json={"answer": "replacement answer"},
    )
    assert response.status_code == 409
    assert "legacy private answer" not in response.text
    with sessionmaker(bind=engine)() as session:
        attempts = session.scalars(select(QuestionAttempt)).all()
        assert len(attempts) == 1
        assert attempts[0].answer == "legacy private answer"
        assert session.scalars(select(QuestionAttemptAssessment)).all() == []
    engine.dispose()

def test_submission_advisory_lock_key_is_deterministic_and_scoped() -> None:
    user_id = uuid4()
    question_version_id = uuid4()

    lock_key = question_bank_service._submission_lock_key(user_id, question_version_id)

    assert lock_key == question_bank_service._submission_lock_key(user_id, question_version_id)
    assert lock_key != question_bank_service._submission_lock_key(uuid4(), question_version_id)
    assert lock_key != question_bank_service._submission_lock_key(user_id, uuid4())


def test_postgresql_submission_lock_precedes_replay_and_history_reads(monkeypatch: object) -> None:
    events: list[tuple[str, object]] = []
    user_id = uuid4()
    question_version_id = uuid4()
    knowledge_base = SimpleNamespace(id=uuid4(), space_id=uuid4())
    version = SimpleNamespace(
        id=question_version_id,
        question_type=QuestionType.SHORT,
        expected_answer="correct",
        expected_keywords=[],
        explanation=None,
    )

    class PostgreSQLSession:
        def get_bind(self) -> object:
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement: object, parameters: object) -> object:
            events.append(("lock", (str(statement), parameters)))
            return SimpleNamespace()

        def scalars(self, _: object) -> object:
            events.append(("history", None))
            return SimpleNamespace(all=lambda: [])

        def begin_nested(self) -> object:
            return nullcontext()

        def add(self, _: object) -> None:
            return None

        def flush(self) -> None:
            return None

    def no_replay(_: object, **__: object) -> None:
        events.append(("replay", None))
        return None

    monkeypatch.setattr(
        question_bank_service,
        "get_readable_knowledge_base",
        lambda *_: knowledge_base,
    )
    monkeypatch.setattr(question_bank_service, "_private_question_version", lambda *_: version)
    monkeypatch.setattr(question_bank_service, "_replayed_attempt_result", no_replay)
    monkeypatch.setattr(
        question_bank_service,
        "_new_attempt_assessment",
        lambda **_: SimpleNamespace(),
    )

    question_bank_service.record_attempt(
        PostgreSQLSession(),
        SimpleNamespace(id=user_id),
        knowledge_base.id,
        question_version_id,
        CreateAttemptRequest(answer="correct"),
        "different-key",
    )

    assert [name for name, _ in events] == ["lock", "replay", "history"]
    statement, parameters = events[0][1]
    assert "pg_advisory_xact_lock" in statement
    assert parameters == {
        "lock_key": question_bank_service._submission_lock_key(user_id, question_version_id)
    }


def test_sqlite_submission_path_skips_postgresql_advisory_lock() -> None:
    class SQLiteSession:
        def get_bind(self) -> object:
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def execute(self, *_: object) -> object:
            raise AssertionError("SQLite must not execute PostgreSQL advisory lock SQL")

    question_bank_service._lock_submission(SQLiteSession(), uuid4(), uuid4())

def test_citation_source_must_remain_active_ready_and_present() -> None:
    client, engine = make_client()
    registration = register(client, "question-source-state-owner")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Source State"
    )
    source = seed_active_source(engine, knowledge_base["id"], registration["user"]["id"], "state")
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    question_url = f"/api/v1/knowledge-bases/{knowledge_base['id']}/questions"

    with sessionmaker(bind=engine)() as session:
        document = session.get(Document, UUID(source["document_id"]))
        assert document is not None
        document.state = DocumentState.ARCHIVED
        session.commit()
    assert client.post(question_url, json=question_payload(citation_id)).status_code == 404

    with sessionmaker(bind=engine)() as session:
        document = session.get(Document, UUID(source["document_id"]))
        document_version = session.get(DocumentVersion, UUID(source["document_version_id"]))
        assert document is not None and document_version is not None
        document.state = DocumentState.ACTIVE
        document_version.state = DocumentVersionState.PARSING
        session.commit()
    assert client.post(question_url, json=question_payload(citation_id)).status_code == 404

    with sessionmaker(bind=engine)() as session:
        document_version = session.get(DocumentVersion, UUID(source["document_version_id"]))
        index = session.get(IndexVersion, UUID(source["index_version_id"]))
        assert document_version is not None and index is not None
        document_version.state = DocumentVersionState.READY
        index.state = IndexVersionState.READY
        session.commit()
    assert client.post(question_url, json=question_payload(citation_id)).status_code == 404

    with sessionmaker(bind=engine)() as session:
        index = session.get(IndexVersion, UUID(source["index_version_id"]))
        chunk = session.get(Chunk, UUID(source["chunk_id"]))
        assert index is not None and chunk is not None
        index.state = IndexVersionState.ACTIVE
        session.delete(chunk)
        session.commit()
    assert client.post(question_url, json=question_payload(citation_id)).status_code == 404

    with sessionmaker(bind=engine)() as session:
        assert session.scalars(select(Question)).all() == []
    engine.dispose()





def test_review_items_empty_owner_queue_uses_readable_knowledge_base() -> None:
    client, engine = make_client()
    registration = register(client, "review-empty-owner")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Empty Review"
    )
    response = client.get(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/review-items"
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "next_cursor": None}
    engine.dispose()


def test_review_items_return_exact_safe_projection_and_defer_private_columns() -> None:
    client, engine = make_client()
    registration = register(client, "review-safe-owner")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Safe Review"
    )
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "review-safe"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    question = post_question(client, knowledge_base, citation_id)
    attempt_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempts"
    )
    private_answer = "private-review-answer-sentinel"
    submitted = client.post(
        attempt_url,
        headers={"Idempotency-Key": "review-safe-wrong"},
        json={"answer": private_answer},
    )
    assert submitted.status_code == 201, submitted.text

    response = client.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}/review-items")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "next_cursor"}
    assert body["next_cursor"] is None
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert set(item) == REVIEW_ITEM_FIELDS
    assert item["question_id"] == question["id"]
    assert item["question_version_id"] == question["question_version_id"]
    assert item["question_type"] == "short"
    assert item["prompt"] == "State the theorem."
    assert item["correct"] is False
    assert item["score_basis_points"] == 0
    assert item["needs_review"] is True
    assert not (REVIEW_ITEM_PRIVATE_FIELDS & set(item))
    for marker in (
        private_answer,
        "private expected answer",
        source["content"],
        source["content_sha256"],
        source["source_pointer"],
        source["index_signature"],
    ):
        assert marker not in response.text

    with sessionmaker(bind=engine)() as session:
        user = session.get(User, UUID(registration["user"]["id"]))
        assert user is not None
        result = question_bank_service.list_review_items(
            session,
            user,
            UUID(knowledge_base["id"]),
            scope="all",
            limit=20,
            cursor=None,
        )
        result_item = result.items[0]
        assert {
            "user_id",
            "space_id",
            "knowledge_base_id",
            "question_attempt_id",
            "prior_correct_streak",
            "next_correct_streak",
        } <= inspect(result_item.assessment).unloaded
        assert {
            "expected_answer",
            "expected_keywords",
            "source_chunk_id",
            "source_chunk_ordinal",
            "source_pointer",
            "source_content_sha256",
            "source_index_signature",
            "document_version_id",
            "created_by_user_id",
        } <= inspect(result_item.version).unloaded
        assert {"space_id", "knowledge_base_id", "owner_user_id", "created_by_user_id"} <= inspect(
            result_item.question
        ).unloaded
    engine.dispose()


def test_review_items_are_current_user_only_hidden_and_read_only() -> None:
    owner, engine = make_client()
    owner_registration = register(owner, "review-classroom-owner")
    classroom = create_classroom(owner, "Review Classroom")
    knowledge_base = post_knowledge_base(owner, classroom["space"]["id"], "Review Class KB")
    source = seed_active_source(
        engine, knowledge_base["id"], owner_registration["user"]["id"], "review-classroom"
    )
    secret = owner.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    question = post_question(owner, knowledge_base, citation_id)
    attempt_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempts"
    )
    assert owner.post(
        attempt_url,
        headers={"Idempotency-Key": "review-owner-wrong"},
        json={"answer": "owner wrong"},
    ).status_code == 201
    readable_other, _ = add_classroom_member(
        owner, classroom, "review-classroom-teacher", ClassroomRole.TEACHER
    )
    outsider = TestClient(owner.app)
    register(outsider, "review-classroom-outsider")
    review_url = f"/api/v1/knowledge-bases/{knowledge_base['id']}/review-items"
    with sessionmaker(bind=engine)() as session:
        attempt_count = len(session.scalars(select(QuestionAttempt)).all())
        assessment_count = len(session.scalars(select(QuestionAttemptAssessment)).all())

    readable_response = readable_other.get(review_url)
    hidden_response = outsider.get(review_url)
    assert readable_response.status_code == 200, readable_response.text
    assert readable_response.json() == {"items": [], "next_cursor": None}
    assert hidden_response.status_code == 404
    with sessionmaker(bind=engine)() as session:
        assert len(session.scalars(select(QuestionAttempt)).all()) == attempt_count
        assert len(session.scalars(select(QuestionAttemptAssessment)).all()) == assessment_count
    engine.dispose()


def test_review_items_use_latest_assessment_and_due_scope() -> None:
    client, engine = make_client()
    registration = register(client, "review-latest-owner")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Latest Review"
    )
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "review-latest"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    first_question = post_question(client, knowledge_base, citation_id)
    second_question = post_question(client, knowledge_base, citation_id)

    def submit(question: dict, key: str, answer: str) -> dict:
        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
            f"{question['question_version_id']}/attempts",
            headers={"Idempotency-Key": key},
            json={"answer": answer},
        )
        assert response.status_code == 201, response.text
        return response.json()

    older_wrong = submit(first_question, "review-older-wrong", "wrong")
    newer_correct = submit(first_question, "review-newer-correct", "private expected answer")
    latest_wrong = submit(first_question, "review-latest-wrong", "wrong again")
    future_wrong = submit(second_question, "review-future-wrong", "other wrong")
    base = datetime.now(UTC).replace(microsecond=0)
    with sessionmaker(bind=engine)() as session:
        assessments = {
            assessment.question_attempt_id: assessment
            for assessment in session.scalars(select(QuestionAttemptAssessment)).all()
        }
        assessments[UUID(older_wrong["id"])].created_at = base
        assessments[UUID(newer_correct["id"])].created_at = base + timedelta(seconds=1)
        assessments[UUID(latest_wrong["id"])].created_at = base + timedelta(seconds=2)
        assessments[UUID(latest_wrong["id"])].review_due_at = base - timedelta(minutes=1)
        assessments[UUID(future_wrong["id"])].created_at = base + timedelta(seconds=3)
        assessments[UUID(future_wrong["id"])].review_due_at = base + timedelta(days=1)
        session.commit()

    review_url = f"/api/v1/knowledge-bases/{knowledge_base['id']}/review-items"
    all_response = client.get(review_url)
    due_response = client.get(f"{review_url}?scope=due")
    assert all_response.status_code == due_response.status_code == 200
    assert [item["question_id"] for item in all_response.json()["items"]] == [
        first_question["id"],
        second_question["id"],
    ]
    assert [item["question_id"] for item in due_response.json()["items"]] == [
        first_question["id"]
    ]
    latest_item = all_response.json()["items"][0]
    assert latest_item["score_basis_points"] == latest_wrong["score_basis_points"]
    assert latest_item["correct"] is False
    engine.dispose()


def test_review_items_use_stable_keyset_pagination_and_validate_query() -> None:
    client, engine = make_client()
    registration = register(client, "review-page-owner")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Paged Review"
    )
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "review-page"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    submitted: list[tuple[dict, dict]] = []
    for index in range(3):
        question = post_question(client, knowledge_base, citation_id)
        response = client.post(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
            f"{question['question_version_id']}/attempts",
            headers={"Idempotency-Key": f"review-page-{index}"},
            json={"answer": f"wrong {index}"},
        )
        assert response.status_code == 201, response.text
        submitted.append((question, response.json()))
    base = datetime.now(UTC).replace(microsecond=0)
    with sessionmaker(bind=engine)() as session:
        assessment_question_ids: list[tuple[UUID, str]] = []
        for question, attempt in submitted:
            assessment = session.scalar(
                select(QuestionAttemptAssessment).where(
                    QuestionAttemptAssessment.question_attempt_id == UUID(attempt["id"])
                )
            )
            assert assessment is not None
            assessment.created_at = base
            assessment.review_due_at = base
            assessment_question_ids.append((assessment.id, question["id"]))
        session.commit()
    expected_question_ids = [question_id for _, question_id in sorted(assessment_question_ids)]
    review_url = f"/api/v1/knowledge-bases/{knowledge_base['id']}/review-items"
    first_page = client.get(f"{review_url}?limit=2")
    assert first_page.status_code == 200, first_page.text
    assert first_page.json()["next_cursor"] is not None
    second_page = client.get(
        f"{review_url}?limit=2&cursor={first_page.json()['next_cursor']}"
    )
    assert second_page.status_code == 200, second_page.text
    assert second_page.json()["next_cursor"] is None
    returned_question_ids = [
        item["question_id"]
        for item in first_page.json()["items"] + second_page.json()["items"]
    ]
    assert returned_question_ids == expected_question_ids
    assert len(returned_question_ids) == len(set(returned_question_ids)) == 3
    assert client.get(f"{review_url}?limit=0").status_code == 422
    assert client.get(f"{review_url}?limit=51").status_code == 422
    assert client.get(f"{review_url}?cursor=not-a-valid-cursor").status_code == 422
    assert client.get(f"{review_url}?cursor=%3F").status_code == 422
    assert client.get(f"{review_url}?cursor={'x' * 257}").status_code == 422
    assert client.get(f"{review_url}?scope=unknown").status_code == 422
    engine.dispose()

# Task5 focused tests

ATTEMPT_HISTORY_ITEM_FIELDS = {
    "question_id",
    "question_version_id",
    "question_type",
    "prompt",
    "attempted_at",
    "correct",
    "score_basis_points",
    "error_type",
    "needs_review",
    "mastery_basis_points",
    "mastery_evidence_count",
    "review_due_at",
    "review_interval_days",
    "grading_contract_version",
    "mastery_contract_version",
    "review_policy_version",
}
ATTEMPT_HISTORY_PRIVATE_FIELDS = {
    "answer",
    "expected_answer",
    "expected_keywords",
    "source_chunk_id",
    "source_chunk_ordinal",
    "source_pointer",
    "source_content_sha256",
    "source_index_signature",
    "document_version_id",
    "user_id",
    "space_id",
    "request_key_hash",
    "attempt_id",
    "assessment_id",
    "prior_correct_streak",
    "next_correct_streak",
}


def test_attempt_history_returns_owner_full_history_newest_first_with_safe_projection() -> None:
    client, engine = make_client()
    registration = register(client, "history-owner")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Attempt History"
    )
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "attempt-history"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    question = post_question(client, knowledge_base, citation_id)
    attempt_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempts"
    )
    submitted = []
    for index, answer in enumerate(("wrong oldest", "private expected answer", "wrong newest")):
        response = client.post(
            attempt_url,
            headers={"Idempotency-Key": f"history-owner-{index}"},
            json={"answer": answer},
        )
        assert response.status_code == 201, response.text
        submitted.append(response.json())

    base = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    attempt_times = [base, base + timedelta(seconds=2), base + timedelta(seconds=1)]
    with sessionmaker(bind=engine)() as session:
        assessments = {
            assessment.question_attempt_id: assessment
            for assessment in session.scalars(select(QuestionAttemptAssessment)).all()
        }
        for submitted_attempt, attempted_at in zip(submitted, attempt_times, strict=True):
            attempt = session.get(QuestionAttempt, UUID(submitted_attempt["id"]))
            assert attempt is not None
            attempt.created_at = attempted_at
            assessments[attempt.id].created_at = attempted_at + timedelta(days=1)
        session.commit()

    history_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempt-history"
    )
    response = client.get(history_url)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "next_cursor"}
    assert body["next_cursor"] is None
    assert len(body["items"]) == 3
    assert all(set(item) == ATTEMPT_HISTORY_ITEM_FIELDS for item in body["items"])
    assert [item["attempted_at"] for item in body["items"]] == [
        attempted_at.isoformat().replace("+00:00", "Z")
        for attempted_at in (attempt_times[1], attempt_times[2], attempt_times[0])
    ]
    assert [item["correct"] for item in body["items"]] == [True, False, False]
    assert not (ATTEMPT_HISTORY_PRIVATE_FIELDS & set(body["items"][0]))
    for marker in (
        "wrong newest",
        "private expected answer",
        source["content"],
        source["content_sha256"],
        source["source_pointer"],
        source["index_signature"],
    ):
        assert marker not in response.text

    with sessionmaker(bind=engine)() as session:
        user = session.get(User, UUID(registration["user"]["id"]))
        assert user is not None
        result = question_bank_service.list_attempt_history(
            session,
            user,
            UUID(knowledge_base["id"]),
            UUID(question["question_version_id"]),
            limit=20,
            cursor=None,
        )
        result_item = result.items[0]
        assert {
            "user_id",
            "space_id",
            "knowledge_base_id",
            "question_attempt_id",
            "prior_correct_streak",
            "next_correct_streak",
            "created_at",
        } <= inspect(result_item.assessment).unloaded
        assert {
            "expected_answer",
            "expected_keywords",
            "source_chunk_id",
            "source_chunk_ordinal",
            "source_pointer",
            "source_content_sha256",
            "source_index_signature",
            "document_version_id",
            "created_by_user_id",
        } <= inspect(result_item.version).unloaded
        assert {"space_id", "knowledge_base_id", "owner_user_id", "created_by_user_id"} <= inspect(
            result_item.question
        ).unloaded
    engine.dispose()


def test_attempt_history_is_current_user_only_tenant_scoped_and_read_only() -> None:
    owner, engine = make_client()
    owner_registration = register(owner, "history-classroom-owner")
    classroom = create_classroom(owner, "History Classroom")
    knowledge_base = post_knowledge_base(owner, classroom["space"]["id"], "History Class KB")
    source = seed_active_source(
        engine, knowledge_base["id"], owner_registration["user"]["id"], "history-classroom"
    )
    secret = owner.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    question = post_question(owner, knowledge_base, citation_id)
    student, student_registration = add_classroom_member(
        owner, classroom, "history-student", ClassroomRole.STUDENT
    )
    other_student, _ = add_classroom_member(
        owner, classroom, "history-other-student", ClassroomRole.STUDENT
    )
    attempt_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempts"
    )
    for attempt_client, key in (
        (student, "history-student-key"),
        (other_student, "history-other-key"),
    ):
        response = attempt_client.post(
            attempt_url,
            headers={"Idempotency-Key": key},
            json={"answer": "student answer"},
        )
        assert response.status_code == 201, response.text

    second_knowledge_base = post_knowledge_base(owner, classroom["space"]["id"], "Other History KB")
    history_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempt-history"
    )
    with sessionmaker(bind=engine)() as session:
        attempt_count = len(session.scalars(select(QuestionAttempt)).all())
        assessment_count = len(session.scalars(select(QuestionAttemptAssessment)).all())

    own_response = student.get(history_url)
    assert own_response.status_code == 200, own_response.text
    assert len(own_response.json()["items"]) == 1
    assert own_response.json()["items"][0]["question_version_id"] == question["question_version_id"]
    assert owner.get(history_url).json() == {"items": [], "next_cursor": None}
    assert owner.get(
        f"/api/v1/knowledge-bases/{second_knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempt-history"
    ).status_code == 404
    assert student.get(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/{uuid4()}/attempt-history"
    ).status_code == 404

    outsider = TestClient(owner.app)
    register(outsider, "history-outsider")
    assert outsider.get(history_url).status_code == 404
    with sessionmaker(bind=engine)() as session:
        assert len(session.scalars(select(QuestionAttempt)).all()) == attempt_count
        assert len(session.scalars(select(QuestionAttemptAssessment)).all()) == assessment_count
    assert student_registration["user"]["id"] != owner_registration["user"]["id"]
    engine.dispose()


def test_attempt_history_keyset_pagination_uses_secondary_assessment_key_and_validates_bounds(
) -> None:
    client, engine = make_client()
    registration = register(client, "history-pager")
    knowledge_base = post_knowledge_base(
        client, registration["personal_space"]["id"], "Paged Attempt History"
    )
    source = seed_active_source(
        engine, knowledge_base["id"], registration["user"]["id"], "history-pager"
    )
    secret = client.app.state.settings.object_storage_secret_key.get_secret_value()
    citation_id = citation_id_for_chunk(
        UUID(source["chunk_id"]), UUID(knowledge_base["id"]), secret
    )
    question = post_question(client, knowledge_base, citation_id)
    attempt_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempts"
    )
    submitted = []
    for index in range(3):
        response = client.post(
            attempt_url,
            headers={"Idempotency-Key": f"history-page-{index}"},
            json={"answer": f"wrong {index}"},
        )
        assert response.status_code == 201, response.text
        submitted.append(response.json())

    base = datetime(2026, 8, 21, 13, 0, tzinfo=UTC)
    expected_review_due_at = []
    with sessionmaker(bind=engine)() as session:
        for submitted_attempt in submitted:
            attempt = session.get(QuestionAttempt, UUID(submitted_attempt["id"]))
            assert attempt is not None
            attempt.created_at = base
        assessments = sorted(
            session.scalars(select(QuestionAttemptAssessment)).all(),
            key=lambda assessment: assessment.id,
            reverse=True,
        )
        for offset, assessment in enumerate(assessments, start=1):
            assessment.review_due_at = base + timedelta(days=offset)
            expected_review_due_at.append(assessment.review_due_at)
        session.commit()

    history_url = (
        f"/api/v1/knowledge-bases/{knowledge_base['id']}/question-versions/"
        f"{question['question_version_id']}/attempt-history"
    )
    first_page = client.get(f"{history_url}?limit=2")
    assert first_page.status_code == 200, first_page.text
    assert first_page.json()["next_cursor"] is not None
    second_page = client.get(
        f"{history_url}?limit=2&cursor={first_page.json()['next_cursor']}"
    )
    assert second_page.status_code == 200, second_page.text
    assert second_page.json()["next_cursor"] is None
    returned_items = first_page.json()["items"] + second_page.json()["items"]
    assert [item["attempted_at"] for item in returned_items] == [
        base.isoformat().replace("+00:00", "Z")
    ] * 3
    assert [item["review_due_at"] for item in returned_items] == [
        review_due_at.isoformat().replace("+00:00", "Z")
        for review_due_at in expected_review_due_at
    ]
    assert len({item["review_due_at"] for item in returned_items}) == 3
    assert client.get(f"{history_url}?limit=0").status_code == 422
    assert client.get(f"{history_url}?limit=51").status_code == 422
    assert client.get(f"{history_url}?cursor=not-a-valid-cursor").status_code == 422
    assert client.get(f"{history_url}?cursor=%3F").status_code == 422
    assert client.get(f"{history_url}?cursor={'x' * 257}").status_code == 422
    engine.dispose()
