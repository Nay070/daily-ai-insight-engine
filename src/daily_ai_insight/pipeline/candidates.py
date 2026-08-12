"""Generate cheap deterministic candidate pairs before semantic event comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations

from daily_ai_insight.domain.models import RawNewsItem
from daily_ai_insight.pipeline.normalize import normalize_text

TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]{2,}", re.IGNORECASE)
STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "is",
    "of",
    "on",
    "the",
    "to",
    "with",
    "introduces",
    "introducing",
    "releases",
}


@dataclass(frozen=True)
class EventCandidatePair:
    left_item_id: str
    right_item_id: str
    title_similarity: float
    shared_tokens: tuple[str, ...]


def title_tokens(title: str) -> set[str]:
    return {
        token
        for token in TOKEN.findall(normalize_text(title).casefold())
        if token not in STOPWORDS and len(token) > 1
    }


def generate_event_candidates(
    items: list[RawNewsItem] | tuple[RawNewsItem, ...],
    *,
    similarity_threshold: float = 0.25,
    minimum_shared_tokens: int = 2,
) -> tuple[EventCandidatePair, ...]:
    """Return pairs whose normalized titles warrant semantic comparison."""

    candidates: list[EventCandidatePair] = []
    token_sets = {item.id: title_tokens(item.title) for item in items}

    for left, right in combinations(items, 2):
        left_tokens = token_sets[left.id]
        right_tokens = token_sets[right.id]
        shared = left_tokens & right_tokens
        union = left_tokens | right_tokens
        similarity = len(shared) / len(union) if union else 0.0
        if len(shared) >= minimum_shared_tokens and similarity >= similarity_threshold:
            candidates.append(
                EventCandidatePair(
                    left_item_id=left.id,
                    right_item_id=right.id,
                    title_similarity=round(similarity, 4),
                    shared_tokens=tuple(sorted(shared)),
                )
            )

    return tuple(candidates)

