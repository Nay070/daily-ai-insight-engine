"""Deterministic exact deduplication for normalized source records."""

from __future__ import annotations

from dataclasses import dataclass

from daily_ai_insight.domain.models import RawNewsItem


@dataclass(frozen=True)
class DuplicateRecord:
    duplicate_item_id: str
    retained_item_id: str
    reason: str


@dataclass(frozen=True)
class DeduplicationResult:
    items: tuple[RawNewsItem, ...]
    duplicates: tuple[DuplicateRecord, ...]


def exact_deduplicate(items: list[RawNewsItem]) -> DeduplicationResult:
    """Keep the first item for each URL or normalized content hash."""

    retained: list[RawNewsItem] = []
    duplicates: list[DuplicateRecord] = []
    seen_urls: dict[str, str] = {}
    seen_hashes: dict[str, str] = {}

    for item in items:
        url = str(item.source_url)
        if url in seen_urls:
            duplicates.append(
                DuplicateRecord(
                    duplicate_item_id=item.id,
                    retained_item_id=seen_urls[url],
                    reason="same_source_url",
                )
            )
            continue

        if item.content_hash in seen_hashes:
            duplicates.append(
                DuplicateRecord(
                    duplicate_item_id=item.id,
                    retained_item_id=seen_hashes[item.content_hash],
                    reason="same_normalized_content",
                )
            )
            continue

        retained.append(item)
        seen_urls[url] = item.id
        seen_hashes[item.content_hash] = item.id

    return DeduplicationResult(items=tuple(retained), duplicates=tuple(duplicates))

