"""Validate the primary recent dataset as part of the test suite."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from daily_ai_insight.data import load_source_items, validate_dataset_coverage
from daily_ai_insight.domain.models import ContentKind, Language


class CommittedDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.items = load_source_items(PROJECT_ROOT / "data" / "input" / "2026-08-12.json")

    def test_dataset_meets_coverage_gates(self) -> None:
        coverage = validate_dataset_coverage(
            self.items,
            report_date=date(2026, 8, 12),
        )

        self.assertEqual(coverage.item_count, 16)
        self.assertGreaterEqual(len(coverage.source_types), 3)
        self.assertIn(Language.ZH, coverage.languages)
        self.assertIn(Language.EN, coverage.languages)

    def test_dataset_contains_only_editorial_summaries(self) -> None:
        self.assertTrue(
            all(item.content_kind is ContentKind.EDITORIAL_SUMMARY for item in self.items)
        )

    def test_every_item_is_within_thirty_days_of_report_date(self) -> None:
        report_date = date(2026, 8, 12)
        ages = [(report_date - item.published_at.date()).days for item in self.items]

        self.assertTrue(all(0 <= age <= 30 for age in ages))


if __name__ == "__main__":
    unittest.main()
