from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).with_name("resume_wireless_knowledge_16k.py")
SPEC = importlib.util.spec_from_file_location("resume_wireless_knowledge_16k", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_normalize_candidate_json_uses_formula_symbol_spelling_from_expression() -> None:
    payload = {
        "notes": [
            {
                "key": "formula-test",
                "title": "测试公式",
                "kind": "formula",
                "parent_key": None,
                "markdown": "测试",
                "source_pointers": ["source#block=1"],
                "formula_verification": {
                    "status": "insufficient_evidence",
                    "textbook_expression": "A_u = λH",
                    "normalized_expression": "A_u = \\lambda H",
                    "variable_mapping": [
                        {
                            "textbook_symbol": "Au",
                            "external_symbol": None,
                            "meaning": "话务强度",
                            "unit": "Erlang",
                        },
                        {
                            "textbook_symbol": "λ",
                            "external_symbol": None,
                            "meaning": "平均呼叫到达率",
                            "unit": "1/s",
                        },
                    ],
                },
                "external_sources": [],
            },
            {
                "key": "formula-spacing",
                "title": "间隔测试公式",
                "kind": "formula",
                "parent_key": None,
                "markdown": "测试",
                "source_pointers": ["source#block=2"],
                "formula_verification": {
                    "status": "insufficient_evidence",
                    "textbook_expression": "Pr[d>t]",
                    "normalized_expression": "Pr[d > t]",
                    "variable_mapping": [
                        {
                            "textbook_symbol": "Pr[d>t]",
                            "external_symbol": None,
                            "meaning": "概率",
                            "unit": None,
                        }
                    ],
                },
                "external_sources": [],
            },
        ],
        "links": [],
    }

    normalized = json.loads(MODULE.normalize_candidate_json(json.dumps(payload)))

    assert normalized["notes"][0]["formula_verification"]["variable_mapping"][0]["textbook_symbol"] == "A_u"
    assert normalized["notes"][0]["formula_verification"]["variable_mapping"][1]["textbook_symbol"] == "\\lambda"
    assert normalized["notes"][1]["formula_verification"]["variable_mapping"][0]["textbook_symbol"] == "Pr[d > t]"

def test_validate_or_repair_sends_initial_invalid_json_to_repair(tmp_path: Path) -> None:
    valid = json.dumps(
        {
            "notes": [
                {
                    "key": "concept-test",
                    "title": "测试概念",
                    "kind": "concept",
                    "parent_key": None,
                    "markdown": "测试正文",
                    "source_pointers": ["source#block=1"],
                }
            ],
            "links": [],
        },
        ensure_ascii=False,
    )

    class Completion:
        text = valid
        request_id = "repair-test"

        class Usage:
            total_tokens = 1

        usage = Usage()

    class Adapter:
        def complete_markdown(self, _prompt: str) -> Completion:
            return Completion()

    result = MODULE.validate_or_repair(
        Adapter(),
        '{"notes":"bad\\q"}',
        label="invalid-json-test",
        repaired_raw_path=tmp_path / "repaired.txt",
    )

    assert json.loads(result)["notes"][0]["key"] == "concept-test"

def test_normalize_candidate_json_uses_exact_markdown_formula_when_evidence_fields_missing() -> None:
    payload = {
        "notes": [
            {
                "key": "formula-path-loss",
                "title": "路径损耗公式",
                "kind": "formula",
                "parent_key": None,
                "markdown": "### 路径损耗公式\n\n$$P_r(d) = P_0 - 10n \\log_{10}(d_i/d_0)$$",
                "source_pointers": ["source#block=737"],
            }
        ],
        "links": [],
    }

    normalized = json.loads(MODULE.normalize_candidate_json(json.dumps(payload)))
    note = normalized["notes"][0]

    assert note["formula_verification"] == {
        "status": "insufficient_evidence",
        "textbook_expression": "P_r(d) = P_0 - 10n \\log_{10}(d_i/d_0)",
        "normalized_expression": "P_r(d) = P_0 - 10n \\log_{10}(d_i/d_0)",
        "variable_mapping": [],
    }
    assert note["external_sources"] == []

def test_normalize_candidate_json_removes_unexpected_formula_verification_fields() -> None:
    payload = {
        "notes": [
            {
                "key": "formula-extra",
                "title": "测试公式",
                "kind": "formula",
                "parent_key": None,
                "markdown": "$$A = B$$",
                "source_pointers": ["source#block=1"],
                "formula_verification": {
                    "status": "insufficient_evidence",
                    "textbook_expression": "A = B",
                    "normalized_expression": "A = B",
                    "variable_mapping": [],
                    "evidence": "",
                    "external_sources": [],
                },
            }
        ],
        "links": [],
    }

    normalized = json.loads(MODULE.normalize_candidate_json(json.dumps(payload)))
    note = normalized["notes"][0]

    assert set(note["formula_verification"]) == {
        "status",
        "textbook_expression",
        "normalized_expression",
        "variable_mapping",
    }
    assert note["external_sources"] == []

def test_normalize_candidate_json_downgrades_unknown_term_relation_to_mentions() -> None:
    payload = {
        "notes": [
            {"key": "source", "title": "来源", "kind": "concept", "parent_key": None, "markdown": "来源", "source_pointers": ["source#1"]},
            {"key": "target", "title": "目标", "kind": "method", "parent_key": None, "markdown": "目标", "source_pointers": ["source#2"]},
        ],
        "links": [
            {"kind": "term", "relation": "illustrates", "source_key": "source", "target_key": "target", "source_pointer": "source#1", "occurrence": "目标", "context": "示例"}
        ],
    }

    normalized = json.loads(MODULE.normalize_candidate_json(json.dumps(payload)))

    assert normalized["links"][0]["relation"] == "mentions"

def test_normalize_candidate_json_removes_formula_mapping_absent_from_expression() -> None:
    payload = {
        "notes": [
            {
                "key": "formula-unmatched",
                "title": "测试公式",
                "kind": "formula",
                "parent_key": None,
                "markdown": "$$L_{50} = L_F$$",
                "source_pointers": ["source#1"],
                "formula_verification": {
                    "status": "insufficient_evidence",
                    "textbook_expression": "L_{50} = L_F",
                    "normalized_expression": "L_{50} = L_F",
                    "variable_mapping": [
                        {"textbook_symbol": "L50", "external_symbol": None, "meaning": "简写不匹配", "unit": "dB"},
                        {"textbook_symbol": "L_F", "external_symbol": None, "meaning": "有效映射", "unit": "dB"},
                    ],
                },
                "external_sources": [],
            }
        ],
        "links": [],
    }

    normalized = json.loads(MODULE.normalize_candidate_json(json.dumps(payload)))
    mappings = normalized["notes"][0]["formula_verification"]["variable_mapping"]

    assert [mapping["textbook_symbol"] for mapping in mappings] == ["L_F"]

def test_normalize_candidate_json_adds_null_occurrence_to_structure_link() -> None:
    payload = {
        "notes": [
            {"key": "chapter", "title": "章", "kind": "chapter", "parent_key": None, "markdown": "章", "source_pointers": ["source#1"]},
            {"key": "section", "title": "节", "kind": "section", "parent_key": "chapter", "markdown": "节", "source_pointers": ["source#2"]},
        ],
        "links": [
            {"kind": "structure", "relation": "contains", "source_key": "chapter", "target_key": "section", "source_pointer": "source#1", "context": "结构"}
        ],
    }

    normalized = json.loads(MODULE.normalize_candidate_json(json.dumps(payload)))

    assert normalized["links"][0]["occurrence"] is None

def test_normalize_candidate_json_replaces_numeric_term_occurrence_with_target_title() -> None:
    payload = {
        "notes": [
            {"key": "source", "title": "来源", "kind": "concept", "parent_key": None, "markdown": "来源", "source_pointers": ["source#1"]},
            {"key": "target", "title": "目标术语", "kind": "concept", "parent_key": None, "markdown": "目标", "source_pointers": ["source#2"]},
        ],
        "links": [
            {"kind": "term", "relation": "mentions", "source_key": "source", "target_key": "target", "source_pointer": "source#1", "occurrence": 1, "context": "上下文"}
        ],
    }

    normalized = json.loads(MODULE.normalize_candidate_json(json.dumps(payload)))

    assert normalized["links"][0]["occurrence"] == "目标术语"

def test_normalize_candidate_json_replaces_numeric_structure_occurrence_with_null() -> None:
    payload = {
        "notes": [
            {"key": "chapter", "title": "章", "kind": "chapter", "parent_key": None, "markdown": "章", "source_pointers": ["source#1"]},
            {"key": "section", "title": "节", "kind": "section", "parent_key": "chapter", "markdown": "节", "source_pointers": ["source#2"]},
        ],
        "links": [{"kind": "structure", "relation": "contains", "source_key": "chapter", "target_key": "section", "source_pointer": "source#1", "occurrence": 1, "context": "结构"}],
    }
    normalized = json.loads(MODULE.normalize_candidate_json(json.dumps(payload)))
    assert normalized["links"][0]["occurrence"] is None

def test_candidate_payload_text_strips_legacy_metadata() -> None:
    wrapped = {"chapter": 1, "model": "gemini", "notes": [], "links": []}
    payload = json.loads(MODULE.candidate_payload_text(json.dumps(wrapped)))
    assert payload == {"notes": [], "links": []}

