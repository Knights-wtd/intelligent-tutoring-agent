from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import tutor_api.agent.models  # noqa: F401
import tutor_api.classrooms.models  # noqa: F401
import tutor_api.identity.models  # noqa: F401
import tutor_api.knowledge.models  # noqa: F401
import tutor_api.question_bank.models  # noqa: F401
import tutor_api.spaces.models  # noqa: F401
import tutor_api.tutor.models  # noqa: F401
import tutor_api.vault.models  # noqa: F401
from tutor_api.classrooms.models import ClassroomRole
from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.identity.models import User
from tutor_api.knowledge.access import get_writable_knowledge_base
from tutor_api.knowledge.models import (
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    IngestionJob,
    IngestionJobKind,
    IngestionJobState,
    KnowledgeBase,
    KnowledgeBaseState,
    ObjectDeletionOutbox,
    ObjectDeletionState,
    Page,
)
from tutor_api.knowledge.object_deletion import build_vault_scope_deletion_key
from tutor_api.main import create_app


def make_client() -> tuple[TestClient, object]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    app = create_app(Settings(app_env="test"), sessionmaker(bind=engine))
    return TestClient(app), engine


def register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{username}@example.com",
            "username": username,
            "password": "Correct horse battery staple 9",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_classroom(client: TestClient, name: str = "删除权限班级") -> dict:
    response = client.post("/api/v1/classrooms", json={"name": name})
    assert response.status_code == 201
    return response.json()


def add_classroom_member(
    owner: TestClient,
    classroom: dict,
    username: str,
    role: ClassroomRole,
) -> TestClient:
    member = TestClient(owner.app)
    registration = register(member, username)
    invite = owner.post(
        f"/api/v1/classrooms/{classroom['id']}/invites",
        json={"expires_in_hours": 24, "max_uses": 1},
    )
    assert invite.status_code == 201
    joined = member.post("/api/v1/classrooms/join", json={"code": invite.json()["code"]})
    assert joined.status_code == 200
    if role == ClassroomRole.TEACHER:
        promoted = owner.patch(
            f"/api/v1/classrooms/{classroom['id']}/members/{registration['user']['id']}",
            json={"role": "teacher"},
        )
        assert promoted.status_code == 200
    return member


def post_knowledge_base(client: TestClient, space_id: str, name: str) -> dict:
    response = client.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases",
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def seed_document_graph(
    session: Session,
    *,
    knowledge_base: KnowledgeBase,
    job_state: IngestionJobState,
) -> tuple[Document, DocumentVersion, Page, IngestionJob]:
    now = datetime.now(UTC)
    document = Document(
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        owner_user_id=knowledge_base.owner_user_id,
        created_by_user_id=knowledge_base.created_by_user_id,
        title="待删除资料",
        source_kind="upload",
        source_key=f"delete-test-{uuid4()}.pdf",
        state=DocumentState.ACTIVE,
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        version_number=1,
        content_sha256="a" * 64,
        object_key=f"documents/{uuid4()}.pdf",
        content_type="application/pdf",
        state=DocumentVersionState.UPLOADED,
        created_by_user_id=knowledge_base.created_by_user_id,
    )
    session.add(version)
    session.flush()
    page = Page(
        space_id=knowledge_base.space_id,
        document_version_id=version.id,
        page_number=1,
        source_pointer="page:1",
        content_sha256="b" * 64,
        text_object_key=f"pages/{uuid4()}.txt",
        image_object_key=f"pages/{uuid4()}.png",
        source_metadata={},
    )
    session.add(page)
    session.flush()
    running = job_state == IngestionJobState.RUNNING
    retrying = job_state == IngestionJobState.RETRY_WAIT
    job = IngestionJob(
        space_id=knowledge_base.space_id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        document_version_id=version.id,
        kind=IngestionJobKind.PARSE_DOCUMENT,
        state=job_state,
        idempotency_key=f"delete-test:{uuid4()}",
        attempt_count=1 if running or retrying else 0,
        max_attempts=3,
        checkpoint={},
        lease_owner="worker-1" if running else None,
        lease_expires_at=now if running else None,
        started_at=now if running or retrying else None,
        created_by_user_id=knowledge_base.created_by_user_id,
    )
    session.add(job)
    session.commit()
    return document, version, page, job


