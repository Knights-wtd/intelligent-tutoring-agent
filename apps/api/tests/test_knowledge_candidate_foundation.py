from tutor_api.core.database import Base
from tutor_api.knowledge.models import (
    CandidateBatchState,
    CandidateReviewState,
    KnowledgeCandidateBatch,
    KnowledgeCandidateLink,
    KnowledgeCandidateNote,
)


def test_candidate_graph_models_are_exposed_and_registered_with_metadata() -> None:
    assert CandidateBatchState.NEEDS_REVIEW.value == "needs_review"
    assert CandidateReviewState.PENDING.value == "pending"
    assert KnowledgeCandidateBatch.__tablename__ == "knowledge_candidate_batches"
    assert KnowledgeCandidateNote.__tablename__ == "knowledge_candidate_notes"
    assert KnowledgeCandidateLink.__tablename__ == "knowledge_candidate_links"
    assert {
        "knowledge_candidate_batches",
        "knowledge_candidate_notes",
        "knowledge_candidate_links",
    } <= set(Base.metadata.tables)
