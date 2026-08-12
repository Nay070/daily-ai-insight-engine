"""Integration tests for event ranking, report references, charts, and final gates."""

from __future__ import annotations

import tempfile
from pathlib import Path

from daily_ai_insight.reporting.generate import load_clusters
from daily_ai_insight.reporting.verify import verify_report_artifacts

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_committed_events_are_ranked_and_cover_items_once() -> None:
    clusters = load_clusters(
        PROJECT_ROOT / "data" / "processed" / "2026-08-12" / "events.jsonl"
    )
    totals = [cluster.importance.total for cluster in clusters]
    member_ids = [item_id for cluster in clusters for item_id in cluster.member_item_ids]

    assert totals == sorted(totals, reverse=True)
    assert len(clusters) == 15
    assert len(member_ids) == len(set(member_ids)) == 16
    assert any(
        cluster.member_item_ids == ["news_006", "news_007"] for cluster in clusters
    )


def test_committed_report_passes_all_final_gates() -> None:
    with tempfile.TemporaryDirectory() as directory:
        result = verify_report_artifacts(
            raw_path=PROJECT_ROOT / "data" / "raw" / "2026-08-12.jsonl",
            insight_path=PROJECT_ROOT
            / "data"
            / "processed"
            / "2026-08-12"
            / "insights.jsonl",
            event_path=PROJECT_ROOT
            / "data"
            / "processed"
            / "2026-08-12"
            / "events.jsonl",
            report_json_path=PROJECT_ROOT / "reports" / "2026-08-12" / "report.json",
            markdown_path=PROJECT_ROOT / "reports" / "2026-08-12" / "report.md",
            html_path=PROJECT_ROOT / "reports" / "2026-08-12" / "report.html",
            chart_paths=[
                PROJECT_ROOT / "reports" / "2026-08-12" / "charts" / "importance.svg",
                PROJECT_ROOT / "reports" / "2026-08-12" / "charts" / "topics.svg",
                PROJECT_ROOT / "reports" / "2026-08-12" / "charts" / "sources.svg",
            ],
            output_path=Path(directory) / "verification.json",
        )

    assert result["passed"] is True
    assert len(result["checks"]) == 8
    assert result["top_event_count"] == 5
