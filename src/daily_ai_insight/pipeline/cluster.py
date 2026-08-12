"""Deterministic event materialization and importance scoring."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import Field, TypeAdapter

from daily_ai_insight.data import load_raw_items
from daily_ai_insight.domain.models import (
    EventCluster,
    EventType,
    EvidenceFact,
    ImportanceScore,
    NewsInsight,
    SourceType,
    StrictModel,
)
from daily_ai_insight.paths import portable_path
from daily_ai_insight.pipeline.prepare import sha256_file
from daily_ai_insight.storage import write_json, write_jsonl

INSIGHT_LIST = TypeAdapter(list[NewsInsight])

SOURCE_AUTHORITY = {
    SourceType.OFFICIAL: 5.0,
    SourceType.RESEARCH: 4.5,
    SourceType.CODE_RELEASE: 4.5,
    SourceType.TECHNOLOGY_MEDIA: 4.0,
    SourceType.COMMUNITY: 3.0,
    SourceType.AGGREGATOR: 2.5,
}

NOVELTY = {
    EventType.MODEL_RELEASE: 4.5,
    EventType.PRODUCT_RELEASE: 4.0,
    EventType.RESEARCH: 4.0,
    EventType.FUNDING: 3.0,
    EventType.ACQUISITION: 4.0,
    EventType.PARTNERSHIP: 3.5,
    EventType.POLICY: 4.5,
    EventType.SAFETY: 4.5,
    EventType.SECURITY_INCIDENT: 5.0,
    EventType.ADOPTION: 3.5,
    EventType.OTHER: 2.5,
}


class EventMergeSpec(StrictModel):
    member_item_ids: list[str] = Field(min_length=2)
    canonical_title: str = Field(min_length=5, max_length=500)
    summary: str = Field(min_length=20, max_length=1500)
    event_type: EventType


MERGE_LIST = TypeAdapter(list[EventMergeSpec])


def load_insights(path: Path) -> list[NewsInsight]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return INSIGHT_LIST.validate_python(records)


def load_merge_specs(path: Path) -> list[EventMergeSpec]:
    return MERGE_LIST.validate_python(json.loads(path.read_text(encoding="utf-8")))


def _recency_score(age_days: int) -> float:
    if age_days <= 1:
        return 5.0
    if age_days <= 3:
        return 4.5
    if age_days <= 7:
        return 4.0
    if age_days <= 14:
        return 3.0
    if age_days <= 30:
        return 2.0
    return 1.0


def score_event(
    member_items: list[Any], member_insights: list[NewsInsight], *, report_date: date
) -> ImportanceScore:
    """Calculate a transparent 0-5 score from validated, non-generative fields."""

    alert_count = sum(len(insight.alerts) for insight in member_insights)
    unique_topics = {topic.casefold() for insight in member_insights for topic in insight.topics}
    relevance = min(5.0, 3.4 + min(len(unique_topics), 4) * 0.25 + min(alert_count, 2) * 0.3)

    impact = sum(
        max(
            insight.impact.technology,
            insight.impact.application,
            insight.impact.policy,
            insight.impact.capital,
        )
        for insight in member_insights
    ) / len(member_insights)
    source_authority = sum(SOURCE_AUTHORITY[item.source_type] for item in member_items) / len(
        member_items
    )
    unique_sources = {item.source_name.casefold() for item in member_items}
    cross_source_coverage = min(5.0, 1.0 + 2.0 * (len(unique_sources) - 1))
    event_type = Counter(insight.event_type for insight in member_insights).most_common(1)[0][0]
    novelty = NOVELTY[event_type]
    newest_date = max(item.published_at.date() for item in member_items)
    recency = _recency_score(max(0, (report_date - newest_date).days))
    total = (
        relevance * 0.20
        + impact * 0.25
        + source_authority * 0.15
        + cross_source_coverage * 0.15
        + novelty * 0.10
        + recency * 0.15
    )
    return ImportanceScore(
        relevance=round(relevance, 2),
        impact=round(impact, 2),
        source_authority=round(source_authority, 2),
        cross_source_coverage=round(cross_source_coverage, 2),
        novelty=round(novelty, 2),
        recency=round(recency, 2),
        total=round(total, 2),
        methodology_version="importance-v1",
    )


def build_event_clusters(
    *,
    items: list[Any],
    insights: list[NewsInsight],
    merge_specs: list[EventMergeSpec],
    report_date: date,
) -> list[EventCluster]:
    raw_item_by_id = {item.id: item for item in items}
    insight_by_id = {insight.item_id: insight for insight in insights}
    extra = sorted(set(insight_by_id) - set(raw_item_by_id))
    if extra:
        raise ValueError(f"insights reference unknown raw items: {extra}")
    item_by_id = {item_id: raw_item_by_id[item_id] for item_id in insight_by_id}

    grouped_ids: set[str] = set()
    declared_merge_ids: set[str] = set()
    groups: list[tuple[list[str], EventMergeSpec | None]] = []
    for spec in merge_specs:
        if len(spec.member_item_ids) != len(set(spec.member_item_ids)):
            raise ValueError("merge member IDs must be unique")
        unknown = set(spec.member_item_ids) - set(raw_item_by_id)
        overlap = set(spec.member_item_ids) & declared_merge_ids
        if unknown or overlap:
            raise ValueError(f"invalid merge spec; unknown={sorted(unknown)}, overlap={sorted(overlap)}")
        declared_merge_ids.update(spec.member_item_ids)
        available_ids = sorted(set(spec.member_item_ids) & set(insight_by_id))
        if len(available_ids) < 2:
            continue
        grouped_ids.update(available_ids)
        groups.append((available_ids, spec))

    groups.extend(([item_id], None) for item_id in sorted(set(item_by_id) - grouped_ids))
    groups.sort(key=lambda group: group[0][0])

    clusters: list[EventCluster] = []
    for index, (member_ids, spec) in enumerate(groups, start=1):
        member_items = [item_by_id[item_id] for item_id in member_ids]
        member_insights = [insight_by_id[item_id] for item_id in member_ids]
        facts = [
            EvidenceFact(
                fact_id=f"{insight.item_id}.{fact.fact_id}",
                claim=fact.claim,
                evidence=fact.evidence,
            )
            for insight in member_insights
            for fact in insight.key_facts
        ]
        topics = list(
            dict.fromkeys(topic for insight in member_insights for topic in insight.topics)
        )[:10]
        clusters.append(
            EventCluster(
                event_id=f"event_{index:03d}",
                canonical_title=spec.canonical_title if spec else member_items[0].title,
                event_type=spec.event_type if spec else member_insights[0].event_type,
                topics=topics,
                member_item_ids=member_ids,
                summary=spec.summary if spec else member_insights[0].summary,
                supporting_facts=facts,
                importance=score_event(member_items, member_insights, report_date=report_date),
            )
        )
    return sorted(clusters, key=lambda cluster: (-cluster.importance.total, cluster.event_id))


def cluster_dataset(
    *,
    raw_path: Path,
    insight_path: Path,
    merge_spec_path: Path,
    output_path: Path,
    manifest_path: Path,
    report_date: date,
    manifest_root: Path | None = None,
) -> dict[str, Any]:
    items = load_raw_items(raw_path)
    insights = load_insights(insight_path)
    merge_specs = load_merge_specs(merge_spec_path)
    clusters = build_event_clusters(
        items=items,
        insights=insights,
        merge_specs=merge_specs,
        report_date=report_date,
    )
    write_jsonl(output_path, clusters)
    available_ids = {insight.item_id for insight in insights}
    applied_merge_spec_count = sum(
        len(set(spec.member_item_ids) & available_ids) >= 2 for spec in merge_specs
    )
    manifest: dict[str, Any] = {
        "stage": "cluster",
        "report_date": report_date.isoformat(),
        "raw_path": portable_path(raw_path, manifest_root),
        "raw_sha256": sha256_file(raw_path),
        "insight_path": portable_path(insight_path, manifest_root),
        "insight_sha256": sha256_file(insight_path),
        "merge_spec_path": portable_path(merge_spec_path, manifest_root),
        "merge_spec_sha256": sha256_file(merge_spec_path),
        "output_path": portable_path(output_path, manifest_root),
        "input_item_count": len(items),
        "event_count": len(clusters),
        "merged_event_count": sum(len(cluster.member_item_ids) > 1 for cluster in clusters),
        "applied_merge_spec_count": applied_merge_spec_count,
        "skipped_merge_spec_count": len(merge_specs) - applied_merge_spec_count,
        "methodology_version": "importance-v1",
        "schema_version": "1.0",
    }
    write_json(manifest_path, manifest)
    return manifest
