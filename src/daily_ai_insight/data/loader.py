"""Load and validate the manually curated source dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import TypeAdapter

from daily_ai_insight.domain.models import Language, RawNewsItem, SourceItemInput, SourceType

SOURCE_ITEM_LIST = TypeAdapter(list[SourceItemInput])
RAW_ITEM_LIST = TypeAdapter(list[RawNewsItem])


@dataclass(frozen=True)
class DatasetCoverage:
    item_count: int
    source_types: frozenset[SourceType]
    languages: frozenset[Language]


def load_source_items(path: Path) -> list[SourceItemInput]:
    """Load UTF-8 JSON and validate every item against the input contract."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return SOURCE_ITEM_LIST.validate_python(payload)


def load_raw_items(path: Path) -> list[RawNewsItem]:
    """Load a UTF-8 JSONL file and validate every normalized source record."""

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return RAW_ITEM_LIST.validate_python(records)


def validate_dataset_coverage(
    items: list[SourceItemInput],
    *,
    report_date: date,
    min_items: int = 10,
    max_items: int = 20,
    min_source_types: int = 3,
) -> DatasetCoverage:
    """Apply dataset-level gates that cannot be expressed on one record."""

    if not min_items <= len(items) <= max_items:
        raise ValueError(f"dataset must contain {min_items}-{max_items} items")

    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("dataset item IDs must be unique")

    urls = [str(item.source_url) for item in items]
    if len(urls) != len(set(urls)):
        raise ValueError("dataset source URLs must be unique")

    future_items = [item.id for item in items if item.published_at.date() > report_date]
    if future_items:
        raise ValueError(f"dataset contains items after report date: {future_items}")

    source_types = frozenset(item.source_type for item in items)
    if len(source_types) < min_source_types:
        raise ValueError(f"dataset must contain at least {min_source_types} source types")

    languages = frozenset(item.language for item in items)
    if not {Language.ZH, Language.EN}.issubset(languages):
        raise ValueError("sample dataset must include both Chinese and English")

    return DatasetCoverage(
        item_count=len(items),
        source_types=source_types,
        languages=languages,
    )
