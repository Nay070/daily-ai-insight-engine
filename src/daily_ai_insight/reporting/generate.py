"""Build and render a source-linked daily report from validated event data."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import TypeAdapter

from daily_ai_insight.data import load_raw_items
from daily_ai_insight.domain.models import (
    AlertType,
    CoverageSummary,
    DailyReport,
    EventCluster,
    NewsInsight,
    ReportAnalysisPayload,
    SupportedAnalysis,
    TrendDimension,
)
from daily_ai_insight.paths import portable_path
from daily_ai_insight.pipeline.cluster import load_insights
from daily_ai_insight.pipeline.prepare import sha256_file
from daily_ai_insight.storage import write_json
from daily_ai_insight.visualization.svg import write_bar_chart

EVENT_LIST = TypeAdapter(list[EventCluster])


def load_clusters(path: Path) -> list[EventCluster]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return EVENT_LIST.validate_python(records)


TREND_TITLES = {
    TrendDimension.TECHNOLOGY: "技术趋势",
    TrendDimension.APPLICATION: "应用趋势",
    TrendDimension.POLICY: "政策趋势",
    TrendDimension.CAPITAL: "资本趋势",
}


def _alert_analyses(
    clusters: list[EventCluster],
    insights: list[NewsInsight],
    alert_type: AlertType,
) -> list[SupportedAnalysis]:
    insight_by_id = {insight.item_id: insight for insight in insights}
    analyses = []
    for cluster in clusters:
        alerts = [
            (item_id, alert)
            for item_id in cluster.member_item_ids
            for alert in insight_by_id[item_id].alerts
            if alert.type == alert_type
        ]
        if alerts:
            analyses.append(
                SupportedAnalysis(
                    title=cluster.canonical_title,
                    analysis="；".join(
                        dict.fromkeys(alert.description for _, alert in alerts)
                    ),
                    source_item_ids=cluster.member_item_ids,
                    supporting_fact_ids=list(
                        dict.fromkeys(
                            f"{item_id}.{fact_id}"
                            for item_id, alert in alerts
                            for fact_id in alert.supporting_fact_ids
                        )
                    ),
                )
            )
    return analyses[:6]


def build_daily_report(
    *,
    report_date: date,
    generated_at: datetime,
    items: list[Any],
    insights: list[NewsInsight],
    clusters: list[EventCluster],
    analysis_payload: ReportAnalysisPayload,
    quarantined_count: int = 0,
) -> DailyReport:
    if len(clusters) < 3:
        raise ValueError("daily report requires at least three event clusters")
    top_clusters = clusters[:5]
    cluster_by_id = {cluster.event_id: cluster for cluster in clusters}
    expected_top_ids = [cluster.event_id for cluster in top_clusters]
    narrative_top_ids = [section.event_id for section in analysis_payload.top_events]
    if narrative_top_ids != expected_top_ids:
        raise ValueError("report analysis does not match the deterministic Top event ranking")
    unknown_trend_ids = {
        event_id
        for trend in analysis_payload.trends
        for event_id in trend.supporting_event_ids
        if event_id not in cluster_by_id
    }
    if unknown_trend_ids:
        raise ValueError(f"report analysis references unknown events: {sorted(unknown_trend_ids)}")
    known_fact_ids = {
        fact.fact_id for cluster in clusters for fact in cluster.supporting_facts
    }
    analysis_fact_ids = {
        *analysis_payload.executive_summary_fact_ids,
        *(
            fact_id
            for section in analysis_payload.top_events
            for fact_id in [*section.background_fact_ids, *section.impact_fact_ids]
        ),
        *(
            fact_id
            for section in analysis_payload.trends
            for fact_id in section.supporting_fact_ids
        ),
    }
    unknown_fact_ids = analysis_fact_ids - known_fact_ids
    if unknown_fact_ids:
        raise ValueError(
            f"report analysis references unknown facts: {sorted(unknown_fact_ids)}"
        )
    model_names = "、".join(sorted({insight.model_name for insight in insights}))
    top_events = [
        SupportedAnalysis(
            title=cluster_by_id[section.event_id].canonical_title,
            analysis=(
                f"背景：{section.background} "
                f"影响判断：{section.impact_analysis}"
            ),
            source_item_ids=cluster_by_id[section.event_id].member_item_ids,
            supporting_fact_ids=list(
                dict.fromkeys(
                    [*section.background_fact_ids, *section.impact_fact_ids]
                )
            ),
        )
        for section in analysis_payload.top_events
    ]
    trends = [
        SupportedAnalysis(
            title=TREND_TITLES[section.dimension],
            analysis=section.analysis,
            source_item_ids=list(
                dict.fromkeys(
                    item_id
                    for event_id in section.supporting_event_ids
                    for item_id in cluster_by_id[event_id].member_item_ids
                )
            ),
            supporting_fact_ids=section.supporting_fact_ids,
        )
        for section in analysis_payload.trends
    ]
    return DailyReport(
        report_date=report_date,
        title=f"AI 舆情分析日报 · {report_date.isoformat()}",
        executive_summary=(
            f"{analysis_payload.executive_summary} "
            f"本期覆盖 {len(items)} 条信息，形成 {len(clusters)} 个独立事件；"
            f"语义字段由 {model_names} 逐条抽取；所有结论均链接到来源 ID。"
            f"有 {quarantined_count} 条未通过质量门并被隔离，不进入趋势判断。"
        ),
        executive_summary_fact_ids=analysis_payload.executive_summary_fact_ids,
        top_events=top_events,
        trends=trends,
        risks=_alert_analyses(clusters, insights, AlertType.RISK),
        opportunities=_alert_analyses(clusters, insights, AlertType.OPPORTUNITY),
        coverage=CoverageSummary(
            input_count=len(items),
            valid_insight_count=len(insights),
            quarantined_count=quarantined_count,
            event_count=len(clusters),
            source_types=sorted({item.source_type for item in items}, key=lambda value: value.value),
            languages=sorted({item.language for item in items}, key=lambda value: value.value),
        ),
        generated_at=generated_at,
        prompt_version="report-v3",
    )


def _render_templates(
    *,
    project_root: Path,
    report: DailyReport,
    items: list[Any],
    clusters: list[EventCluster],
    markdown_path: Path,
    html_path: Path,
    chart_paths: dict[str, Path],
) -> None:
    environment = Environment(
        loader=FileSystemLoader(project_root / "templates"),
        autoescape=select_autoescape(("html", "xml")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    item_by_id = {item.id: item for item in items}
    fact_by_id = {
        fact.fact_id: fact
        for cluster in clusters
        for fact in cluster.supporting_facts
    }
    fact_source_id_by_id = {
        fact_id: fact_id.partition(".")[0] for fact_id in fact_by_id
    }

    def unique_source_names(item_ids: list[str]) -> list[str]:
        return list(dict.fromkeys(item_by_id[item_id].source_name for item_id in item_ids))

    context = {
        "report": report,
        "items": items,
        "item_by_id": item_by_id,
        "fact_by_id": fact_by_id,
        "fact_source_id_by_id": fact_source_id_by_id,
        "executive_source_item_ids": list(
            dict.fromkeys(
                fact_source_id_by_id[fact_id]
                for fact_id in report.executive_summary_fact_ids
            )
        ),
        "unique_source_names": unique_source_names,
        "chart_paths": {name: path.name for name, path in chart_paths.items()},
        "chart_svg": {
            name: path.read_text(encoding="utf-8") for name, path in chart_paths.items()
        },
    }
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        environment.get_template("daily_report.md.j2").render(**context) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    html_path.write_text(
        environment.get_template("daily_report.html.j2").render(**context) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_charts(
    *,
    items: list[Any],
    clusters: list[EventCluster],
    charts_dir: Path,
) -> dict[str, Path]:
    charts_dir.mkdir(parents=True, exist_ok=True)
    importance_path = charts_dir / "importance.svg"
    topics_path = charts_dir / "topics.svg"
    sources_path = charts_dir / "sources.svg"

    write_bar_chart(
        importance_path,
        [(cluster.canonical_title, cluster.importance.total) for cluster in clusters[:10]],
        title="Top event importance",
        value_suffix=" / 5",
        max_value=5,
    )
    topic_counts = Counter(topic for cluster in clusters for topic in cluster.topics)
    write_bar_chart(
        topics_path,
        [(topic, float(count)) for topic, count in topic_counts.most_common(10)],
        title="Topic distribution",
    )
    source_counts = Counter(item.source_type.value for item in items)
    write_bar_chart(
        sources_path,
        [(source_type, float(count)) for source_type, count in source_counts.most_common()],
        title="Source type coverage",
    )
    return {"importance": importance_path, "topics": topics_path, "sources": sources_path}


def generate_report_artifacts(
    *,
    raw_path: Path,
    insight_path: Path,
    event_path: Path,
    analysis_path: Path,
    output_json_path: Path,
    output_markdown_path: Path,
    output_html_path: Path,
    charts_dir: Path,
    manifest_path: Path,
    project_root: Path,
    report_date: date,
    generated_at: datetime,
    manifest_root: Path | None = None,
) -> dict[str, Any]:
    items = load_raw_items(raw_path)
    insights = load_insights(insight_path)
    clusters = load_clusters(event_path)
    analysis_payload = ReportAnalysisPayload.model_validate_json(
        analysis_path.read_text(encoding="utf-8")
    )
    report = build_daily_report(
        report_date=report_date,
        generated_at=generated_at,
        items=items,
        insights=insights,
        clusters=clusters,
        analysis_payload=analysis_payload,
        quarantined_count=len(items) - len(insights),
    )
    chart_paths = _write_charts(
        items=items,
        clusters=clusters,
        charts_dir=charts_dir,
    )
    _render_templates(
        project_root=project_root,
        report=report,
        items=items,
        clusters=clusters,
        markdown_path=output_markdown_path,
        html_path=output_html_path,
        chart_paths=chart_paths,
    )
    write_json(output_json_path, report)
    manifest: dict[str, Any] = {
        "stage": "report",
        "report_date": report_date.isoformat(),
        "generated_at": generated_at.isoformat(),
        "raw_sha256": sha256_file(raw_path),
        "insight_sha256": sha256_file(insight_path),
        "event_sha256": sha256_file(event_path),
        "analysis_sha256": sha256_file(analysis_path),
        "output_json_path": portable_path(output_json_path, manifest_root),
        "output_markdown_path": portable_path(output_markdown_path, manifest_root),
        "output_html_path": portable_path(output_html_path, manifest_root),
        "chart_paths": {
            name: portable_path(path, manifest_root) for name, path in chart_paths.items()
        },
        "top_event_count": len(report.top_events),
        "trend_count": len(report.trends),
        "risk_count": len(report.risks),
        "opportunity_count": len(report.opportunities),
        "prompt_version": report.prompt_version,
        "schema_version": report.schema_version,
    }
    write_json(manifest_path, manifest)
    return manifest
