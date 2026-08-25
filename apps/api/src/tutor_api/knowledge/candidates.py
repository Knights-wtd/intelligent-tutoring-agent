"""Review-only knowledge candidate graph contracts."""

from enum import StrEnum


class CandidateNoteKind(StrEnum):
    CHAPTER = "chapter"
    SECTION = "section"
    SUBSECTION = "subsection"
    CONCEPT = "concept"
    PROPERTY = "property"
    FORMULA = "formula"
    METHOD = "method"
    EXAMPLE = "example"


class CandidateLinkKind(StrEnum):
    STRUCTURE = "structure"
    TERM = "term"
