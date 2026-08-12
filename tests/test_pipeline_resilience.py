"""Regression tests for resumable extraction and partial-batch clustering."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from daily_ai_insight.ai.extractor import build_extraction_agent
from daily_ai_insight.data import load_raw_items
from daily_ai_insight.domain.models import InsightPayload, NewsInsight, RawNewsItem
from daily_ai_insight.pipeline.cluster import (
    build_event_clusters,
    load_merge_specs,
)
from daily_ai_insight.pipeline.extract import extract_dataset
from daily_ai_insight.storage import write_jsonl

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ITEM_ID = re.compile(r'"id"\s*:\s*"([A-Za-z0-9._-]+)"')


def _latest_user_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in reversed(message.parts):
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    return part.content
    raise AssertionError("missing user prompt")


def _payload(item: RawNewsItem) -> dict[str, Any]:
    evidence = item.content[:80]
    return {
        "event_type": "other",
        "topics": ["AI"],
        "entities": [],
        "key_facts": [
            {
                "fact_id": "fact_01",
                "claim": "该来源描述了一项人工智能相关进展。",
                "evidence": evidence,
            }
        ],
        "summary": "该来源描述了一项近期人工智能产品、技术或应用进展，并提供了可核验事实。",
        "sentiments": [],
        "impact": {
            "technology": 3,
            "application": 3,
            "policy": 1,
            "capital": 1,
            "rationale": "该进展主要影响技术能力和应用方式，政策与资本信号相对有限。",
        },
        "alerts": [],
        "confidence": 0.9,
    }


def test_extract_resume_only_calls_model_for_missing_items(tmp_path: Path) -> None:
    items = load_raw_items(PROJECT_ROOT / "data/raw/2026-08-12.jsonl")[:2]
    raw_path = tmp_path / "raw.jsonl"
    output_path = tmp_path / "insights.jsonl"
    write_jsonl(raw_path, items)
    existing = NewsInsight(
        **InsightPayload.model_validate(_payload(items[0])).model_dump(),
        item_id=items[0].id,
        model_name="test:model",
        prompt_version="extract-v2",
        extracted_at=datetime(2026, 8, 12, 4, 30, tzinfo=UTC),
    )
    write_jsonl(output_path, [existing])
    calls = 0

    def model_function(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        match = ITEM_ID.search(_latest_user_text(messages))
        assert match is not None
        item = next(item for item in items if item.id == match.group(1))
        return ModelResponse(
            parts=[ToolCallPart(agent_info.output_tools[0].name, _payload(item))]
        )

    agent = build_extraction_agent(FunctionModel(model_function), PROJECT_ROOT)
    manifest = extract_dataset(
        agent=agent,
        input_path=raw_path,
        output_path=output_path,
        model_runs_dir=tmp_path / "model-runs",
        trace_path=tmp_path / "trace.jsonl",
        quarantine_path=tmp_path / "quarantine.jsonl",
        manifest_path=tmp_path / "manifest.json",
        attempt_manifest_path=tmp_path / "attempt-001.json",
        model_name="test:model",
        extracted_at=datetime(2026, 8, 12, 4, 30, tzinfo=UTC),
        resume=True,
    )

    assert calls == 1
    assert manifest["resumed_valid_count"] == 1
    assert manifest["attempted_count"] == 1
    assert manifest["valid_insight_count"] == 2
    assert manifest["quarantined_count"] == 0
    assert (tmp_path / "attempt-001.json").is_file()


def test_cluster_skips_merge_when_one_member_is_quarantined() -> None:
    items = load_raw_items(PROJECT_ROOT / "data/raw/2026-08-12.jsonl")
    insights = [
        NewsInsight(
            **InsightPayload.model_validate(_payload(item)).model_dump(),
            item_id=item.id,
            model_name="test:model",
            prompt_version="extract-v2",
            extracted_at=datetime(2026, 8, 12, 4, 30, tzinfo=UTC),
        )
        for item in items
        if item.id != "news_007"
    ]
    merge_specs = load_merge_specs(
        PROJECT_ROOT / "data/decisions/2026-08-12.event-merges.json"
    )

    clusters = build_event_clusters(
        items=items,
        insights=insights,
        merge_specs=merge_specs,
        report_date=date(2026, 8, 12),
    )

    member_ids = [item_id for cluster in clusters for item_id in cluster.member_item_ids]
    assert set(member_ids) == {insight.item_id for insight in insights}
    assert all(len(cluster.member_item_ids) == 1 for cluster in clusters)


def test_failed_provider_call_keeps_error_trace_and_attempt_manifest(
    tmp_path: Path,
) -> None:
    item = load_raw_items(PROJECT_ROOT / "data/raw/2026-08-12.jsonl")[0]
    raw_path = tmp_path / "raw.jsonl"
    trace_path = tmp_path / "trace.jsonl"
    write_jsonl(raw_path, [item])

    def failing_model(_messages: list[ModelMessage], _agent_info: AgentInfo) -> ModelResponse:
        raise RuntimeError("provider unavailable")

    agent = build_extraction_agent(FunctionModel(failing_model), PROJECT_ROOT)
    manifest = extract_dataset(
        agent=agent,
        input_path=raw_path,
        output_path=tmp_path / "insights.jsonl",
        model_runs_dir=tmp_path / "model-runs",
        trace_path=trace_path,
        quarantine_path=tmp_path / "quarantine.jsonl",
        manifest_path=tmp_path / "extract.json",
        attempt_manifest_path=tmp_path / "extract.attempt-001.json",
        model_name="test:model",
        extracted_at=datetime(2026, 8, 12, 4, 30, tzinfo=UTC),
    )

    trace_events = [
        json.loads(line)["event"]
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert manifest["quarantined_count"] == 1
    assert "run_started" in trace_events
    assert "run_failed" in trace_events
    assert (tmp_path / "extract.attempt-001.json").is_file()
