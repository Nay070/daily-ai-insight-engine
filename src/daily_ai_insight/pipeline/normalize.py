"""Normalize curated records and generate stable content hashes."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime

from daily_ai_insight.domain.models import RawNewsItem, SourceItemInput

WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Apply Unicode NFKC and collapse all whitespace to single spaces."""

    normalized = unicodedata.normalize("NFKC", value)
    return WHITESPACE.sub(" ", normalized).strip()


def calculate_content_hash(*, title: str, content: str) -> str:
    """Hash normalized title and content using an explicit separator."""

    canonical = f"{normalize_text(title)}\n{normalize_text(content)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def materialize_raw_item(item: SourceItemInput, *, collected_at: datetime) -> RawNewsItem:
    """Convert one curated record into the immutable normalized raw contract."""

    title = normalize_text(item.title)
    content = normalize_text(item.content)
    payload = item.model_dump()
    payload.update(
        {
            "title": title,
            "content": content,
            "collected_at": collected_at,
            "content_hash": calculate_content_hash(title=title, content=content),
        }
    )
    return RawNewsItem.model_validate(payload)

