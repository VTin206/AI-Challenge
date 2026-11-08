"""Code-acting loop: every question × sample is a trajectory; all active ones advance in lockstep rounds."""
from __future__ import annotations

import ast
import json
import re
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .answer import InvalidAnswer, coerce
from .prompt import FORCE_FINAL, SYSTEM, first_user_turn, observation

_FINAL = re.compile(r"<final>\s*(.*?)\s*(?:</final>|$)", re.S)
_CODE = re.compile(r"<code>\s*(.*?)\s*(?:</code>|$)", re.S)
_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)
_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


@dataclass
class Trajectory:
    qid: str
    sample: int
    question: str
    as_of: str
    messages: list[dict[str, str]]
    turns: int = 0
    forced: bool = False
    done: bool = False
    answer: dict | None = None
    error: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)

    @property
    def tid(self) -> str:
        return f"{self.qid}#{self.sample}"


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        value = ast.literal_eval(text.replace("true", "True").replace("false", "False").replace("null", "None"))
        if not isinstance(value, dict):
            raise ValueError("final is not an object")
        return value


def parse_reply(text: str) -> tuple[str, Any]:
    """Return ("final", dict) | ("code", str) | ("none", None); thinking is ignored."""
    body = _THINK.sub("", text)
    if "<think>" in body:
        body = body.split("</think>")[-1]
    final = _FINAL.search(body)
    code = _CODE.search(body)
    if final and (not code or final.start() < code.start()):
        try:
            return "final", _parse_json(final.group(1))
        except (ValueError, SyntaxError) as exc:
            return "bad_final", str(exc)
    if code and code.group(1).strip():
        return "code", code.group(1)
    fence = _FENCE.search(body)
    if fence:
        return "code", fence.group(1)
    return "none", None


def _seed(base: int, tid: str, turn: int) -> int:
    return (base + zlib.crc32(tid.encode()) * 31 + turn) % (2**31 - 1)


def run_trajectories(engine, sandbox, questions: list[dict], context: str, *, k: int, max_turns: int = 5,
                     seed: int = 0, min_budget: int = 512, require_code: bool = True, on_round=None) -> dict[str, list[Trajectory]]:
    cfg = engine.cfg
    trajs = [
        Trajectory(q["id"], s, q["question"], q["as_of_date"], [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": first_user_turn(context, q["question"], q["as_of_date"])},
        ])
        for q in questions for s in range(k)
    ]
    pool = ThreadPoolExecutor(max_workers=max(1, len(getattr(sandbox, "workers", [1]))))
    try:
        while True:
            active = [t for t in trajs if not t.done]
            if not active:
                break
            prompts, budgets, seeds, batch = [], [], [], []
            for t in active:
                if t.turns >= max_turns and not t.forced:
                    t.messages.append({"role": "user", "content": FORCE_FINAL})
                    t.forced = True
                prompt = engine.render(t.messages)
                budget = min(cfg.max_new_tokens, cfg.max_model_len - engine.count(prompt) - 256)
                if budget < min_budget and not t.forced:
                    t.messages.append({"role": "user", "content": FORCE_FINAL})
                    t.forced = True
                    prompt = engine.render(t.messages)
                    budget = min(cfg.max_new_tokens, cfg.max_model_len - engine.count(prompt) - 256)
                if budget < 64:
                    t.done, t.error = True, "context exhausted"
                    continue
                prompts.append(prompt)
                budgets.append(budget)
                seeds.append(_seed(seed, t.tid, t.turns))
                batch.append(t)
            if not batch:
                continue
            try:
                replies = engine.generate(prompts, budgets, seeds)
            except Exception as exc:  # noqa: BLE001 - one bad batch must not kill the run
                replies = []
                for p, b, s in zip(prompts, budgets, seeds):
                    try:
                        replies.append(engine.generate([p], [b], [s])[0])
                    except Exception as inner:  # noqa: BLE001
                        replies.append(f"<engine-error>{inner or exc}</engine-error>")
            to_exec: list[tuple[Trajectory, str]] = []
            for t, reply in zip(batch, replies):
                kind, payload = parse_reply(reply)
                t.steps.append({"turn": t.turns, "reply": reply, "kind": kind})
                t.messages.append({"role": "assistant", "content": _THINK.sub("", reply).strip()})
                t.turns += 1
                if kind == "final" and require_code and not t.forced and not any(s.get("kind") == "code" for s in t.steps):
                    t.messages.append({"role": "user", "content": "Chưa chạy code nào. Hãy kiểm tra dữ liệu bằng <code>...</code> trước khi trả lời."})
                elif kind == "final":
                    try:
                        t.answer = coerce(payload.get("type"), payload.get("answer"), payload.get("unit"), payload.get("reason"))
                    except (InvalidAnswer, AttributeError) as exc:
                        t.error = f"invalid final: {exc}"
                    t.done = True
                elif t.forced:
                    t.done, t.error = True, f"no final after force ({kind})"
                elif kind == "code":
                    to_exec.append((t, payload))
                else:
                    hint = "JSON trong <final> không hợp lệ." if kind == "bad_final" else "Không thấy <code> hay <final>."
                    t.messages.append({"role": "user", "content": hint + " Hãy viết một khối <code>...</code> hoặc <final>{...}</final>."})
            outputs = list(pool.map(lambda tc: sandbox.run(tc[0].tid, tc[1], tc[0].as_of), to_exec))
            for (t, code), out in zip(to_exec, outputs):
                t.steps[-1]["output"] = out
                t.messages.append({"role": "user", "content": observation(out)})
            if on_round:
                on_round(trajs)
    finally:
        pool.shutdown(wait=True)
        for t in trajs:
            try:
                sandbox.drop(t.tid)
            except Exception:  # noqa: BLE001
                pass
    grouped: dict[str, list[Trajectory]] = {}
    for t in trajs:
        grouped.setdefault(t.qid, []).append(t)
    return grouped
