"""One-command online pipeline for the single primary deliverable."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import date, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import Any

from daily_ai_insight.ai.extractor import (
    EXTRACTION_PROMPT_VERSION,
    build_extraction_agent,
)
from daily_ai_insight.ai.reporter import (
    REPORT_ANALYSIS_PROMPT_VERSION,
    analyze_report,
    build_report_analysis_agent,
)
from daily_ai_insight.paths import portable_path
from daily_ai_insight.pipeline.cluster import cluster_dataset, load_insights
from daily_ai_insight.pipeline.extract import extract_dataset
from daily_ai_insight.pipeline.prepare import prepare_dataset, sha256_file
from daily_ai_insight.reporting.generate import generate_report_artifacts, load_clusters
from daily_ai_insight.reporting.verify import verify_report_artifacts
from daily_ai_insight.storage import write_json, write_jsonl

SCHEMA_VERSION = "1.0"
REPORT_SCHEMA_VERSION = "1.1"


def _remove_tree(path: Path, artifact_root: Path) -> None:
    resolved = path.resolve()
    if resolved == artifact_root.resolve():
        raise ValueError("refusing to remove the artifact root")
    try:
        resolved.relative_to(artifact_root.resolve())
    except ValueError as error:
        raise ValueError(f"refusing to remove path outside artifact root: {resolved}") from error
    if resolved.is_dir():
        shutil.rmtree(resolved)
    elif resolved.exists():
        resolved.unlink()


def _clear_run_outputs(
    *,
    artifact_root: Path,
    run_root: Path,
    processed_dir: Path,
    report_dir: Path,
) -> None:
    for path in (run_root, processed_dir, report_dir):
        _remove_tree(path, artifact_root)


def _next_attempt_index(manifests_dir: Path) -> int:
    indexes = []
    for path in manifests_dir.glob("extract.attempt-*.json"):
        try:
            indexes.append(int(path.stem.rsplit("-", maxsplit=1)[1]))
        except (IndexError, ValueError):
            continue
    return max(indexes, default=0) + 1


def _load_attempt_history(manifests_dir: Path, root: Path) -> list[dict[str, Any]]:
    history = []
    for path in sorted(manifests_dir.glob("extract.attempt-*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        history.append(
            {
                "attempt_index": manifest["attempt_index"],
                "attempted_count": manifest["attempted_count"],
                "resumed_valid_count": manifest["resumed_valid_count"],
                "valid_insight_count": manifest["valid_insight_count"],
                "quarantined_count": manifest["quarantined_count"],
                "failed_item_ids": manifest["failed_item_ids"],
                "usage": manifest["current_run_usage"],
                "manifest_path": portable_path(path, root),
            }
        )
    return history


def run_live_pipeline(
    *,
    project_root: Path,
    input_path: Path,
    merge_spec_path: Path,
    report_date: date,
    model_name: str,
    retry_failures: int = 1,
    fresh: bool = False,
    artifact_root: Path | None = None,
    extraction_agent: Any | None = None,
    report_analysis_agent: Any | None = None,
) -> dict[str, Any]:
    """Run prepare through verification using one configured online model."""

    if retry_failures < 0:
        raise ValueError("retry_failures cannot be negative")
    pipeline_started_clock = perf_counter()
    stage_durations: dict[str, float] = {}
    resources_root = project_root.resolve()
    outputs_root = (artifact_root or project_root).resolve()
    input_path = input_path.resolve()
    merge_spec_path = merge_spec_path.resolve()
    date_key = report_date.isoformat()

    raw_path = outputs_root / "data" / "raw" / f"{date_key}.jsonl"
    processed_dir = outputs_root / "data" / "processed" / date_key
    insight_path = processed_dir / "insights.jsonl"
    event_path = processed_dir / "events.jsonl"
    analysis_path = processed_dir / "report-analysis.json"
    run_root = outputs_root / "data" / "runs" / date_key
    model_messages_dir = run_root / "model_messages"
    traces_dir = run_root / "traces"
    quarantine_dir = run_root / "quarantine"
    manifests_dir = run_root / "manifests"
    extract_manifest_path = manifests_dir / "extract.json"
    report_dir = outputs_root / "reports" / date_key
    charts_dir = report_dir / "charts"

    if fresh:
        _clear_run_outputs(
            artifact_root=outputs_root,
            run_root=run_root,
            processed_dir=processed_dir,
            report_dir=report_dir,
        )

    started_at = datetime.now().astimezone()
    source_input_sha256 = sha256_file(input_path)
    resume = False
    previous_extract_manifest: dict[str, Any] | None = None
    previous_run_manifest_path = manifests_dir / "run.json"
    if (
        not fresh
        and raw_path.is_file()
        and insight_path.is_file()
        and extract_manifest_path.is_file()
        and (manifests_dir / "prepare.json").is_file()
    ):
        previous = json.loads(extract_manifest_path.read_text(encoding="utf-8"))
        previous_extract_manifest = previous
        previous_source_sha256 = previous.get("source_input_sha256")
        if previous_source_sha256 is None and previous_run_manifest_path.is_file():
            previous_run = json.loads(
                previous_run_manifest_path.read_text(encoding="utf-8")
            )
            previous_source_sha256 = previous_run.get("input_sha256")
        resume = all(
            (
                previous_source_sha256 == source_input_sha256,
                previous.get("model_name") == model_name,
                previous.get("prompt_version") == EXTRACTION_PROMPT_VERSION,
                previous.get("schema_version") == SCHEMA_VERSION,
            )
        )
    elif not fresh and (insight_path.exists() or extract_manifest_path.exists()):
        resume = False

    if not resume and not fresh and (insight_path.exists() or extract_manifest_path.exists()):
        _clear_run_outputs(
            artifact_root=outputs_root,
            run_root=run_root,
            processed_dir=processed_dir,
            report_dir=report_dir,
        )
    prepare_started_clock = perf_counter()
    if resume:
        prepare_manifest = json.loads(
            (manifests_dir / "prepare.json").read_text(encoding="utf-8")
        )
    else:
        prepare_manifest = prepare_dataset(
            input_path=input_path,
            output_path=raw_path,
            manifest_path=manifests_dir / "prepare.json",
            report_date=report_date,
            collected_at=started_at,
            manifest_root=outputs_root,
        )
    stage_durations["prepare"] = round(perf_counter() - prepare_started_clock, 3)

    extraction_started_clock = perf_counter()
    extraction_agent = extraction_agent or build_extraction_agent(model_name, resources_root)
    already_complete = bool(
        resume
        and previous_extract_manifest
        and previous_extract_manifest.get("valid_insight_count")
        == prepare_manifest["input_count"]
        and previous_extract_manifest.get("quarantined_count") == 0
    )
    if already_complete:
        extract_manifest = previous_extract_manifest
        if extract_manifest.get("source_input_sha256") is None:
            extract_manifest["source_input_sha256"] = source_input_sha256
            write_json(extract_manifest_path, extract_manifest)
        attempt_index = int(previous_extract_manifest["attempt_index"])
    else:
        attempt_index = _next_attempt_index(manifests_dir)
        extract_manifest = extract_dataset(
            agent=extraction_agent,
            input_path=raw_path,
            output_path=insight_path,
            model_runs_dir=model_messages_dir,
            trace_path=traces_dir / "extract.jsonl",
            quarantine_path=quarantine_dir / "extract.jsonl",
            manifest_path=extract_manifest_path,
            attempt_manifest_path=(
                manifests_dir / f"extract.attempt-{attempt_index:03d}.json"
            ),
            attempt_index=attempt_index,
            model_name=model_name,
            extracted_at=datetime.now().astimezone(),
            resume=resume,
            source_input_sha256=source_input_sha256,
            manifest_root=outputs_root,
        )
    for _ in range(retry_failures):
        if extract_manifest["quarantined_count"] == 0:
            break
        attempt_index += 1
        extract_manifest = extract_dataset(
            agent=extraction_agent,
            input_path=raw_path,
            output_path=insight_path,
            model_runs_dir=model_messages_dir,
            trace_path=traces_dir / "extract.jsonl",
            quarantine_path=quarantine_dir / "extract.jsonl",
            manifest_path=extract_manifest_path,
            attempt_manifest_path=(
                manifests_dir / f"extract.attempt-{attempt_index:03d}.json"
            ),
            attempt_index=attempt_index,
            model_name=model_name,
            extracted_at=datetime.now().astimezone(),
            resume=True,
            source_input_sha256=source_input_sha256,
            manifest_root=outputs_root,
        )
    stage_durations["extract"] = round(perf_counter() - extraction_started_clock, 3)

    cluster_started_clock = perf_counter()
    cluster_manifest = cluster_dataset(
        raw_path=raw_path,
        insight_path=insight_path,
        merge_spec_path=merge_spec_path,
        output_path=event_path,
        manifest_path=manifests_dir / "cluster.json",
        report_date=report_date,
        manifest_root=outputs_root,
    )
    stage_durations["cluster"] = round(perf_counter() - cluster_started_clock, 3)

    insights = load_insights(insight_path)
    clusters = load_clusters(event_path)
    analysis_started_clock = perf_counter()
    report_analysis_agent = report_analysis_agent or build_report_analysis_agent(
        model_name, resources_root
    )
    analysis_run = analyze_report(report_analysis_agent, clusters, insights)
    stage_durations["report_analysis"] = round(
        perf_counter() - analysis_started_clock, 3
    )
    write_json(analysis_path, analysis_run.analysis)
    write_json(
        model_messages_dir / "report.messages.json",
        json.loads(analysis_run.message_history_json),
    )
    write_jsonl(traces_dir / "report.jsonl", analysis_run.trace)
    analysis_manifest: dict[str, Any] = {
        "stage": "analyze",
        "model_name": model_name,
        "prompt_version": REPORT_ANALYSIS_PROMPT_VERSION,
        "schema_version": REPORT_SCHEMA_VERSION,
        "insight_sha256": sha256_file(insight_path),
        "event_sha256": sha256_file(event_path),
        "output_path": portable_path(analysis_path, outputs_root),
        "output_sha256": sha256_file(analysis_path),
        "top_event_count": len(analysis_run.analysis.top_events),
        "trend_count": len(analysis_run.analysis.trends),
        "usage": analysis_run.usage,
        "duration_seconds": stage_durations["report_analysis"],
    }
    write_json(manifests_dir / "analyze.json", analysis_manifest)

    generated_at = datetime.now().astimezone()
    render_started_clock = perf_counter()
    report_manifest = generate_report_artifacts(
        raw_path=raw_path,
        insight_path=insight_path,
        event_path=event_path,
        analysis_path=analysis_path,
        output_json_path=report_dir / "report.json",
        output_markdown_path=report_dir / "report.md",
        output_html_path=report_dir / "report.html",
        charts_dir=charts_dir,
        manifest_path=manifests_dir / "report.json",
        project_root=resources_root,
        report_date=report_date,
        generated_at=generated_at,
        manifest_root=outputs_root,
    )
    stage_durations["render"] = round(perf_counter() - render_started_clock, 3)
    chart_paths = [
        charts_dir / "importance.svg",
        charts_dir / "topics.svg",
        charts_dir / "sources.svg",
    ]
    verify_started_clock = perf_counter()
    verify_manifest = verify_report_artifacts(
        raw_path=raw_path,
        insight_path=insight_path,
        event_path=event_path,
        report_json_path=report_dir / "report.json",
        markdown_path=report_dir / "report.md",
        html_path=report_dir / "report.html",
        chart_paths=chart_paths,
        output_path=manifests_dir / "verify.json",
    )
    stage_durations["verify"] = round(perf_counter() - verify_started_clock, 3)

    total_usage: Counter[str] = Counter(extract_manifest["usage"])
    total_usage.update(analysis_run.usage)
    completed_at = datetime.now().astimezone()
    total_duration = round(perf_counter() - pipeline_started_clock, 3)
    run_manifest: dict[str, Any] = {
        "run_id": date_key,
        "mode": "online_model_only",
        "report_date": date_key,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "input_path": portable_path(input_path, outputs_root),
        "input_sha256": sha256_file(input_path),
        "model_name": model_name,
        "resume_validation": {
            "status": "matched" if resume else "fresh_or_reset",
            "required_fields": [
                "input_hash",
                "model_name",
                "prompt_version",
                "schema_version",
            ],
        },
        "harness": {
            "implementation": "repository-native-pydantic-ai-v2",
            "pydantic-ai": version("pydantic-ai-slim"),
        },
        "prompt_versions": {
            "extraction": extract_manifest["prompt_version"],
            "report_analysis": REPORT_ANALYSIS_PROMPT_VERSION,
        },
        "schema_version": SCHEMA_VERSION,
        "schema_versions": {
            "source_insight_event": SCHEMA_VERSION,
            "report": REPORT_SCHEMA_VERSION,
        },
        "counts": {
            "input": prepare_manifest["input_count"],
            "valid_insights": extract_manifest["valid_insight_count"],
            "quarantined": extract_manifest["quarantined_count"],
            "events": cluster_manifest["event_count"],
            "top_events": report_manifest["top_event_count"],
            "trends": report_manifest["trend_count"],
        },
        "extraction_attempts": _load_attempt_history(manifests_dir, outputs_root),
        "failures": extract_manifest["failed_item_ids"],
        "usage": {
            "extraction": extract_manifest["usage"],
            "report_analysis": analysis_run.usage,
            "total": dict(total_usage),
        },
        "performance": {
            "duration_seconds": total_duration,
            "stage_duration_seconds": stage_durations,
            "extraction_mode": "reused" if already_complete else "model_called",
        },
        "verification_passed": verify_manifest["passed"],
        "artifacts": {
            "raw": portable_path(raw_path, outputs_root),
            "insights": portable_path(insight_path, outputs_root),
            "events": portable_path(event_path, outputs_root),
            "report_analysis": portable_path(analysis_path, outputs_root),
            "report_json": portable_path(report_dir / "report.json", outputs_root),
            "report_markdown": portable_path(
                report_dir / "report.md", outputs_root
            ),
            "report_html": portable_path(report_dir / "report.html", outputs_root),
        },
    }
    write_json(manifests_dir / "run.json", run_manifest)
    return run_manifest
