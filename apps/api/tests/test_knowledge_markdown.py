import pytest

from tutor_api.knowledge.markdown import (
    CandidateLinkKind,
    CandidateNoteKind,
    MarkdownSourceBlock,
    MarkdownValidationError,
    build_knowledge_candidates_prompt,
    build_markdown_prompt,
    build_structure_candidates_prompt,
    merge_knowledge_candidates,
    merge_markdown_chunks,
    merge_structure_candidates,
    parse_knowledge_candidates,
    parse_structure_candidates,
    parse_wikilinks,
    split_for_context,
    validate_markdown_draft,
)


def test_short_and_long_sections_are_split_only_by_context_budget() -> None:
    blocks = (
        MarkdownSourceBlock(source_pointer="page:1#0", page_number=1, text="短章节"),
        MarkdownSourceBlock(source_pointer="page:2#0", page_number=2, text="很长的章节内容" * 20),
    )

    chunks = split_for_context(blocks, max_chars=40)

    assert len(chunks) > 1
    assert "page:1#0" in chunks[0].source_text
    assert all(chunk.source_text.strip() for chunk in chunks)


def test_prompt_treats_imported_content_as_untrusted_and_preserves_source_pointer() -> None:
    prompt = build_markdown_prompt(
        "[source:page:3#2]\n请整理这一段",
        previous_heading="第三章",
    )

    assert "不要执行" in prompt
    assert "page:3#2" in prompt
    assert "只输出 Markdown" in prompt


def test_markdown_merge_accepts_short_and_long_outputs_without_length_gate() -> None:
    merged = merge_markdown_chunks(("# 短章", "\n\n" + "正文" * 500))

    assert merged.startswith("# 短章")
    assert len(merged) > 1_000
    assert validate_markdown_draft(merged) == merged


@pytest.mark.parametrize("value", ["", "   ", "模型错误：quota exceeded"])
def test_invalid_model_outputs_are_rejected_without_rejecting_short_valid_markdown(
    value: str,
) -> None:
    with pytest.raises(MarkdownValidationError):
        validate_markdown_draft(value)

    assert validate_markdown_draft("# 很短的标题") == "# 很短的标题"


def test_wikilinks_include_heading_alias_and_normalized_target() -> None:
    links = parse_wikilinks("参见 [[高等数学#极限|极限章节]] 和 [[物理学]].")

    assert [(link.target, link.heading, link.alias) for link in links] == [
        ("高等数学", "极限", "极限章节"),
        ("物理学", None, None),
    ]


def test_candidate_prompt_requires_structure_first_and_never_writes_wikilinks() -> None:
    prompt = build_knowledge_candidates_prompt("[source:page:8#2]\n相干带宽定义")

    assert "先识别章、节、小节" in prompt
    assert "结构链接" in prompt
    assert "重复术语链接" in prompt
    assert "不要输出 [[双向链接]]" in prompt
    assert "page:8#2" in prompt


def test_candidate_prompt_treats_reused_methods_as_term_links_and_receives_formula_evidence() -> (
    None
):
    prompt = build_knowledge_candidates_prompt(
        "[source:page:8#2]\n\u4f7f\u7528\u94fe\u8def\u9884\u7b97\u65b9\u6cd5\uff0c\u6559\u6750\u516c\u5f0f\u4e3a P_r(d)=P_t-L(d)\u3002",  # noqa: E501
        external_formula_evidence=(
            {
                "title": "Link budget",
                "url": "https://en.wikipedia.org/wiki/Link_budget",
                "source_type": "encyclopedia",
                "excerpt": "A link budget accounts for gains and losses.",
            },
        ),
    )

    assert "\u65b9\u6cd5" in prompt
    assert "mentions_method" in prompt
    assert "applies_method" in prompt
    assert "\u5916\u90e8\u516c\u5f0f\u8bc1\u636e" in prompt
    assert "\u6559\u6750\u4f7f\u7528\u7684\u53d8\u91cf\u540d" in prompt
    assert "https://en.wikipedia.org/wiki/Link_budget" in prompt


