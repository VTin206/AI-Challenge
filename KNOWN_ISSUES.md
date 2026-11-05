# Known issues and limits

- No official development kit, data, rulebook, solar-lunar calendar, evaluator, or submission guidance was present in the workspace.
- The official portal's detailed Evaluation/Data/Rule/Submission Guidance content could not be retrieved from the public configuration endpoint during this run. The broad overview is verified, but exact scoring and serialization are not.
- `unanswerable` and `abstain` use a provisional `{id,type,answer:null}` serialization. Change it when the official contract is known.
- Deterministic Vietnamese understanding covers a small set of common sales queries. It is not a general Vietnamese semantic parser, and typo/diacritic normalization does not resolve intent by itself.
- SQL authorizer and resource limits constrain execution, but do not prove business correctness, aggregation grain, or join cardinality.
- Join validation currently admits only one equality join matching a high-confidence many-to-one candidate; it does not infer arbitrary multi-hop join plans.
- Schema relation inference is heuristic and advisory only.
- Lunar calendar conversion is not implemented; the official calendar format is unknown.
- Full table/list rendering, broad multi-table deterministic planning, and evaluator score reproduction remain open.
- Optional LLM integration requires a locally available OpenAI-compatible runtime and has not been tested with model weights; Ollama is not installed in this environment.
- No representative/public-data benchmark or official scoring/accuracy claim is available. A four-question synthetic latency measurement is recorded in `TEST_REPORT.md` and should not be generalized.

