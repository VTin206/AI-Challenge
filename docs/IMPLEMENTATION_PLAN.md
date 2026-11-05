# Implementation plan

## Phase 1 — analysis

- [x] Inspect workspace and official DataMate portal.
- [x] Record available official input/output facts and unresolved details.
- [x] Create architecture and implementation plan.

## Phase 2 — initialization

- [x] Create Python package, config, examples, CLI, and project metadata.
- [x] Verify environment setup and install requirements in a project virtual environment.
- [x] Verify CLI startup and configured limits.

## Phase 3 — baseline

- [x] Implement CSV/XLSX/SQLite ingestion and schema profiling.
- [x] Implement rulebook loading and explicit conflict handling.
- [x] Implement safe SQLite execution, temporal resolver, deterministic planner, formatter.
- [x] Run unit/integration tests and repair failures.
- [x] Record results in `TEST_REPORT.md`.

## Phase 4 — optional agent

- [x] Add opt-in OpenAI-compatible planner interface for local model runtimes.
- [ ] Verify against an installed local model and approved track requirements.
- [ ] Add retries and semantic query-repair only after evaluator feedback.

## Phase 5 — evaluation and optimization

- [ ] Integrate official evaluation software once available in the workspace.
- [x] Build non-official exact-match/abstain/unanswerable and latency report tooling.
- [ ] Run error breakdown on permitted official development data.
- [ ] Benchmark candidate SLMs under verified resource and track limits.

## Phase 6 — submission

- [ ] Confirm submission entrypoint, output contract, packaging, offline mode, and resource limits from the official kit.
- [ ] Run official evaluator on authorized public data only.
- [ ] Package the verified solution.

