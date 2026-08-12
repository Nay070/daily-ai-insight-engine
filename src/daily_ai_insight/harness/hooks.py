"""Lifecycle hooks that enforce traceability around model extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic_ai.capabilities import Hooks
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.tools import RunContext

from daily_ai_insight.domain.models import InsightPayload, RawNewsItem


@dataclass
class ExtractionDependencies:
    item: RawNewsItem
    model_name: str
    prompt_version: str
    extracted_at: datetime
    trace: list[dict[str, Any]] = field(default_factory=list)


def _record(deps: ExtractionDependencies, event: str, **details: Any) -> None:
    deps.trace.append({"event": event, "item_id": deps.item.id, **details})


def validate_evidence(payload: InsightPayload, item: RawNewsItem) -> None:
    """Reject facts whose quoted evidence is not present in the source content."""

    missing = [fact.fact_id for fact in payload.key_facts if fact.evidence not in item.content]
    if missing:
        raise ValueError(
            "evidence must be a literal substring of source content; invalid facts: "
            + ", ".join(missing)
        )


def contains_chinese(text: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in text)


def validate_chinese_narratives(payload: InsightPayload) -> None:
    fields = [payload.summary, payload.impact.rationale]
    fields.extend(sentiment.rationale for sentiment in payload.sentiments)
    fields.extend(alert.description for alert in payload.alerts)
    if any(not contains_chinese(value) for value in fields):
        raise ValueError(
            "summary, impact rationale, sentiment rationales, and alerts must be Chinese"
        )


def build_extraction_hooks() -> Hooks[ExtractionDependencies]:
    hooks: Hooks[ExtractionDependencies] = Hooks()

    @hooks.on.before_run
    def before_run(ctx: RunContext[ExtractionDependencies]) -> None:
        if not ctx.deps.item.content.strip():
            raise ValueError("source content is empty")
        _record(ctx.deps, "run_started")

    @hooks.on.after_output_validate
    def after_output_validate(
        ctx: RunContext[ExtractionDependencies],
        *,
        output_context: Any,
        output: Any,
    ) -> Any:
        del output_context
        if not isinstance(output, InsightPayload):
            raise ModelRetry("Return the required InsightPayload structured output.")
        try:
            validate_evidence(output, ctx.deps.item)
            validate_chinese_narratives(output)
        except ValueError as error:
            _record(ctx.deps, "evidence_rejected", reason=str(error))
            raise ModelRetry(str(error)) from error
        _record(ctx.deps, "output_validated", fact_count=len(output.key_facts))
        return output

    @hooks.on.after_run
    def after_run(
        ctx: RunContext[ExtractionDependencies], *, result: Any
    ) -> Any:
        _record(ctx.deps, "run_completed")
        return result

    @hooks.on.run_error
    def run_error(
        ctx: RunContext[ExtractionDependencies], *, error: BaseException
    ) -> Any:
        _record(ctx.deps, "run_failed", error_type=type(error).__name__)
        raise error

    return hooks
