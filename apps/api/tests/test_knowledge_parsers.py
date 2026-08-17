from __future__ import annotations

import binascii
import struct
import unicodedata
import zipfile
import zlib
from io import BytesIO

import pytest

from tutor_api.knowledge.parsers import (
    ParsedBlockKind,
    ParsedPage,
    ParseError,
    ParseErrorCode,
    parse_docx,
    parse_jpeg,
    parse_markdown,
    parse_obsidian_vault_zip,
    parse_pdf,
    parse_png,
)


def make_pdf() -> bytes:
    content = (
        b"BT /F1 12 Tf 72 720 Td (Native PDF text is long enough to parse.) Tj "
        b"0 -24 Td (Second ordered block remains on page one.) Tj ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>"
        ),
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def make_single_page_pdf(text: str) -> bytes:
    encoded = text.encode("cp1252")
    literal = b"".join(f"\\{byte:03o}".encode() for byte in encoded)
    content = b"BT /F1 12 Tf 72 720 Td (" + literal + b") Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def make_docx_from_xml(document_xml: bytes) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr("word/document.xml", document_xml)
    return output.getvalue()


def make_docx(*, dangerous_xml: bool = False) -> bytes:
    prefix = (
        '<!DOCTYPE w:document [<!ENTITY leak SYSTEM "file:///secret">]>'
        if dangerous_xml
        else ""
    )
    document_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
{prefix}
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Chapter One</w:t></w:r></w:p>
    <w:p><w:r><w:t>First paragraph.</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>2</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
    <w:p><w:r><w:t>Last paragraph.</w:t></w:r></w:p>
  </w:body>
