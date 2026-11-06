# DataMate 2026 baseline


<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/PyTorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white" alt="PyTorch">
  <img src="https://img.shields.io/badge/TensorFlow-FF6F00?style=for-the-badge&logo=tensorflow&logoColor=white" alt="TensorFlow">
  <img src="https://img.shields.io/badge/Scikit--Learn-F7931E?style=for-the-badge&logo=scikitlearn&logoColor=white" alt="Scikit-learn">
  <img src="https://img.shields.io/badge/NumPy-013243?style=for-the-badge&logo=numpy&logoColor=white" alt="NumPy">
  <img src="https://img.shields.io/badge/Pandas-150458?style=for-the-badge&logo=pandas&logoColor=white" alt="Pandas">
  <img src="https://img.shields.io/badge/Jupyter-F37626?style=for-the-badge&logo=jupyter&logoColor=white" alt="Jupyter">
</p>

CPU-first, modular baseline for Vietnamese question answering over CSV, Excel, and SQLite business packages. It reads an `as_of_date`, profiles schemas, loads business notes and rulebooks, plans a constrained query, executes read-only SQL, and emits one JSON object per line.

## Status and official compatibility

The workspace initially contained no competition kit, datasets, evaluator, or submission instructions. The official challenge page confirms the input fields `id`, `business_id`, `question`, `as_of_date`; supported source formats CSV/XLSX/SQLite; answer categories (value, `unanswerable`, `abstain`); and a sample output with `id`, `type`, `answer`. The exact evaluation formula, control-answer serialization, data layout, runtime/resource limits, calendar schema, and model-track constraints have not been verified. Output serialization for `unanswerable` and `abstain` is therefore provisional and isolated in `output/formatter.py`.

This repository is not represented as a high-scoring or official-kit-compatible submission. No training or test labels have been invented. The example data is synthetic and lives only under `examples/`.

## Run

Python 3.11+ is supported. On Windows, from this directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m datamate.cli --data-root examples/data --questions examples/questions.jsonl --output outputs/demo.jsonl --config configs/default.json --metrics outputs/demo.metrics.json
```

Or install dependencies and run `python -m datamate.cli ...` with `PYTHONPATH=src`.

Optional local LLM planning uses an OpenAI-compatible endpoint. Copy `.env.example` values into your process environment; no API is called unless a base URL and model are configured. The deterministic baseline remains available as fallback. The adapter has not been benchmarked against a model or competition evaluator.

## Data layout

Each business gets one directory named by `business_id`. Supported package files can be mixed in that directory. Place business-specific `README.md` and `RULEBOOK.md` beside the data. A shared `RULEBOOK.md` can sit at the data root. Use explicit rule directives when machine application is required:

```text
RULE [priority=20]: metric.revenue = quantity * unit_price
RULE [priority=20]: exclude.revenue = status in cancelled, returned
```

Directive formulas accept column identifiers and basic `+ - * /` arithmetic. If equally ranked applicable rules conflict, the agent abstains. Plain prose is retained in the retrieved business context but is not silently converted into executable logic.

## Current baseline coverage

- CSV encodings/delimiters, Excel sheets, and read-only SQLite table extraction.
- Conservative type inference; ambiguous numeric/date strings are preserved as text.
- Schema catalog with samples, null/distinct counts, key candidates, and tentative foreign-key relations.
- Relative solar-date ranges anchored only to `as_of_date` (day, week, month, quarter, year, previous period, and same period last year).
- Single-table count, sum/average, and top-group queries for common sales semantics.
- SQLite authorizer, query-only mode, row cap, time/VM-step limits, and structured query logs.
- Optional local OpenAI-compatible SQL planner; every proposed query passes the same safety gate.

Multi-table SQL can be proposed by a configured LLM and is constrained to discovered tables, but join correctness is not fully proven. Lunar dates, broad typo repair, general multi-hop reasoning, rich table/list answer rendering, and official scoring are not yet implemented or verified. Unsupported or ambiguous requests abstain.

## Tests

Run `python -m pytest`. See `TEST_REPORT.md` for the latest command and result. The included evaluator reports exact-match, abstain/unanswerable rates, and optional measured latency; it does not reproduce the official score.

