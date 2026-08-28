from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tutor_api.core.config import Settings
from tutor_api.core.database import Base, create_engine_from_url
from tutor_api.knowledge.models import (
    CandidateBatchState,
    Document,
    DocumentState,
    DocumentVersion,
    DocumentVersionState,
    KnowledgeCandidateBatch,
    MarkdownNote,
    MarkdownNoteState,
    MarkdownRevision,
    MarkdownRevisionState,
)
from tutor_api.main import create_app


def make_client() -> tuple[TestClient, object]:
    engine = create_engine_from_url("sqlite://", app_env="test")
    Base.metadata.create_all(engine)
    return TestClient(create_app(Settings(app_env="test"), sessionmaker(bind=engine))), engine


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


def create_knowledge_base(client: TestClient, space_id: str) -> dict:
    response = client.post(
        f"/api/v1/spaces/{space_id}/knowledge-bases",
        json={"name": "恢复测试知识库"},
    )
    assert response.status_code == 201
    return response.json()


def seed_workspace(
    engine: object,
    *,
    owner_id: UUID,
    space_id: UUID,
    knowledge_base_id: UUID,
) -> dict[str, UUID]:
    session = sessionmaker(bind=engine)()
    try:
        now = datetime.now(UTC)
        document = Document(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            owner_user_id=owner_id,
            created_by_user_id=owner_id,
            title="Faro API 教程",
            source_kind="upload",
            source_key="Faro_API_小白使用教程.docx",
        )
        archived_document = Document(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            owner_user_id=owner_id,
            created_by_user_id=owner_id,
            title="旧资料",
            source_kind="upload",
            source_key="old.txt",
            state=DocumentState.ARCHIVED,
        )
        session.add_all([document, archived_document])
        session.flush()
        old_version = DocumentVersion(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
            version_number=1,
            content_sha256="1" * 64,
            object_key=f"knowledge/{document.id}/v1.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            state=DocumentVersionState.READY,
            created_by_user_id=owner_id,
            created_at=now - timedelta(minutes=5),
        )
        latest_version = DocumentVersion(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
            version_number=2,
            content_sha256="2" * 64,
            object_key=f"knowledge/{document.id}/v2.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            state=DocumentVersionState.PARSING,
            created_by_user_id=owner_id,
            created_at=now,
        )
        archived_version = DocumentVersion(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            document_id=archived_document.id,
            version_number=1,
            content_sha256="3" * 64,
            object_key=f"knowledge/{archived_document.id}/v1.txt",
            content_type="text/plain",
            created_by_user_id=owner_id,
        )
        session.add_all([old_version, latest_version, archived_version])
        session.flush()
        confirmed = KnowledgeCandidateBatch(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
            document_version_id=latest_version.id,
            generation_number=1,
            state=CandidateBatchState.CONFIRMED,
            created_by_user_id=owner_id,
            created_at=now - timedelta(minutes=3),
        )
        needs_review = KnowledgeCandidateBatch(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
            document_version_id=latest_version.id,
            generation_number=2,
            state=CandidateBatchState.NEEDS_REVIEW,
            created_by_user_id=owner_id,
            created_at=now - timedelta(minutes=2),
        )
        processing = KnowledgeCandidateBatch(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
            document_version_id=latest_version.id,
            generation_number=3,
            state=CandidateBatchState.PROCESSING,
            created_by_user_id=owner_id,
            created_at=now - timedelta(minutes=1),
        )
        session.add_all([confirmed, needs_review, processing])
        session.flush()
        parent = MarkdownNote(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            source_document_id=document.id,
            title="Faro 配置",
            normalized_title="faro 配置",
            state=MarkdownNoteState.PUBLISHED,
            created_by_user_id=owner_id,
        )
        child = MarkdownNote(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            source_document_id=document.id,
            title="配置文件位置",
            normalized_title="配置文件位置",
            state=MarkdownNoteState.PUBLISHED,
            created_by_user_id=owner_id,
        )
        draft = MarkdownNote(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            source_document_id=document.id,
            title="未发布",
            normalized_title="未发布",
            state=MarkdownNoteState.DRAFT,
            created_by_user_id=owner_id,
        )
        session.add_all([parent, child, draft])
        session.flush()
        parent_revision = MarkdownRevision(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            note_id=parent.id,
            source_document_id=document.id,
            source_document_version_id=latest_version.id,
            revision_number=1,
            state=MarkdownRevisionState.PUBLISHED,
            markdown="# Faro 配置\n\n- contains → [[配置文件位置]]",
            content_sha256="4" * 64,
            source_markers=["Faro_API_小白使用教程.docx#block=10"],
            created_by_user_id=owner_id,
        )
        child_revision = MarkdownRevision(
            space_id=space_id,
            knowledge_base_id=knowledge_base_id,
            note_id=child.id,
            source_document_id=document.id,
            source_document_version_id=latest_version.id,
            revision_number=1,
            state=MarkdownRevisionState.PUBLISHED,
            markdown="# 配置文件位置\n\n正文\n\n- 所属结构 → [[Faro 配置]]",
            content_sha256="5" * 64,
            source_markers=["Faro_API_小白使用教程.docx#block=20"],
            created_by_user_id=owner_id,
        )
        session.add_all([parent_revision, child_revision])
        session.commit()
        return {
            "document": document.id,
            "latest_version": latest_version.id,
            "processing": processing.id,
            "parent": parent.id,
            "child": child.id,
            "draft": draft.id,
        }
    finally:
        session.close()


