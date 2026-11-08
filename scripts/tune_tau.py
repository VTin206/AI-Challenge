"""Grid-search the abstain threshold τ (global, then per answer type) on a labelled run's log.jsonl."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamate.evaluation.metrics import score_one
from datamate.slm.vote import decide


def load(path: Path) -> list[dict]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            rows[str(rec["id"])] = rec
    return list(rows.values())


def pa(logs: list[dict], gold: dict[str, dict], tau: float, by_type: dict[str, float]) -> float:
    return sum(score_one(decide(r.get("top"), r["agreement"], tau, by_type), gold[str(r["id"])]) for r in logs) / max(1, len(logs))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--log", required=True, type=Path)
    p.add_argument("--gold", required=True, type=Path)
    p.add_argument("--min-per-type", type=int, default=15, help="tune a per-type τ only with this many questions")
    a = p.parse_args()
    gold = {str(g["id"]): g for g in map(json.loads, filter(str.strip, a.gold.read_text(encoding="utf-8").splitlines()))}
    logs = [r for r in load(a.log) if str(r["id"]) in gold]
    grid = sorted({0.0, *(round(r["agreement"], 4) for r in logs), 1.01})
    best_tau = max(grid, key=lambda t: (pa(logs, gold, t, {}), -t))
    by_type: dict[str, float] = {}
    for t in sorted({r["top"]["type"] for r in logs if r.get("top")}):
        subset = [r for r in logs if r.get("top") and r["top"]["type"] == t]
        if len(subset) >= a.min_per_type:
            by_type[t] = max(grid, key=lambda x: (pa(subset, gold, x, {}), -x))
    report = {
        "n": len(logs),
        "pa_no_abstain": round(pa(logs, gold, 0.0, {}), 4),
        "tau": best_tau, "pa_tau": round(pa(logs, gold, best_tau, {}), 4),
        "tau_by_type": by_type, "pa_tau_by_type": round(pa(logs, gold, best_tau, by_type), 4),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
