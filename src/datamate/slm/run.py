"""Run the SLM agent over a split directory and write ``submission.jsonl`` + ``log.jsonl``."""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..schema.profiler import render_frame_card
from .agent import run_trajectories
from .engine import GenConfig, build_engine
from .frames import cache_business, load_cached, read_readme
from .prompt import context_block
from .sandbox import Sandbox
from .vote import aggregate

DEFAULTS: dict[str, Any] = {
    "k": 5, "max_turns": 5, "seed": 0, "tau": 0.0, "tau_by_type": {}, "sandbox_workers": 8,
    "exec_timeout": 20, "card_chars": 12000, "chunk_questions": 64, "cache_dir": "cache",
}


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _completed_ids(sub_path: Path) -> set[str]:
    """Read finished ids; drop a torn last line left by an interrupted run."""
    if not sub_path.exists():
        return set()
    good, ids = [], set()
    for line in sub_path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        good.append(line)
        ids.add(str(rec["id"]))
    sub_path.write_text("".join(g + "\n" for g in good), encoding="utf-8")
    return ids


def load_config(path: str | Path | None, overrides: dict[str, Any]) -> dict[str, Any]:
    cfg = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    merged = {**DEFAULTS, **{k: v for k, v in cfg.items() if k != "gen"}}
    gen = dict(cfg.get("gen", {}))
    for key, value in overrides.items():
        if value is None:
            continue
        if key in GenConfig.__dataclass_fields__:
            gen[key] = value
        else:
            merged[key] = value
    merged["gen"] = gen
    return merged


def run(split: Path, out: Path, cfg: dict[str, Any], ids: set[str] | None = None, businesses: set[str] | None = None,
        limit: int | None = None, resume: bool = False, engine=None) -> Path:
    questions = _jsonl(split / "questions.jsonl")
    if ids:
        questions = [q for q in questions if str(q["id"]) in ids]
    if businesses:
        questions = [q for q in questions if q["business_id"] in businesses]
    if limit:
        questions = questions[:limit]
    out.mkdir(parents=True, exist_ok=True)
    sub_path, log_path = out / "submission.jsonl", out / "log.jsonl"
    done = _completed_ids(sub_path) if resume else set()
    if not resume:
        sub_path.write_text("", encoding="utf-8")
        log_path.write_text("", encoding="utf-8")
    cfg_path = out / "run_config.json"
    if resume and cfg_path.exists():
        old = json.loads(cfg_path.read_text(encoding="utf-8"))
        changed = sorted(k for k in set(old) | set(cfg) if old.get(k) != cfg.get(k) and k != "cache_dir")
        if changed:
            raise SystemExit(f"--resume with a different config ({', '.join(changed)}); use a new --out")
    cfg_path.write_text(_dump(cfg), encoding="utf-8")

    by_biz: dict[str, list[dict]] = defaultdict(list)
    for q in questions:
        if str(q["id"]) not in done:
            by_biz[q["business_id"]].append(q)
    if not by_biz:
        return sub_path

    engine = engine or build_engine(GenConfig(**cfg["gen"]))
    rulebook_path = split / "rulebook.md"
    rulebook = rulebook_path.read_text(encoding="utf-8") if rulebook_path.exists() else ""
    calendar = split / "calendar.csv"
    cache_root = Path(cfg["cache_dir"]) / split.name
    total = sum(len(v) for v in by_biz.values())
    finished = 0
    with sub_path.open("a", encoding="utf-8") as sub, log_path.open("a", encoding="utf-8") as log:
        for biz, qs in sorted(by_biz.items()):
            t0 = time.time()
            biz_dir = split / "data" / biz
            cache = cache_business(biz_dir, cache_root)
            card = render_frame_card(load_cached(cache), max_chars=cfg["card_chars"])
            context = context_block(rulebook, read_readme(biz_dir), card)
            with Sandbox(cache, calendar, workers=cfg["sandbox_workers"], timeout=cfg["exec_timeout"]) as sandbox:
                for i in range(0, len(qs), cfg["chunk_questions"]):
                    chunk = qs[i:i + cfg["chunk_questions"]]
                    c0 = time.time()
                    result = run_trajectories(engine, sandbox, chunk, context, k=cfg["k"], max_turns=cfg["max_turns"], seed=cfg["seed"])
                    per_q = (time.time() - c0) / max(1, len(chunk))
                    for q in chunk:
                        trajs = result.get(q["id"], [])
                        dec = aggregate([t.answer for t in trajs], cfg["tau"], cfg["tau_by_type"])
                        sub.write(_dump({"id": q["id"], **dec["answer"]}) + "\n")
                        log.write(_dump({
                            "id": q["id"], "business_id": biz, "question": q["question"], "as_of_date": q["as_of_date"],
                            "submitted": dec["answer"], "top": dec.get("top"), "agreement": dec["agreement"], "votes": dec["votes"],
                            "k": cfg["k"], "sec_per_question": round(per_q, 2),
                            "samples": [{"answer": t.answer, "error": t.error, "turns": t.turns, "forced": t.forced, "steps": t.steps} for t in trajs],
                        }) + "\n")
                    sub.flush()
                    log.flush()
                    finished += len(chunk)
            print(f"[{finished}/{total}] {biz}: {len(qs)} q in {time.time() - t0:.0f}s", flush=True)
    return sub_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="DataMate SLM agent runner")
    p.add_argument("--split", required=True, type=Path, help="split dir with questions.jsonl, rulebook.md, calendar.csv, data/")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--ids", type=Path, help="file with one question id per line")
    p.add_argument("--businesses", nargs="*", help="only these business ids (e.g. holdout)")
    p.add_argument("--holdout", type=Path, help="configs/holdout.json → use its business list")
    p.add_argument("--limit", type=int)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--model")
    p.add_argument("--lora")
    p.add_argument("--backend", choices=["vllm", "hf"])
    p.add_argument("--k", type=int)
    p.add_argument("--tau", type=float)
    p.add_argument("--thinking", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--cache-dir", dest="cache_dir")
    a = p.parse_args(argv)
    cfg = load_config(a.config, {"model": a.model, "lora": a.lora, "backend": a.backend, "k": a.k, "tau": a.tau,
                                 "thinking": a.thinking, "cache_dir": a.cache_dir})
    ids = {line.strip() for line in a.ids.read_text(encoding="utf-8").splitlines() if line.strip()} if a.ids else None
    biz = set(a.businesses or [])
    if a.holdout:
        biz |= set(json.loads(a.holdout.read_text(encoding="utf-8"))["businesses"])
    path = run(a.split, a.out, cfg, ids=ids, businesses=biz or None, limit=a.limit, resume=a.resume)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
