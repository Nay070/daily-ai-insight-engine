"""Tests for repository skills and the Pydantic AI extraction harness."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from daily_ai_insight.ai.extractor import build_extraction_agent, extract_one
from daily_ai_insight.domain.models import InsightPayload, RawNewsItem
from daily_ai_insight.harness.hooks import validate_evidence
from daily_ai_insight.harness.skills import SkillCapability, load_skill

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_first_item() -> RawNewsItem:
    first_line = (PROJECT_ROOT / "data" / "raw" / "2026-08-12.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()[0]
    return RawNewsItem.model_validate_json(first_line)


def valid_payload(item: RawNewsItem) -> dict[str, Any]:
    evidence = "adds native vision support"
    assert evidence in item.content
    return {
        "event_type": "product_release",
        "topics": ["coding model", "GitHub Copilot"],
        "entities": [
            {"name": "GitHub", "type": "organization", "canonical_name": "GitHub"}
        ],
        "key_facts": [
            {
                "fact_id": "fact_01",
                "claim": "该编码模型增加了原生视觉支持。",
                "evidence": evidence,
            }
        ],
        "summary": "GitHub Copilot 正在上线一款增加原生视觉支持并改进工具使用能力的编码模型。",
        "sentiments": [],
        "impact": {
            "technology": 3,
            "application": 2,
            "policy": 2,
            "capital": 1,
            "rationale": "该模型的视觉和工具使用能力会影响开发者工作流，但政策与资本影响有限。",
        },
        "alerts": [
            {
                "type": "opportunity",
                "description": "更低价格和视觉能力可能扩大编码模型在开发工作流中的采用。",
                "supporting_fact_ids": ["fact_01"],
            }
        ],
        "confidence": 0.88,
    }


def test_load_skill_and_capability() -> None:
    skill_dir = PROJECT_ROOT / "skills" / "extract-news-insight"
    skill = load_skill(skill_dir)
    capability = SkillCapability(skill_dir)

    assert skill.name == "extract-news-insight"
    assert "occurs verbatim" in capability.get_instructions()


def test_evidence_guard_rejects_non_literal_quote() -> None:
    item = load_first_item()
    payload_data = valid_payload(item)
    payload_data["key_facts"][0]["evidence"] = "This exact text is absent."
    payload = InsightPayload.model_validate(payload_data)

    with pytest.raises(ValueError, match="literal substring"):
        validate_evidence(payload, item)


def test_extraction_agent_records_provenance_and_trace() -> None:
    item = load_first_item()
    payload_data = valid_payload(item)

    def model_function(_messages: list[Any], agent_info: AgentInfo) -> ModelResponse:
        assert agent_info.output_tools
        return ModelResponse(
            parts=[ToolCallPart(agent_info.output_tools[0].name, payload_data)]
        )

    agent = build_extraction_agent(
        FunctionModel(model_function, model_name="test-model"), PROJECT_ROOT
    )
    run = extract_one(
        agent,
        item,
        model_name="test-model",
        extracted_at=datetime(2026, 8, 12, 4, 30, tzinfo=UTC),
    )

    assert run.insight.item_id == item.id
    assert run.insight.model_name == "test-model"
    assert run.insight.prompt_version == "extract-v2"
    assert [event["event"] for event in run.trace] == [
        "run_started",
        "output_validated",
        "run_completed",
    ]
    assert json.loads(run.message_history_json)
