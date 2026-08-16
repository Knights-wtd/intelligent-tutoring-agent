"""Pure, bounded parsers for supported native knowledge sources."""

from __future__ import annotations

import binascii
import math
import posixpath
import re
import stat
import struct
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree

import yaml
from pypdf import PdfReader

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_WINDOWS_DRIVE_PATH = re.compile(r"^[A-Za-z]:")
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
_MARKDOWN_TABLE_SEPARATOR = re.compile(r"^:?-{3,}:?$")
_WIKILINK = re.compile(r"\[\[([^\[\]\r\n]{1,512})\]\]")
_INLINE_TAG = re.compile(r"(?<![\w/])#([\w-]+)", re.UNICODE)
_DOCX_HEADING_STYLE = re.compile(r"^heading\s*([1-6])$", re.IGNORECASE)
_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD = f"{{{_WORD_NAMESPACE}}}"
_MAX_FRONTMATTER_BYTES = 64 * 1024
_MAX_FRONTMATTER_NODES = 10_000
_MAX_FRONTMATTER_DEPTH = 32
_DEFAULT_MAX_COMPRESSION_RATIO = 100.0
_DOCX_MAX_FILES = 2_048
_DOCX_MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
_DOCX_MAX_MEMBER_BYTES = 8 * 1024 * 1024
_ARCHIVE_READ_CHUNK_BYTES = 64 * 1024
_MAX_PNG_DECOMPRESSED_BYTES = 64 * 1024 * 1024
_PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}

type FrozenScalar = str | int | float | bool | None
type FrozenValue = (
    FrozenScalar | tuple[FrozenValue, ...] | tuple[tuple[str, FrozenValue], ...]
)
type MetadataValue = str | int | float | bool


class ParseErrorCode(StrEnum):
    """Stable, non-sensitive parser error codes."""

    INVALID_FORMAT = "invalid_format"
    UNSAFE_ARCHIVE = "unsafe_archive"
    ARCHIVE_LIMIT_EXCEEDED = "archive_limit_exceeded"
    UNSAFE_XML = "unsafe_xml"
    INVALID_FRONTMATTER = "invalid_frontmatter"


_ERROR_MESSAGES = {
    ParseErrorCode.INVALID_FORMAT: "source could not be parsed",
    ParseErrorCode.UNSAFE_ARCHIVE: "archive is unsafe",
    ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED: "archive limits exceeded",
    ParseErrorCode.UNSAFE_XML: "XML content is unsafe",
    ParseErrorCode.INVALID_FRONTMATTER: "frontmatter is invalid",
}


class ParseError(RuntimeError):
    """Public parser failure with a stable code and redacted message."""

    def __init__(self, code: ParseErrorCode) -> None:
        if not isinstance(code, ParseErrorCode):
            raise TypeError("code must be a ParseErrorCode")
        self.code = code
        self.public_message = _ERROR_MESSAGES[code]
        super().__init__(self.public_message)


