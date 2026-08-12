"""Final quality gates for evidence, references, coverage, and rendered artifacts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from daily_ai_insight.data import load_raw_items
from daily_ai_insight.domain.models import DailyReport, SupportedAnalysis
from daily_ai_insight.harness.hooks import contains_chinese, validate_evidence
from daily_ai_insight.pipeline.cluster import load_insights
from daily_ai_insight.pipeline.prepare import sha256_file
from daily_ai_insight.reporting.generate import load_clusters
from daily_ai_insight.storage import write_json


def _all_sections(report: DailyReport) -> list[SupportedAnalysis]:
    return [
        *report.top_events,
        *report.trends,
        *report.risks,
        *report.opportunities,
    ]


def verify_report_artifacts(
    *,
    raw_path: Path,
    insight_path: Path,
    event_path: Path,
    report_json_path: Path,
    markdown_path: Path,
    html_path: Path,
    chart_paths: list[Path],
    output_path: Path,
) -> dict[str, Any]:
    items = load_raw_items(raw_path)
    insights = load_insights(insight_path)
    clusters = load_clusters(event_path)
    report = DailyReport.model_validate_json(report_json_path.read_text(encoding="utf-8"))
    item_by_id = {item.id: item for item in items}
    insight_by_id = {insight.item_id: insight for insight in insights}
    checks: list[dict[str, Any]] = []

    for insight in insights:
        validate_evidence(insight, item_by_id[insight.item_id])
    checks.append({"name": "all_evidence_is_literal", "passed": True, "count": len(insights)})

    member_ids = [item_id for cluster in clusters for item_id in cluster.member_item_ids]
    if len(member_ids) != len(set(member_ids)) or set(member_ids) != set(insight_by_id):
        raise ValueError("event clusters must cover every valid insight exactly once")
    checks.append({"name": "event_membership_is_complete", "passed": True, "count": len(member_ids)})

    for cluster in clusters:
        for fact in cluster.supporting_facts:
            item_id, _, _ = fact.fact_id.partition(".")
            if item_id not in item_by_id or fact.evidence not in item_by_id[item_id].content:
                raise ValueError(f"cluster fact is not grounded: {fact.fact_id}")
    checks.append({"name": "cluster_facts_are_grounded", "passed": True})

    known_ids = set(item_by_id)
    known_fact_ids = {
        fact.fact_id for cluster in clusters for fact in cluster.supporting_facts
    }
    unknown_executive_facts = (
        set(report.executive_summary_fact_ids) - known_fact_ids
    )
    if unknown_executive_facts:
        raise ValueError(
            "executive summary references unknown facts: "
            f"{sorted(unknown_executive_facts)}"
        )
    for section in _all_sections(report):
        unknown = set(section.source_item_ids) - known_ids
        if unknown:
            raise ValueError(f"report section references unknown sources: {sorted(unknown)}")
        unknown_facts = set(section.supporting_fact_ids) - known_fact_ids
        if unknown_facts:
            raise ValueError(
                f"report section references unknown facts: {sorted(unknown_facts)}"
            )
    checks.append({"name": "report_sources_and_facts_are_known", "passed": True})

    expected_trends = {"技术趋势", "应用趋势", "政策趋势", "资本趋势"}
    if {section.title for section in report.trends} != expected_trends:
        raise ValueError("report must contain technology, application, policy, and capital trends")
    if any(
        "背景：" not in section.analysis or "影响判断：" not in section.analysis
        for section in report.top_events
    ):
        raise ValueError("every top event requires explicit background and impact analysis")
    reader_texts = [report.executive_summary]
    reader_texts.extend(section.analysis for section in _all_sections(report))
    if any(not contains_chinese(text) for text in reader_texts):
        raise ValueError("all reader-facing report analysis must be Chinese")
    if any(re.search(r"\bevent_\d+\b", text) for text in reader_texts):
        raise ValueError("reader-facing report analysis must not expose internal event IDs")
    checks.append({"name": "deep_analysis_and_four_trends_exist", "passed": True})

    if report.coverage.input_count != len(items):
        raise ValueError("report input coverage does not match raw item count")
    if report.coverage.valid_insight_count != len(insight_by_id):
        raise ValueError("report insight coverage does not match insight count")
    if report.coverage.event_count != len(clusters):
        raise ValueError("report event coverage does not match cluster count")
    checks.append({"name": "coverage_counts_balance", "passed": True})

    markdown = markdown_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")
    if '<details class="evidence-details">' not in html:
        raise ValueError("HTML report must provide collapsible evidence details")
    for section in report.top_events:
        if section.title not in markdown or section.title not in html:
            raise ValueError(f"rendered report is missing top event: {section.title}")
        if not all(item_id in markdown for item_id in section.source_item_ids):
            raise ValueError(f"Markdown is missing source IDs for: {section.title}")
        if not all(
            fact_id in markdown and fact_id in html
            for fact_id in section.supporting_fact_ids
        ):
            raise ValueError(f"rendered report is missing fact IDs for: {section.title}")
    checks.append({"name": "rendered_top_events_and_sources_exist", "passed": True})

    for chart_path in chart_paths:
        chart = chart_path.read_text(encoding="utf-8")
        if "<svg" not in chart or "<rect" not in chart:
            raise ValueError(f"chart is not a populated SVG: {chart_path}")
    checks.append({"name": "charts_are_populated_svg", "passed": True, "count": len(chart_paths)})

    result: dict[str, Any] = {
        "stage": "verify",
        "passed": True,
        "checks": checks,
        "raw_sha256": sha256_file(raw_path),
        "insight_sha256": sha256_file(insight_path),
        "event_sha256": sha256_file(event_path),
        "report_json_sha256": sha256_file(report_json_path),
        "markdown_sha256": sha256_file(markdown_path),
        "html_sha256": sha256_file(html_path),
        "chart_sha256": {path.name: sha256_file(path) for path in chart_paths},
        "item_count": len(items),
        "insight_count": len(insights),
        "event_count": len(clusters),
        "top_event_count": len(report.top_events),
        "schema_version": report.schema_version,
    }
    write_json(output_path, result)
    return result
