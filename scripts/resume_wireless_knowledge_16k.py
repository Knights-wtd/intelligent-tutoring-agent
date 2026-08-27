from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(r"E:\项目\知识库课本\.worktrees\platform-foundation")
SOURCE = Path(
    r"C:\Users\asus\Downloads\无线通信原理与应用（第二版） Wireless communications principles and practice "
    r"((Theodore S. Rappaport) , [美] 西奥多 S 拉帕波特 etc.) (z-library.sk, 1lib.sk, z-lib.sk).docx"
)
OUT = ROOT / "artifacts" / "wireless-knowledge-gemini-3.6"
MODEL = "gemini-3.6-flash-tiered"
MAX_CHUNK_CHARS = 16_000

sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from tutor_api.knowledge.candidates import (
    CandidateValidationError,
    StructureCandidate,
    build_knowledge_candidates_prompt,
    build_structure_candidates_prompt,
    parse_knowledge_candidates,
    parse_structure_candidates,
)
from tutor_api.knowledge.parsers import parse_docx
from tutor_api.llm.faro import FaroOpenAICompatibleAdapter
from tutor_api.llm.ports import LlmProviderError

CHAPTER_RE = re.compile(r"^第\s*(\d{1,2})\s*章\s*(.+?)\s*$")
SECTION_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,3})\s+(.+?)\s*$")
STOP_RE = re.compile(r"^(习题|参考文献)\s*$")


def load_api_key() -> str:
    env_path = ROOT / ".env"
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "FARO_API_KEY":
            return value.strip().strip('"').strip("'")
    raise RuntimeError("FARO_API_KEY_missing")