class BlockKind(StrEnum):
    """Ordered native block types shared by source formats."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    kind: BlockKind
    text: str
    order: int
    source_pointer: str
    page_number: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    heading_level: int | None = None
    table: tuple[tuple[str, ...], ...] = ()
    metadata: tuple[tuple[str, MetadataValue], ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedPage:
    page_number: int
    blocks: tuple[ParsedBlock, ...]
    needs_ocr: bool
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class WikiLink:
    target: str
    alias: str | None
    source_path: str
    source_pointer: str
    line_start: int
    line_end: int


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source_name: str
    media_type: str
    blocks: tuple[ParsedBlock, ...] = ()
    pages: tuple[ParsedPage, ...] = ()
    frontmatter: tuple[tuple[str, FrozenValue], ...] = ()
    tags: tuple[str, ...] = ()
    wikilinks: tuple[WikiLink, ...] = ()

    @property
    def needs_ocr(self) -> bool:
        return any(page.needs_ocr for page in self.pages)


@dataclass(frozen=True, slots=True)
class VaultAttachment:
    path: str
    size: int


@dataclass(frozen=True, slots=True)
class VaultNote:
    path: str
    document: ParsedDocument
    attachment_links: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VaultParseResult:
    notes: tuple[VaultNote, ...]
    attachments: tuple[VaultAttachment, ...]
    wikilinks: tuple[WikiLink, ...]


@dataclass(frozen=True, slots=True)
class _ArchiveEntry:
    info: zipfile.ZipInfo
    path: str
    is_directory: bool


@dataclass(frozen=True, slots=True)
class _ArchiveContents:
    entries: tuple[_ArchiveEntry, ...]
    kept: tuple[tuple[str, bytes], ...]


def _raise(code: ParseErrorCode) -> None:
    raise ParseError(code) from None


def _source_pointer(source_name: str, start: int, end: int) -> str:
    if start == end:
        return f"{source_name}:L{start}"
    return f"{source_name}:L{start}-L{end}"


def _looks_like_ocr_candidate(text: str) -> bool:
    meaningful = sum(character.isalnum() for character in text)
    if meaningful < 20:
        return True
    suspicious = sum(
        character == "\ufffd"
        or (
            unicodedata.category(character) in {"Cc", "Cs", "Co"}
            and character not in "\n\r\t"
        )
        for character in text
    )
    if suspicious >= 3 and suspicious / max(len(text), 1) > 0.05:
        return True
    mojibake_markers = ("Ã", "Â", "â€", "ðŸ", "ï¿½")
    return sum(text.count(marker) for marker in mojibake_markers) >= 3


def parse_pdf(data: bytes, *, source_name: str = "document.pdf") -> ParsedDocument:
    """Extract native PDF text per page and flag weak pages for later OCR."""

    try:
        reader = PdfReader(BytesIO(bytes(data)), strict=True)
        if reader.is_encrypted:
            _raise(ParseErrorCode.INVALID_FORMAT)
        pages: list[ParsedPage] = []
        all_blocks: list[ParsedBlock] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            lines = tuple(line.strip() for line in text.splitlines() if line.strip())
            blocks = tuple(
                ParsedBlock(
                    kind=BlockKind.PARAGRAPH,
                    text=line,
                    order=order,
                    source_pointer=f"{source_name}#page={page_number}&block={order + 1}",
                    page_number=page_number,
                )
                for order, line in enumerate(lines)
            )
            pages.append(
                ParsedPage(
                    page_number=page_number,
                    blocks=blocks,
                    needs_ocr=_looks_like_ocr_candidate(text),
                )
            )
            all_blocks.extend(blocks)
        if not pages:
            _raise(ParseErrorCode.INVALID_FORMAT)
        return ParsedDocument(
            source_name=source_name,
            media_type="application/pdf",
            blocks=tuple(all_blocks),
            pages=tuple(pages),
        )
    except ParseError:
        raise
    except Exception:
        _raise(ParseErrorCode.INVALID_FORMAT)


def _normalize_archive_path(raw_path: str, *, is_directory: bool) -> str:
    if not raw_path or "\\" in raw_path or raw_path.startswith("/"):
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    if _WINDOWS_DRIVE_PATH.match(raw_path):
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    candidate = raw_path[:-1] if is_directory and raw_path.endswith("/") else raw_path
    if not candidate or candidate.endswith("/"):
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in candidate):
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    normalized = unicodedata.normalize("NFC", candidate)
    if normalized.startswith("/") or _WINDOWS_DRIVE_PATH.match(normalized):
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    normalized_parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in normalized_parts):
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    return normalized


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    if info.create_system != 3:
        return False
    return stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK


def _validate_archive_limits(
    *,
    max_files: int,
    max_uncompressed_bytes: int,
    max_member_bytes: int,
    max_compression_ratio: float,
) -> None:
    if (
        isinstance(max_files, bool)
        or not isinstance(max_files, int)
        or max_files < 1
        or isinstance(max_uncompressed_bytes, bool)
        or not isinstance(max_uncompressed_bytes, int)
        or max_uncompressed_bytes < 1
        or isinstance(max_member_bytes, bool)
        or not isinstance(max_member_bytes, int)
        or max_member_bytes < 1
        or isinstance(max_compression_ratio, bool)
        or not isinstance(max_compression_ratio, int | float)
        or not math.isfinite(max_compression_ratio)
        or max_compression_ratio < 1
    ):
        raise ValueError("archive limits must be positive finite values")


def _read_archive(
    data: bytes,
    *,
    keep_suffixes: tuple[str, ...],
    max_files: int,
    max_uncompressed_bytes: int,
    max_member_bytes: int,
    max_compression_ratio: float,
) -> _ArchiveContents:
    _validate_archive_limits(
        max_files=max_files,
        max_uncompressed_bytes=max_uncompressed_bytes,
        max_member_bytes=max_member_bytes,
        max_compression_ratio=max_compression_ratio,
    )
    try:
        with zipfile.ZipFile(BytesIO(bytes(data))) as archive:
            entries: list[_ArchiveEntry] = []
            seen_paths: set[str] = set()
            declared_total = 0
            file_count = 0
            for info in archive.infolist():
                is_directory = info.is_dir()
                path = _normalize_archive_path(info.orig_filename, is_directory=is_directory)
                if path in seen_paths:
                    _raise(ParseErrorCode.UNSAFE_ARCHIVE)
                seen_paths.add(path)
                if info.flag_bits & 0x1 or _is_symlink(info):
                    _raise(ParseErrorCode.UNSAFE_ARCHIVE)
                if is_directory:
                    entries.append(_ArchiveEntry(info=info, path=path, is_directory=True))
                    continue
                file_count += 1
                if file_count > max_files:
                    _raise(ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED)
                if info.file_size > max_member_bytes:
                    _raise(ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED)
                declared_total += info.file_size
                if declared_total > max_uncompressed_bytes:
                    _raise(ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED)
                if info.file_size:
                    if info.compress_size == 0:
                        _raise(ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED)
                    if info.file_size / info.compress_size > max_compression_ratio:
                        _raise(ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED)
                entries.append(_ArchiveEntry(info=info, path=path, is_directory=False))

            kept: list[tuple[str, bytes]] = []
            actual_total = 0
            suffixes = tuple(suffix.casefold() for suffix in keep_suffixes)
            for entry in entries:
                if entry.is_directory:
                    continue
                member = bytearray()
                actual_member = 0
                with archive.open(entry.info, "r") as stream:
                    while True:
                        chunk = stream.read(_ARCHIVE_READ_CHUNK_BYTES)
                        if not chunk:
                            break
                        actual_member += len(chunk)
                        actual_total += len(chunk)
                        if (
                            actual_member > max_member_bytes
                            or actual_total > max_uncompressed_bytes
                        ):
                            _raise(ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED)
                        if entry.path.casefold().endswith(suffixes):
                            member.extend(chunk)
                if actual_member != entry.info.file_size:
                    _raise(ParseErrorCode.UNSAFE_ARCHIVE)
                if entry.path.casefold().endswith(suffixes):
                    kept.append((entry.path, bytes(member)))
            return _ArchiveContents(entries=tuple(entries), kept=tuple(kept))
    except ParseError:
        raise
    except (OSError, EOFError, RuntimeError, NotImplementedError, zipfile.BadZipFile):
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)


def _contains_dangerous_xml_declaration(data: bytes) -> bool:
    lowered = data.lower()
    compact = lowered.replace(b"\x00", b"")
    return b"<!doctype" in compact or b"<!entity" in compact


def _parse_xml(data: bytes) -> ElementTree.Element:
    if len(data) > _DOCX_MAX_MEMBER_BYTES or _contains_dangerous_xml_declaration(data):
        _raise(ParseErrorCode.UNSAFE_XML)
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError:
        _raise(ParseErrorCode.INVALID_FORMAT)


def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for element in paragraph.iter():
        if element.tag == f"{_WORD}t" and element.text:
            parts.append(element.text)
        elif element.tag == f"{_WORD}tab":
            parts.append("\t")
        elif element.tag in {f"{_WORD}br", f"{_WORD}cr"}:
            parts.append("\n")
    return "".join(parts).strip()


def _docx_heading_level(paragraph: ElementTree.Element) -> int | None:
    style = paragraph.find(f"{_WORD}pPr/{_WORD}pStyle")
    if style is None:
        return None
    value = style.get(f"{_WORD}val", "")
    match = _DOCX_HEADING_STYLE.fullmatch(value.strip())
    return int(match.group(1)) if match else None


def _docx_table_rows(table: ElementTree.Element) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for row in table.findall(f"{_WORD}tr"):
        cells: list[str] = []
        for cell in row.findall(f"{_WORD}tc"):
            paragraphs = tuple(
                text
                for paragraph in cell.findall(f".//{_WORD}p")
                if (text := _docx_paragraph_text(paragraph))
            )
            cells.append("\n".join(paragraphs))
        rows.append(tuple(cells))
    return tuple(rows)


def parse_docx(data: bytes, *, source_name: str = "document.docx") -> ParsedDocument:
    """Parse DOCX body order using bounded ZIP and standard-library XML handling."""

    contents = _read_archive(
        data,
        keep_suffixes=(".xml", ".rels"),
        max_files=_DOCX_MAX_FILES,
        max_uncompressed_bytes=_DOCX_MAX_UNCOMPRESSED_BYTES,
        max_member_bytes=_DOCX_MAX_MEMBER_BYTES,
        max_compression_ratio=_DEFAULT_MAX_COMPRESSION_RATIO,
    )
    kept = dict(contents.kept)
    if "[Content_Types].xml" not in kept or "word/document.xml" not in kept:
        _raise(ParseErrorCode.INVALID_FORMAT)
    for xml_data in kept.values():
        if _contains_dangerous_xml_declaration(xml_data):
            _raise(ParseErrorCode.UNSAFE_XML)
    root = _parse_xml(kept["word/document.xml"])
    if root.tag != f"{_WORD}document":
        _raise(ParseErrorCode.INVALID_FORMAT)
    body = root.find(f"{_WORD}body")
    if body is None:
        _raise(ParseErrorCode.INVALID_FORMAT)

    blocks: list[ParsedBlock] = []
    for child in body:
        if child.tag == f"{_WORD}p":
            text = _docx_paragraph_text(child)
            if not text:
                continue
            heading_level = _docx_heading_level(child)
            order = len(blocks)
            blocks.append(
                ParsedBlock(
                    kind=BlockKind.HEADING if heading_level else BlockKind.PARAGRAPH,
                    text=text,
                    order=order,
                    source_pointer=f"{source_name}#block={order + 1}",
                    heading_level=heading_level,
                )
            )
        elif child.tag == f"{_WORD}tbl":
            rows = _docx_table_rows(child)
            if not rows:
                continue
            order = len(blocks)
            columns = max((len(row) for row in rows), default=0)
            blocks.append(
                ParsedBlock(
                    kind=BlockKind.TABLE,
                    text="\n".join(" | ".join(row) for row in rows),
                    order=order,
                    source_pointer=f"{source_name}#block={order + 1}",
                    table=rows,
                    metadata=(("columns", columns), ("rows", len(rows))),
                )
            )
    return ParsedDocument(
        source_name=source_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        blocks=tuple(blocks),
    )


def _freeze_yaml(
    value: object,
    *,
    depth: int = 0,
    active_ids: frozenset[int] = frozenset(),
    budget: list[int] | None = None,
) -> FrozenValue:
    if budget is None:
        budget = [_MAX_FRONTMATTER_NODES]
    budget[0] -= 1
    if budget[0] < 0 or depth > _MAX_FRONTMATTER_DEPTH:
        _raise(ParseErrorCode.INVALID_FRONTMATTER)
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _raise(ParseErrorCode.INVALID_FRONTMATTER)
        return value
    if isinstance(value, list | dict):
        identity = id(value)
        if identity in active_ids:
            _raise(ParseErrorCode.INVALID_FRONTMATTER)
        active_ids = active_ids | {identity}
    if isinstance(value, list):
        return tuple(
            _freeze_yaml(item, depth=depth + 1, active_ids=active_ids, budget=budget)
            for item in value
        )
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            _raise(ParseErrorCode.INVALID_FRONTMATTER)
        return tuple(
            (
                key,
                _freeze_yaml(
                    value[key], depth=depth + 1, active_ids=active_ids, budget=budget
                ),
            )
            for key in sorted(value)
        )
    _raise(ParseErrorCode.INVALID_FRONTMATTER)


def _parse_frontmatter(
    lines: list[str],
) -> tuple[int, tuple[tuple[str, FrozenValue], ...], tuple[str, ...]]:
    if not lines or lines[0].strip() != "---":
        return 0, (), ()
    closing_index = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    if closing_index is None:
        _raise(ParseErrorCode.INVALID_FRONTMATTER)
    yaml_text = "\n".join(lines[1:closing_index])
    if len(yaml_text.encode("utf-8")) > _MAX_FRONTMATTER_BYTES:
        _raise(ParseErrorCode.INVALID_FRONTMATTER)
    try:
        loaded = yaml.safe_load(yaml_text)
    except (RecursionError, yaml.YAMLError):
        _raise(ParseErrorCode.INVALID_FRONTMATTER)
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        _raise(ParseErrorCode.INVALID_FRONTMATTER)
    try:
        frozen = _freeze_yaml(loaded)
    except RecursionError:
        _raise(ParseErrorCode.INVALID_FRONTMATTER)
    if not isinstance(frozen, tuple):
        _raise(ParseErrorCode.INVALID_FRONTMATTER)

    raw_tags = loaded.get("tags", ())
    if isinstance(raw_tags, str):
        candidates = raw_tags.replace(",", " ").split()
    elif isinstance(raw_tags, list) and all(isinstance(tag, str) for tag in raw_tags):
        candidates = raw_tags
    elif raw_tags in (None, ()):
        candidates = []
    else:
        _raise(ParseErrorCode.INVALID_FRONTMATTER)
    tags = tuple(tag for candidate in candidates if (tag := candidate.strip().lstrip("#")))
    return closing_index + 1, frozen, tags


def _markdown_table_cells(line: str) -> tuple[str, ...]:
    stripped = line.strip()
    if "|" not in stripped:
        return ()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells = tuple(cell.strip() for cell in stripped.split("|"))
    return cells if len(cells) >= 2 else ()


def _is_markdown_table(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    header = _markdown_table_cells(lines[index])
    separator = _markdown_table_cells(lines[index + 1])
    return bool(
        header
        and len(header) == len(separator)
        and all(_MARKDOWN_TABLE_SEPARATOR.fullmatch(cell) for cell in separator)
    )


def _collect_wikilinks(
    lines: list[str], source_name: str, start_index: int
) -> tuple[WikiLink, ...]:
    links: list[WikiLink] = []
    for index in range(start_index, len(lines)):
        line_number = index + 1
        for match in _WIKILINK.finditer(lines[index]):
            raw_target, separator, raw_alias = match.group(1).partition("|")
            target = unicodedata.normalize("NFC", raw_target.strip())
            alias = raw_alias.strip() if separator and raw_alias.strip() else None
            if not target:
                continue
            links.append(
                WikiLink(
                    target=target,
                    alias=alias,
                    source_path=source_name,
                    source_pointer=_source_pointer(source_name, line_number, line_number),
                    line_start=line_number,
                    line_end=line_number,
                )
            )
    return tuple(links)


def _append_unique(values: list[str], candidate: str) -> None:
    normalized = unicodedata.normalize("NFC", candidate.strip().lstrip("#"))
    if normalized and normalized not in values:
        values.append(normalized)


def parse_markdown(data: bytes, *, source_name: str = "document.md") -> ParsedDocument:
    """Parse Markdown blocks while preserving exact one-based source line ranges."""

    try:
        text = bytes(data).decode("utf-8-sig")
    except UnicodeDecodeError:
        _raise(ParseErrorCode.INVALID_FORMAT)
    lines = text.splitlines()
    body_start, frontmatter, frontmatter_tags = _parse_frontmatter(lines)
    tags: list[str] = []
    for tag in frontmatter_tags:
        _append_unique(tags, tag)
    for line in lines[body_start:]:
        for match in _INLINE_TAG.finditer(line):
            _append_unique(tags, match.group(1))

    blocks: list[ParsedBlock] = []
    index = body_start
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        heading = _MARKDOWN_HEADING.fullmatch(lines[index])
        if heading:
            line_number = index + 1
            blocks.append(
                ParsedBlock(
                    kind=BlockKind.HEADING,
                    text=heading.group(2).strip(),
                    order=len(blocks),
                    source_pointer=_source_pointer(source_name, line_number, line_number),
                    line_start=line_number,
                    line_end=line_number,
                    heading_level=len(heading.group(1)),
                )
            )
            index += 1
            continue
        if _is_markdown_table(lines, index):
            start = index
            rows = [_markdown_table_cells(lines[index])]
            index += 2
            while index < len(lines):
                row = _markdown_table_cells(lines[index])
                if not row:
                    break
                rows.append(row)
                index += 1
            line_start = start + 1
            line_end = index
            table = tuple(rows)
            blocks.append(
                ParsedBlock(
                    kind=BlockKind.TABLE,
                    text="\n".join(" | ".join(row) for row in table),
                    order=len(blocks),
                    source_pointer=_source_pointer(source_name, line_start, line_end),
                    line_start=line_start,
                    line_end=line_end,
                    table=table,
                    metadata=(
                        ("columns", max((len(row) for row in table), default=0)),
                        ("rows", len(table)),
                    ),
                )
            )
            continue

        start = index
        paragraph_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            if index != start and (
                _MARKDOWN_HEADING.fullmatch(lines[index]) or _is_markdown_table(lines, index)
            ):
                break
            paragraph_lines.append(lines[index].strip())
            index += 1
        line_start = start + 1
        line_end = start + len(paragraph_lines)
        blocks.append(
            ParsedBlock(
                kind=BlockKind.PARAGRAPH,
                text="\n".join(paragraph_lines),
                order=len(blocks),
                source_pointer=_source_pointer(source_name, line_start, line_end),
                line_start=line_start,
                line_end=line_end,
            )
        )

    return ParsedDocument(
        source_name=source_name,
        media_type="text/markdown",
        blocks=tuple(blocks),
        frontmatter=frontmatter,
        tags=tuple(tags),
        wikilinks=_collect_wikilinks(lines, source_name, body_start),
    )


def _validate_png_image_data(
    compressed: bytes,
    *,
    width: int,
    height: int,
    bit_depth: int,
    color_type: int,
) -> None:
    row_bytes = (width * _PNG_CHANNELS[color_type] * bit_depth + 7) // 8
    expected_bytes = height * (row_bytes + 1)
    if expected_bytes > _MAX_PNG_DECOMPRESSED_BYTES:
        _raise(ParseErrorCode.INVALID_FORMAT)
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(compressed, expected_bytes + 1)
    except zlib.error:
        _raise(ParseErrorCode.INVALID_FORMAT)
    if (
        len(decoded) != expected_bytes
        or not decompressor.eof
        or decompressor.unconsumed_tail
        or decompressor.unused_data
    ):
        _raise(ParseErrorCode.INVALID_FORMAT)
    stride = row_bytes + 1
    if any(decoded[offset] > 4 for offset in range(0, len(decoded), stride)):
        _raise(ParseErrorCode.INVALID_FORMAT)


def parse_png(data: bytes, *, source_name: str = "image.png") -> ParsedDocument:
    """Validate PNG chunks and bounded non-interlaced scanlines without OCR."""

    raw = bytes(data)
    if not raw.startswith(_PNG_SIGNATURE):
        _raise(ParseErrorCode.INVALID_FORMAT)
    offset = len(_PNG_SIGNATURE)
    width: int | None = None
    height: int | None = None
    bit_depth: int | None = None
    color_type: int | None = None
    idat_parts: list[bytes] = []
    saw_idat = False
    saw_iend = False
    chunk_index = 0
    while offset < len(raw):
        if len(raw) - offset < 12:
            _raise(ParseErrorCode.INVALID_FORMAT)
        length = struct.unpack_from(">I", raw, offset)[0]
        chunk_type = raw[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(raw) or len(chunk_type) != 4 or not chunk_type.isalpha():
            _raise(ParseErrorCode.INVALID_FORMAT)
        chunk_data = raw[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack_from(">I", raw, offset + 8 + length)[0]
        actual_crc = binascii.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            _raise(ParseErrorCode.INVALID_FORMAT)
        if chunk_index == 0:
            if chunk_type != b"IHDR" or length != 13:
                _raise(ParseErrorCode.INVALID_FORMAT)
            width, height, bit_depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", chunk_data)
            )
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if (
                width == 0
                or height == 0
                or bit_depth not in valid_depths.get(color_type, set())
                or compression != 0
                or filtering != 0
                or interlace != 0
            ):
                _raise(ParseErrorCode.INVALID_FORMAT)
        elif chunk_type == b"IHDR":
            _raise(ParseErrorCode.INVALID_FORMAT)
        if chunk_type == b"IDAT":
            saw_idat = True
            idat_parts.append(chunk_data)
        if chunk_type == b"IEND":
            if length != 0 or not saw_idat or end != len(raw):
                _raise(ParseErrorCode.INVALID_FORMAT)
            saw_iend = True
            offset = end
            break
        offset = end
        chunk_index += 1
    if (
        not saw_iend
        or width is None
        or height is None
        or bit_depth is None
        or color_type is None
    ):
        _raise(ParseErrorCode.INVALID_FORMAT)
    _validate_png_image_data(
        b"".join(idat_parts),
        width=width,
        height=height,
        bit_depth=bit_depth,
        color_type=color_type,
    )
    page = ParsedPage(page_number=1, blocks=(), needs_ocr=True, width=width, height=height)
    return ParsedDocument(
        source_name=source_name,
        media_type="image/png",
        pages=(page,),
    )


def _resolve_vault_link(note_path: str, target: str) -> str | None:
    path_target = target.split("#", 1)[0].strip()
    if not path_target or "\\" in path_target:
        return None
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in path_target):
        return None
    if path_target.startswith("/"):
        combined = path_target.lstrip("/")
    else:
        combined = posixpath.join(str(PurePosixPath(note_path).parent), path_target)
    normalized = unicodedata.normalize("NFC", posixpath.normpath(combined))
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return None
    return normalized


def parse_obsidian_vault_zip(
    data: bytes,
    *,
    max_files: int = 5_000,
    max_uncompressed_bytes: int = 500 * 1024 * 1024,
    max_compression_ratio: float = _DEFAULT_MAX_COMPRESSION_RATIO,
) -> VaultParseResult:
    """Parse Markdown notes from a bounded, traversal-safe Obsidian Vault ZIP."""

    contents = _read_archive(
        data,
        keep_suffixes=(".md",),
        max_files=max_files,
        max_uncompressed_bytes=max_uncompressed_bytes,
        max_member_bytes=max_uncompressed_bytes,
        max_compression_ratio=max_compression_ratio,
    )
    files = tuple(entry for entry in contents.entries if not entry.is_directory)
    note_bytes = dict(contents.kept)
    note_paths = sorted(note_bytes)
    attachments = tuple(
        VaultAttachment(path=entry.path, size=entry.info.file_size)
        for entry in sorted(files, key=lambda item: item.path)
        if not entry.path.casefold().endswith(".md")
    )
    attachment_paths = {attachment.path for attachment in attachments}

    notes: list[VaultNote] = []
    all_links: list[WikiLink] = []
    for path in note_paths:
        document = parse_markdown(note_bytes[path], source_name=path)
        attachment_links: list[str] = []
        for link in document.wikilinks:
            resolved = _resolve_vault_link(path, link.target)
            if resolved in attachment_paths and resolved not in attachment_links:
                attachment_links.append(resolved)
        notes.append(
            VaultNote(
                path=path,
                document=document,
                attachment_links=tuple(attachment_links),
            )
        )
        all_links.extend(document.wikilinks)
    return VaultParseResult(
        notes=tuple(notes),
        attachments=attachments,
        wikilinks=tuple(all_links),
    )


__all__ = [
    "BlockKind",
    "ParseError",
    "ParseErrorCode",
    "ParsedBlock",
    "ParsedDocument",
    "ParsedPage",
    "VaultAttachment",
    "VaultNote",
    "VaultParseResult",
    "WikiLink",
    "parse_docx",
    "parse_markdown",
    "parse_obsidian_vault_zip",
    "parse_pdf",
    "parse_png",
]