</w:document>'''.encode()
    return make_docx_from_xml(document_xml)


def png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = binascii.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def make_png(
    width: int = 3,
    height: int = 2,
    *,
    idat: bytes | None = None,
    interlace: int = 0,
) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, interlace)
    raw_rows = b"".join(b"\x00" + (b"\x00\x00\x00" * width) for _ in range(height))
    image_data = zlib.compress(raw_rows) if idat is None else idat
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", image_data)
        + png_chunk(b"IEND", b"")
    )


def make_zip(entries: list[tuple[str | zipfile.ZipInfo, bytes]]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


def patch_zip_filename(data: bytes, safe_name: str, unsafe_name: str) -> bytes:
    safe = safe_name.encode()
    unsafe = unsafe_name.encode()
    assert len(safe) == len(unsafe)
    assert data.count(safe) == 2
    return data.replace(safe, unsafe)


def patch_zip64_eocd_sentinel(data: bytes) -> bytes:
    patched = bytearray(data)
    eocd = patched.rfind(b"PK\x05\x06")
    assert eocd >= 0
    struct.pack_into("<H", patched, eocd + 8, 0xFFFF)
    struct.pack_into("<H", patched, eocd + 10, 0xFFFF)
    return bytes(patched)


def patch_zip_encrypted(data: bytes) -> bytes:
    patched = bytearray(data)
    local = patched.find(b"PK\x03\x04")
    central = patched.find(b"PK\x01\x02")
    assert local >= 0 and central >= 0
    local_flags = struct.unpack_from("<H", patched, local + 6)[0] | 0x1
    central_flags = struct.unpack_from("<H", patched, central + 8)[0] | 0x1
    struct.pack_into("<H", patched, local + 6, local_flags)
    struct.pack_into("<H", patched, central + 8, central_flags)
    return bytes(patched)


def test_pdf_preserves_pages_order_and_marks_only_low_text_page_for_ocr() -> None:
    parsed = parse_pdf(make_pdf(), source_name="lesson.pdf")

    assert [page.page_number for page in parsed.pages] == [1, 2]
    assert [block.text for block in parsed.pages[0].blocks] == [
        "Native PDF text is long enough to parse.",
        "Second ordered block remains on page one.",
    ]
    assert [block.order for block in parsed.pages[0].blocks] == [0, 1]
    assert parsed.pages[0].needs_ocr is False
    assert parsed.pages[1].needs_ocr is True
    assert parsed.needs_ocr is True
    assert [block.page_number for block in parsed.blocks] == [1, 1]


def test_garbled_pdf_page_is_marked_for_ocr_through_public_parser() -> None:
    mojibake = (
        "Readable native paragraph with enough text 1234567890 "
        "ÃƒÂ© ÃƒÂ¶ Ã¢â‚¬â„¢ ÃƒÂ±"
    )

    parsed = parse_pdf(make_single_page_pdf(mojibake), source_name="garbled.pdf")

    extracted = parsed.pages[0].blocks[0].text
    assert sum(character.isalnum() for character in extracted) >= 20
    assert sum(unicodedata.category(character) == "Cc" for character in extracted) >= 3
    assert parsed.pages[0].needs_ocr is True


def test_pdf_failures_use_stable_public_error() -> None:
    with pytest.raises(ParseError) as raised:
        parse_pdf(b"not a PDF and /internal/secret", source_name="broken.pdf")

    assert raised.value.code is ParseErrorCode.INVALID_FORMAT
    assert raised.value.public_message == "source could not be parsed"
    assert "secret" not in str(raised.value)


def test_docx_preserves_heading_paragraph_table_order() -> None:
    parsed = parse_docx(make_docx(), source_name="lesson.docx")

    assert [block.kind for block in parsed.blocks] == [
        ParsedBlockKind.HEADING,
        ParsedBlockKind.PARAGRAPH,
        ParsedBlockKind.TABLE,
        ParsedBlockKind.PARAGRAPH,
    ]
    assert [block.text for block in parsed.blocks] == [
        "Chapter One",
        "First paragraph.",
        "A | B\n1 | 2",
        "Last paragraph.",
    ]
    assert parsed.blocks[0].heading_level == 1
    assert parsed.blocks[2].table == (("A", "B"), ("1", "2"))
    assert dict(parsed.blocks[2].metadata) == {"columns": 2, "rows": 2}


def test_docx_rejects_dtd_without_leaking_parser_details() -> None:
    with pytest.raises(ParseError) as raised:
        parse_docx(make_docx(dangerous_xml=True), source_name="danger.docx")

    assert raised.value.code is ParseErrorCode.UNSAFE_XML
    assert str(raised.value) == "XML content is unsafe"
    assert "file:///secret" not in str(raised.value)


def test_docx_rejects_utf16_dangerous_xml_before_entity_expansion() -> None:
    xml = """<?xml version="1.0" encoding="UTF-16"?>
<!DOCTYPE w:document [<!ENTITY expanded "EXPANDED SECRET">]>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>&expanded;</w:t></w:r></w:p></w:body>
</w:document>""".encode("utf-16")

    with pytest.raises(ParseError) as raised:
        parse_docx(make_docx_from_xml(xml), source_name="utf16-danger.docx")

    assert raised.value.code is ParseErrorCode.UNSAFE_XML
    assert "EXPANDED SECRET" not in str(raised.value)


def test_markdown_retains_frontmatter_tags_tables_wikilinks_and_line_ranges() -> None:
    markdown = """---
title: Algebra
tags:
  - math
  - algebra
---
# Intro
First paragraph with #geometry and [[assets/diagram.png|diagram]].
continues here.

| A | B |
|---|---|
| 1 | 2 |

## Next
See [[Other Note]].
"""

    parsed = parse_markdown(markdown.encode(), source_name="notes/algebra.md")

    assert dict(parsed.frontmatter) == {
        "tags": ("math", "algebra"),
        "title": "Algebra",
    }
    assert parsed.tags == ("math", "algebra", "geometry")
    assert [block.kind for block in parsed.blocks] == [
        ParsedBlockKind.HEADING,
        ParsedBlockKind.PARAGRAPH,
        ParsedBlockKind.TABLE,
        ParsedBlockKind.HEADING,
        ParsedBlockKind.PARAGRAPH,
    ]
    paragraph = parsed.blocks[1]
    assert (paragraph.line_start, paragraph.line_end) == (8, 9)
    assert paragraph.source_pointer == "notes/algebra.md:L8-L9"
    assert parsed.blocks[2].table == (("A", "B"), ("1", "2"))
    assert (parsed.blocks[2].line_start, parsed.blocks[2].line_end) == (11, 13)
    assert [(link.target, link.alias, link.line_start) for link in parsed.wikilinks] == [
        ("assets/diagram.png", "diagram", 8),
        ("Other Note", None, 16),
    ]
    assert all(block.line_start > 6 for block in parsed.blocks)


def test_markdown_parses_pipe_less_table_with_exact_line_range() -> None:
    parsed = parse_markdown(
        b"Heading paragraph\n\nA | B\n--- | ---\n1 | 2\n",
        source_name="pipe-less.md",
    )

    table = parsed.blocks[1]
    assert table.kind is ParsedBlockKind.TABLE
    assert table.table == (("A", "B"), ("1", "2"))
    assert (table.line_start, table.line_end) == (3, 5)
    assert table.source_pointer == "pipe-less.md:L3-L5"


def test_markdown_rejects_non_mapping_frontmatter() -> None:
    with pytest.raises(ParseError) as raised:
        parse_markdown(b"---\n- unsafe\n- shape\n---\nbody\n", source_name="bad.md")

    assert raised.value.code is ParseErrorCode.INVALID_FRONTMATTER
    assert str(raised.value) == "frontmatter is invalid"




def test_jpeg_reads_dimensions_and_defers_ocr() -> None:
    jpeg = (
        b"\xff\xd8"
        + b"\xff\xc0\x00\x11\x08\x00\x02\x00\x03\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        + b"\xff\xd9"
    )

    parsed = parse_jpeg(jpeg, source_name="scan.jpg")

    assert parsed.media_type == "image/jpeg"
    assert parsed.pages == (ParsedPage(1, (), True, width=3, height=2),)


def test_jpeg_rejects_missing_frame_dimensions() -> None:
    with pytest.raises(ParseError, match="source could not be parsed"):
        parse_jpeg(b"\xff\xd8\xff\xd9")
def test_png_validates_structure_reads_dimensions_and_defers_ocr() -> None:
    parsed = parse_png(make_png(), source_name="scan.png")

    assert len(parsed.pages) == 1
    page = parsed.pages[0]
    assert (page.page_number, page.width, page.height) == (1, 3, 2)
    assert page.needs_ocr is True
    assert page.blocks == ()
    assert parsed.needs_ocr is True


def test_png_rejects_invalid_zlib_stream_and_unsupported_interlace() -> None:
    with pytest.raises(ParseError) as invalid_stream:
        parse_png(make_png(idat=b"not a zlib stream"), source_name="invalid-idat.png")
    assert invalid_stream.value.code is ParseErrorCode.INVALID_FORMAT

    with pytest.raises(ParseError) as interlaced:
        parse_png(make_png(interlace=1), source_name="interlaced.png")
    assert interlaced.value.code is ParseErrorCode.INVALID_FORMAT


def test_png_rejects_bad_chunk_crc() -> None:
    damaged = bytearray(make_png())
    damaged[-1] ^= 0xFF

    with pytest.raises(ParseError) as raised:
        parse_png(bytes(damaged), source_name="damaged.png")

    assert raised.value.code is ParseErrorCode.INVALID_FORMAT


def test_obsidian_vault_normalizes_paths_and_preserves_links_and_attachments() -> None:
    decomposed_note = "Notes/cafe\u0301.md"
    vault = make_zip(
        [
            (
                "Notes/Second.md",
                b"# Second\nSee [[caf\xc3\xa9]] and [[../assets/chart.png|chart]].\n",
            ),
            (
                decomposed_note,
                b"---\ntags: [vault]\n---\n# Cafe\nEmbed [[../assets/chart.png]].\n",
            ),
            ("assets/chart.png", make_png(1, 1)),
            ("assets/data.csv", b"x,y\n1,2\n"),
        ]
    )

    parsed = parse_obsidian_vault_zip(vault)

    assert [note.path for note in parsed.notes] == ["Notes/Second.md", "Notes/caf\u00e9.md"]
    assert [attachment.path for attachment in parsed.attachments] == [
        "assets/chart.png",
        "assets/data.csv",
    ]
    cafe = parsed.notes[1]
    assert cafe.document.tags == ("vault",)
    assert cafe.attachment_links == ("assets/chart.png",)
    assert [(link.source_path, link.target) for link in parsed.wikilinks] == [
        ("Notes/Second.md", "caf\u00e9"),
        ("Notes/Second.md", "../assets/chart.png"),
        ("Notes/caf\u00e9.md", "../assets/chart.png"),
    ]


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "/absolute.md",
        "C:/drive.md",
        "notes\\backslash.md",
        "notes//empty.md",
        "notes/../escape.md",
        "notes/./dot.md",
        "notes/nul\x00.md",
        "notes/control\x1f.md",
        "notes/zero\u200bwidth.md",
    ],
)
def test_obsidian_vault_rejects_unsafe_paths(unsafe_name: str) -> None:
    safe_name = unsafe_name.replace("\\", "/").replace("\x00", "x")
    vault = make_zip([(safe_name, b"# unsafe\n")])
    if safe_name != unsafe_name:
        vault = patch_zip_filename(vault, safe_name, unsafe_name)

    with pytest.raises(ParseError) as raised:
        parse_obsidian_vault_zip(vault)

    assert raised.value.code is ParseErrorCode.UNSAFE_ARCHIVE


def test_obsidian_vault_rejects_drive_relative_path() -> None:
    with pytest.raises(ParseError) as raised:
        parse_obsidian_vault_zip(make_zip([("C:relative.md", b"unsafe")]))

    assert raised.value.code is ParseErrorCode.UNSAFE_ARCHIVE


def test_obsidian_vault_rejects_duplicate_normalized_paths() -> None:
    vault = make_zip(
        [
            ("Notes/cafe\u0301.md", b"first"),
            ("Notes/caf\u00e9.md", b"second"),
        ]
    )

    with pytest.raises(ParseError) as raised:
        parse_obsidian_vault_zip(vault)

    assert raised.value.code is ParseErrorCode.UNSAFE_ARCHIVE


def test_obsidian_vault_rejects_symlink_and_encrypted_entries() -> None:
    symlink = zipfile.ZipInfo("link.md")
    symlink.create_system = 3
    symlink.external_attr = 0o120777 << 16

    with pytest.raises(ParseError) as symlink_error:
        parse_obsidian_vault_zip(make_zip([(symlink, b"target")]))
    assert symlink_error.value.code is ParseErrorCode.UNSAFE_ARCHIVE

    encrypted = patch_zip_encrypted(make_zip([("note.md", b"# encrypted")]))
    with pytest.raises(ParseError) as encrypted_error:
        parse_obsidian_vault_zip(encrypted)
    assert encrypted_error.value.code is ParseErrorCode.UNSAFE_ARCHIVE


def test_obsidian_vault_enforces_file_total_and_compression_ratio_limits() -> None:
    two_files = make_zip([("one.md", b"one"), ("two.md", b"two")])
    with pytest.raises(ParseError) as files_error:
        parse_obsidian_vault_zip(two_files, max_files=1)
    assert files_error.value.code is ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED

    too_large = make_zip([("large.md", b"x" * 128)])
    with pytest.raises(ParseError) as bytes_error:
        parse_obsidian_vault_zip(too_large, max_uncompressed_bytes=127)
    assert bytes_error.value.code is ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED

    bomb = make_zip([("bomb.bin", b"0" * 20_000)])
    with pytest.raises(ParseError) as ratio_error:
        parse_obsidian_vault_zip(bomb, max_compression_ratio=10)
    assert ratio_error.value.code is ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED


def test_docx_reuses_archive_guards_for_suspicious_members() -> None:
    docx = make_zip(
        [
            ("[Content_Types].xml", b"<Types/>"),
            ("word/document.xml", b"<document/>"),
            ("../escape.xml", b"secret"),
        ]
    )

    with pytest.raises(ParseError) as raised:
        parse_docx(docx, source_name="unsafe.docx")

    assert raised.value.code is ParseErrorCode.UNSAFE_ARCHIVE


def test_deep_yaml_recursion_is_redacted_as_invalid_frontmatter() -> None:
    depth = 1_200
    nested = "[" * depth + "value" + "]" * depth
    markdown = f"---\nvalue: {nested}\n---\nbody\n".encode()

    with pytest.raises(ParseError) as raised:
        parse_markdown(markdown, source_name="deep.md")

    assert raised.value.code is ParseErrorCode.INVALID_FRONTMATTER
    assert str(raised.value) == "frontmatter is invalid"


def test_frontmatter_values_are_deeply_immutable() -> None:
    parsed = parse_markdown(
        b"---\nsettings:\n  modes: [one, two]\n  nested:\n    enabled: true\n---\nbody\n",
        source_name="immutable.md",
    )

    settings = dict(parsed.frontmatter)["settings"]
    assert settings == (("modes", ("one", "two")), ("nested", (("enabled", True),)))
    assert isinstance(settings, tuple)


def test_vault_note_paths_are_nfc_and_posix() -> None:
    parsed = parse_obsidian_vault_zip(make_zip([("folder/cafe\u0301.md", b"body")]))

    assert parsed.notes[0].path == unicodedata.normalize("NFC", "folder/cafe\u0301.md")
    assert "\\" not in parsed.notes[0].path


def test_parser_block_kind_is_distinct_from_orm_block_kind() -> None:
    from tutor_api.knowledge import ParsedBlockKind
    from tutor_api.knowledge.models import BlockKind as ModelBlockKind

    assert ParsedBlockKind.PARAGRAPH.value == ModelBlockKind.PARAGRAPH.value
    assert ParsedBlockKind is not ModelBlockKind


def test_pdf_rejects_duplicate_page_reference_before_text_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pypdf._page import PageObject

    duplicate = make_pdf().replace(
        b"/Kids [3 0 R 5 0 R]", b"/Kids [3 0 R 3 0 R]"
    )
    extraction_calls: list[PageObject] = []

    def record_extract(page: PageObject, *args: object, **kwargs: object) -> str:
        extraction_calls.append(page)
        return "should not be extracted"

    monkeypatch.setattr(PageObject, "extract_text", record_extract)

    with pytest.raises(ParseError) as raised:
        parse_pdf(duplicate, max_pages=2)

    assert raised.value.code is ParseErrorCode.LIMIT_EXCEEDED
    assert extraction_calls == []


@pytest.mark.parametrize(
    ("limits", "pdf"),
    [
        ({"max_page_text_chars": 20}, make_single_page_pdf("x" * 40)),
        ({"max_total_text_chars": 50}, make_pdf()),
        ({"max_blocks": 1}, make_pdf()),
    ],
)
def test_pdf_enforces_text_and_block_budgets(
    limits: dict[str, int], pdf: bytes
) -> None:
    with pytest.raises(ParseError) as raised:
        parse_pdf(pdf, **limits)

    assert raised.value.code is ParseErrorCode.LIMIT_EXCEEDED
    assert str(raised.value) == "parser limits exceeded"


def test_zip_entry_limit_counts_directories() -> None:
    vault = make_zip([("folder/", b""), ("folder/note.md", b"body")])

    with pytest.raises(ParseError) as raised:
        parse_obsidian_vault_zip(vault, max_files=1)

    assert raised.value.code is ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED


def test_zip64_eocd_is_rejected_before_zipfile_parsing() -> None:
    vault = patch_zip64_eocd_sentinel(make_zip([("note.md", b"body")]))

    with pytest.raises(ParseError) as raised:
        parse_obsidian_vault_zip(vault)

    assert raised.value.code is ParseErrorCode.UNSAFE_ARCHIVE


@pytest.mark.parametrize(
    "limits",
    [
        {"max_path_bytes": 8},
        {"max_path_depth": 1},
        {"max_total_path_bytes": 8},
    ],
)
def test_vault_enforces_path_name_budgets(limits: dict[str, int]) -> None:
    vault = make_zip([("folder/note.md", b"body")])

    with pytest.raises(ParseError) as raised:
        parse_obsidian_vault_zip(vault, **limits)

    assert raised.value.code is ParseErrorCode.ARCHIVE_LIMIT_EXCEEDED


@pytest.mark.parametrize(
    ("markdown", "limits"),
    [
        (b"one\ntwo\n", {"max_lines": 1}),
        (b"long line\n", {"max_line_chars": 4}),
        (b"one\n\ntwo\n", {"max_blocks": 1}),
        (b"#one #two\n", {"max_tags": 1}),
        (b"[[one]] [[two]]\n", {"max_wikilinks": 1}),
    ],
)
def test_markdown_enforces_output_budgets(
    markdown: bytes, limits: dict[str, int]
) -> None:
    with pytest.raises(ParseError) as raised:
        parse_markdown(markdown, **limits)

    assert raised.value.code is ParseErrorCode.LIMIT_EXCEEDED


def test_markdown_tags_are_ordered_and_deduplicated() -> None:
    parsed = parse_markdown(
        b"---\ntags: [alpha, beta, alpha]\n---\n#beta #gamma #alpha\n"
    )

    assert parsed.tags == ("alpha", "beta", "gamma")


@pytest.mark.parametrize(
    "limits",
    [
        {"max_markdown_member_bytes": 3},
        {"max_total_markdown_bytes": 7},
    ],
)
def test_vault_enforces_markdown_byte_budgets(limits: dict[str, int]) -> None:
    vault = make_zip([("one.md", b"body"), ("two.md", b"body")])

    with pytest.raises(ParseError) as raised:
        parse_obsidian_vault_zip(vault, **limits)

    assert raised.value.code is ParseErrorCode.LIMIT_EXCEEDED


@pytest.mark.parametrize(
    ("entries", "limits"),
    [
        ([("one.md", b"body"), ("two.md", b"body")], {"max_lines": 1}),
        ([("one.md", b"body"), ("two.md", b"body")], {"max_blocks": 1}),
        ([("one.md", b"#one"), ("two.md", b"#two")], {"max_tags": 1}),
        (
            [("one.md", b"[[one]]"), ("two.md", b"[[two]]")],
            {"max_wikilinks": 1},
        ),
    ],
)
def test_vault_output_budgets_are_cumulative_across_notes(
    entries: list[tuple[str | zipfile.ZipInfo, bytes]], limits: dict[str, int]
) -> None:
    with pytest.raises(ParseError) as raised:
        parse_obsidian_vault_zip(make_zip(entries), **limits)

    assert raised.value.code is ParseErrorCode.LIMIT_EXCEEDED


def test_vault_rejects_large_central_directory_before_zipfile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = zipfile.ZipInfo("note.md")
    info.comment = b"c" * 256
    info.extra = b"\xfe\xca" + struct.pack("<H", 128) + b"x" * 128
    vault = make_zip([(info, b"body")])
    zipfile_calls: list[object] = []

    def record_zipfile(*args: object, **kwargs: object) -> object:
        zipfile_calls.append((args, kwargs))
        raise AssertionError("ZipFile must not be constructed")

    monkeypatch.setattr(
        "tutor_api.knowledge.parsers.zipfile.ZipFile", record_zipfile
    )

    with pytest.raises(ParseError) as raised:
        parse_obsidian_vault_zip(vault, max_central_directory_bytes=64)

    assert raised.value.code is ParseErrorCode.LIMIT_EXCEEDED
    assert zipfile_calls == []


@pytest.mark.parametrize("invalid_limit", [0, -1, True, 1.5])
def test_vault_rejects_invalid_central_directory_limit(
    invalid_limit: object,
) -> None:
    with pytest.raises(ValueError):
        parse_obsidian_vault_zip(
            make_zip([("note.md", b"body")]),
            max_central_directory_bytes=invalid_limit,  # type: ignore[arg-type]
        )