def call_model(adapter: FaroOpenAICompatibleAdapter, prompt: str, label: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            completion = adapter.complete_markdown(prompt)
            print(
                f"OK {label} attempt={attempt} tokens={completion.usage.total_tokens} "
                f"request_id={completion.request_id or '-'}",
                flush=True,
            )
            return completion.text
        except LlmProviderError as error:
            last_error = error
            print(f"RETRY {label} attempt={attempt} error={error}", flush=True)
            if attempt < 3:
                time.sleep(4 * attempt)
    raise RuntimeError(f"three_strikes:{label}:{last_error}")


def clean_json_text(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


_ALLOWED_TERM_RELATIONS = {
    "mentions",
    "mentions_method",
    "applies_method",
    "compares_method",
    "derives_method",
    "method_example",
    "formula_definition",
    "formula_derivation",
    "formula_condition",
    "formula_example",
}


_GREEK_TO_LATEX = {
    "α": "\\alpha",
    "β": "\\beta",
    "γ": "\\gamma",
    "δ": "\\delta",
    "λ": "\\lambda",
    "μ": "\\mu",
    "π": "\\pi",
    "ρ": "\\rho",
    "σ": "\\sigma",
    "θ": "\\theta",
}


def _formula_symbol_spelling(expression: str, symbol: str) -> str:
    if symbol in expression:
        return symbol

    greek = _GREEK_TO_LATEX.get(symbol)
    if greek and greek in expression:
        return greek

    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]+", symbol):
        subscript = f"{symbol[0]}_{symbol[1:]}"
        if subscript in expression:
            return subscript

    compact_symbol = "".join(character for character in symbol if not character.isspace())
    positions = [index for index, character in enumerate(expression) if not character.isspace()]
    compact_expression = "".join(expression[index] for index in positions)
    compact_start = compact_expression.find(compact_symbol)
    if compact_symbol and compact_start >= 0:
        original_start = positions[compact_start]
        original_end = positions[compact_start + len(compact_symbol) - 1] + 1
        return expression[original_start:original_end]
    return symbol


def normalize_candidate_json(value: str) -> str:
    payload = json.loads(clean_json_text(value))
    notes = payload.get("notes") if isinstance(payload, dict) else None
    links = payload.get("links") if isinstance(payload, dict) else None
    if not isinstance(notes, list) or not isinstance(links, list):
        return json.dumps(payload, ensure_ascii=False)
    for note in notes:
        if not isinstance(note, dict) or note.get("kind") != "formula":
            continue
        verification = note.get("formula_verification")
        if not isinstance(verification, dict):
            markdown = note.get("markdown")
            match = re.search(r"\$\$(.+?)\$\$", markdown, re.DOTALL) if isinstance(markdown, str) else None
            if match is None:
                continue
            expression_from_markdown = match.group(1).strip()
            verification = {
                "status": "insufficient_evidence",
                "textbook_expression": expression_from_markdown,
                "normalized_expression": expression_from_markdown,
                "variable_mapping": [],
            }
            note["formula_verification"] = verification
        note.setdefault("external_sources", [])
        required_verification_fields = {
            "status",
            "textbook_expression",
            "normalized_expression",
            "variable_mapping",
        }
        verification = {
            key: value
            for key, value in verification.items()
            if key in required_verification_fields
        }
        note["formula_verification"] = verification
        expression = verification.get("normalized_expression")
        mappings = verification.get("variable_mapping")
        if not isinstance(expression, str) or not isinstance(mappings, list):
            continue
        normalized_mappings = []
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue
            symbol = mapping.get("textbook_symbol")
            if not isinstance(symbol, str) or not symbol:
                continue
            normalized_symbol = _formula_symbol_spelling(expression, symbol)
            if normalized_symbol not in expression:
                continue
            mapping["textbook_symbol"] = normalized_symbol
            normalized_mappings.append(mapping)
        verification["variable_mapping"] = normalized_mappings
    titles = {
        item.get("key"): item.get("title")
        for item in notes
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    parents = {
        item.get("key"): item.get("parent_key")
        for item in notes
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }
    for link in links:
        if not isinstance(link, dict):
            continue
        link.setdefault("occurrence", None)
        if link.get("relation") == "child":
            link["relation"] = "contains"
        if (
            link.get("kind") == "structure"
            and link.get("relation") == "contains"
            and parents.get(link.get("target_key")) != link.get("source_key")
        ):
            link["relation"] = "references"
        if (
            link.get("kind") == "term"
            and link.get("relation") not in _ALLOWED_TERM_RELATIONS
        ):
            link["relation"] = "mentions"
        if link.get("kind") == "term" and not isinstance(link.get("occurrence"), str):
            link["occurrence"] = titles.get(link.get("target_key")) or None
        if link.get("kind") == "term" and not link.get("occurrence"):
            link["occurrence"] = titles.get(link.get("target_key")) or None
        elif link.get("kind") == "structure" and (
            not isinstance(link.get("occurrence"), str) or link.get("occurrence") == ""
        ):
            link["occurrence"] = None
    return json.dumps(payload, ensure_ascii=False, indent=2)


def repair_prompt(candidate_json: str, validation_error: Exception) -> str:
    return (
        "修复下面的候选知识 JSON，使其通过既定格式校验。只输出修复后的 JSON 对象，不要代码围栏。\n"
        "不得新增原文没有的知识、目录、公式或外部来源。保留所有可用 source 指针。\n"
        "顶层只能有 notes 和 links；每个 parent_key 及链接两端必须指向本 JSON 内存在的 note。\n"
        "structure 关系只能是 contains、references、defines、has_property、uses_formula、"
        "applies_method、illustrates。term 链接必须有非空 occurrence。\n"
        "若公式没有外部证据，status 使用 insufficient_evidence，external_sources 使用空数组，"
        "不得声称 verified。\n"
        f"校验错误：{validation_error}\n\n待修复 JSON：\n{candidate_json}"
    )


def validate_or_repair(
    adapter: FaroOpenAICompatibleAdapter,
    raw: str,
    *,
    label: str,
    repaired_raw_path: Path,
) -> str:
    candidate = clean_json_text(raw)
    for repair_round in range(3):
        try:
            candidate = normalize_candidate_json(candidate)
            parse_knowledge_candidates(candidate)
            return candidate
        except (CandidateValidationError, json.JSONDecodeError) as error:
            if repair_round >= 2:
                raise RuntimeError(f"candidate_validation_failed:{label}:{error}") from error
            repaired = call_model(
                adapter,
                repair_prompt(candidate, error),
                f"{label}-repair-{repair_round + 1}",
            )
            repaired_raw_path.with_name(
                repaired_raw_path.stem + f"-{repair_round + 1}" + repaired_raw_path.suffix
            ).write_text(repaired, encoding="utf-8")
            candidate = clean_json_text(repaired)
    raise AssertionError("unreachable")


def structure_to_json(items: tuple[StructureCandidate, ...]) -> str:
    return json.dumps(
        {
            "structures": [
                {
                    "key": item.key,
                    "title": item.title,
                    "kind": item.kind.value,
                    "parent_key": item.parent_key,
                    "source_pointers": list(item.source_pointers),
                }
                for item in items
            ]
        },
        ensure_ascii=False,
        indent=2,
    )


def chapter_ranges(blocks: tuple) -> dict[int, tuple[int, int]]:
    starts: dict[int, int] = {}
    expected = 1
    for index, block in enumerate(blocks):
        text = block.text.strip()
        match = CHAPTER_RE.match(text)
        if not match or int(match.group(1)) != expected or len(text) > 100:
            continue
        starts[expected] = index
        expected += 1
        if expected == 12:
            break
    if set(starts) != set(range(1, 12)):
        raise RuntimeError(f"chapter_detection_failed:{sorted(starts)}")
    ranges: dict[int, tuple[int, int]] = {}
    for chapter in range(1, 12):
        start = starts[chapter]
        end = starts.get(chapter + 1, len(blocks))
        ranges[chapter] = (start, end)
    return ranges


def structure_source(chapter_blocks: tuple) -> str:
    selected: list[str] = []
    stopped = False
    for index, block in enumerate(chapter_blocks):
        text = block.text.strip()
        if not text:
            continue
        if STOP_RE.match(text):
            stopped = True
        if stopped:
            continue
        if index == 0 or CHAPTER_RE.match(text) or SECTION_RE.match(text):
            selected.append(f"[{block.source_pointer}] {text}")
    return "\n".join(selected)


def get_structures(
    adapter: FaroOpenAICompatibleAdapter,
    chapter: int,
    chapter_blocks: tuple,
) -> tuple[StructureCandidate, ...]:
    final_path = OUT / f"chapter-{chapter:02d}-structure.json"
    if final_path.exists():
        existing = json.loads(final_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and "structures" in existing:
            existing = {"structures": existing["structures"]}
        parsed = parse_structure_candidates(json.dumps(existing, ensure_ascii=False))
        print(f"REUSE chapter={chapter} structures={len(parsed)}", flush=True)
        return parsed
    raw = call_model(
        adapter,
        build_structure_candidates_prompt(structure_source(chapter_blocks)),
        f"chapter-{chapter:02d}-structure",
    )
    (OUT / f"chapter-{chapter:02d}-structure-raw.txt").write_text(raw, encoding="utf-8")
    cleaned = clean_json_text(raw)
    items = parse_structure_candidates(cleaned)
    final_path.write_text(structure_to_json(items), encoding="utf-8")
    return items


def split_blocks(chapter_blocks: tuple) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_chars = 0
    for block in chapter_blocks:
        text = block.text.strip()
        if not text:
            continue
        rendered = f"[{block.source_pointer}] {text}"
        if current and current_chars + len(rendered) + 1 > MAX_CHUNK_CHARS:
            chunks.append("\n".join(current))
            current = []
            current_chars = 0
        current.append(rendered)
        current_chars += len(rendered) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def candidate_payload_text(value: str) -> str:
    payload = json.loads(value)
    if isinstance(payload, dict) and "notes" in payload and "links" in payload:
        payload = {"notes": payload["notes"], "links": payload["links"]}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def aggregate_results() -> None:
    chapter_rows: list[dict[str, object]] = []
    all_parts: list[dict[str, object]] = []
    title_index: dict[str, list[dict[str, str]]] = {}
    grand_note_kinds: Counter[str] = Counter()
    grand_link_kinds: Counter[str] = Counter()

    for chapter in range(1, 12):
        if chapter == 1:
            files = [OUT / "chapter-01-candidates.json"]
        elif chapter == 2:
            files = sorted(OUT.glob("chapter-02-part-*-candidates.json"))
        else:
            files = sorted(OUT.glob(f"chapter-{chapter:02d}-part-*-16k-candidates.json"))
        if not files:
            raise RuntimeError(f"aggregate_missing_chapter:{chapter}")
        chapter_note_kinds: Counter[str] = Counter()
        chapter_link_kinds: Counter[str] = Counter()
        for part_number, path in enumerate(files, 1):
            text = candidate_payload_text(path.read_text(encoding="utf-8"))
            parsed = parse_knowledge_candidates(text)
            payload = json.loads(text)
            note_counts = Counter(note.kind.value for note in parsed.notes)
            link_counts = Counter(link.kind.value for link in parsed.links)
            chapter_note_kinds.update(note_counts)
            chapter_link_kinds.update(link_counts)
            grand_note_kinds.update(note_counts)
            grand_link_kinds.update(link_counts)
            all_parts.append(
                {
                    "chapter": chapter,
                    "part": part_number,
                    "file": path.name,
                    "notes": payload["notes"],
                    "links": payload["links"],
                }
            )
            for note in payload["notes"]:
                normalized_title = re.sub(r"\s+", "", note["title"]).casefold()
                title_index.setdefault(normalized_title, []).append(
                    {
                        "chapter": str(chapter),
                        "part": str(part_number),
                        "key": note["key"],
                        "title": note["title"],
                    }
                )
        chapter_rows.append(
            {
                "chapter": chapter,
                "parts": len(files),
                "notes": sum(chapter_note_kinds.values()),
                "links": sum(chapter_link_kinds.values()),
                "note_kinds": dict(sorted(chapter_note_kinds.items())),
                "link_kinds": dict(sorted(chapter_link_kinds.items())),
            }
        )

    review_pack = {
        "status": "review_only",
        "model": MODEL,
        "source": SOURCE.name,
        "chunk_limit_chars": MAX_CHUNK_CHARS,
        "chapters": chapter_rows,
        "parts": all_parts,
        "canonical_title_index": {
            title: occurrences
            for title, occurrences in sorted(title_index.items())
            if len(occurrences) > 1
        },
    }
    (OUT / "knowledge-candidates-review.json").write_text(
        json.dumps(review_pack, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 无线通信教材知识候选提取摘要",
        "",
        "- 状态：仅供人工审核，未发布正式双向链接",
        f"- 模型：`{MODEL}`",
        f"- 来源：`{SOURCE.name}`",
        f"- 分块上限：{MAX_CHUNK_CHARS} 字符",
        f"- 候选笔记总数（分块内计数）：{sum(grand_note_kinds.values())}",
        f"- 候选链接总数（分块内计数）：{sum(grand_link_kinds.values())}",
        "",
        "| 章 | 分块 | 笔记 | 链接 |",
        "|---:|---:|---:|---:|",
    ]
    for row in chapter_rows:
        lines.append(
            f"| {row['chapter']} | {row['parts']} | {row['notes']} | {row['links']} |"
        )
    lines.extend(
        [
            "",
            "## 笔记类型计数",
            "",
            *[f"- {kind}: {count}" for kind, count in sorted(grand_note_kinds.items())],
            "",
            "## 链接类型计数",
            "",
            *[f"- {kind}: {count}" for kind, count in sorted(grand_link_kinds.items())],
            "",
            "> 相同标题索引只用于人工复核，不代表已自动合并语义或发布链接。",
        ]
    )
    (OUT / "knowledge-candidates-summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        f"AGGREGATE chapters=11 notes={sum(grand_note_kinds.values())} "
        f"links={sum(grand_link_kinds.values())}",
        flush=True,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    api_key = load_api_key()
    adapter = FaroOpenAICompatibleAdapter(
        api_key=api_key,
        base_url="https://faroapi.com/v1",
        model=MODEL,
        timeout_seconds=180.0,
    )
    document = parse_docx(SOURCE.read_bytes(), source_name="wireless-communications-2e.docx")
    ranges = chapter_ranges(document.blocks)
    print(f"PARSED blocks={len(document.blocks)} chapters={len(ranges)}", flush=True)
    progress: dict[str, object] = {
        "status": "in_progress",
        "model": MODEL,
        "chunk_limit_chars": MAX_CHUNK_CHARS,
        "chapters": {},
    }
    progress_path = OUT / "progress-summary-16k.json"

    for chapter in range(3, 12):
        start, end = ranges[chapter]
        chapter_blocks = document.blocks[start:end]
        structures = get_structures(adapter, chapter, chapter_blocks)
        chunks = split_blocks(chapter_blocks)
        print(
            f"CHAPTER chapter={chapter} blocks={len(chapter_blocks)} "
            f"structures={len(structures)} chunks={len(chunks)}",
            flush=True,
        )
        note_total = 0
        link_total = 0
        for part, source_text in enumerate(chunks, 1):
            stem = f"chapter-{chapter:02d}-part-{part:02d}-16k"
            final_path = OUT / f"{stem}-candidates.json"
            if final_path.exists():
                validated = parse_knowledge_candidates(final_path.read_text(encoding="utf-8"))
                note_total += len(validated.notes)
                link_total += len(validated.links)
                print(
                    f"SKIP {stem} notes={len(validated.notes)} links={len(validated.links)}",
                    flush=True,
                )
                continue
            raw = call_model(
                adapter,
                build_knowledge_candidates_prompt(source_text, structures=structures),
                stem,
            )
            (OUT / f"{stem}-raw.txt").write_text(raw, encoding="utf-8")
            candidate_json = validate_or_repair(
                adapter,
                raw,
                label=stem,
                repaired_raw_path=OUT / f"{stem}-repaired-raw.txt",
            )
            validated = parse_knowledge_candidates(candidate_json)
            final_path.write_text(candidate_json, encoding="utf-8")
            note_total += len(validated.notes)
            link_total += len(validated.links)
            print(
                f"SAVED {stem} notes={len(validated.notes)} links={len(validated.links)}",
                flush=True,
            )
        progress["chapters"][str(chapter)] = {
            "parts": len(chunks),
            "notes": note_total,
            "links": link_total,
        }
        progress_path.write_text(
            json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"DONE chapter={chapter} parts={len(chunks)} notes={note_total} links={link_total}",
            flush=True,
        )

    progress["status"] = "complete"
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
    aggregate_results()
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()













