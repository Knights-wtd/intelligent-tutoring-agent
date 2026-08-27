from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


TARGET = Path(r"E:\obsidian work\communication\communication\wire sign")
DIGITAL_INDEX = Path(r"E:\obsidian work\communication\communication\通信\教材\数字通信学习索引.md")
ARTIFACTS = Path(
    r"E:\项目\知识库课本\.worktrees\platform-foundation\artifacts\wireless-knowledge-gemini-3.6"
)
BACKUP = ARTIFACTS / "wire-sign-before-graph-simplification-20260824.zip"
STAGING = ARTIFACTS / "wire-sign-hierarchical-staging"
MANIFEST = ARTIFACTS / "wire-sign-graph-simplification-manifest.json"

HOME = "无线通信原理与应用（第二版）- 教材主页"
TOC = "无线通信原理与应用（第二版）- PDF目录"
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
RELATED_RE = re.compile(r"(?ms)^## 相关笔记\s*\n(.*?)(?=^## |\Z)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def scalar(text: str, key: str) -> str | None:
    match = re.search(rf'(?m)^{re.escape(key)}:\s*"?([^"\r\n]+)"?\s*$', text)
    return match.group(1).strip() if match else None


def plain_wikilinks(line: str) -> str:
    return LINK_RE.sub(lambda m: (m.group(2) or Path(m.group(1)).name).strip(), line)


def unique(lines: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        normalized = line.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def simplify_related(text: str, kind: str) -> str:
    match = RELATED_RE.search(text)
    if not match:
        return text

    hierarchy: list[str] = []
    semantics: list[str] = []
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("-"):
            semantics.append(plain_wikilinks(line))
            continue
        if "所属结构" in line or "所属教材" in line:
            hierarchy.append(line)
        elif re.match(r"^-\s*(?:\*\*)?contains(?:\*\*)?\s*→", line, re.IGNORECASE):
            if kind in {"chapter", "section", "subsection"}:
                hierarchy.append(line)
            else:
                semantics.append(plain_wikilinks(line))
        else:
            semantics.append(plain_wikilinks(line))

    if kind == "chapter":
        hierarchy.insert(0, f"- 所属教材 → [[{HOME}]]")

    hierarchy = unique(hierarchy)
    semantics = unique(semantics)
    pieces = ["## 层级导航", "", *(hierarchy or ["- 暂无已确认的直属层级"])]
    if semantics:
        pieces.extend(["", "## 语义关系（不参与关系图）", "", *semantics])
    replacement = "\n".join(pieces).rstrip() + "\n\n"
    return text[: match.start()] + replacement + text[match.end() :]


def simplify_toc(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        # Keep chapter headings as the TOC's only structural links. All detail
        # rows remain readable but no longer create graph edges.
        if line.startswith("- [["):
            line = plain_wikilinks(line)
        lines.append(line)
    ending = "\n" if text.endswith("\n") else ""
    return "\n".join(lines) + ending


def transform(path: Path, text: str) -> str:
    text = text.replace(
        f'book_home: "[[{HOME}]]"', f'book_home: "{HOME}"'
    )
    text = text.replace(
        f"> 教材主页：[[{HOME}]]；教材总索引：[[通信教材总索引]]",
        "> 教材：无线通信原理与应用（第二版）；层级导航见本文末尾",
    )

    kind = scalar(text, "kind")
    if kind:
        text = simplify_related(text, kind)

    if path.stem == TOC:
        text = simplify_toc(text)

    part = scalar(text, "document_part")
    if part in {"appendix", "index"} and "## 层级导航" not in text:
        insert = f"\n## 层级导航\n\n- 所属教材 → [[{HOME}]]\n"
        source_pos = text.find("\n## 来源位置")
        text = text[:source_pos] + insert + text[source_pos:] if source_pos >= 0 else text.rstrip() + insert + "\n"
    return text


def link_metrics(files: dict[str, str]) -> dict[str, object]:
    links_total = 0
    adjacency: dict[str, set[str]] = defaultdict(set)
    unique_edges: set[tuple[str, str]] = set()
    stems = set(files)
    unresolved_internal: set[str] = set()

    for source, text in files.items():
        for match in LINK_RE.finditer(text):
            links_total += 1
            target = Path(match.group(1).replace("/", "\\")).name
            if target.endswith(".md"):
                target = target[:-3]
            edge = tuple(sorted((source, target)))
            unique_edges.add(edge)
            adjacency[source].add(target)
            adjacency[target].add(source)
            looks_external = "/" in match.group(1) or "\\" in match.group(1)
            if target not in stems and not looks_external and target not in {"通信教材总索引"}:
                unresolved_internal.add(target)

    ranked = sorted(((name, len(neighbors)) for name, neighbors in adjacency.items()), key=lambda x: (-x[1], x[0]))
    return {
        "files": len(files),
        "wikilinks_total": links_total,
        "unique_edges": len(unique_edges),
        "max_degree": ranked[0][1] if ranked else 0,
        "highest_degree_nodes": [{"note": n, "degree": d} for n, d in ranked[:10]],
        "home_degree": len(adjacency.get(HOME, set())),
        "toc_degree": len(adjacency.get(TOC, set())),
        "total_index_degree_from_wireless": len(adjacency.get("通信教材总索引", set())),
        "unresolved_internal_targets": sorted(unresolved_internal),
    }


def load_markdown(root: Path) -> dict[str, str]:
    files = sorted(root.glob("*.md"))
    return {path.stem: path.read_text(encoding="utf-8-sig") for path in files}


def validate(files: dict[str, str], before_count: int) -> list[str]:
    errors: list[str] = []
    if len(files) != before_count:
        errors.append(f"file count changed: {before_count} -> {len(files)}")
    for name, text in files.items():
        if text.startswith("---\n") and "\n---\n" not in text[4:]:
            errors.append(f"invalid frontmatter delimiter: {name}")
        if f'book_home: "[[{HOME}]]"' in text:
            errors.append(f"book_home still creates edge: {name}")
        if "> 教材主页：[[" in text:
            errors.append(f"global callout link still present: {name}")

    toc_text = files.get(TOC, "")
    toc_chapter_links = len(re.findall(rf"(?m)^## \[\[[^\]]+\]\]$", toc_text))
    toc_detail_links = len(re.findall(r"(?m)^- \[\[", toc_text))
    if toc_chapter_links != 11:
        errors.append(f"TOC chapter links: expected 11, got {toc_chapter_links}")
    if toc_detail_links:
        errors.append(f"TOC still has {toc_detail_links} detail links")

    metrics = link_metrics(files)
    if metrics["unresolved_internal_targets"]:
        errors.append("unresolved internal targets: " + ", ".join(metrics["unresolved_internal_targets"][:20]))
    return errors


def main() -> int:
    if not TARGET.is_dir():
        raise RuntimeError(f"missing target: {TARGET}")
    if not DIGITAL_INDEX.is_file():
        raise RuntimeError(f"missing digital index: {DIGITAL_INDEX}")
    if BACKUP.exists() or STAGING.exists() or MANIFEST.exists():
        raise RuntimeError("output path already exists; refusing to overwrite a backup or prior run")

    before_hash = sha256(DIGITAL_INDEX)
    before_files = load_markdown(TARGET)
    before_metrics = link_metrics(before_files)

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BACKUP, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(TARGET.glob("*.md")):
            archive.write(path, arcname=path.name)

    STAGING.mkdir()
    for source in sorted(TARGET.glob("*.md")):
        original = source.read_text(encoding="utf-8-sig")
        updated = transform(source, original)
        (STAGING / source.name).write_text(updated, encoding="utf-8", newline="\n")

    staged_files = load_markdown(STAGING)
    errors = validate(staged_files, len(before_files))
    after_metrics = link_metrics(staged_files)
    if after_metrics["unique_edges"] >= before_metrics["unique_edges"]:
        errors.append("unique edge count did not decrease")
    if after_metrics["home_degree"] >= before_metrics["home_degree"]:
        errors.append("book home degree did not decrease")
    if sha256(DIGITAL_INDEX) != before_hash:
        errors.append("digital communications index changed before deployment")
    if errors:
        raise RuntimeError("staging validation failed:\n- " + "\n- ".join(errors))

    for staged in sorted(STAGING.glob("*.md")):
        shutil.copy2(staged, TARGET / staged.name)

    deployed_files = load_markdown(TARGET)
    deployment_errors = validate(deployed_files, len(before_files))
    final_hash = sha256(DIGITAL_INDEX)
    if final_hash != before_hash:
        deployment_errors.append("digital communications index changed after deployment")
    if deployment_errors:
        raise RuntimeError("deployment validation failed:\n- " + "\n- ".join(deployment_errors))

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": str(TARGET),
        "backup": str(BACKUP),
        "staging": str(STAGING),
        "scope": "wireless communications only",
        "digital_index": str(DIGITAL_INDEX),
        "digital_index_sha256_before": before_hash,
        "digital_index_sha256_after": final_hash,
        "before": before_metrics,
        "after": link_metrics(deployed_files),
        "validation": {"passed": True, "errors": []},
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
