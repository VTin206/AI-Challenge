import json
import os
import pickle
from pathlib import Path

import pandas as pd
import pytest

from datamate.slm.agent import parse_reply
from datamate.slm.engine import GenConfig
from datamate.slm.run import load_config, run
from datamate.slm.sandbox import Sandbox
from datamate.slm.vote import aggregate

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_parse_reply_variants():
    assert parse_reply("<code>print(1)</code>") == ("code", "print(1)")
    assert parse_reply("<think>hmm <final>{}</final></think>\n<code>x=1</code>")[0] == "code"
    kind, payload = parse_reply('<final>{"type": "number", "answer": 5, "unit": "count"}</final>')
    assert kind == "final" and payload["answer"] == 5
    assert parse_reply("<final>{'type': 'boolean', 'answer': true}</final>")[1]["answer"] is True
    assert parse_reply("```python\nprint(2)\n```") == ("code", "print(2)\n")
    assert parse_reply("<final>{not json</final>")[0] == "bad_final"
    assert parse_reply("xin chào")[0] == "none"


def test_vote_majority_normalizes_and_abstains_below_tau():
    a = {"type": "number", "answer": 48250000}
    b = {"type": "number", "answer": 48250000.0}
    c = {"type": "number", "answer": 1}
    dec = aggregate([a, b, c, None, a], tau=0.6)
    assert dec["answer"] == a and dec["agreement"] == 0.6
    assert aggregate([a, c, None], tau=0.6)["answer"] == {"type": "abstain"}
    assert aggregate([None, None])["answer"] == {"type": "abstain"}
    lst1 = {"type": "list", "answer": ["A", "B"]}
    lst2 = {"type": "list", "answer": ["B", "A"]}
    assert aggregate([lst1, lst2], tau=0.6)["answer"] == {"type": "abstain"}


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    path = tmp_path_factory.mktemp("cache") / "biz.pkl"
    with path.open("wb") as f:
        pickle.dump({"sales": pd.DataFrame({"sp": ["a", "b"], "tien": ["10k", "20,000"]})}, f)
    return path


def test_sandbox_isolation_timeout_and_env(cache, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "secret-value")
    with Sandbox(cache, None, workers=1, timeout=3) as sb:
        assert sb.run("q#0", "x = h.num(dfs['sales']['tien']).sum()\nx", "2026-03-04").strip() == "30000.0"
        assert "NameError" in sb.run("q#1", "print(x)", "2026-03-04")
        sb.run("q#1", "dfs['sales']['tien'] = 0", "2026-03-04")
        assert "10k" in sb.run("q#0", "dfs['sales']['tien'].tolist()", "2026-03-04")
        assert sb.run("q#2", "import os\nprint(os.environ.get('HF_TOKEN'))", "2026-03-04").strip() == "None"
        assert sb.run("q#2", "AS_OF", "2026-03-04").strip() == "datetime.date(2026, 3, 4)"
        assert "TimeoutError" in sb.run("q#3", "while True: pass", "2026-03-04")
        assert sb.run("q#3", "1 + 1", "2026-03-04").strip() == "2"
        assert "môi trường đã được khởi động lại" in sb.run("q#0", "1", "2026-03-04")
        assert "WorkerCrashed" in sb.run("q#4", "import os\nos._exit(1)", "2026-03-04")
        assert sb.run("q#4", "dfs['sales']['sp'].str.upper()", "2026-03-04").split() == ["0", "A", "1", "B"]


class FakeEngine:
    """Writes one code step, then answers from the observed output."""

    def __init__(self):
        self.cfg = GenConfig(model="fake", backend="fake", max_model_len=200_000)

    def render(self, messages):
        return json.dumps(messages, ensure_ascii=False)

    def count(self, text):
        return len(text) // 4

    def generate(self, prompts, max_tokens, seeds):
        outs = []
        for p in prompts:
            msgs = json.loads(p)
            if msgs[-1]["content"].startswith("<output>"):
                n = msgs[-1]["content"].split("\n")[1].strip()
                outs.append(f'<final>{{"type": "number", "answer": {n}, "unit": "count"}}</final>')
            else:
                outs.append("<code>print(len(next(iter(dfs.values()))))</code>")
        return outs


def test_run_end_to_end_with_fake_engine_and_resume(tmp_path):
    cfg = load_config(None, {"k": 2, "sandbox_workers": 1, "cache_dir": str(tmp_path / "cache")})
    out = tmp_path / "out"
    sub = run(EXAMPLES, out, cfg, limit=2, engine=FakeEngine())
    rows = [json.loads(line) for line in sub.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and all(r["type"] == "number" and isinstance(r["answer"], int) for r in rows)
    log = [json.loads(line) for line in (out / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert log[0]["agreement"] == 1.0 and len(log[0]["samples"]) == 2
    with sub.open("a", encoding="utf-8") as f:
        f.write('{"id": "torn')
    run(EXAMPLES, out, cfg, limit=3, resume=True, engine=FakeEngine())
    ids = [json.loads(line)["id"] for line in sub.read_text(encoding="utf-8").splitlines()]
    assert len(ids) == 3 and len(set(ids)) == 3
