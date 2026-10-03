"""Urgent-sign (red flag) rules, run on the user's own words before the model sees them.

The rule file (data/rules/red_flags.yaml) is a draft that clinicians must review.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel

# A negation within four words before a match, in the same clause, cancels it.
_NEGATION = re.compile(r"\b(no|not|denies|denied|without|never|none|nor)\b|n't\b", re.I)
_CLAUSE_END = re.compile(r"[.;:!?]|\bbut\b|\bhowever\b", re.I)


class RedFlagRule(BaseModel):
    id: str
    patterns: list[str]
    message: str
    steps: list[str] = []


class RedFlagHit(BaseModel):
    rule_id: str
    message: str
    matched: str
    steps: list[str]


class RedFlags(BaseModel):
    default_steps: list[str] = []
    rules: list[RedFlagRule] = []

    @classmethod
    def load(cls, data_dir: Path) -> RedFlags:
        return cls(**yaml.safe_load((data_dir / "rules" / "red_flags.yaml").read_text()))

    def screen(self, text: str, delay: str = "unknown") -> list[RedFlagHit]:
        hits = []
        for rule in self.rules:
            for pattern in rule.patterns:
                match = next(
                    (m for m in re.finditer(pattern, text, re.I) if not _negated(text, m.start())),
                    None,
                )
                if match:
                    hits.append(
                        RedFlagHit(
                            rule_id=rule.id,
                            message=rule.message,
                            matched=match.group(0),
                            steps=self.steps(rule.steps, delay),
                        )
                    )
                    break
        return hits

    def steps(self, steps: list[str] | None = None, delay: str = "unknown") -> list[str]:
        return [s.replace("{delay}", delay) for s in (steps or self.default_steps)]


def _negated(text: str, start: int) -> bool:
    before = text[:start]
    clauses = _CLAUSE_END.split(before)
    words = clauses[-1].split()[-4:]
    return bool(_NEGATION.search(" ".join(words)))