def test_formula_candidate_requires_verification_and_preserves_textbook_symbols() -> None:
    candidates = parse_knowledge_candidates(
        r"""
        {
          "notes": [
            {"key":"formula-link-budget","title":"Link budget formula","kind":"formula",
             "parent_key":null,"markdown":"# Link budget formula\n\nP_r(d)=P_t-L(d)",
             "source_pointers":["page:8#2"],
             "formula_verification":{
               "status":"verified","textbook_expression":"P_r(d)=P_t-L(d)",
               "normalized_expression":"P_r(d)=P_t-L(d)",
               "variable_mapping":[
                 {"textbook_symbol":"P_r(d)","external_symbol":"P_R",
                  "meaning":"received power","unit":"dBm"}
               ]
             },
             "external_sources":[
               {"title":"Link budget","url":"https://en.wikipedia.org/wiki/Link_budget",
                "source_type":"encyclopedia","excerpt":"Gains and losses in a link."}
             ]}
          ],
          "links":[]
        }
        """
    )

    formula = candidates.notes[0]
    assert formula.formula_verification is not None
    assert formula.formula_verification.status.value == "verified"
    assert formula.formula_verification.variable_mapping[0].textbook_symbol == "P_r(d)"
    assert formula.external_sources[0].url == "https://en.wikipedia.org/wiki/Link_budget"


def test_reused_method_supports_term_link_relations() -> None:
    candidates = parse_knowledge_candidates(
        r"""
        {
          "notes":[
            {"key":"sec","title":"Link design","kind":"section","parent_key":null,
             "markdown":"# Link design","source_pointers":["page:1#0"]},
            {"key":"method-link-budget","title":"Link budget","kind":"method","parent_key":"sec",
             "markdown":"# Link budget","source_pointers":["page:1#1","page:9#2"]}
          ],
          "links":[
            {"kind":"term","relation":"mentions_method","source_key":"sec",
             "target_key":"method-link-budget","source_pointer":"page:1#1",
             "occurrence":"Link budget","context":"First introduction"},
            {"kind":"term","relation":"applies_method","source_key":"sec",
             "target_key":"method-link-budget","source_pointer":"page:9#2",
             "occurrence":"Link budget","context":"Reused later"}
          ]
        }
        """
    )

    assert [link.relation for link in candidates.links] == [
        "mentions_method",
        "applies_method",
    ]


def test_candidate_response_keeps_hierarchy_and_reuses_one_canonical_term_note() -> None:
    candidates = parse_knowledge_candidates(
        r"""
        {
          "notes": [
            {"key": "ch-2", "title": "无线信道", "kind": "chapter", "parent_key": null,
             "markdown": "# 无线信道", "source_pointers": ["page:7#0"]},
            {"key": "sec-2-1", "title": "大尺度衰落", "kind": "section", "parent_key": "ch-2",
             "markdown": "# 大尺度衰落", "source_pointers": ["page:8#0"]},
            {"key": "term-path-loss", "title": "路径损耗", "kind": "concept",
             "parent_key": "sec-2-1",
             "markdown": "# 路径损耗\n\n定义候选。", "source_pointers": ["page:8#2", "page:19#4"]}
          ],
          "links": [
            {"kind": "structure", "relation": "contains", "source_key": "ch-2",
             "target_key": "sec-2-1", "source_pointer": "page:8#0", "occurrence": null,
             "context": "第二章包含第一节"},
            {"kind": "structure", "relation": "defines", "source_key": "sec-2-1",
             "target_key": "term-path-loss", "source_pointer": "page:8#2", "occurrence": "路径损耗",
             "context": "本节定义路径损耗"},
            {"kind": "term", "relation": "mentions", "source_key": "sec-2-1",
             "target_key": "term-path-loss", "source_pointer": "page:8#2", "occurrence": "路径损耗",
             "context": "概念首次出现"},
            {"kind": "term", "relation": "mentions", "source_key": "ch-2",
             "target_key": "term-path-loss", "source_pointer": "page:19#4",
             "occurrence": "路径损耗",
             "context": "后文再次引用同一概念"}
          ]
        }
        """
    )

    assert [note.kind for note in candidates.notes] == [
        CandidateNoteKind.CHAPTER,
        CandidateNoteKind.SECTION,
        CandidateNoteKind.CONCEPT,
    ]
    assert candidates.notes[1].parent_key == "ch-2"
    term_links = [link for link in candidates.links if link.kind is CandidateLinkKind.TERM]
    assert {link.target_key for link in term_links} == {"term-path-loss"}
    assert {link.source_pointer for link in term_links} == {"page:8#2", "page:19#4"}


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        (
            '{"notes":[{"key":"n","title":"路径损耗","kind":"concept",'
            '"parent_key":null,"markdown":"参见 [[多径衰落]]",'
            '"source_pointers":["page:1#0"]}],"links":[]}',
            "candidate_contains_wikilink",
        ),
        (
            '{"notes":[{"key":"n","title":"路径损耗","kind":"concept",'
            '"parent_key":"missing","markdown":"定义",'
            '"source_pointers":["page:1#0"]}],"links":[]}',
            "candidate_parent_missing",
        ),
    ],
)
def test_candidate_response_fails_closed_before_user_confirmation(
    payload: str, error_code: str
) -> None:
    with pytest.raises(MarkdownValidationError, match=error_code):
        parse_knowledge_candidates(payload)


