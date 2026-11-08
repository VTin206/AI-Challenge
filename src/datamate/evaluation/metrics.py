"""Penalized Accuracy scorer implementing the DataMate Evaluation rules.

Per question: correct (+1), abstain or missing (0), wrong (−1). A non-abstain answer is correct
only when its type equals the reference type and the value matches:
- number: numerically equal; percent: equal after rounding to 2 decimals;
- string: NFC → lowercase → non letter/digit/space → space → collapse; any accepted form
  (answer or alias) matches;
- date / boolean: exact;
- list: ordered, element-wise with the string/number rule (element i accepts answer[i] or alias[i]);
- table: columns by normalized name else by position; rows as a set, name cells by the string
  rule, numeric cells by the number rule;
- unanswerable: correct iff the reference is unanswerable.

Known gap: the official grader also accepts every spelling present in the shop's files; the
``alias`` field may not list all of them, so local PA is a lower bound.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any

CONTROL = {"abstain"}


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value)).lower()
    text = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number_eq(a: Any, b: Any) -> bool:
    return _is_number(a) and _is_number(b) and math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-6)


def _forms(answer: Any, alias: Any) -> list[Any]:
    forms = [answer]
    if isinstance(alias, list):
        forms.extend(alias)
    elif alias is not None:
        forms.append(alias)
    return forms


def _scalar_match(pred: Any, gold: Any, alias: Any = None) -> bool:
    if _is_number(gold):
        if _number_eq(pred, gold):
            return True
        if not isinstance(pred, str):
            return False
    if isinstance(pred, (list, dict)) or pred is None or isinstance(pred, bool):
        return False
    target = normalize_text(pred)
    return any(not isinstance(f, (list, dict)) and f is not None and normalize_text(f) == target for f in _forms(gold, alias))


def _list_match(pred: Any, gold: list, alias: Any) -> bool:
    if not isinstance(pred, list) or len(pred) != len(gold):
        return False
    per_element = isinstance(alias, list) and len(alias) == len(gold) and all(isinstance(a, list) for a in alias)
    for i, (p, g) in enumerate(zip(pred, gold)):
        if not _scalar_match(p, g, alias[i] if per_element else None):
            return False
    return True


def _table_match(pred: Any, gold: dict, alias: Any) -> bool:
    if not isinstance(pred, dict) or not isinstance(pred.get("columns"), list) or not isinstance(pred.get("rows"), list):
        return False
    g_cols, p_cols = gold.get("columns", []), pred["columns"]
    if len(p_cols) != len(g_cols):
        return False
    g_norm, p_norm = [normalize_text(c) for c in g_cols], [normalize_text(c) for c in p_cols]
    order = [p_norm.index(c) for c in g_norm] if sorted(g_norm) == sorted(p_norm) and len(set(p_norm)) == len(p_norm) else list(range(len(g_cols)))
    g_rows = gold.get("rows", [])
    if len(pred["rows"]) != len(g_rows):
        return False
    row_alias = alias if isinstance(alias, list) and len(alias) == len(g_rows) else [None] * len(g_rows)
    unused = list(range(len(g_rows)))
    for p_row in pred["rows"]:
        if not isinstance(p_row, list) or len(p_row) != len(g_cols):
            return False
        p_aligned = [p_row[j] for j in order]
        hit = next((k for k in unused if all(
            _scalar_match(p_aligned[c], g_rows[k][c], row_alias[k] if c == 0 else None) for c in range(len(g_cols))
        )), None)
        if hit is None:
            return False
        unused.remove(hit)
    return True


def score_one(pred: dict | None, gold: dict) -> int:
    """+1 correct, 0 abstain/missing, −1 wrong."""
    if pred is None or pred.get("type") in CONTROL or pred.get("type") is None:
        return 0
    g_type, p_type = gold.get("type"), pred.get("type")
    if g_type != p_type:
        return -1
    if g_type == "unanswerable":
        return 1
    g, p, alias = gold.get("answer"), pred.get("answer"), gold.get("alias")
    if g_type == "number":
        ok = _number_eq(p, g)
    elif g_type == "percent":
        ok = _is_number(p) and _is_number(g) and round(float(p), 2) == round(float(g), 2)
    elif g_type == "string":
        ok = isinstance(p, str) and _scalar_match(p, g, alias)
    elif g_type in {"date", "boolean"}:
        ok = p == g and type(p) is type(g)
    elif g_type == "list":
        ok = _list_match(p, g, alias)
    elif g_type == "table":
        ok = _table_match(p, g, alias)
    else:
        ok = False
    return 1 if ok else -1


def evaluate_predictions(gold: list[dict[str, Any]], predictions: list[dict[str, Any]], questions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    by_id = {str(row.get("id")): row for row in predictions}
    business = {str(q["id"]): q.get("business_id") for q in questions or []}
    totals = Counter()
    by_type: dict[str, Counter] = defaultdict(Counter)
    by_biz: dict[str, Counter] = defaultdict(Counter)
    for truth in gold:
        item_id = str(truth.get("id"))
        s = score_one(by_id.get(item_id), truth)
        label = {1: "correct", 0: "abstain", -1: "wrong"}[s]
        totals[label] += 1
        by_type[str(truth.get("type"))][label] += 1
        if item_id in business:
            by_biz[str(business[item_id])][label] += 1

    def summary(c: Counter) -> dict[str, Any]:
        n = sum(c.values())
        answered = c["correct"] + c["wrong"]
        return {
            "n": n, "correct": c["correct"], "wrong": c["wrong"], "abstain": c["abstain"],
            "pa": round((c["correct"] - c["wrong"]) / n, 4) if n else None,
            "coverage": round(answered / n, 4) if n else None,
            "precision": round(c["correct"] / answered, 4) if answered else None,
        }

    report = summary(totals)
    report["missing"] = sum(1 for t in gold if str(t.get("id")) not in by_id)
    report["by_gold_type"] = {k: summary(v) for k, v in sorted(by_type.items())}
    if by_biz:
        report["by_business"] = {k: summary(v) for k, v in sorted(by_biz.items())}
    return report
