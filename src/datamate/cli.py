from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from .agent import DataMateAgent
from .models import Answer, AnswerType, QuestionInput
from .output import write_jsonl
from .util import json_dumps


def _read_questions(path: Path) -> list[QuestionInput]:
    questions = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                questions.append(QuestionInput.from_dict(json.loads(line)))
            except Exception as exc:
                raise ValueError(f"Invalid question on line {line_number}: {exc}") from exc
    return questions


def run(data_root: Path, questions_path: Path, output_path: Path, include_null_control_answer: bool = True, metrics_output: Path | None = None, engine_options: dict | None = None) -> int:
    questions = _read_questions(questions_path)
    agent_cache: dict[str, DataMateAgent | None] = {}
    answers = []
    latencies = []
    for question in questions:
        started = time.perf_counter()
        if question.business_id not in agent_cache:
            # Reject path traversal and keep every package under the configured data root.
            business_id = question.business_id
            if not business_id or Path(business_id).name != business_id or business_id in {".", ".."}:
                agent_cache[business_id] = None
            else:
                package_root = data_root / business_id
                try:
                    agent_cache[business_id] = DataMateAgent.from_directory(package_root, **(engine_options or {}))
                except (FileNotFoundError, OSError, RuntimeError, ValueError):
                    agent_cache[business_id] = None
        agent = agent_cache[question.business_id]
        if agent is None:
            answers.append(Answer(question.id, AnswerType.UNANSWERABLE, None, "Business data package is missing or invalid"))
        else:
            answers.append(agent.answer(question))
        latencies.append({"id": question.id, "latency_ms": round((time.perf_counter() - started) * 1000, 3)})
    write_jsonl(output_path, answers, include_null_control_answer)
    if metrics_output:
        metrics_output.parent.mkdir(parents=True, exist_ok=True)
        metrics_output.write_text(json_dumps({"note": "Non-official per-question wall time; first question for each business includes package loading.", "latencies": latencies}), encoding="utf-8")
    for agent in agent_cache.values():
        if agent is not None:
            agent.close()
    return len(answers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the DataMate question-answering baseline")
    parser.add_argument("--data-root", type=Path, required=True, help="Directory containing one subdirectory per business_id")
    parser.add_argument("--questions", type=Path, required=True, help="Input JSONL with id/business_id/question/as_of_date")
    parser.add_argument("--output", type=Path, required=True, help="Output JSONL destination")
    parser.add_argument("--metrics", type=Path, help="Optional non-submission JSON file with measured per-question latency")
    parser.add_argument("--config", type=Path, help="Optional JSON config for SQL resource limits and output control serialization")
    parser.add_argument("--omit-null-control-answer", action="store_true", help="Omit the answer key for unanswerable/abstain (provisional contract option)")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
        if not isinstance(config, dict):
            raise ValueError("Configuration root must be a JSON object")
        allowed = {"max_sql_seconds", "max_sql_vm_steps", "max_result_rows"}
        engine_options = {key: config[key] for key in allowed if key in config}
        for key, value in engine_options.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"Configuration value {key} must be a positive finite number")
        for key in ("max_sql_vm_steps", "max_result_rows"):
            if key in engine_options and not isinstance(engine_options[key], int):
                raise ValueError(f"Configuration value {key} must be an integer")
        include_null = bool(config.get("output_control_answer_null", True)) and not args.omit_null_control_answer
        count = run(args.data_root, args.questions, args.output, include_null, args.metrics, engine_options)
    except Exception as exc:
        print(f"datamate: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {count} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

