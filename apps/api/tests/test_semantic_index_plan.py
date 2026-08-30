import pytest
from pydantic import ValidationError

from tutor_api.knowledge.semantic_plan import (
    SEMANTIC_INDEX_PLANNER_SYSTEM_PROMPT,
    validate_semantic_index_plan,
)


def payload(count: int = 3) -> dict:
    return {
        "schema_version": "1.0",
        "source_hash": "a" * 64,
        "chunks": [
            {"ordinal": i, "heading": f"H{i}", "start": i, "end": i + 1} for i in range(count)
        ],
        "concepts": [
            {
                "name": f"C{i}",
                "aliases": [],
                "tags": ["知识点"],
                "provenance": "source",
                "confidence": 1.0,
            }
            for i in range(count)
        ],
        "terms": [
            {"term": f"T{i}", "definition": f"D{i}", "provenance": "source", "confidence": 1.0}
            for i in range(count)
        ],
        "links": [
            {
                "source": f"C{i}",
                "target": f"C{i + 1}",
                "relation": "related",
                "provenance": "source",
                "confidence": 1.0,
            }
            for i in range(count - 1)
        ],
    }


def test_plan_accepts_many_items_without_product_count_cap():
    plan = validate_semantic_index_plan(payload(250), expected_source_hash="a" * 64)
    assert len(plan.chunks) == 250
    assert len(plan.concepts) == 250


@pytest.mark.parametrize("mutation", ["offset", "ordinal", "link", "hash"])
def test_plan_rejects_invalid_or_stale_structure(mutation: str):
    data = payload()
    if mutation == "offset":
        data["chunks"][0]["end"] = data["chunks"][0]["start"]
    elif mutation == "ordinal":
        data["chunks"][1]["ordinal"] = 0
    elif mutation == "link":
        data["links"][0]["target"] = "missing"
    with pytest.raises((ValidationError, ValueError)):
        validate_semantic_index_plan(
            data,
            expected_source_hash="b" * 64 if mutation == "hash" else "a" * 64,
        )


def test_external_inference_requires_provenance_and_confidence():
    data = payload()
    data["concepts"][0].pop("provenance")
    with pytest.raises(ValidationError):
        validate_semantic_index_plan(data)
    assert "公开 Web" in SEMANTIC_INDEX_PLANNER_SYSTEM_PROMPT
    assert "不得虚构原文" in SEMANTIC_INDEX_PLANNER_SYSTEM_PROMPT
