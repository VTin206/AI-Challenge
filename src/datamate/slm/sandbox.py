"""Spawn-started worker processes that execute model-generated pandas code.

Each worker loads one business's pickled frames once. Every trajectory gets its own namespace
(``dfs`` copies under pandas copy-on-write, ``h`` helpers, ``AS_OF``, ``CAL``) kept across turns.
Exec is bounded by a wall-clock timeout (worker killed and restarted) and a stdout cap.
"""
from __future__ import annotations

import ast
import contextlib
import io
import multiprocessing as mp
import os
import re
import threading
import traceback
from datetime import date
from pathlib import Path
from typing import Any

STDOUT_CAP = 4000
_SECRET = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|^HF_|^WANDB|^OPENAI|^ANTHROPIC|^KAGGLE|^GOOGLE", re.I)


def _scrub_env() -> None:
    for name in list(os.environ):
        if _SECRET.search(name):
            os.environ.pop(name, None)
    os.environ["HOME"] = os.environ.get("TMPDIR", "/tmp") + "/dm"


def _exec_capture(code: str, ns: dict[str, Any]) -> str:
    buf = io.StringIO()
    try:
        tree = ast.parse(code, mode="exec")
        last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exec(compile(tree, "<code>", "exec"), ns)
            if last is not None:
                value = eval(compile(ast.Expression(last.value), "<code>", "eval"), ns)
                if hasattr(value, "item") and getattr(value, "ndim", 1) == 0:
                    value = value.item()
                if value is not None:
                    if hasattr(value, "columns"):
                        print(value.to_string(max_rows=40, max_cols=12))
                    elif hasattr(value, "to_string"):
                        print(value.to_string(max_rows=40))
                    else:
                        print(repr(value))
    except BaseException:  # noqa: BLE001 - report every failure to the model
        tb = traceback.format_exc(limit=3).strip().splitlines()
        buf.write("\n".join(tb[-6:]))
    out = buf.getvalue()
    if len(out) > STDOUT_CAP:
        out = out[: STDOUT_CAP // 2] + f"\n...[cắt bớt {len(out) - STDOUT_CAP} ký tự]...\n" + out[-STDOUT_CAP // 2:]
    return out if out.strip() else "(không có output — hãy print kết quả)"


def _limit_memory(mem_gb: float | None) -> None:
    if not mem_gb:
        return
    try:
        import resource

        limit = int(mem_gb * (1 << 30))
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):
        pass  # not available on Windows


def _worker_main(conn, cache_path: str, calendar_path: str | None, mem_gb: float | None = None) -> None:
    _scrub_env()
    _limit_memory(mem_gb)
    import numpy as np
    import pandas as pd

    from . import helpers
    from .frames import load_cached

    pd.options.mode.copy_on_write = True
    pd.set_option("display.width", 160)
    frames = load_cached(cache_path)
    cal = helpers.load_calendar(calendar_path) if calendar_path and Path(calendar_path).exists() else []
    spaces: dict[str, dict[str, Any]] = {}
    conn.send(("ready", None))
    while True:
        try:
            op, tid, payload = conn.recv()
        except EOFError:
            return
        if op == "exec":
            ns = spaces.get(tid)
            if ns is None:
                ns = {
                    "__name__": "__sandbox__", "pd": pd, "np": np, "h": helpers, "date": date,
                    "dfs": {k: v.copy(deep=False) for k, v in frames.items()},
                    "AS_OF": date.fromisoformat(payload["as_of"]), "CAL": cal,
                }
                ns["timedelta"] = __import__("datetime").timedelta
                spaces[tid] = ns
            conn.send(("ok", _exec_capture(payload["code"], ns)))
        elif op == "drop":
            spaces.pop(tid, None)
            conn.send(("ok", None))
        elif op == "stop":
            return


class _Worker:
    def __init__(self, cache_path: Path, calendar_path: Path | None, mem_gb: float | None = None):
        self.args = (str(cache_path), str(calendar_path) if calendar_path else None, mem_gb)
        self.lock = threading.Lock()
        self.generation = 0
        self._start()

    def _start(self) -> None:
        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=_worker_main, args=(child, *self.args), daemon=True)
        self.proc.start()
        child.close()
        self.ready = False

    def _restart(self) -> None:
        with contextlib.suppress(Exception):
            self.proc.kill()
            self.proc.join()
        self.generation += 1
        self._start()

    def _await_ready(self, timeout: float) -> None:
        if not self.ready:
            if not self.conn.poll(timeout):
                raise TimeoutError("worker failed to load data")
            self.conn.recv()
            self.ready = True

    def call(self, op: str, tid: str, payload: Any, timeout: float, load_timeout: float = 300) -> str | None:
        with self.lock:
            try:
                self._await_ready(load_timeout)
                self.conn.send((op, tid, payload))
                if self.conn.poll(timeout):
                    return self.conn.recv()[1]
                message = f"TimeoutError: code chạy quá {timeout:.0f}s và đã bị dừng; mọi biến trước đó đã mất, dfs vẫn còn."
            except (EOFError, BrokenPipeError, ConnectionError, OSError):
                message = "WorkerCrashed: code làm tiến trình bị dừng (có thể hết bộ nhớ); mọi biến trước đó đã mất, dfs vẫn còn."
            self._restart()
            return message

    def stop(self) -> None:
        with contextlib.suppress(Exception):
            self.conn.send(("stop", "", None))
        self.proc.join(timeout=5)
        if self.proc.is_alive():
            self.proc.kill()


class Sandbox:
    """Pool of workers for one business; trajectories are pinned to a worker by id."""

    def __init__(self, cache_path: Path, calendar_path: Path | None = None, workers: int = 4, timeout: float = 20.0,
                 mem_gb: float | None = 12.0):
        self.timeout = timeout
        self.workers = [_Worker(cache_path, calendar_path, mem_gb) for _ in range(max(1, workers))]
        self._pin: dict[str, int] = {}
        self._seen: dict[str, int] = {}

    def _worker(self, tid: str) -> _Worker:
        if tid not in self._pin:
            self._pin[tid] = len(self._pin) % len(self.workers)
        return self.workers[self._pin[tid]]

    def run(self, tid: str, code: str, as_of: str) -> str:
        worker = self._worker(tid)
        notice = ""
        if tid in self._seen and self._seen[tid] != worker.generation:
            notice = "Lưu ý: môi trường đã được khởi động lại; các biến tạo ở lượt trước đã mất, hãy tạo lại.\n"
        out = worker.call("exec", tid, {"code": code, "as_of": as_of}, self.timeout) or ""
        self._seen[tid] = worker.generation
        return notice + out

    def drop(self, tid: str) -> None:
        if tid in self._pin:
            self._worker(tid).call("drop", tid, None, 10)

    def close(self) -> None:
        for w in self.workers:
            w.stop()

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
