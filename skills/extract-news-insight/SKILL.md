---
name: extract-news-insight
description: Extract one normalized AI news item into the project's evidence-grounded InsightPayload schema. Use for per-item entity, event, fact, sentiment, impact, risk, and opportunity extraction before event clustering or report generation.
---

# Extract News Insight

Process exactly one supplied source item. Do not use outside knowledge.

1. Classify the main event using only the allowed `EventType` values.
2. Assign 1-8 concise topics. Avoid synonyms that duplicate one another.
3. Extract only explicitly named entities. Do not infer people, organizations, models, or locations.
4. Write 1-12 atomic facts. For every fact, copy a short evidence span that occurs verbatim in the supplied normalized content.
5. Write the neutral summary in Chinese and include no fact absent from the evidence.
6. Add sentiment only when a clear target and attitude are present. Write its rationale in Chinese and use `unknown` when evidence is insufficient.
7. Score technology, application, policy, and capital impact from 0-5. Explain the scores in Chinese without inventing market data.
8. Add a risk or opportunity only when it cites known fact IDs, and write its description in Chinese.
9. Set confidence below 0.60 when the source is ambiguous or too thin for reliable extraction.

Return only the requested `InsightPayload`. Never add operational metadata such as model name, prompt version, source ID, or extraction time.
