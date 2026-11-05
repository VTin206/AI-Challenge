# Test report

**Status:** Local baseline verified; official evaluator not available.

## Environment and checks

- Environment: full suite on Python 3.12.10 virtual environment on Windows; project declares Python `>=3.11`. CLI also ran successfully under the installed Python 3.11.7 runtime.
- Dependencies: openpyxl 3.1.5 and pytest 8.4.2 installed from PyPI into `.venv`.
- `python -m pytest -q`: **21 passed** in 42.65 seconds on Python 3.12.10.
- `python -m compileall -q src tests scripts`: passed.
- CLI generated four JSONL records from the synthetic package under both Python runtimes. Observed answers: revenue `469000`, top product `Trà sữa truyền thống`, order count `7`, lunar-month question `abstain`.
- The latest synthetic CLI run recorded four wall-time values; observed mean was `5.78 ms`, P95 `22.20 ms`. The first record includes package loading. This tiny fixture measurement is not representative of competition latency.

Test areas include mixed file loading, schema/key/relationship inference, strict number parsing, relative date boundaries/year/leap-day handling, read-only SQL and external-access rejection, verified join direction, rule conflicts, JSONL formatting, evaluation metrics, and synthetic end-to-end behavior.

The evaluator reports no official score (`official_score: null`) because the official score definition and evaluator were not available in the workspace.

