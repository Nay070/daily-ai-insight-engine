"""One-record-at-a-time structured extraction agent."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model

from daily_ai_insight.domain.models import InsightPayload, NewsInsight, RawNewsItem
from daily_ai_insight.harness.hooks import ExtractionDependencies, build_extraction_hooks
from daily_ai_insight.harness.skills import SkillCapability

EXTRACTION_PROMPT_VERSION = "extract-v2"


class ExtractionRunError(RuntimeError):
    """Preserve lifecycle trace when a provider call or validation ultimately fails."""

    def __init__(self, original: Exception, trace: list[dict[str, Any]]) -> None:
        super().__init__(str(original))
        self.original_type = type(original).__name__
        self.trace = trace


@dataclass(frozen=True)
class ExtractionRun:
    insight: NewsInsight
    message_history_json: str
    trace: list[dict[str, Any]]
    usage: dict[str, Any]


def build_extraction_agent(model: Model | str, project_root: Path) -> Agent[ExtractionDependencies, InsightPayload]:
    prompt = (project_root / "prompts" / "extract_v2.md").read_text(encoding="utf-8")
    skill = SkillCapability(project_root / "skills" / "extract-news-insight")
    return Agent(
        model,
        deps_type=ExtractionDependencies,
        output_type=InsightPayload,
        instructions=prompt,
        retries=2,
        capabilities=[skill, build_extraction_hooks()],
    )


def build_extraction_request(item: RawNewsItem) -> str:
    source_record = {
        "id": item.id,
        "title": item.title,
        "content": item.content,
        "content_kind": item.content_kind,
        "source_name": item.source_name,
        "source_type": item.source_type,
        "published_at": item.published_at.isoformat(),
        "published_at_precision": item.published_at_precision,
        "language": item.language,
    }
    serialized = json.dumps(source_record, ensure_ascii=False, indent=2)
    return (
        "Extract one structured insight from this source record.\n"
        "<source_record>\n"
        f"{serialized}\n"
        "</source_record>"
    )


def extract_one(
    agent: Agent[ExtractionDependencies, InsightPayload],
    item: RawNewsItem,
    *,
    model_name: str,
    extracted_at: datetime,
) -> ExtractionRun:
    deps = ExtractionDependencies(
        item=item,
        model_name=model_name,
        prompt_version=EXTRACTION_PROMPT_VERSION,
        extracted_at=extracted_at,
    )
    try:
        result = agent.run_sync(build_extraction_request(item), deps=deps)
    except Exception as error:
        raise ExtractionRunError(error, list(deps.trace)) from error
    insight = NewsInsight(
        **result.output.model_dump(),
        item_id=item.id,
        model_name=model_name,
        prompt_version=EXTRACTION_PROMPT_VERSION,
        extracted_at=extracted_at,
    )
    return ExtractionRun(
        insight=insight,
        message_history_json=result.all_messages_json().decode("utf-8"),
        trace=list(deps.trace),
        usage=asdict(result.usage),
    )
