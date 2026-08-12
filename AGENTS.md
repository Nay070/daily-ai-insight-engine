# Daily AI Insight Engine

## Mission

Build a reproducible, evidence-grounded AI news analysis pipeline. The system must turn
10-20 recent Chinese and English source items into validated structured data, event-level
insights, a readable daily report, and deterministic visualizations.

## Non-negotiable rules

- Never invent a fact, date, number, entity, quotation, source, or URL.
- Every material analytical claim must reference one or more fact IDs that map to source item IDs and literal evidence.
- Never send the entire raw dataset to a model in a single request.
- Extract one item at a time or in explicitly bounded small batches.
- Model output must pass the Pydantic schema and evidence checks before downstream use.
- A quoted evidence span must occur verbatim in the normalized source content.
- Failed or low-confidence items go to `data/quarantine/`; do not silently discard them.
- Rank event clusters, not individual articles, so duplicate coverage cannot dominate Top N.
- Generate charts only from validated structured data.
- Preserve raw inputs, prompts, schema versions, model settings, and run metadata.
- Do not commit secrets. Read credentials from environment variables.

## Required workflow

`collect -> normalize -> exact_deduplicate -> extract -> validate -> cluster -> rank -> analyze -> render -> verify`

Each stage must have an explicit input and output contract. Deterministic code owns parsing,
validation, scoring, rendering, and quality gates. The language model is used only for bounded
per-item extraction and event-digest report analysis; it never receives the full raw dataset.

## Definition of done

- A fresh environment can install and run the project using documented commands.
- At least 10 recent source items across at least 3 source types are included.
- All committed structured outputs validate against the current schema.
- The sample report contains 3-5 top events plus source and fact IDs for every key conclusion.
- Invalid model output is retried with a bounded budget, then quarantined.
- A single command reproduces the committed sample output from committed raw data.
- Automated tests cover schema validation, evidence grounding, deduplication, scoring, and report references.
- `run_manifest.json` records input hash, prompt/schema versions, model, counts, failures, time, and usage.

## Engineering conventions

- Use Python 3.11+ and type annotations.
- Keep provider-specific model code behind an adapter boundary.
- Prefer pure functions for deterministic stages.
- Use timezone-aware timestamps and ISO 8601 for serialization.
- Add tests with every behavioral change.
- Keep prompts in versioned files under `prompts/`; do not hide prompts inside application code.
