"""Urgent-sign (red flag) rules, run on the user's own words before the model sees them.

The rule file (data/rules/red_flags.yaml) is a draft that clinicians must review.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel

# A negation within four words before a match, in the same clause and with no comma or "and"
# between, cancels it ("no chest pain"; but not "no fever, I have chest pain" or "no fever
# and chest pain since this morning", which may mean the chest pain is present).
_NEGATION = re.compile(
    r"\b(no|not|denies|denied|without|never|none|nor|negative for)\b|n't\b", re.I
)
_CLAUSE_END = re.compile(
    r"[.;:!?\n]|\b(?:but|however|though|although|except|apart from|other than)\b", re.I
)
_WINDOW_END = re.compile(r",|\band\b", re.I)
# A negation also covers a list: "no spacewalk, radiation alert, smoke or smell".
_LIST_SEP = re.compile(r",|/|\b(?:or|nor|and)\b", re.I)
_NEW_STATEMENT = re.compile(
    r"\b(i|i'm|i've|he|she|they|we|you|it|there|this|that|the|a|an|my|his|her|their|our|is|"
    r"was|are|were|has|had|have|feel|feels|felt|got|gets|did|does|do|went|started|became|"
    r"seems|now|still|then)\b",
    re.I,
)
# "denies fever, chills, chest pain" is a clinical list of negatives; after a plain "no", a
# list counts as negated only when it is joined by "or" or "nor" ("no fever, cough or chest
# pain"), because "no fever, chest pain" may mean the chest pain is present.
_CLINICAL_NEGATION = re.compile(r"\b(denies|denied|negative for)\b", re.I)


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
    before = _CLAUSE_END.split(text[:start])[-1]
    window = _WINDOW_END.split(before)[-1].split()[-4:]
    if _NEGATION.search(" ".join(window)):
        return True
    return _in_negated_list(before, _CLAUSE_END.split(text[start:])[0])


def _list_item(part: str) -> bool:
    return len(part.split()) <= 3 and not _NEW_STATEMENT.search(part)


def _in_negated_list(before: str, after: str) -> bool:
    """Whether the match at the boundary of `before` and `after` (both within one clause) is
    an item of a list that follows a negation."""
    cues = list(_NEGATION.finditer(before))
    if not cues:
        return False
    rest = before[cues[-1].end() :]
    parts = _LIST_SEP.split(rest)
    seps = [s.strip().lower() for s in re.findall(_LIST_SEP, rest)]
    if not seps or len(parts[0].split()) > 4 or not all(_list_item(p) for p in parts[1:]):
        return False
    # The items after the match, while they still look like list items.
    after_parts = _LIST_SEP.split(after)
    for sep, part in zip(re.findall(_LIST_SEP, after), after_parts[1:], strict=False):
        if not _list_item(part):
            break
        seps.append(sep.strip().lower())
    clinical = any(_CLINICAL_NEGATION.match(c.group(0)) for c in cues)
    return clinical or any(s in ("or", "nor") for s in seps)
