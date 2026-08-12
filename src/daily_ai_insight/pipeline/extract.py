"""Batch orchestration for bounded, auditable per-item model extraction."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic_ai import Agent

from daily_ai_insight.ai.extractor import (
    EXTRACTION_PROMPT_VERSION,
    ExtractionDependencies,
    ExtractionRunError,
    InsightPayload,
    extract_one,
)
from daily_ai_insight.data import load_raw_items
from daily_ai_insight.paths import portable_path
from daily_ai_insight.pipeline.prepare import sha256_file
from daily_ai_insight.storage import write_json, write_jsonl


def extract_dataset(
    *,
    agent: Agent[ExtractionDependencies, InsightPayload],
    input_path: Path,
    output_path: Path,
    model_runs_dir: Path,
    trace_path: Path,
    quarantine_path: Path,
    manifest_path: Path,
    model_name: str,
    extracted_at: datetime,
    resume: bool = False,
    attempt_index: int = 1,
    attempt_manifest_path: Path | None = None,
    source_input_sha256: str | None = None,
    manifest_root: Path | None = None,
) -> dict[str, Any]:
    """Extract each item independently and retain model messages, traces, and failures.

    When ``resume`` is enabled, already-valid insights are retained and only missing
    items are sent to the model again. Outputs are checkpointed after every item so an
    interrupted batch can continue without paying for successful calls twice.
    """

    started_clock = perf_counter()
    items = load_raw_items(input_path)
    item_ids = {item.id for item in items}
    insights_by_id = {
        insight.item_id: insight
        for insight in (load_existing_insights(output_path) if resume else [])
    }
    unknown_existing = sorted(set(insights_by_id) - item_ids)
    if unknown_existing:
        raise ValueError(f"existing insights reference unknown input items: {unknown_existing}")

    traces = load_jsonl_records(trace_path) if resume else []
    failures_by_id = {
        record["item_id"]: record
        for record in (load_jsonl_records(quarantine_path) if resume else [])
        if isinstance(record.get("item_id"), str)
    }
    usage: Counter[str] = Counter()
    if resume and manifest_path.is_file():
        previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        usage.update(previous_manifest.get("usage", {}))
    current_run_usage: Counter[str] = Counter()
    model_runs_dir.mkdir(parents=True, exist_ok=True)
    attempted_count = 0
    resumed_count = len(insights_by_id)

    for item in items:
        if item.id in insights_by_id:
            continue
        attempted_count += 1
        failures_by_id.pop(item.id, None)
        try:
            run = extract_one(
                agent,
                item,
                model_name=model_name,
                extracted_at=extracted_at,
            )
        except Exception as error:  # noqa: BLE001 - quarantine is the batch boundary
            if isinstance(error, ExtractionRunError):
                traces.extend(error.trace)
                error_type = error.original_type
            else:
                error_type = type(error).__name__
            failures_by_id[item.id] = {
                "item_id": item.id,
                "error_type": error_type,
                "message": str(error),
            }
            checkpoint_outputs(
                items=items,
                insights_by_id=insights_by_id,
                traces=traces,
                failures_by_id=failures_by_id,
                output_path=output_path,
                trace_path=trace_path,
                quarantine_path=quarantine_path,
            )
            continue

        traces.extend(run.trace)
        for field in (
            "input_tokens",
            "cache_write_tokens",
            "cache_read_tokens",
            "output_tokens",
            "requests",
            "tool_calls",
        ):
            value = int(run.usage.get(field, 0))
            usage[field] += value
            current_run_usage[field] += value
        write_json(
            model_runs_dir / f"{item.id}.messages.json",
            json.loads(run.message_history_json),
        )
        if run.insight.confidence < 0.60:
            failures_by_id[item.id] = {
                "item_id": item.id,
                "error_type": "LowConfidence",
                "message": (
                    f"confidence {run.insight.confidence:.2f} is below the 0.60 gate"
                ),
            }
            checkpoint_outputs(
                items=items,
                insights_by_id=insights_by_id,
                traces=traces,
                failures_by_id=failures_by_id,
                output_path=output_path,
                trace_path=trace_path,
                quarantine_path=quarantine_path,
            )
            continue
        insights_by_id[item.id] = run.insight
        checkpoint_outputs(
            items=items,
            insights_by_id=insights_by_id,
            traces=traces,
            failures_by_id=failures_by_id,
            output_path=output_path,
            trace_path=trace_path,
            quarantine_path=quarantine_path,
        )

    insights = [insights_by_id[item.id] for item in items if item.id in insights_by_id]
    failures = [failures_by_id[item.id] for item in items if item.id in failures_by_id]
    checkpoint_outputs(
        items=items,
        insights_by_id=insights_by_id,
        traces=traces,
        failures_by_id=failures_by_id,
        output_path=output_path,
        trace_path=trace_path,
        quarantine_path=quarantine_path,
    )
    manifest: dict[str, Any] = {
        "stage": "extract",
        "input_path": portable_path(input_path, manifest_root),
        "input_sha256": sha256_file(input_path),
        "source_input_sha256": source_input_sha256,
        "output_path": portable_path(output_path, manifest_root),
        "model_runs_dir": portable_path(model_runs_dir, manifest_root),
        "trace_path": portable_path(trace_path, manifest_root),
        "quarantine_path": portable_path(quarantine_path, manifest_root),
        "model_name": model_name,
        "prompt_version": EXTRACTION_PROMPT_VERSION,
        "schema_version": "1.0",
        "extracted_at": extracted_at.isoformat(),
        "attempt_index": attempt_index,
        "resume": resume,
        "resumed_valid_count": resumed_count,
        "attempted_count": attempted_count,
        "input_count": len(items),
        "valid_insight_count": len(insights),
        "quarantined_count": len(failures),
        "failed_item_ids": [failure["item_id"] for failure in failures],
        "usage": dict(usage),
        "current_run_usage": dict(current_run_usage),
        "duration_seconds": round(perf_counter() - started_clock, 3),
    }
    write_json(manifest_path, manifest)
    if attempt_manifest_path is not None:
        write_json(attempt_manifest_path, manifest)
    return manifest


def load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def load_existing_insights(path: Path) -> list[Any]:
    if not path.is_file():
        return []
    from daily_ai_insight.pipeline.cluster import load_insights

    return load_insights(path)


def checkpoint_outputs(
    *,
    items: list[Any],
    insights_by_id: dict[str, Any],
    traces: list[dict[str, Any]],
    failures_by_id: dict[str, dict[str, Any]],
    output_path: Path,
    trace_path: Path,
    quarantine_path: Path,
) -> None:
    """Atomically persist current batch progress in stable input order."""

    write_jsonl(
        output_path,
        [insights_by_id[item.id] for item in items if item.id in insights_by_id],
    )
    write_jsonl(trace_path, traces)
    write_jsonl(
        quarantine_path,
        [failures_by_id[item.id] for item in items if item.id in failures_by_id],
    )
