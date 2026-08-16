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
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

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
_DEFAULT_MAX_PDF_PAGES = 1_000
_DEFAULT_MAX_PDF_PAGE_TEXT_CHARS = 1_000_000
_DEFAULT_MAX_PDF_TOTAL_TEXT_CHARS = 16_000_000
_DEFAULT_MAX_PDF_BLOCKS = 200_000
_MAX_PDF_PAGE_TREE_DEPTH = 64
_DEFAULT_MAX_PATH_BYTES = 1_024
_DEFAULT_MAX_TOTAL_PATH_BYTES = 1024 * 1024
_DEFAULT_MAX_PATH_DEPTH = 32
_DEFAULT_MAX_MARKDOWN_MEMBER_BYTES = 16 * 1024 * 1024
_DEFAULT_MAX_TOTAL_MARKDOWN_BYTES = 64 * 1024 * 1024
_DEFAULT_MAX_MARKDOWN_LINES = 500_000
_DEFAULT_MAX_MARKDOWN_BLOCKS = 200_000
_DEFAULT_MAX_MARKDOWN_TAGS = 50_000
_DEFAULT_MAX_MARKDOWN_WIKILINKS = 200_000
_DEFAULT_MAX_MARKDOWN_LINE_CHARS = 1_000_000

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
    LIMIT_EXCEEDED = "limit_exceeded"


_ERROR_MESSAGES = {
    ParseErrorCode.INVALID_FORMAT: "source could not be parsed",
    ParseErrorCode.UNSAFE_ARCHIVE: "archive is unsafe",
    ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED: "archive limits exceeded",
    ParseErrorCode.UNSAFE_XML: "XML content is unsafe",
    ParseErrorCode.INVALID_FRONTMATTER: "frontmatter is invalid",
    ParseErrorCode.LIMIT_EXCEEDED: "parser limits exceeded",
}


class ParseError(RuntimeError):
    """Public parser failure with a stable code and redacted message."""

    def __init__(self, code: ParseErrorCode) -> None:
        if not isinstance(code, ParseErrorCode):
            raise TypeError("code must be a ParseErrorCode")
        self.code = code
        self.public_message = _ERROR_MESSAGES[code]
        super().__init__(self.public_message)


