# Decisions

1. Use Python 3.11+ and the standard-library SQLite engine for a CPU-first baseline. It avoids a large analytical dependency and gives us an authorizer for read-only SQL.
2. Use `openpyxl` for XLSX reading. The deterministic baseline stays stdlib-only; the SLM agent (`datamate.slm`) uses pandas because generated analysis code is written against DataFrames.
3. Retain original labels and source provenance while using safe internal identifiers.
4. Convert only strict numeric strings; preserve ambiguous values as text instead of guessing locale conventions.
5. Use `Decimal` aggregate helpers for exact decimal accumulation. Ordinary SQLite `SUM()` is not used by the deterministic planner for decimal measures.
6. Never use machine wall-clock time in relative-date resolution; require the input `as_of_date`.
7. Ship a deterministic baseline and an opt-in OpenAI-compatible LLM adapter. No model is bundled or claimed benchmarked.
8. Treat output serialization for `unanswerable` and `abstain` as provisional until the official evaluation specification is available.
9. Do not include official or private datasets, labels, model weights, credentials, or generated answers in versioned files.

