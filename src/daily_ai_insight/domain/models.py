"""Versioned Pydantic contracts for raw news, extracted insights, and reports."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
SchemaVersion = Literal["1.0"]
ReportSchemaVersion = Literal["1.1"]


class StrictModel(BaseModel):
    """Reject unknown fields so upstream changes fail visibly."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Language(StrEnum):
    ZH = "zh"
    EN = "en"
    MIXED = "mixed"
    OTHER = "other"


class SourceType(StrEnum):
    OFFICIAL = "official"
    TECHNOLOGY_MEDIA = "technology_media"
    RESEARCH = "research"
    CODE_RELEASE = "code_release"
    COMMUNITY = "community"
    AGGREGATOR = "aggregator"


class ContentKind(StrEnum):
    EDITORIAL_SUMMARY = "editorial_summary"
    SOURCE_EXCERPT = "source_excerpt"
    FULL_TEXT = "full_text"


class TimestampPrecision(StrEnum):
    DATETIME = "datetime"
    DATE = "date"
    MONTH = "month"


class EventType(StrEnum):
    MODEL_RELEASE = "model_release"
    PRODUCT_RELEASE = "product_release"
    RESEARCH = "research"
    FUNDING = "funding"
    ACQUISITION = "acquisition"
    PARTNERSHIP = "partnership"
    POLICY = "policy"
    SAFETY = "safety"
    SECURITY_INCIDENT = "security_incident"
    ADOPTION = "adoption"
    OTHER = "other"


class EntityType(StrEnum):
    ORGANIZATION = "organization"
    PERSON = "person"
    PRODUCT = "product"
    MODEL = "model"
    TECHNOLOGY = "technology"
    LOCATION = "location"
    REGULATION = "regulation"


