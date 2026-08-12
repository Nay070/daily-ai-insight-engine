"""End-to-end test for the online orchestrator using provider test doubles."""

from __future__ import annotations

import json
import re
from datetime import date
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
from daily_ai_insight.ai.reporter import build_report_analysis_agent
from daily_ai_insight.pipeline.live import run_live_pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_BLOCK = re.compile(r"<source_record>\s*(\{.*?\})\s*</source_record>", re.DOTALL)
EVENT_BLOCK = re.compile(r"<event_digests>\s*(\{.*\})\s*</event_digests>", re.DOTALL)


def _latest_user_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in reversed(message.parts):
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    return part.content
    raise AssertionError("missing user prompt")


def _extraction_response(
    messages: list[ModelMessage], agent_info: AgentInfo
) -> ModelResponse:
    match = SOURCE_BLOCK.search(_latest_user_text(messages))
    assert match is not None
    source = json.loads(match.group(1))
    payload: dict[str, Any] = {
        "event_type": "other",
        "topics": ["人工智能"],
        "entities": [],
        "key_facts": [
            {
                "fact_id": "fact_01",
                "claim": "该来源描述了一项人工智能相关进展。",
                "evidence": source["content"][:80],
            }
        ],
        "summary": "该来源描述了一项近期人工智能产品、技术或应用进展，并提供了可以回溯的事实。",
        "sentiments": [],
        "impact": {
            "technology": 3,
            "application": 3,
            "policy": 1,
            "capital": 1,
            "rationale": "该进展主要影响技术能力和应用方式，政策与资本层面的信号相对有限。",
        },
        "alerts": [],
        "confidence": 0.9,
    }
    return ModelResponse(parts=[ToolCallPart(agent_info.output_tools[0].name, payload)])


def _report_response(messages: list[ModelMessage], agent_info: AgentInfo) -> ModelResponse:
    match = EVENT_BLOCK.search(_latest_user_text(messages))
    assert match is not None
    source = json.loads(match.group(1))
    top_ids = source["expected_top_event_ids"]
    support_ids = [event["event_id"] for event in source["events"][:3]]
    event_by_id = {event["event_id"]: event for event in source["events"]}
    support_fact_ids = [
        event_by_id[event_id]["grounded_facts"][0]["fact_id"]
        for event_id in support_ids
    ]
    payload = {
        "executive_summary": (
            "本期样本集中体现了人工智能能力迭代、产品落地与治理实践，"
            "所有判断均限定在已验证事件范围内。"
        ),
        "executive_summary_fact_ids": support_fact_ids,
        "top_events": [
            {
                "event_id": event_id,
                "background": "该事件来自已验证来源摘要和逐字证据，反映近期人工智能领域的一项具体变化。",
                "background_fact_ids": [
                    event_by_id[event_id]["grounded_facts"][0]["fact_id"]
                ],
                "impact_analysis": "结构化评分显示其主要影响技术与应用方向，结论只适用于当前样本，不外推市场整体。",
                "impact_fact_ids": [
                    event_by_id[event_id]["grounded_facts"][0]["fact_id"]
                ],
            }
            for event_id in top_ids
        ],
        "trends": [
            {
                "dimension": dimension,
                "analysis": "本期多个已验证事件在该维度形成样本信号，但证据范围有限，不代表全市场趋势。",
                "supporting_event_ids": support_ids,
                "supporting_fact_ids": support_fact_ids,
            }
            for dimension in ("technology", "application", "policy", "capital")
        ],
    }
    return ModelResponse(parts=[ToolCallPart(agent_info.output_tools[0].name, payload)])


def test_run_live_pipeline_end_to_end_without_network(tmp_path: Path) -> None:
    extraction_agent = build_extraction_agent(
        FunctionModel(_extraction_response, model_name="test-extraction"), PROJECT_ROOT
    )
    report_agent = build_report_analysis_agent(
        FunctionModel(_report_response, model_name="test-report"), PROJECT_ROOT
    )

    result = run_live_pipeline(
        project_root=PROJECT_ROOT,
        artifact_root=tmp_path,
        input_path=PROJECT_ROOT / "data/input/2026-08-12.json",
        merge_spec_path=PROJECT_ROOT / "data/decisions/2026-08-12.event-merges.json",
        report_date=date(2026, 8, 12),
        model_name="test:model",
        retry_failures=0,
        fresh=True,
        extraction_agent=extraction_agent,
        report_analysis_agent=report_agent,
    )

    assert result["verification_passed"] is True
    assert result["counts"]["valid_insights"] == 16
    assert result["counts"]["trends"] == 4
    assert len(result["extraction_attempts"]) == 1
    assert (tmp_path / "reports/2026-08-12/report.html").is_file()
    assert (tmp_path / "data/runs/2026-08-12/manifests/analyze.json").is_file()
    assert (tmp_path / "data/runs/2026-08-12/model_messages/report.messages.json").is_file()
    report = json.loads(
        (tmp_path / "reports/2026-08-12/report.json").read_text(encoding="utf-8")
    )
    assert report["schema_version"] == "1.1"
    assert report["prompt_version"] == "report-v3"
    assert report["executive_summary_fact_ids"]
    assert all(section["supporting_fact_ids"] for section in report["top_events"])

    extract_manifest_path = (
        tmp_path / "data/runs/2026-08-12/manifests/extract.json"
    )
    stale_manifest = json.loads(extract_manifest_path.read_text(encoding="utf-8"))
    stale_manifest["prompt_version"] = "obsolete-prompt"
    extract_manifest_path.write_text(
        json.dumps(stale_manifest, ensure_ascii=False), encoding="utf-8"
    )

    rerun = run_live_pipeline(
        project_root=PROJECT_ROOT,
        artifact_root=tmp_path,
        input_path=PROJECT_ROOT / "data/input/2026-08-12.json",
        merge_spec_path=PROJECT_ROOT / "data/decisions/2026-08-12.event-merges.json",
        report_date=date(2026, 8, 12),
        model_name="test:model",
        retry_failures=0,
        fresh=False,
        extraction_agent=extraction_agent,
        report_analysis_agent=report_agent,
    )

    assert len(rerun["extraction_attempts"]) == 1
    assert rerun["extraction_attempts"][0]["resumed_valid_count"] == 0
    assert rerun["extraction_attempts"][0]["attempted_count"] == 16
