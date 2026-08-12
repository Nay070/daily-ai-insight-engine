"""Lifecycle and grounding guards for bounded report narrative generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import Hooks
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.tools import RunContext

from daily_ai_insight.domain.models import ReportAnalysisPayload
from daily_ai_insight.harness.hooks import contains_chinese


@dataclass
class ReportAnalysisDependencies:
    known_event_ids: set[str]
    expected_top_event_ids: list[str]
    fact_ids_by_event: dict[str, set[str]]
    trace: list[dict[str, Any]] = field(default_factory=list)


def _record(deps: ReportAnalysisDependencies, event: str, **details: Any) -> None:
    deps.trace.append({"event": event, **details})


def validate_report_analysis(
    payload: ReportAnalysisPayload, deps: ReportAnalysisDependencies
) -> None:
    top_ids = [section.event_id for section in payload.top_events]
    if top_ids != deps.expected_top_event_ids:
        raise ValueError("top event IDs and order must exactly match the supplied ranking")
    known_fact_ids = set().union(*deps.fact_ids_by_event.values())
    unknown_executive_facts = set(payload.executive_summary_fact_ids) - known_fact_ids
    if unknown_executive_facts:
        raise ValueError(
            "executive summary references unknown fact IDs: "
            f"{sorted(unknown_executive_facts)}"
        )
    for section in payload.top_events:
        allowed_fact_ids = deps.fact_ids_by_event[section.event_id]
        referenced_fact_ids = {
            *section.background_fact_ids,
            *section.impact_fact_ids,
        }
        unknown_fact_ids = referenced_fact_ids - allowed_fact_ids
        if unknown_fact_ids:
            raise ValueError(
                f"Top event {section.event_id} references facts outside its event: "
                f"{sorted(unknown_fact_ids)}"
            )
    referenced_ids = {
        event_id
        for trend in payload.trends
        for event_id in trend.supporting_event_ids
    }
    unknown = referenced_ids - deps.known_event_ids
    if unknown:
        raise ValueError(f"trend narratives reference unknown event IDs: {sorted(unknown)}")
    for trend in payload.trends:
        allowed_fact_ids = set().union(
            *(deps.fact_ids_by_event[event_id] for event_id in trend.supporting_event_ids)
        )
        unknown_fact_ids = set(trend.supporting_fact_ids) - allowed_fact_ids
        if unknown_fact_ids:
            raise ValueError(
                f"{trend.dimension.value} trend references facts outside its events: "
                f"{sorted(unknown_fact_ids)}"
            )
        cited_event_ids = {
            event_id
            for event_id in trend.supporting_event_ids
            if set(trend.supporting_fact_ids) & deps.fact_ids_by_event[event_id]
        }
        missing_event_facts = set(trend.supporting_event_ids) - cited_event_ids
        if missing_event_facts:
            raise ValueError(
                f"{trend.dimension.value} trend lacks fact support for events: "
                f"{sorted(missing_event_facts)}"
            )
    narratives = [payload.executive_summary]
    narratives.extend(section.background for section in payload.top_events)
    narratives.extend(section.impact_analysis for section in payload.top_events)
    narratives.extend(section.analysis for section in payload.trends)
    if any(not contains_chinese(text) for text in narratives):
        raise ValueError("all report narratives must be written in Chinese")
    if any(re.search(r"\bevent_\d+\b", text) for text in narratives):
        raise ValueError("internal event IDs must not appear in reader-facing narratives")


def build_report_analysis_hooks() -> Hooks[ReportAnalysisDependencies]:
    hooks: Hooks[ReportAnalysisDependencies] = Hooks()

    @hooks.on.before_run
    def before_run(ctx: RunContext[ReportAnalysisDependencies]) -> None:
        _record(ctx.deps, "report_analysis_started")

    @hooks.on.after_output_validate
    def after_output_validate(
        ctx: RunContext[ReportAnalysisDependencies],
        *,
        output_context: Any,
        output: Any,
    ) -> Any:
        del output_context
        if not isinstance(output, ReportAnalysisPayload):
            raise ModelRetry("Return the required ReportAnalysisPayload structured output.")
        try:
            validate_report_analysis(output, ctx.deps)
        except ValueError as error:
            _record(ctx.deps, "report_analysis_rejected", reason=str(error))
            raise ModelRetry(str(error)) from error
        _record(ctx.deps, "report_analysis_validated")
        return output

    @hooks.on.after_run
    def after_run(ctx: RunContext[ReportAnalysisDependencies], *, result: Any) -> Any:
        _record(ctx.deps, "report_analysis_completed")
        return result

    @hooks.on.run_error
    def run_error(
        ctx: RunContext[ReportAnalysisDependencies], *, error: BaseException
    ) -> Any:
        _record(ctx.deps, "report_analysis_failed", error_type=type(error).__name__)
        raise error

    return hooks
