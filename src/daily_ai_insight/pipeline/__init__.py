"""Deterministic pipeline stages."""

from .deduplicate import DeduplicationResult, DuplicateRecord, exact_deduplicate
from .normalize import materialize_raw_item, normalize_text

__all__ = [
    "DeduplicationResult",
    "DuplicateRecord",
    "exact_deduplicate",
    "materialize_raw_item",
    "normalize_text",
]

