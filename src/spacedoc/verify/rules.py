"""Deterministic rules (hallucination layer L6): formulary, equipment, environment
feasibility, numeric integrity, and prompt-injection screening."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from spacedoc.answer.schema import Action, Claim, Finding, Passage
from spacedoc.env.context import EnvironmentContext
from spacedoc.tools.calculators import CalcResult
from spacedoc.tools.formulary import Formulary

# ---- numbers ---------------------------------------------------------------------------

# A number not glued to a preceding letter, so labels like S1, T4, R2, C3 are ignored.
_NUM = re.compile(r"(?<![A-Za-z0-9.])\d+(?:[.,]\d+)?")


def numbers_in(text: str) -> set[str]:
    out = set()
    for m in _NUM.findall(text or ""):
        n = m.replace(",", "")
        n = n.rstrip("0").rstrip(".") if "." in n else n
        out.add(n)
    return out


def check_claim_numbers(
    claim: Claim, passages: dict[str, Passage], patient_text: str
) -> Finding | None:
    """SR-02 for claims: a number in a claim must appear in what the claim relies on."""
    nums = numbers_in(claim.text)
    if not nums:
        return None
    if claim.kind == "reasoning":
        return Finding(
            rule_id="NUM-REASONING",
            severity="block",
            target=claim.id,
            message="Numbers are not allowed in unsourced reasoning",
        )
    if claim.kind == "patient":
        allowed = numbers_in(patient_text)
    else:
        allowed = set().union(
            *(numbers_in(passages[c].text) for c in claim.citations if c in passages)
        )
    missing = nums - allowed
    if missing:
        return Finding(
            rule_id="NUM-UNTRACED",
            severity="block",
            target=claim.id,
            message=f"Number(s) {', '.join(sorted(missing))} not found in the cited source or record",
        )
    return None


def check_action_numbers(
    action: Action, calcs: dict[str, CalcResult], formulary: Formulary
) -> Finding | None:
    """SR-02 for actions: every number must come from the referenced calculator result
    (or be the product strength printed in the formulary)."""
    nums = numbers_in(action.text)
    if not nums:
        return None
    allowed: set[str] = set()
    calc = calcs.get(action.calc_ref or "")
    if calc:
        allowed |= numbers_in(calc.text) | numbers_in(str(calc.value))
    if action.item and (item := formulary.find(action.item)) and item.strength:
        allowed |= numbers_in(item.strength)
    missing = nums - allowed
    if missing:
        why = "no calculator result referenced" if not calc else "not in the calculator result"
        return Finding(
            rule_id="NUM-ACTION",
            severity="block",
            target=action.id,
            message=f"Number(s) {', '.join(sorted(missing))} in this action are untraced ({why})",
        )
    return None


# ---- formulary and equipment -----------------------------------------------------------


def check_formulary(
    action: Action, formulary: Formulary, today: date | None = None
) -> list[Finding]:
    if action.kind != "medication":
        return []
    if not action.item:
        return [
            Finding(
                rule_id="FORM-UNLINKED",
                severity="block",
                target=action.id,
                message="Medication action is not linked to a formulary item",
            )
        ]
    avail = formulary.availability(action.item, today)
    if avail.status in {"not_aboard", "expired", "depleted"}:
        subs = ""
        if avail.item and avail.item.substitutes:
            names = []
            for s in avail.item.substitutes:
                sub = formulary.find(s)
                if sub and formulary.availability(s, today).status in {"available", "low"}:
                    names.append(sub.name)
            if names:
                subs = f". Available alternative(s): {', '.join(names)}"
        return [
            Finding(
                rule_id=f"FORM-{avail.status.upper()}",
                severity="block",
                target=action.id,
                message=avail.message + subs,
            )
        ]
    findings = []
    if avail.status == "low":
        findings.append(
            Finding(rule_id="FORM-LOW", severity="warn", target=action.id, message=avail.message)
        )
    if avail.item and avail.item.validation_status != "clinician-validated":
        findings.append(
            Finding(
                rule_id="FORM-UNVALIDATED",
                severity="warn",
                target=action.id,
                message=f"{avail.item.name}: formulary entry is not clinician-validated",
            )
        )
    return findings


def check_equipment(action: Action, env: EnvironmentContext) -> list[Finding]:
    aboard = {e.lower() for e in env.equipment}
    missing = [e for e in action.equipment if e.lower() not in aboard]
    if not missing:
        return []
    return [
        Finding(
            rule_id="EQUIP-MISSING",
            severity="block",
            target=action.id,
            message=f"Equipment not aboard: {', '.join(missing)}",
        )
    ]


# ---- environment feasibility -----------------------------------------------------------


class FeasibilityRule(BaseModel):
    id: str
    description: str
    patterns: list[str]
    max_gravity_g: float | None = None
    min_gravity_g: float | None = None
    tiers: list[str] | None = None
    requires_tags: list[str] = []
    severity: str = "block"
    message: str
    alternative: str | None = None
    status: str = "draft"

    def applies(self, env: EnvironmentContext) -> bool:
        if self.max_gravity_g is not None and env.gravity_g > self.max_gravity_g:
            return False
        if self.min_gravity_g is not None and env.gravity_g < self.min_gravity_g:
            return False
        if self.tiers is not None and env.tier not in self.tiers:
            return False
        return set(self.requires_tags) <= env.tags

    def matches(self, text: str) -> bool:
        return any(re.search(p, text, flags=re.IGNORECASE) for p in self.patterns)


def load_feasibility_rules(data_dir: Path) -> list[FeasibilityRule]:
    raw = yaml.safe_load((data_dir / "rules" / "feasibility.yaml").read_text())
    return [FeasibilityRule(**r) for r in raw["rules"]]


def check_feasibility(
    target_id: str,
    text: str,
    env: EnvironmentContext,
    rules: list[FeasibilityRule],
    is_action: bool,
) -> list[Finding]:
    findings = []
    for rule in rules:
        if rule.applies(env) and rule.matches(text):
            # A rule that blocks an action only warns on a claim (describing a test is not doing it).
            severity = rule.severity if is_action else "warn"
            alt = f" Alternative: {rule.alternative}" if rule.alternative else ""
            findings.append(
                Finding(
                    rule_id=rule.id, severity=severity, target=target_id, message=rule.message + alt
                )
            )
    return findings


# ---- prompt injection ------------------------------------------------------------------

_INJECTION = [
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts?)",
    r"disregard (the )?(system|previous) (prompt|instructions)",
    r"you are now\b",
    r"new instructions\s*:",
    r"system prompt",
]


def screen_passage(passage: Passage) -> Finding | None:
    """SR-11: retrieved text is data. Passages that look like instructions are dropped."""
    for p in _INJECTION:
        if re.search(p, passage.text, flags=re.IGNORECASE):
            return Finding(
                rule_id="INJECTION",
                severity="block",
                target=passage.cid,
                message=f"Passage from {passage.source_id} contains instruction-like text and was excluded",
            )
    return None


def patient_text(patient: dict[str, Any] | None) -> str:
    return yaml.safe_dump(patient or {}, sort_keys=True)
