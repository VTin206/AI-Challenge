import json
import os
from pathlib import Path

import pytest

from datamate.evaluation.metrics import score_one
from datamate.slm.answer import InvalidAnswer, coerce, vote_key

ROOT = os.environ.get("DATAMATE_DATA_DIR")


def test_coerce_rounds_by_unit_and_types():
    assert coerce("number", 1234.5, "vnd") == {"type": "number", "answer": 1235}
    assert coerce("number", "12.0", "count") == {"type": "number", "answer": 12}
    assert coerce("percent", 12.345) == {"type": "percent", "answer": 12.35}
    assert coerce("percent", "12,5%")["answer"] == 12.5
    assert coerce("number", "1.234.567", "vnd")["answer"] == 1234567
    assert coerce("date", "2026-08") == {"type": "date", "answer": "2026-08"}
    assert coerce("boolean", "có")["answer"] is True
    assert coerce("unanswerable", None)["type"] == "unanswerable"
    with pytest.raises(InvalidAnswer):
        coerce("number", "abc")
    with pytest.raises(InvalidAnswer):
        coerce("list", "a, b")


def test_vote_key_merges_equivalents():
    assert vote_key(coerce("string", "Cà phê, sữa")) == vote_key(coerce("string", "cà phê sữa"))
    t1 = coerce("table", {"columns": ["a", "b"], "rows": [["x", 1], ["y", 2.0]]})
    t2 = coerce("table", {"columns": ["a", "b"], "rows": [["y", 2], ["x", 1]]})
    assert vote_key(t1) == vote_key(t2)


@pytest.mark.skipif(not ROOT, reason="set DATAMATE_DATA_DIR")
def test_coerced_gold_scores_perfectly():
    lines = (Path(ROOT) / "train" / "answers.jsonl").read_text(encoding="utf-8").splitlines()
    for g in (json.loads(line) for line in lines if line.strip()):
        unit = "vnd" if g["type"] == "number" and isinstance(g["answer"], int) else "other"
        assert score_one(coerce(g["type"], g["answer"], unit), g) == 1, g