def test_delete_route_requires_authentication() -> None:
    client, engine = make_client()
    assert client.delete(f"/api/v1/knowledge-bases/{uuid4()}").status_code == 401
    engine.dispose()


def test_personal_owner_hard_deletes_graph_and_enqueues_object_cleanup() -> None:
    client, engine = make_client()
    registration = register(client, "delete-personal-owner")
    created = post_knowledge_base(
        client, registration["personal_space"]["id"], "永久删除测试"
    )
    knowledge_base_id = UUID(created["id"])
    with Session(engine) as session:
        knowledge_base = session.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        document, version, page, job = seed_document_graph(
            session,
            knowledge_base=knowledge_base,
            job_state=IngestionJobState.QUEUED,
        )
        ids = (document.id, version.id, page.id, job.id)
        expected_keys = {
            version.object_key,
            page.text_object_key,
            page.image_object_key,
            build_vault_scope_deletion_key(
                knowledge_base.space_id,
                knowledge_base.id,
            ),
        }

    response = client.delete(f"/api/v1/knowledge-bases/{knowledge_base_id}")

    assert response.status_code == 204
    assert response.content == b""
    with Session(engine) as session:
        assert session.get(KnowledgeBase, knowledge_base_id) is None
        assert session.get(Document, ids[0]) is None
        assert session.get(DocumentVersion, ids[1]) is None
        assert session.get(Page, ids[2]) is None
        assert session.get(IngestionJob, ids[3]) is None
        outbox = list(session.scalars(select(ObjectDeletionOutbox)))
        assert {item.object_key for item in outbox} == expected_keys
        assert {item.state for item in outbox} == {ObjectDeletionState.PENDING}
        assert all(item.attempt_count == 0 for item in outbox)
    engine.dispose()


def test_delete_does_not_enqueue_object_key_still_referenced_by_another_knowledge_base() -> None:
    client, engine = make_client()
    registration = register(client, "delete-shared-object-owner")
    space_id = registration["personal_space"]["id"]
    first = post_knowledge_base(client, space_id, "共享对象来源")
    second = post_knowledge_base(client, space_id, "共享对象保留")

    with Session(engine) as session:
        first_knowledge_base = session.get(KnowledgeBase, UUID(first["id"]))
        second_knowledge_base = session.get(KnowledgeBase, UUID(second["id"]))
        assert first_knowledge_base is not None
        assert second_knowledge_base is not None
        _, first_version, first_page, _ = seed_document_graph(
            session,
            knowledge_base=first_knowledge_base,
            job_state=IngestionJobState.QUEUED,
        )
        _, _, second_page, _ = seed_document_graph(
            session,
            knowledge_base=second_knowledge_base,
            job_state=IngestionJobState.QUEUED,
        )
        shared_key = first_page.text_object_key
        assert shared_key is not None
        second_page.text_object_key = shared_key
        second_page_id = second_page.id
        session.commit()
        exclusive_keys = {
            first_version.object_key,
            first_page.image_object_key,
            build_vault_scope_deletion_key(
                first_knowledge_base.space_id,
                first_knowledge_base.id,
            ),
        }

    response = client.delete(f"/api/v1/knowledge-bases/{first['id']}")

    assert response.status_code == 204
    with Session(engine) as session:
        assert session.get(KnowledgeBase, UUID(second["id"])) is not None
        assert session.get(Page, second_page_id) is not None
        queued_keys = {
            item.object_key for item in session.scalars(select(ObjectDeletionOutbox))
        }
        assert queued_keys == exclusive_keys
        assert shared_key not in queued_keys
    engine.dispose()