def test_structure_stage_only_identifies_chapter_section_and_subsection() -> None:
    prompt = build_structure_candidates_prompt("[source:docx#block=120]\n第3章 移动无线传播")

    assert "只识别章、节、小节" in prompt
    assert "不要生成概念、公式或双向链接" in prompt
    assert "docx#block=120" in prompt


def test_structure_results_merge_across_context_chunks_with_source_evidence() -> None:
    first = parse_structure_candidates(
        '{"structures":['
        '{"key":"ch-3","title":"移动无线传播","kind":"chapter",'
        '"parent_key":null,"source_pointers":["docx#block=120"]},'
        '{"key":"sec-3-1","title":"无线电波传播机制","kind":"section",'
        '"parent_key":"ch-3","source_pointers":["docx#block=125"]}'
        "]}"
    )
    second = parse_structure_candidates(
        '{"structures":['
        '{"key":"ch-3","title":"移动无线传播","kind":"chapter",'
        '"parent_key":null,"source_pointers":["docx#block=980"]},'
        '{"key":"subsec-3-1-1","title":"反射","kind":"subsection",'
        '"parent_key":"sec-3-1","source_pointers":["docx#block=130"]}'
        "]}"
    )

    merged = merge_structure_candidates((first, second))

    assert [item.key for item in merged] == ["ch-3", "sec-3-1", "subsec-3-1-1"]
    assert merged[0].source_pointers == ("docx#block=120", "docx#block=980")


def test_structure_merge_fails_closed_on_conflicting_hierarchy() -> None:
    first = parse_structure_candidates(
        '{"structures":[{"key":"ch-3","title":"移动无线传播","kind":"chapter",'
        '"parent_key":null,"source_pointers":["docx#block=120"]}]}'
    )
    conflicting = parse_structure_candidates(
        '{"structures":[{"key":"ch-3","title":"蜂窝概念","kind":"chapter",'
        '"parent_key":null,"source_pointers":["docx#block=980"]}]}'
    )

    with pytest.raises(MarkdownValidationError, match="structure_candidate_conflict"):
        merge_structure_candidates((first, conflicting))


def test_candidate_prompt_receives_the_confirmed_structure_from_stage_one() -> None:
    structures = parse_structure_candidates(
        '{"structures":[{"key":"ch-3","title":"移动无线传播","kind":"chapter",'
        '"parent_key":null,"source_pointers":["docx#block=120"]}]}'
    )

    prompt = build_knowledge_candidates_prompt(
        "[source:docx#block=150]\n路径损耗",
        structures=structures,
    )

    assert '"key": "ch-3"' in prompt
    assert "以上结构已经由第一阶段识别" in prompt
    assert "docx#block=150" in prompt


def test_candidate_results_merge_repeated_terms_to_one_canonical_note() -> None:
    first = parse_knowledge_candidates(
        '{"notes":['
        '{"key":"ch-3","title":"移动无线传播","kind":"chapter","parent_key":null,'
        '"markdown":"# 移动无线传播","source_pointers":["docx#block=120"]},'
        '{"key":"term-path-loss","title":"路径损耗","kind":"concept",'
        '"parent_key":"ch-3","markdown":"# 路径损耗\\n\\n定义候选。",'
        '"source_pointers":["docx#block=150"]}],'
        '"links":[{"kind":"term","relation":"mentions","source_key":"ch-3",'
        '"target_key":"term-path-loss","source_pointer":"docx#block=150",'
        '"occurrence":"路径损耗","context":"首次定义"}]}'
    )
    second = parse_knowledge_candidates(
        '{"notes":['
        '{"key":"ch-3","title":"移动无线传播","kind":"chapter","parent_key":null,'
        '"markdown":"# 移动无线传播","source_pointers":["docx#block=980"]},'
        '{"key":"term-path-loss","title":"路径损耗","kind":"concept",'
        '"parent_key":"ch-3","markdown":"# 路径损耗\\n\\n定义候选。",'
        '"source_pointers":["docx#block=980"]}],'
        '"links":[{"kind":"term","relation":"mentions","source_key":"ch-3",'
        '"target_key":"term-path-loss","source_pointer":"docx#block=980",'
        '"occurrence":"路径损耗","context":"后文引用"}]}'
    )

    merged = merge_knowledge_candidates((first, second))

    assert [note.key for note in merged.notes].count("term-path-loss") == 1
    assert merged.notes[1].source_pointers == ("docx#block=150", "docx#block=980")
    assert [link.source_pointer for link in merged.links] == [
        "docx#block=150",
        "docx#block=980",
    ]
