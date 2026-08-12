"""Contract tests that run with the Python standard library test runner."""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from daily_ai_insight.domain.models import (
    Alert,
    AlertType,
    Entity,
    EntityType,
    EventType,
    EvidenceFact,
    Impact,
    Language,
    NewsInsight,
    RawNewsItem,
    SourceType,
    TimestampPrecision,
)


class RawNewsItemTests(unittest.TestCase):
    def valid_payload(self) -> dict[str, object]:
        return {
            "id": "news_001",
            "title": "An AI company releases a new model",
            "content": "The company released a new model with improved reasoning capabilities.",
            "source_name": "Example AI",
            "source_type": SourceType.OFFICIAL,
            "source_url": "https://example.com/news/model-release",
            "published_at": datetime(2026, 8, 10, 8, tzinfo=UTC),
            "published_at_precision": TimestampPrecision.DATETIME,
            "language": Language.EN,
            "collected_at": datetime(2026, 8, 10, 9, tzinfo=UTC),
            "content_hash": "a" * 64,
            "selection_reason": "Primary source for a material model release.",
        }

    def test_accepts_valid_item(self) -> None:
        item = RawNewsItem.model_validate(self.valid_payload())
        self.assertEqual(item.schema_version, "1.0")

    def test_rejects_timezone_naive_timestamp(self) -> None:
        payload = self.valid_payload()
        payload["published_at"] = datetime.fromisoformat("2026-08-10T08:00:00")

        with self.assertRaises(ValidationError):
            RawNewsItem.model_validate(payload)

    def test_rejects_unknown_field(self) -> None:
        payload = self.valid_payload()
        payload["unexpected"] = "must fail visibly"

        with self.assertRaises(ValidationError):
            RawNewsItem.model_validate(payload)


class NewsInsightTests(unittest.TestCase):
    def valid_payload(self) -> dict[str, object]:
        return {
            "item_id": "news_001",
            "event_type": EventType.MODEL_RELEASE,
            "topics": ["reasoning", "foundation-model"],
            "entities": [
                Entity(name="Example AI", type=EntityType.ORGANIZATION),
            ],
            "key_facts": [
                EvidenceFact(
                    fact_id="fact_001",
                    claim="Example AI released a new model.",
                    evidence="released a new model",
                )
            ],
            "summary": "Example AI announced a model intended to improve reasoning performance.",
            "sentiments": [],
            "impact": Impact(
                technology=4,
                application=3,
                policy=1,
                capital=2,
                rationale="The release may affect model capability competition and product adoption.",
            ),
            "alerts": [
                Alert(
                    type=AlertType.OPPORTUNITY,
                    description="Teams may evaluate the model for reasoning-heavy workflows.",
                    supporting_fact_ids=["fact_001"],
                )
            ],
            "confidence": 0.85,
            "model_name": "test-model",
            "prompt_version": "extract_v1",
            "extracted_at": datetime(2026, 8, 10, 9, 5, tzinfo=UTC),
        }

    def test_accepts_valid_insight(self) -> None:
        insight = NewsInsight.model_validate(self.valid_payload())
        self.assertEqual(insight.key_facts[0].fact_id, "fact_001")

    def test_rejects_duplicate_topics_ignoring_case(self) -> None:
        payload = self.valid_payload()
        payload["topics"] = ["Reasoning", "reasoning"]

        with self.assertRaises(ValidationError):
            NewsInsight.model_validate(payload)

    def test_rejects_alert_reference_to_unknown_fact(self) -> None:
        payload = self.valid_payload()
        payload["alerts"] = [
            Alert(
                type=AlertType.RISK,
                description="A risk must still be supported by a known fact.",
                supporting_fact_ids=["fact_missing"],
            )
        ]

        with self.assertRaises(ValidationError):
            NewsInsight.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