def test_classroom_owner_can_delete_members_are_forbidden_and_outsider_gets_404() -> None:
    owner, engine = make_client()
    register(owner, "delete-classroom-owner")
    classroom = create_classroom(owner)
    space_id = classroom["space"]["id"]
    knowledge_base = post_knowledge_base(owner, space_id, "班级删除测试")
    teacher = add_classroom_member(
        owner, classroom, "delete-classroom-teacher", ClassroomRole.TEACHER
    )
    student = add_classroom_member(
        owner, classroom, "delete-classroom-student", ClassroomRole.STUDENT
    )
    outsider = TestClient(owner.app)
    register(outsider, "delete-classroom-outsider")

    teacher_response = teacher.delete(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}"
    )
    student_response = student.delete(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}"
    )
    outsider_response = outsider.delete(
        f"/api/v1/knowledge-bases/{knowledge_base['id']}"
    )
    owner_response = owner.delete(f"/api/v1/knowledge-bases/{knowledge_base['id']}")

    assert teacher_response.status_code == 403
    assert teacher_response.json() == {"detail": "无权限执行此操作"}
    assert student_response.status_code == 403
    assert student_response.json() == {"detail": "无权限执行此操作"}
    assert outsider_response.status_code == 404
    assert outsider_response.json() == {"detail": "资源不存在"}
    assert owner_response.status_code == 204
    engine.dispose()


def test_running_ingestion_job_blocks_delete_without_partial_changes() -> None:
    client, engine = make_client()
    registration = register(client, "delete-running-owner")
    created = post_knowledge_base(client, registration["personal_space"]["id"], "运行中任务")
    knowledge_base_id = UUID(created["id"])
    with Session(engine) as session:
        knowledge_base = session.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        document, version, page, job = seed_document_graph(
            session,
            knowledge_base=knowledge_base,
            job_state=IngestionJobState.RUNNING,
        )
        expected_ids = (document.id, version.id, page.id, job.id)

    response = client.delete(f"/api/v1/knowledge-bases/{knowledge_base_id}")

    assert response.status_code == 409
    assert response.json() == {"detail": "知识库仍有任务正在运行，请稍后重试"}
    with Session(engine) as session:
        assert session.get(KnowledgeBase, knowledge_base_id) is not None
        assert session.get(Document, expected_ids[0]) is not None
        assert session.get(DocumentVersion, expected_ids[1]) is not None
        assert session.get(Page, expected_ids[2]) is not None
        assert session.get(IngestionJob, expected_ids[3]) is not None
        assert session.scalar(select(ObjectDeletionOutbox.id)) is None
    engine.dispose()


def test_retry_wait_job_is_cancelled_then_cascaded_during_delete() -> None:
    client, engine = make_client()
    registration = register(client, "delete-retry-owner")
    created = post_knowledge_base(client, registration["personal_space"]["id"], "等待重试任务")
    knowledge_base_id = UUID(created["id"])
    with Session(engine) as session:
        knowledge_base = session.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        _, _, _, job = seed_document_graph(
            session,
            knowledge_base=knowledge_base,
            job_state=IngestionJobState.RETRY_WAIT,
        )
        job_id = job.id

    response = client.delete(f"/api/v1/knowledge-bases/{knowledge_base_id}")

    assert response.status_code == 204
    with Session(engine) as session:
        assert session.get(IngestionJob, job_id) is None
    engine.dispose()


def test_archived_knowledge_base_is_hidden_from_list_detail_and_write_access() -> None:
    client, engine = make_client()
    registration = register(client, "archived-hidden-owner")
    created = post_knowledge_base(client, registration["personal_space"]["id"], "归档隐藏")
    knowledge_base_id = UUID(created["id"])
    user_id = UUID(registration["user"]["id"])
    with Session(engine) as session:
        knowledge_base = session.get(KnowledgeBase, knowledge_base_id)
        assert knowledge_base is not None
        knowledge_base.state = KnowledgeBaseState.ARCHIVED
        session.commit()

    listed = client.get(
        f"/api/v1/spaces/{registration['personal_space']['id']}/knowledge-bases"
    )
    detail = client.get(f"/api/v1/knowledge-bases/{knowledge_base_id}")

    assert listed.status_code == 200
    assert listed.json() == []
    assert detail.status_code == 404
    with Session(engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        try:
            get_writable_knowledge_base(session, user, knowledge_base_id)
        except Exception as error:
            assert getattr(error, "status_code", None) == 404
        else:
            raise AssertionError("archived knowledge base must not be writable")
    engine.dispose()