class SentimentLabel(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class AlertType(StrEnum):
    RISK = "risk"
    OPPORTUNITY = "opportunity"


class TrendDimension(StrEnum):
    TECHNOLOGY = "technology"
    APPLICATION = "application"
    POLICY = "policy"
    CAPITAL = "capital"


class SourceItemInput(StrictModel):
    """Human-curated input before normalization and collection metadata are added."""

    id: Identifier
    title: str = Field(min_length=3, max_length=500)
    content: str = Field(min_length=20)
    content_kind: ContentKind = ContentKind.EDITORIAL_SUMMARY
    source_name: str = Field(min_length=2, max_length=200)
    source_type: SourceType
    source_url: HttpUrl
    published_at: datetime
    published_at_precision: TimestampPrecision
    language: Language
    author: str | None = Field(default=None, max_length=200)
    selection_reason: str = Field(min_length=10, max_length=500)

    @field_validator("published_at")
    @classmethod
    def input_timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("published_at must include a timezone")
        return value


class RawNewsItem(SourceItemInput):
    """Immutable source record retained for audit and reproducibility."""

    id: Identifier
    collected_at: datetime
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_version: SchemaVersion = "1.0"

    @field_validator("collected_at")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def collection_cannot_predate_publication(self) -> RawNewsItem:
        if self.collected_at < self.published_at:
            raise ValueError("collected_at cannot be earlier than published_at")
        return self


class Entity(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    type: EntityType
    canonical_name: str | None = Field(default=None, max_length=200)


class EvidenceFact(StrictModel):
    fact_id: Identifier
    claim: str = Field(min_length=5, max_length=800)
    evidence: str = Field(min_length=3, max_length=1000)


class TargetSentiment(StrictModel):
    target: str = Field(min_length=2, max_length=200)
    label: SentimentLabel
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=5, max_length=500)


class Impact(StrictModel):
    technology: int = Field(ge=0, le=5)
    application: int = Field(ge=0, le=5)
    policy: int = Field(ge=0, le=5)
    capital: int = Field(ge=0, le=5)
    rationale: str = Field(min_length=10, max_length=1000)


class Alert(StrictModel):
    type: AlertType
    description: str = Field(min_length=5, max_length=800)
    supporting_fact_ids: list[Identifier] = Field(min_length=1)

    @field_validator("supporting_fact_ids")
    @classmethod
    def fact_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("supporting_fact_ids must be unique")
        return values


class InsightPayload(StrictModel):
    """Semantic fields generated by the model for exactly one source item.

    Runtime provenance deliberately lives outside this contract so the model cannot
    invent item IDs, prompt versions, model names, or extraction timestamps.
    """

    event_type: EventType
    topics: list[str] = Field(min_length=1, max_length=8)
    entities: list[Entity] = Field(default_factory=list, max_length=30)
    key_facts: list[EvidenceFact] = Field(min_length=1, max_length=12)
    summary: str = Field(min_length=20, max_length=1200)
    sentiments: list[TargetSentiment] = Field(default_factory=list, max_length=8)
    impact: Impact
    alerts: list[Alert] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0, le=1)

    @field_validator("topics")
    @classmethod
    def topics_must_be_unique(cls, values: list[str]) -> list[str]:
        normalized = [value.casefold() for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("topics must be unique ignoring case")
        return values

    @field_validator("key_facts")
    @classmethod
    def key_fact_ids_must_be_unique(cls, values: list[EvidenceFact]) -> list[EvidenceFact]:
        fact_ids = [fact.fact_id for fact in values]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("key fact IDs must be unique")
        return values

    @model_validator(mode="after")
    def alerts_must_reference_known_facts(self) -> InsightPayload:
        known_fact_ids = {fact.fact_id for fact in self.key_facts}
        referenced = {
            fact_id for alert in self.alerts for fact_id in alert.supporting_fact_ids
        }
        unknown = referenced - known_fact_ids
        if unknown:
            raise ValueError(f"alerts reference unknown fact IDs: {sorted(unknown)}")
        return self


class NewsInsight(InsightPayload):
    """Validated semantic extraction enriched with trusted runtime provenance."""

    item_id: Identifier
    model_name: str = Field(min_length=1, max_length=100)
    prompt_version: Identifier
    extracted_at: datetime
    schema_version: SchemaVersion = "1.0"

    @field_validator("extracted_at")
    @classmethod
    def extracted_at_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("extracted_at must include a timezone")
        return value


class Contradiction(StrictModel):
    description: str = Field(min_length=5, max_length=800)
    source_item_ids: list[Identifier] = Field(min_length=2)


class ImportanceScore(StrictModel):
    relevance: float = Field(ge=0, le=5)
    impact: float = Field(ge=0, le=5)
    source_authority: float = Field(ge=0, le=5)
    cross_source_coverage: float = Field(ge=0, le=5)
    novelty: float = Field(ge=0, le=5)
    recency: float = Field(ge=0, le=5)
    total: float = Field(ge=0, le=5)
    methodology_version: Identifier


class EventCluster(StrictModel):
    event_id: Identifier
    canonical_title: str = Field(min_length=5, max_length=500)
    event_type: EventType
    topics: list[str] = Field(min_length=1, max_length=10)
    member_item_ids: list[Identifier] = Field(min_length=1)
    summary: str = Field(min_length=20, max_length=1500)
    supporting_facts: list[EvidenceFact] = Field(min_length=1, max_length=30)
    contradictions: list[Contradiction] = Field(default_factory=list)
    importance: ImportanceScore
    schema_version: SchemaVersion = "1.0"

    @field_validator("member_item_ids", "topics")
    @classmethod
    def cluster_lists_must_be_unique(cls, values: list[str]) -> list[str]:
        normalized = [value.casefold() for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("cluster list values must be unique")
        return values


class TopEventNarrative(StrictModel):
    event_id: Identifier
    background: str = Field(min_length=20, max_length=1200)
    background_fact_ids: list[Identifier] = Field(min_length=1, max_length=8)
    impact_analysis: str = Field(min_length=20, max_length=1200)
    impact_fact_ids: list[Identifier] = Field(min_length=1, max_length=8)

    @field_validator("background_fact_ids", "impact_fact_ids")
    @classmethod
    def top_fact_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("top event fact IDs must be unique")
        return values


class TrendNarrative(StrictModel):
    dimension: TrendDimension
    analysis: str = Field(min_length=20, max_length=1500)
    supporting_event_ids: list[Identifier] = Field(min_length=1, max_length=5)
    supporting_fact_ids: list[Identifier] = Field(min_length=1, max_length=15)

    @field_validator("supporting_event_ids", "supporting_fact_ids")
    @classmethod
    def supporting_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("supporting IDs must be unique")
        return values


class ReportAnalysisPayload(StrictModel):
    """Bounded model output derived from validated event digests, never raw articles."""

    executive_summary: str = Field(min_length=30, max_length=1800)
    executive_summary_fact_ids: list[Identifier] = Field(min_length=1, max_length=15)
    top_events: list[TopEventNarrative] = Field(min_length=3, max_length=5)
    trends: list[TrendNarrative] = Field(min_length=4, max_length=4)

    @field_validator("executive_summary_fact_ids")
    @classmethod
    def executive_fact_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("executive summary fact IDs must be unique")
        return values

    @model_validator(mode="after")
    def report_analysis_keys_must_be_complete_and_unique(self) -> ReportAnalysisPayload:
        event_ids = [section.event_id for section in self.top_events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("top event IDs must be unique")
        dimensions = [section.dimension for section in self.trends]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("trend dimensions must be unique")
        if set(dimensions) != set(TrendDimension):
            raise ValueError("trends must cover technology, application, policy, and capital")
        return self


class SupportedAnalysis(StrictModel):
    title: str = Field(min_length=3, max_length=300)
    analysis: str = Field(min_length=20, max_length=2000)
    source_item_ids: list[Identifier] = Field(min_length=1)
    supporting_fact_ids: list[Identifier] = Field(min_length=1)

    @field_validator("source_item_ids", "supporting_fact_ids")
    @classmethod
    def support_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("source and fact IDs must be unique")
        return values

    @model_validator(mode="after")
    def facts_must_belong_to_section_sources(self) -> SupportedAnalysis:
        fact_source_ids = {fact_id.partition(".")[0] for fact_id in self.supporting_fact_ids}
        unknown_sources = fact_source_ids - set(self.source_item_ids)
        if unknown_sources:
            raise ValueError(
                "supporting facts reference sources outside the section: "
                f"{sorted(unknown_sources)}"
            )
        return self


class CoverageSummary(StrictModel):
    input_count: int = Field(ge=0)
    valid_insight_count: int = Field(ge=0)
    quarantined_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    source_types: list[SourceType]
    languages: list[Language]

    @model_validator(mode="after")
    def item_counts_must_balance(self) -> CoverageSummary:
        if self.valid_insight_count + self.quarantined_count != self.input_count:
            raise ValueError("valid and quarantined counts must equal input_count")
        return self


class DailyReport(StrictModel):
    report_date: date
    title: str = Field(min_length=5, max_length=300)
    executive_summary: str = Field(min_length=30, max_length=2000)
    executive_summary_fact_ids: list[Identifier] = Field(min_length=1, max_length=15)
    top_events: list[SupportedAnalysis] = Field(min_length=3, max_length=5)
    trends: list[SupportedAnalysis] = Field(min_length=1, max_length=8)
    risks: list[SupportedAnalysis] = Field(default_factory=list, max_length=8)
    opportunities: list[SupportedAnalysis] = Field(default_factory=list, max_length=8)
    coverage: CoverageSummary
    generated_at: datetime
    prompt_version: Identifier
    schema_version: ReportSchemaVersion = "1.1"

    @field_validator("executive_summary_fact_ids")
    @classmethod
    def report_executive_fact_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("executive summary fact IDs must be unique")
        return values

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value