def test_workspace_restores_latest_documents_active_batch_and_published_notes() -> None:
    client, engine = make_client()
    registration = register(client, "workspaceowner")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    ids = seed_workspace(
        engine,
        owner_id=UUID(registration["user"]["id"]),
        space_id=UUID(registration["personal_space"]["id"]),
        knowledge_base_id=UUID(knowledge_base["id"]),
    )

    response = client.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["knowledge_base_id"] == knowledge_base["id"]
    assert [
        (item["document_id"], item["document_version_id"]) for item in payload["documents"]
    ] == [(str(ids["document"]), str(ids["latest_version"]))]
    assert payload["documents"][0]["source_name"] == "Faro_API_小白使用教程.docx"
    assert payload["documents"][0]["processing_state"] == "processing"
    assert payload["candidate_batch"]["id"] == str(ids["processing"])
    assert payload["candidate_batch"]["state"] == "processing"
    assert [(note["id"], note["title"], note["parent_id"]) for note in payload["notes"]] == [
        (str(ids["parent"]), "Faro 配置", None),
        (str(ids["child"]), "配置文件位置", str(ids["parent"])),
    ]

    outsider = TestClient(client.app)
    register(outsider, "workspaceoutsider")
    assert (
        outsider.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}/workspace").status_code == 404
    )


def test_note_detail_is_lazy_published_and_tenant_scoped() -> None:
    client, engine = make_client()
    registration = register(client, "noteowner")
    knowledge_base = create_knowledge_base(client, registration["personal_space"]["id"])
    ids = seed_workspace(
        engine,
        owner_id=UUID(registration["user"]["id"]),
        space_id=UUID(registration["personal_space"]["id"]),
        knowledge_base_id=UUID(knowledge_base["id"]),
    )

    response = client.get(f"/api/v1/knowledge-bases/{knowledge_base['id']}/notes/{ids['child']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(ids["child"])
    assert payload["title"] == "配置文件位置"
    assert payload["kind"] == "note"
    assert payload["markdown"].startswith("# 配置文件位置")
    assert payload["source_markers"] == ["Faro_API_小白使用教程.docx#block=20"]
    assert payload["source_document_id"] == str(ids["document"])
    assert payload["source_name"] == "Faro_API_小白使用教程.docx"
    assert payload["parent"] == {"id": str(ids["parent"]), "title": "Faro 配置"}
    assert payload["children"] == []

    assert (
        client.get(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/notes/{ids['draft']}"
        ).status_code
        == 404
    )
    outsider = TestClient(client.app)
    register(outsider, "noteoutsider")
    assert (
        outsider.get(
            f"/api/v1/knowledge-bases/{knowledge_base['id']}/notes/{ids['child']}"
        ).status_code
        == 404
    )
