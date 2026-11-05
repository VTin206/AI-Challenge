from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..models import Rule

_DIRECTIVE = re.compile(r"^\s*RULE\s*(?:\[priority\s*=\s*(-?\d+)\])?\s*:\s*([a-zA-Z0-9_.-]+)\s*=\s*(.*?)\s*$", re.IGNORECASE)


@dataclass
class Rulebook:
    texts: list[tuple[str, str]]
    rules: list[Rule]
    conflicts: list[str]

    def context(self, question: str | None = None, max_chars: int = 8000) -> str:
        content = []
        for source, text in self.texts:
            if not text.strip():
                continue
            content.append(f"[{source}]\n{text.strip()}")
        selected = "\n\n".join(content)
        return selected[:max_chars]

    def executable(self, key: str) -> tuple[str | None, str | None]:
        matches = [rule for rule in self.rules if rule.key.casefold() == key.casefold()]
        if not matches:
            return None, None
        priority = max((rule.priority if rule.priority is not None else 0) for rule in matches)
        best = [rule for rule in matches if (rule.priority if rule.priority is not None else 0) == priority]
        values = {rule.value for rule in best}
        if len(values) > 1:
            return None, f"Conflicting rules for {key} at priority {priority}: " + "; ".join(sorted(values))
        return best[0].value, None

    def conflicts_for(self, keys: list[str]) -> list[str]:
        errors = []
        for key in keys:
            _, error = self.executable(key)
            if error:
                errors.append(error)
        return errors


def _parse_rules(source: str, text: str) -> list[Rule]:
    parsed = []
    for line in text.splitlines():
        match = _DIRECTIVE.match(line)
        if match:
            priority, key, value = match.groups()
            parsed.append(Rule(key=key.casefold(), value=value.strip(), source=source, priority=int(priority) if priority is not None else None))
    return parsed


def load_rulebook(package_root: str | Path, shared_text: str = "", business_readme: str = "") -> Rulebook:
    root = Path(package_root)
    texts = []
    if not business_readme.strip() and (root / "README.md").exists():
        business_readme = (root / "README.md").read_text(encoding="utf-8", errors="replace")
    if shared_text.strip():
        texts.append(("shared rulebook", shared_text))
    if business_readme.strip():
        texts.append(("business README", business_readme))
    local = root / "RULEBOOK.md"
    if local.exists():
        text = local.read_text(encoding="utf-8", errors="replace")
        texts.append(("business rulebook", text))
    rules = []
    for source, text in texts:
        rules.extend(_parse_rules(source, text))
    return Rulebook(texts, rules, [])

