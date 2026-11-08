"""Self-consistency: majority over normalized finals; abstain below the agreement threshold τ."""
from __future__ import annotations

from collections import Counter

from .answer import vote_key


def aggregate(answers: list[dict | None], tau: float = 0.0, tau_by_type: dict[str, float] | None = None) -> dict:
    """``answers`` are coerced finals (None = failed sample). Returns the decision record."""
    k = len(answers)
    keys = [vote_key(a) if a else None for a in answers]
    counts = Counter(key for key in keys if key)
    if not counts:
        return {"answer": {"type": "abstain"}, "agreement": 0.0, "top_type": None, "votes": {}}
    top_key, top_n = max(counts.items(), key=lambda kv: (kv[1], -keys.index(kv[0])))
    top = answers[keys.index(top_key)]
    agreement = top_n / k if k else 0.0
    threshold = (tau_by_type or {}).get(top["type"], tau)
    decision = top if agreement >= threshold else {"type": "abstain"}
    return {"answer": decision, "agreement": round(agreement, 4), "top_type": top["type"], "top": top,
            "votes": dict(counts)}


def decide(top: dict | None, agreement: float, tau: float, tau_by_type: dict[str, float] | None = None) -> dict:
    """Re-apply a threshold to a logged decision (used by τ tuning)."""
    if not top:
        return {"type": "abstain"}
    return top if agreement >= (tau_by_type or {}).get(top["type"], tau) else {"type": "abstain"}