class ParsedBlockKind(StrEnum):
    """Ordered native block types shared by source formats."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    kind: ParsedBlockKind
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


def _validate_pdf_limits(
    *,
    max_pages: int,
    max_page_text_chars: int,
    max_total_text_chars: int,
    max_blocks: int,
) -> None:
    limits = (max_pages, max_page_text_chars, max_total_text_chars, max_blocks)
    if any(isinstance(limit, bool) or not isinstance(limit, int) for limit in limits):
        raise ValueError("PDF limits must be integers")
    if max_pages < 1 or max_page_text_chars < 1 or max_total_text_chars < 1:
        raise ValueError("PDF limits must be positive")
    if max_blocks < 0:
        raise ValueError("max_blocks must be non-negative")


def _preflight_pdf_page_tree(reader: PdfReader, *, max_pages: int) -> int:
    try:
        catalog_reference = reader.trailer.raw_get("/Root")
        catalog = catalog_reference.get_object()
        if not isinstance(catalog, DictionaryObject):
            _raise(ParseErrorCode.INVALID_FORMAT)
        root = catalog.raw_get("/Pages")
    except ParseError:
        raise
    except Exception:
        _raise(ParseErrorCode.INVALID_FORMAT)

    stack: list[tuple[object, int]] = [(root, 0)]
    seen_references: set[tuple[int, int]] = set()
    seen_direct: set[int] = set()
    page_count = 0
    node_count = 0
    max_nodes = max_pages * 4 + 16
    while stack:
        candidate, depth = stack.pop()
        if depth > _MAX_PDF_PAGE_TREE_DEPTH:
            _raise(ParseErrorCode.LIMIT_EXCEEDED)
        if isinstance(candidate, IndirectObject):
            key = (candidate.idnum, candidate.generation)
            if key in seen_references:
                _raise(ParseErrorCode.LIMIT_EXCEEDED)
            seen_references.add(key)
            node = candidate.get_object()
        else:
            node = candidate.get_object() if hasattr(candidate, "get_object") else candidate
            identity = id(node)
            if identity in seen_direct:
                _raise(ParseErrorCode.LIMIT_EXCEEDED)
            seen_direct.add(identity)
        node_count += 1
        if node_count > max_nodes:
            _raise(ParseErrorCode.LIMIT_EXCEEDED)
        if not isinstance(node, DictionaryObject):
            _raise(ParseErrorCode.INVALID_FORMAT)
        node_type = node.get("/Type")
        if node_type == "/Page":
            page_count += 1
            if page_count > max_pages:
                _raise(ParseErrorCode.LIMIT_EXCEEDED)
            continue
        if node_type != "/Pages":
            _raise(ParseErrorCode.INVALID_FORMAT)
        declared_count = node.get("/Count")
        if (
            isinstance(declared_count, bool)
            or not isinstance(declared_count, int)
            or declared_count < 0
        ):
            _raise(ParseErrorCode.INVALID_FORMAT)
        if declared_count > max_pages:
            _raise(ParseErrorCode.LIMIT_EXCEEDED)
        try:
            kids = node.raw_get("/Kids")
        except Exception:
            _raise(ParseErrorCode.INVALID_FORMAT)
        if not isinstance(kids, ArrayObject) or not kids:
            _raise(ParseErrorCode.INVALID_FORMAT)
        if len(kids) > max_nodes - node_count - len(stack):
            _raise(ParseErrorCode.LIMIT_EXCEEDED)
        for kid in reversed(kids):
            if not isinstance(kid, IndirectObject | DictionaryObject):
                _raise(ParseErrorCode.INVALID_FORMAT)
            stack.append((kid, depth + 1))
    if page_count == 0:
        _raise(ParseErrorCode.INVALID_FORMAT)
    return page_count


def parse_pdf(
    data: bytes,
    *,
    source_name: str = "document.pdf",
    max_pages: int = _DEFAULT_MAX_PDF_PAGES,
    max_page_text_chars: int = _DEFAULT_MAX_PDF_PAGE_TEXT_CHARS,
    max_total_text_chars: int = _DEFAULT_MAX_PDF_TOTAL_TEXT_CHARS,
    max_blocks: int = _DEFAULT_MAX_PDF_BLOCKS,
) -> ParsedDocument:
    """Extract bounded native PDF text after a bounded page-tree preflight."""

    _validate_pdf_limits(
        max_pages=max_pages,
        max_page_text_chars=max_page_text_chars,
        max_total_text_chars=max_total_text_chars,
        max_blocks=max_blocks,
    )
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            _raise(ParseErrorCode.INVALID_FORMAT)
        page_count = _preflight_pdf_page_tree(reader, max_pages=max_pages)
        pages: list[ParsedPage] = []
        all_blocks: list[ParsedBlock] = []
        total_text_chars = 0
        for page_index in range(page_count):
            page_number = page_index + 1
            page = reader.get_page(page_index)
            text = page.extract_text() or ""
            if len(text) > max_page_text_chars:
                _raise(ParseErrorCode.LIMIT_EXCEEDED)
            total_text_chars += len(text)
            if total_text_chars > max_total_text_chars:
                _raise(ParseErrorCode.LIMIT_EXCEEDED)
            blocks: list[ParsedBlock] = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if len(all_blocks) + len(blocks) >= max_blocks:
                    _raise(ParseErrorCode.LIMIT_EXCEEDED)
                order = len(blocks)
                blocks.append(
                    ParsedBlock(
                        kind=ParsedBlockKind.PARAGRAPH,
                        text=line,
                        order=order,
                        source_pointer=(
                            f"{source_name}#page={page_number}&block={order + 1}"
                        ),
                        page_number=page_number,
                    )
                )
            frozen_blocks = tuple(blocks)
            pages.append(
                ParsedPage(
                    page_number=page_number,
                    blocks=frozen_blocks,
                    needs_ocr=_looks_like_ocr_candidate(text),
                )
            )
            all_blocks.extend(frozen_blocks)
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
    max_path_bytes: int,
    max_total_path_bytes: int,
    max_path_depth: int,
) -> None:
    integer_limits = (
        max_files,
        max_uncompressed_bytes,
        max_member_bytes,
        max_path_bytes,
        max_total_path_bytes,
        max_path_depth,
    )
    if (
        any(
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
            for limit in integer_limits
        )
        or isinstance(max_compression_ratio, bool)
        or not isinstance(max_compression_ratio, int | float)
        or not math.isfinite(max_compression_ratio)
        or max_compression_ratio < 1
    ):
        raise ValueError("archive limits must be positive finite values")


def _preflight_classic_zip(data: bytes, *, max_entries: int) -> tuple[bytes, int]:
    raw = data if isinstance(data, bytes) else bytes(data)
    if len(raw) < 22:
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    eocd = raw.rfind(b"PK\x05\x06", max(0, len(raw) - 65_557))
    if eocd < 0 or eocd + 22 > len(raw):
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    try:
        (
            disk_number,
            central_disk,
            disk_entries,
            total_entries,
            central_size,
            central_offset,
            comment_length,
        ) = struct.unpack_from("<4H2LH", raw, eocd + 4)
    except struct.error:
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    if eocd + 22 + comment_length != len(raw):
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    if (
        disk_number != 0
        or central_disk != 0
        or disk_entries != total_entries
        or total_entries == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
        or central_offset + central_size != eocd
    ):
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    if b"PK\x06\x07" in raw[max(0, eocd - 20) : eocd]:
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    if total_entries and raw[central_offset : central_offset + 4] != b"PK\x01\x02":
        _raise(ParseErrorCode.UNSAFE_ARCHIVE)
    if total_entries > max_entries:
        _raise(ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED)
    return raw, total_entries


def _read_archive(
    data: bytes,
    *,
    keep_suffixes: tuple[str, ...],
    max_files: int,
    max_uncompressed_bytes: int,
    max_member_bytes: int,
    max_compression_ratio: float,
    max_path_bytes: int = _DEFAULT_MAX_PATH_BYTES,
    max_total_path_bytes: int = _DEFAULT_MAX_TOTAL_PATH_BYTES,
    max_path_depth: int = _DEFAULT_MAX_PATH_DEPTH,
    max_kept_member_bytes: int | None = None,
    max_kept_total_bytes: int | None = None,
) -> _ArchiveContents:
    _validate_archive_limits(
        max_files=max_files,
        max_uncompressed_bytes=max_uncompressed_bytes,
        max_member_bytes=max_member_bytes,
        max_compression_ratio=max_compression_ratio,
        max_path_bytes=max_path_bytes,
        max_total_path_bytes=max_total_path_bytes,
        max_path_depth=max_path_depth,
    )
    if (max_kept_member_bytes is None) != (max_kept_total_bytes is None):
        raise ValueError("kept member limits must be provided together")
    if max_kept_member_bytes is not None and (
        isinstance(max_kept_member_bytes, bool)
        or not isinstance(max_kept_member_bytes, int)
        or max_kept_member_bytes < 1
        or isinstance(max_kept_total_bytes, bool)
        or not isinstance(max_kept_total_bytes, int)
        or max_kept_total_bytes < 1
    ):
        raise ValueError("kept member limits must be positive integers")
    raw, declared_entries = _preflight_classic_zip(data, max_entries=max_files)
    suffixes = tuple(suffix.casefold() for suffix in keep_suffixes)
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) != declared_entries:
                _raise(ParseErrorCode.UNSAFE_ARCHIVE)
            entries: list[_ArchiveEntry] = []
            seen_paths: set[str] = set()
            declared_total = 0
            declared_kept_total = 0
            total_path_bytes = 0
            for info in infos:
                is_directory = info.is_dir()
                path = _normalize_archive_path(info.orig_filename, is_directory=is_directory)
                if path in seen_paths:
                    _raise(ParseErrorCode.UNSAFE_ARCHIVE)
                seen_paths.add(path)
                path_bytes = len(path.encode("utf-8"))
                total_path_bytes += path_bytes
                if (
                    path_bytes > max_path_bytes
                    or total_path_bytes > max_total_path_bytes
                    or len(path.split("/")) > max_path_depth
                ):
                    _raise(ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED)
                if info.flag_bits & 0x1 or _is_symlink(info):
                    _raise(ParseErrorCode.UNSAFE_ARCHIVE)
                entries.append(_ArchiveEntry(info=info, path=path, is_directory=is_directory))
                if is_directory:
                    continue
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
                if path.casefold().endswith(suffixes) and max_kept_member_bytes is not None:
                    if info.file_size > max_kept_member_bytes:
                        _raise(ParseErrorCode.LIMIT_EXCEEDED)
                    declared_kept_total += info.file_size
                    if declared_kept_total > max_kept_total_bytes:
                        _raise(ParseErrorCode.LIMIT_EXCEEDED)

            kept: list[tuple[str, bytes]] = []
            actual_total = 0
            actual_kept_total = 0
            for entry in entries:
                if entry.is_directory:
                    continue
                keep = entry.path.casefold().endswith(suffixes)
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
                        if keep:
                            actual_kept_total += len(chunk)
                            if (
                                max_kept_member_bytes is not None
                                and (
                                    actual_member > max_kept_member_bytes
                                    or actual_kept_total > max_kept_total_bytes
                                )
                            ):
                                _raise(ParseErrorCode.LIMIT_EXCEEDED)
                            member.extend(chunk)
                if actual_member != entry.info.file_size:
                    _raise(ParseErrorCode.UNSAFE_ARCHIVE)
                if keep:
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
                    kind=ParsedBlockKind.HEADING if heading_level else ParsedBlockKind.PARAGRAPH,
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
                    kind=ParsedBlockKind.TABLE,
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


def _validate_markdown_limits(
    *,
    max_lines: int,
    max_blocks: int,
    max_tags: int,
    max_wikilinks: int,
    max_line_chars: int,
) -> None:
    limits = (max_lines, max_blocks, max_tags, max_wikilinks, max_line_chars)
    if any(
        isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        for limit in limits
    ):
        raise ValueError("Markdown limits must be non-negative integers")


def _collect_wikilinks(
    lines: list[str], source_name: str, start_index: int, *, max_wikilinks: int
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
            if len(links) >= max_wikilinks:
                _raise(ParseErrorCode.LIMIT_EXCEEDED)
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


def _append_unique(
    values: list[str], seen: set[str], candidate: str, *, max_values: int
) -> None:
    normalized = unicodedata.normalize("NFC", candidate.strip().lstrip("#"))
    if not normalized or normalized in seen:
        return
    if len(values) >= max_values:
        _raise(ParseErrorCode.LIMIT_EXCEEDED)
    seen.add(normalized)
    values.append(normalized)


def _parse_markdown(
    data: bytes,
    *,
    source_name: str,
    max_lines: int,
    max_blocks: int,
    max_tags: int,
    max_wikilinks: int,
    max_line_chars: int,
) -> tuple[ParsedDocument, int]:
    _validate_markdown_limits(
        max_lines=max_lines,
        max_blocks=max_blocks,
        max_tags=max_tags,
        max_wikilinks=max_wikilinks,
        max_line_chars=max_line_chars,
    )
    try:
        text = data.decode("utf-8-sig")
    except (AttributeError, UnicodeDecodeError):
        _raise(ParseErrorCode.INVALID_FORMAT)
    lines = text.splitlines()
    if len(lines) > max_lines or any(len(line) > max_line_chars for line in lines):
        _raise(ParseErrorCode.LIMIT_EXCEEDED)
    body_start, frontmatter, frontmatter_tags = _parse_frontmatter(lines)
    tags: list[str] = []
    seen_tags: set[str] = set()
    for tag in frontmatter_tags:
        _append_unique(tags, seen_tags, tag, max_values=max_tags)
    for line in lines[body_start:]:
        for match in _INLINE_TAG.finditer(line):
            _append_unique(tags, seen_tags, match.group(1), max_values=max_tags)

    blocks: list[ParsedBlock] = []
    index = body_start
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        heading = _MARKDOWN_HEADING.fullmatch(lines[index])
        if heading:
            if len(blocks) >= max_blocks:
                _raise(ParseErrorCode.LIMIT_EXCEEDED)
            line_number = index + 1
            blocks.append(
                ParsedBlock(
                    kind=ParsedBlockKind.HEADING,
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
            if len(blocks) >= max_blocks:
                _raise(ParseErrorCode.LIMIT_EXCEEDED)
            line_start = start + 1
            line_end = index
            table = tuple(rows)
            blocks.append(
                ParsedBlock(
                    kind=ParsedBlockKind.TABLE,
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
                _MARKDOWN_HEADING.fullmatch(lines[index])
                or _is_markdown_table(lines, index)
            ):
                break
            paragraph_lines.append(lines[index].strip())
            index += 1
        if len(blocks) >= max_blocks:
            _raise(ParseErrorCode.LIMIT_EXCEEDED)
        line_start = start + 1
        line_end = start + len(paragraph_lines)
        blocks.append(
            ParsedBlock(
                kind=ParsedBlockKind.PARAGRAPH,
                text="\n".join(paragraph_lines),
                order=len(blocks),
                source_pointer=_source_pointer(source_name, line_start, line_end),
                line_start=line_start,
                line_end=line_end,
            )
        )

    document = ParsedDocument(
        source_name=source_name,
        media_type="text/markdown",
        blocks=tuple(blocks),
        frontmatter=frontmatter,
        tags=tuple(tags),
        wikilinks=_collect_wikilinks(
            lines, source_name, body_start, max_wikilinks=max_wikilinks
        ),
    )
    return document, len(lines)


def parse_markdown(
    data: bytes,
    *,
    source_name: str = "document.md",
    max_lines: int = _DEFAULT_MAX_MARKDOWN_LINES,
    max_blocks: int = _DEFAULT_MAX_MARKDOWN_BLOCKS,
    max_tags: int = _DEFAULT_MAX_MARKDOWN_TAGS,
    max_wikilinks: int = _DEFAULT_MAX_MARKDOWN_WIKILINKS,
    max_line_chars: int = _DEFAULT_MAX_MARKDOWN_LINE_CHARS,
) -> ParsedDocument:
    """Parse Markdown with bounded ordered output and exact source lines."""

    document, _ = _parse_markdown(
        data,
        source_name=source_name,
        max_lines=max_lines,
        max_blocks=max_blocks,
        max_tags=max_tags,
        max_wikilinks=max_wikilinks,
        max_line_chars=max_line_chars,
    )
    return document


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
    max_path_bytes: int = _DEFAULT_MAX_PATH_BYTES,
    max_total_path_bytes: int = _DEFAULT_MAX_TOTAL_PATH_BYTES,
    max_path_depth: int = _DEFAULT_MAX_PATH_DEPTH,
    max_markdown_member_bytes: int = _DEFAULT_MAX_MARKDOWN_MEMBER_BYTES,
    max_total_markdown_bytes: int = _DEFAULT_MAX_TOTAL_MARKDOWN_BYTES,
    max_lines: int = _DEFAULT_MAX_MARKDOWN_LINES,
    max_blocks: int = _DEFAULT_MAX_MARKDOWN_BLOCKS,
    max_tags: int = _DEFAULT_MAX_MARKDOWN_TAGS,
    max_wikilinks: int = _DEFAULT_MAX_MARKDOWN_WIKILINKS,
    max_line_chars: int = _DEFAULT_MAX_MARKDOWN_LINE_CHARS,
) -> VaultParseResult:
    """Parse a bounded Vault; max_files counts every ZIP entry."""

    _validate_markdown_limits(
        max_lines=max_lines,
        max_blocks=max_blocks,
        max_tags=max_tags,
        max_wikilinks=max_wikilinks,
        max_line_chars=max_line_chars,
    )
    contents = _read_archive(
        data,
        keep_suffixes=(".md",),
        max_files=max_files,
        max_uncompressed_bytes=max_uncompressed_bytes,
        max_member_bytes=max_uncompressed_bytes,
        max_compression_ratio=max_compression_ratio,
        max_path_bytes=max_path_bytes,
        max_total_path_bytes=max_total_path_bytes,
        max_path_depth=max_path_depth,
        max_kept_member_bytes=max_markdown_member_bytes,
        max_kept_total_bytes=max_total_markdown_bytes,
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
    total_lines = 0
    total_blocks = 0
    total_tags = 0
    for path in note_paths:
        document, line_count = _parse_markdown(
            note_bytes[path],
            source_name=path,
            max_lines=max_lines - total_lines,
            max_blocks=max_blocks - total_blocks,
            max_tags=max_tags - total_tags,
            max_wikilinks=max_wikilinks - len(all_links),
            max_line_chars=max_line_chars,
        )
        total_lines += line_count
        total_blocks += len(document.blocks)
        total_tags += len(document.tags)
        attachment_links: list[str] = []
        seen_attachment_links: set[str] = set()
        for link in document.wikilinks:
            resolved = _resolve_vault_link(path, link.target)
            if resolved in attachment_paths and resolved not in seen_attachment_links:
                seen_attachment_links.add(resolved)
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
    "ParsedBlockKind",
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
