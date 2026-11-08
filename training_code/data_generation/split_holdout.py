"""Group-aware holdout: cluster train businesses into template families by column-name overlap,
then hold out whole families (plus one singleton) so holdout PA is not inflated by same-template shops."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from datamate.evaluation.metrics import normalize_text
from datamate.slm.frames import cache_business, load_cached


def signature(cache: Path) -> frozenset[str]:
    cols = set()
    for df in load_cached(cache).values():
        cols |= {normalize_text(c) for c in df.columns if c != "_source"}
    return frozenset(cols)


def families(sigs: dict[str, frozenset[str]], threshold: float) -> list[list[str]]:
    parent = {b: b for b in sigs}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    names = sorted(sigs)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            inter, union = len(sigs[a] & sigs[b]), len(sigs[a] | sigs[b]) or 1
            if inter / union >= threshold:
                parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for b in names:
        groups.setdefault(find(b), []).append(b)
    return sorted(groups.values(), key=lambda g: (-len(g), g))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--split", required=True, type=Path, help="train split dir")
    p.add_argument("--cache-dir", type=Path, default=Path("cache"))
    p.add_argument("--out", type=Path, default=Path("configs/split.json"))
    p.add_argument("--target", type=int, default=6, help="approximate number of holdout businesses")
    p.add_argument("--threshold", type=float, default=0.6)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--keep-in-train", nargs="*", default=["biz_123"])
    a = p.parse_args()
    bizs = sorted(d.name for d in (a.split / "data").iterdir() if d.is_dir())
    sigs = {b: signature(cache_business(a.split / "data" / b, a.cache_dir / a.split.name)) for b in bizs}
    fams = families(sigs, a.threshold)
    rng = random.Random(a.seed)
    eligible = [f for f in fams if not set(f) & set(a.keep_in_train)]
    singles = [f for f in eligible if len(f) == 1]
    multis = [f for f in eligible if 1 < len(f) <= a.target - 1]
    rng.shuffle(singles)
    rng.shuffle(multis)
    holdout: list[str] = []
    if singles:
        holdout += singles.pop()
    for fam in multis + singles:
        if len(holdout) + len(fam) <= a.target:
            holdout += fam
        if len(holdout) >= a.target:
            break
    result = {"seed": a.seed, "threshold": a.threshold, "holdout": sorted(holdout),
              "train": sorted(set(bizs) - set(holdout)), "families": fams}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"holdout": result["holdout"], "n_families": len(fams)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
