from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamate.evaluation import evaluate_predictions


def load_jsonl(path: Path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main():
    parser = argparse.ArgumentParser(description="Non-official exact-match report for known-answer development fixtures")
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--latencies", type=Path)
    args = parser.parse_args()
    latency_rows = load_jsonl(args.latencies) if args.latencies else []
    print(json.dumps(evaluate_predictions(load_jsonl(args.gold), load_jsonl(args.predictions), latency_rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

