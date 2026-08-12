"""Tests for normalization, exact deduplication, and preparation artifacts."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from daily_ai_insight.data import load_source_items
from daily_ai_insight.pipeline.candidates import generate_event_candidates
from daily_ai_insight.pipeline.deduplicate import exact_deduplicate
from daily_ai_insight.pipeline.normalize import (
    calculate_content_hash,
    materialize_raw_item,
    normalize_text,
)
from daily_ai_insight.pipeline.prepare import prepare_dataset


class NormalizationTests(unittest.TestCase):
    def test_normalize_text_collapses_unicode_and_whitespace(self) -> None:
        self.assertEqual(normalize_text("ＡＩ\n  news\titem"), "AI news item")

    def test_content_hash_is_stable_after_whitespace_normalization(self) -> None:
        first = calculate_content_hash(title="AI  release", content="one\n two")
        second = calculate_content_hash(title="AI release", content="one two")
        self.assertEqual(first, second)


class DeduplicationTests(unittest.TestCase):
    def test_duplicate_content_is_removed(self) -> None:
        source = load_source_items(PROJECT_ROOT / "data" / "input" / "2026-08-12.json")[0]
        collected_at = datetime(2026, 8, 12, 4, tzinfo=UTC)
        first = materialize_raw_item(source, collected_at=collected_at)
        duplicate_payload = source.model_dump()
        duplicate_payload.update(
            {
                "id": "news_duplicate",
                "source_url": "https://example.com/duplicate-coverage",
            }
        )
        duplicate = materialize_raw_item(
            source.__class__.model_validate(duplicate_payload),
            collected_at=collected_at,
        )

        result = exact_deduplicate([first, duplicate])

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.duplicates[0].reason, "same_normalized_content")
        self.assertEqual(result.duplicates[0].retained_item_id, first.id)


class PrepareDatasetTests(unittest.TestCase):
    def test_daybreak_items_become_event_comparison_candidates(self) -> None:
        sources = load_source_items(PROJECT_ROOT / "data" / "input" / "2026-08-12.json")
        collected_at = datetime(2026, 8, 12, 4, tzinfo=UTC)
        raw_items = [
            materialize_raw_item(source, collected_at=collected_at) for source in sources
        ]

        pairs = generate_event_candidates(raw_items)
        pair_ids = {
            frozenset((pair.left_item_id, pair.right_item_id)) for pair in pairs
        }

        self.assertIn(frozenset(("news_006", "news_007")), pair_ids)

    def test_prepare_committed_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            output_path = temporary / "raw.jsonl"
            manifest_path = temporary / "manifest.json"

            manifest = prepare_dataset(
                input_path=PROJECT_ROOT / "data" / "input" / "2026-08-12.json",
                output_path=output_path,
                manifest_path=manifest_path,
                report_date=date(2026, 8, 12),
                collected_at=datetime(2026, 8, 12, 4, tzinfo=UTC),
            )

            lines = output_path.read_text(encoding="utf-8").splitlines()
            persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(lines), 16)
            self.assertEqual(manifest["output_count"], 16)
            self.assertEqual(persisted_manifest["duplicate_count"], 0)
            self.assertGreaterEqual(persisted_manifest["event_candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
