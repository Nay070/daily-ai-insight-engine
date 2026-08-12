"""Orchestrate the deterministic dataset preparation stage."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Any

from daily_ai_insight.data import load_source_items, validate_dataset_coverage
from daily_ai_insight.paths import portable_path
from daily_ai_insight.pipeline.candidates import generate_event_candidates
from daily_ai_insight.pipeline.deduplicate import exact_deduplicate
from daily_ai_insight.pipeline.normalize import materialize_raw_item
from daily_ai_insight.storage import write_json, write_jsonl


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_dataset(
    *,
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    report_date: date,
    collected_at: datetime,
    manifest_root: Path | None = None,
) -> dict[str, Any]:
    """Validate, normalize, deduplicate, persist, and describe one source dataset."""

    source_items = load_source_items(input_path)
    coverage = validate_dataset_coverage(source_items, report_date=report_date)
    normalized_items = [
        materialize_raw_item(item, collected_at=collected_at) for item in source_items
    ]
    deduplication = exact_deduplicate(normalized_items)
    event_candidates = generate_event_candidates(deduplication.items)

    write_jsonl(output_path, deduplication.items)
    manifest: dict[str, Any] = {
        "stage": "prepare",
        "report_date": report_date.isoformat(),
        "collected_at": collected_at.isoformat(),
        "input_path": portable_path(input_path, manifest_root),
        "input_sha256": sha256_file(input_path),
        "output_path": portable_path(output_path, manifest_root),
        "input_count": coverage.item_count,
        "output_count": len(deduplication.items),
        "duplicate_count": len(deduplication.duplicates),
        "duplicates": [duplicate.__dict__ for duplicate in deduplication.duplicates],
        "event_candidate_count": len(event_candidates),
        "event_candidates": [candidate.__dict__ for candidate in event_candidates],
        "source_types": sorted(source_type.value for source_type in coverage.source_types),
        "languages": sorted(language.value for language in coverage.languages),
        "schema_version": "1.0",
    }
    write_json(manifest_path, manifest)
    return manifest
