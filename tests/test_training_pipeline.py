import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = _load("gen_trajectories", "training_code/data_generation/gen_trajectories.py")


def _split(tmp_path: Path) -> Path:
    split = tmp_path / "train"
    shutil.copytree(ROOT / "examples" / "data", split / "data")
    shutil.copy(ROOT / "examples" / "questions.jsonl", split / "questions.jsonl")
    (split / "rulebook.md").write_text("# rules", encoding="utf-8")
    qs = [json.loads(x) for x in (split / "questions.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    answers = [{"id": q["id"], "type": "unanswerable" if i == 0 else "number", "answer": None if i == 0 else 1, "alias": []}
               for i, q in enumerate(qs)]
    (split / "answers.jsonl").write_text("".join(json.dumps(a) + "\n" for a in answers), encoding="utf-8")
    return split


def test_leak_filter():
    bad = SimpleNamespace(steps=[{"kind": "code", "reply": "<code>open('../answers.jsonl')</code>"}])
    env = SimpleNamespace(steps=[{"kind": "code", "reply": "<code>import os; os.environ['X']</code>"}])
    ok = SimpleNamespace(steps=[{"kind": "code", "reply": "<code>dfs['sales'].head()</code>"}])
    assert gen.leaks(bad) and gen.leaks(env) and not gen.leaks(ok)


def test_dry_run_keeps_only_correct_and_stages_without_answers(tmp_path, monkeypatch):
    split = _split(tmp_path)
    out, work = tmp_path / "out", tmp_path / "work"
    cfg = tmp_path / "slm.json"
    cfg.write_text(json.dumps({"gen": {"model": "x"}, "sandbox_workers": 1, "max_turns": 3}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["gen", "--split", str(split), "--out", str(out), "--work", str(work),
                                      "--config", str(cfg), "--split-file", str(tmp_path / "none.json"), "--dry-run"])
    gen.main()
    assert not (work / "train_noanswers" / "answers.jsonl").exists()
    sft = [json.loads(x) for x in (out / "sft.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(sft) == 1 and sft[0]["type"] == "unanswerable"
    assert sft[0]["messages"][0]["role"] == "system" and sft[0]["messages"][-1]["role"] == "assistant"
    raw = [json.loads(x) for f in (out / "raw").glob("*.jsonl") for x in f.read_text(encoding="utf-8").splitlines()]
    assert raw and sum(r["accepted"] for r in raw) == 1


def test_refuses_split_without_answers(tmp_path, monkeypatch):
    split = _split(tmp_path)
    (split / "answers.jsonl").unlink()
    monkeypatch.setattr(sys, "argv", ["gen", "--split", str(split), "--dry-run"])
    with pytest.raises(SystemExit):
        gen.main()
