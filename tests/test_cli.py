import json
from pathlib import Path

from datamate.cli import run


def test_cli_batch_writes_one_record_per_question(tmp_path):
    project = Path(__file__).parents[1]
    out = tmp_path / "submission.jsonl"
    metrics = tmp_path / "run_metrics.json"
    count = run(project / "examples" / "data", project / "examples" / "questions.jsonl", out, metrics_output=metrics)
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert count == 4
    assert [record["id"] for record in records] == ["demo_revenue_march", "demo_top_last_week", "demo_count", "demo_lunar"]
    assert records[0] == {"id": "demo_revenue_march", "type": "number", "answer": 469000}
    assert records[1] == {"id": "demo_top_last_week", "type": "string", "answer": "Trà sữa truyền thống"}
    assert records[2]["answer"] == 7
    assert len(json.loads(metrics.read_text(encoding="utf-8"))["latencies"]) == 4

