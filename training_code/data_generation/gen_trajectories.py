"""Rejection-sample agent trajectories on the TRAIN split with an open teacher (Qwen3 on vLLM).

Leak guards:
- answers.jsonl is read from its own path; the sandbox sees a staged copy of the split WITHOUT it;
- question ids/texts overlapping public_test abort the run;
- trajectories whose code touches answers/questions files, parent dirs or env vars are rejected.
Pass 1: ``--attempts`` samples, thinking off. Pass 2: ``--retry-attempts`` thinking-on samples for failures.
All raw trajectories (accepted and rejected) are kept under ``<out>/raw/``.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from collections import Counter
from pathlib import Path

from datamate.evaluation.metrics import score_one
from datamate.schema.profiler import render_frame_card
from datamate.slm.agent import run_trajectories
from datamate.slm.engine import GenConfig, build_engine
from datamate.slm.frames import cache_business, load_cached, read_readme
from datamate.slm.prompt import context_block
from datamate.slm.sandbox import Sandbox

LEAK = re.compile(r"answers|questions\.jsonl|\.\./|os\.environ|getenv|open\(|glob|listdir|scandir|subprocess|Path\(", re.I)


def jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def stage_split(split: Path, stage: Path) -> Path:
    """Copy the split minus answers.jsonl so sandboxed code cannot reach labels."""
    if not (stage / "data").exists():
        tmp = stage.with_name(stage.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(split, tmp, ignore=shutil.ignore_patterns("answers.jsonl"))
        tmp.replace(stage)
    assert not (stage / "answers.jsonl").exists()
    return stage


def leaks(traj) -> bool:
    return any(LEAK.search(step["reply"].split("</think>")[-1]) for step in traj.steps if step.get("kind") == "code")


class CannedEngine:
    """--dry-run: one code step, then an unanswerable final. Exercises the pipeline without a GPU."""

    def __init__(self):
        self.cfg = GenConfig(model="canned", backend="canned", max_model_len=10**6)

    def render(self, messages):
        return json.dumps(messages, ensure_ascii=False)

    def count(self, text):
        return len(text) // 4

    def generate(self, prompts, max_tokens, seeds):
        return ['<final>{"type": "unanswerable", "reason": "dry run"}</final>' if "<output>" in json.loads(p)[-1]["content"]
                else "<code>print(list(dfs))</code>" for p in prompts]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--split", required=True, type=Path, help="train split dir (must contain answers.jsonl)")
    p.add_argument("--public-test", type=Path, help="public_test dir, only questions.jsonl is read for overlap checks")
    p.add_argument("--split-file", type=Path, default=Path("configs/split.json"), help="holdout businesses are excluded")
    p.add_argument("--out", type=Path, default=Path("training_code/data"))
    p.add_argument("--work", type=Path, default=Path("/content/work"))
    p.add_argument("--config", type=Path, default=Path("configs/slm.json"))
    p.add_argument("--attempts", type=int, default=1)
    p.add_argument("--retry-attempts", type=int, default=2)
    p.add_argument("--max-hours", type=float, default=6.0)
    p.add_argument("--limit", type=int)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-holdout", action="store_true", help="train on every business (no holdout evaluation possible)")
    a = p.parse_args()

    answers_path = a.split / "answers.jsonl"
    if not answers_path.exists():
        raise SystemExit("refusing: split has no answers.jsonl (never generate on test splits)")
    gold = {g["id"]: g for g in jsonl(answers_path)}
    questions = jsonl(a.split / "questions.jsonl")
    if a.public_test:
        test_q = jsonl(a.public_test / "questions.jsonl")
        key = lambda q: (q["id"],)  # noqa: E731
        triple = lambda q: (q["business_id"], q["question"], q["as_of_date"])  # noqa: E731
        overlap = ({key(q) for q in test_q} & {key(q) for q in questions}) | ({triple(q) for q in test_q} & {triple(q) for q in questions})
        if overlap:
            raise SystemExit(f"refusing: {len(overlap)} questions overlap public_test")
    if a.split_file.exists():
        holdout = set(json.loads(a.split_file.read_text(encoding="utf-8"))["holdout"])
    elif a.no_holdout or a.dry_run:
        holdout = set()
    else:
        raise SystemExit(f"refusing: {a.split_file} missing (run split_holdout.py, or pass --no-holdout)")
    questions = [q for q in questions if q["business_id"] not in holdout]
    if a.limit:
        questions = questions[: a.limit]

    cfg = json.loads(a.config.read_text(encoding="utf-8"))
    stage = stage_split(a.split, a.work / "train_noanswers")
    out_raw = a.out / "raw"
    out_raw.mkdir(parents=True, exist_ok=True)
    state_path = a.out / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"solved": [], "tried": {}}
    solved, tried = set(state["solved"]), state["tried"]
    rulebook = (stage / "rulebook.md").read_text(encoding="utf-8")
    deadline = time.time() + a.max_hours * 3600
    shared: list = []

    def engine(thinking: bool):
        """One resident model; thinking is a render/generation flag, not a reload."""
        if not shared:
            shared.append(CannedEngine() if a.dry_run else build_engine(GenConfig(**{**cfg["gen"], "thinking": thinking})))
        shared[0].cfg.thinking = thinking
        return shared[0]

    stats = Counter()
    with (a.out / "sft.jsonl").open("a", encoding="utf-8") as sft:
        for pass_no, (thinking, attempts) in enumerate([(False, a.attempts), (True, a.retry_attempts)], start=1):
            todo = [q for q in questions if q["id"] not in solved and tried.get(q["id"], 0) < pass_no]
            by_biz: dict[str, list[dict]] = {}
            for q in todo:
                by_biz.setdefault(q["business_id"], []).append(q)
            for biz, qs in sorted(by_biz.items()):
                if time.time() > deadline or attempts <= 0:
                    break
                biz_dir = stage / "data" / biz
                cache = cache_business(biz_dir, a.work / "cache")
                context = context_block(rulebook, read_readme(biz_dir), render_frame_card(load_cached(cache)))
                with Sandbox(cache, stage / "calendar.csv", workers=cfg.get("sandbox_workers", 8), timeout=cfg.get("exec_timeout", 20)) as sb:
                    result = run_trajectories(engine(thinking), sb, qs, context, k=attempts,
                                              max_turns=cfg.get("max_turns", 5), seed=1000 * pass_no)
                with (out_raw / f"pass{pass_no}_{biz}.jsonl").open("a", encoding="utf-8") as raw:
                    for q in qs:
                        tried[q["id"]] = pass_no
                        for t in result.get(q["id"], []):
                            ok = t.answer is not None and score_one(t.answer, gold[q["id"]]) == 1
                            leak = leaks(t)
                            accepted = ok and not leak and q["id"] not in solved
                            raw.write(json.dumps({"id": q["id"], "business_id": biz, "pass": pass_no, "thinking": thinking,
                                                  "accepted": accepted, "correct": ok, "leak": leak, "answer": t.answer,
                                                  "error": t.error, "messages": t.messages, "steps": t.steps},
                                                 ensure_ascii=False, default=str) + "\n")
                            stats[f"{gold[q['id']]['type']}:{'ok' if ok else 'fail'}"] += 1
                            if accepted:
                                solved.add(q["id"])
                                sft.write(json.dumps({"id": q["id"], "type": gold[q["id"]]["type"], "messages": t.messages},
                                                     ensure_ascii=False) + "\n")
                sft.flush()
                tmp = state_path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"solved": sorted(solved), "tried": tried}), encoding="utf-8")
                tmp.replace(state_path)
                print(f"pass {pass_no} {biz}: solved {len(solved)}/{len(questions)}", flush=True)
    report = {"questions": len(questions), "solved": len(solved), "yield": round(len(solved) / max(1, len(questions)), 4),
              "by_type": dict(sorted(stats.items()))}
    (a.out / "yield_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
