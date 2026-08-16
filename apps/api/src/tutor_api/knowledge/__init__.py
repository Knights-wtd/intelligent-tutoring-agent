"""Runtime boundaries for knowledge ingestion and indexing."""

from tutor_api.knowledge.embeddings import EmbeddingAdapter, HashEmbeddingAdapter
from tutor_api.knowledge.ocr import DisabledOCRAdapter, OCRAdapter, OCRError
from tutor_api.knowledge.storage import (
    MemoryObjectStorage,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    ObjectStorage,
    StoredObject,
    build_document_object_key,
)

__all__ = [
    "DisabledOCRAdapter",
    "EmbeddingAdapter",
    "HashEmbeddingAdapter",
    "MemoryObjectStorage",
    "OCRAdapter",
    "OCRError",
    "ObjectAlreadyExistsError",
    "ObjectNotFoundError",
    "ObjectStorage",
    "StoredObject",
    "build_document_object_key",
]
