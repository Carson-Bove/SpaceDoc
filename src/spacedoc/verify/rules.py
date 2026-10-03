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


def _plural(nums: set[str]) -> str:
    items = ", ".join(sorted(nums))
    return f"number {items} is" if len(nums) == 1 else f"numbers {items} are"


def check_claim_numbers(
    claim: Claim, passages: dict[str, Passage], patient_text: str
) -> Finding | None:
    """SR-02 for claims: a number in a claim must appear in what the claim relies on."""
    nums = numbers_in(claim.text)
    if not nums:
        return None
    if claim.kind == "reasoning":
        # Reasoning may quote the patient's own numbers ("a 1/2 inch cut"), nothing else.
        if nums <= numbers_in(patient_text):
            return None
        return Finding(
            rule_id="NUM-REASONING",
            severity="block",
            target=claim.id,
            message="The model's own reasoning may only contain numbers from the patient record "
            "or what was reported, so this statement is hidden.",
        )
    if claim.kind == "patient":
        allowed = numbers_in(patient_text)
        where = "the patient record or what was reported"
    else:
        allowed = set().union(
            *(numbers_in(passages[c].text) for c in claim.citations if c in passages)
        )
        cited = ", ".join(c for c in claim.citations if c in passages)
        where = f"the cited source ({cited})" if cited else "any cited source"
    missing = nums - allowed
    if missing:
        return Finding(
            rule_id="NUM-UNTRACED",
            severity="block",
            target=claim.id,
            message=f"The {_plural(missing)} not in {where}, so this statement is hidden.",
        )
    return None


# Record fields that may be quoted in an action with their unit (e.g. "64 kg").
_RECORD_UNITS = {"weight_kg": "kg", "height_cm": "cm"}

# A number with a dose, rate or weight unit, e.g. "500 mg", "4 tablets", "100 mL/h".
_QTY = re.compile(
    r"(?<![A-Za-z0-9.])(\d+(?:[.,]\d+)?)\s*"
    r"(mg/kg|mcg/kg|ml/kg|ml/h|ml/hr|mg|mcg|µg|kg|g|ml|l|units?|iu|tablets?|tabs?|capsules?"
    r"|caps?|drops?|cm)(?![A-Za-z])",
    re.I,
)
_UNIT_ALIASES = {"µg": "mcg", "ml/hr": "ml/h", "tab": "tablet", "cap": "capsule"}


def _norm_number(n: str) -> str:
    n = n.replace(",", "")
    return n.rstrip("0").rstrip(".") if "." in n else n


def _norm_unit(u: str) -> str:
    u = u.lower()
    u = u[:-1] if u.endswith("s") and u not in {"tabs", "caps"} else u
    u = {"tabs": "tablet", "caps": "capsule"}.get(u, u)
    return _UNIT_ALIASES.get(u, u)


def quantities_in(text: str) -> set[tuple[str, str]]:
    return {(_norm_number(m.group(1)), _norm_unit(m.group(2))) for m in _QTY.finditer(text or "")}


def _record_quantities(patient: dict[str, Any] | None) -> set[tuple[str, str]]:
    out = set()
    for key, unit in _RECORD_UNITS.items():
        value = (patient or {}).get(key)
        if isinstance(value, int | float):
            out.add((_norm_number(f"{value:g}"), unit))
    return out


def _untraced_spans(
    action: Action,
    calcs: dict[str, CalcResult],
    formulary: Formulary,
    patient: dict[str, Any] | None,
) -> list[tuple[int, int, str]]:
    """Where the action states a number that SpaceDoc cannot trace.

    A number with a unit (a dose, rate or weight) must match, number and unit together, the
    linked calculator result or a record value (weight in kg). A bare number must appear in the
    calculator result (e.g. "every 6 hours"). Without a calculator result, the product strength
    printed in the formulary is allowed instead. With one, it is not: "ibuprofen 200 mg" next to
    a calculated 400 mg would show two different doses.
    """
    text = action.text
    calc = calcs.get(action.calc_ref or "")
    item = formulary.find(action.item) if action.item else None
    allowed_q = _record_quantities(patient)
    allowed_n: set[str] = set()
    if calc:
        sources = [calc.text, f"{calc.value:g} {calc.unit}"]
    else:
        sources = [item.strength] if item and item.strength else []
    for source in sources:
        allowed_q |= quantities_in(source)
        allowed_n |= numbers_in(source)
    spans, covered = [], []
    for m in _QTY.finditer(text):
        covered.append((m.start(), m.end()))
        if (_norm_number(m.group(1)), _norm_unit(m.group(2))) not in allowed_q:
            spans.append((m.start(), m.end(), m.group(0)))
    for m in _NUM.finditer(text):
        if any(a <= m.start() < b for a, b in covered):
            continue
        if _norm_number(m.group(0)) not in allowed_n:
            spans.append((m.start(), m.end(), m.group(0)))
    return sorted(spans)


def untraced_action_numbers(
    action: Action,
    calcs: dict[str, CalcResult],
    formulary: Formulary,
    patient: dict[str, Any] | None = None,
) -> list[str]:
    return [t for _, _, t in _untraced_spans(action, calcs, formulary, patient)]


def action_display_text(
    action: Action,
    calcs: dict[str, CalcResult],
    formulary: Formulary,
    patient: dict[str, Any] | None = None,
) -> str | None:
    """The action text with untraced numbers removed, or None if nothing was removed."""
    spans = _untraced_spans(action, calcs, formulary, patient)
    if not spans:
        return None
    text = action.text
    for start, end, _ in reversed(spans):
        text = text[:start] + text[end:]
    return re.sub(r"\s{2,}", " ", text).replace(" ,", ",").replace("( )", "").strip()


def check_action_numbers(
    action: Action,
    calcs: dict[str, CalcResult],
    formulary: Formulary,
    patient: dict[str, Any] | None = None,
) -> Finding | None:
    """SR-02 for actions: a dose or rate must come from SpaceDoc's calculator.

    With a calculator result linked, numbers the model wrote are removed and the calculated
    value is shown instead (a warning). Without one, the action cannot be given as written.
    """
    missing = untraced_action_numbers(action, calcs, formulary, patient)
    if not missing:
        return None
    wrote = ", ".join(f'"{m}"' for m in missing)
    if action.calc_ref in calcs:
        return Finding(
            rule_id="DOSE-REPLACED",
            severity="warn",
            target=action.id,
            message=f"The model wrote {wrote} itself. SpaceDoc removed it; use the calculator "
            "result shown with this action.",
        )
    return Finding(
        rule_id="NUM-ACTION",
        severity="block",
        target=action.id,
        message=f"The model wrote {wrote} itself and SpaceDoc has no calculator result for "
        "it, so it is not shown. Doses and rates must come from SpaceDoc's calculator or a "
        "clinician.",
    )


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
                message="This medication is not matched to an item in the onboard formulary, "
                "so SpaceDoc cannot check its availability, expiry, allergies or dose.",
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


def check_allergies(
    action: Action, formulary: Formulary, patient: dict[str, Any] | None
) -> list[Finding]:
    """A medication must not match an allergy in the patient record (by name or drug class)."""
    allergies = [str(a) for a in (patient or {}).get("allergies") or []]
    if action.kind != "medication" or not action.item or not allergies:
        return []
    item = formulary.find(action.item)
    if item is None:
        return []
    terms = {t.lower().rstrip("s") for t in item.names() + item.allergy_classes if t}
    findings = []
    for allergy in allergies:
        text = allergy.lower()
        words = {w.rstrip("s") for w in re.findall(r"[a-z][a-z-]+", text)}
        if any(t in text for t in terms) or words & terms:
            findings.append(
                Finding(
                    rule_id="ALLERGY",
                    severity="block",
                    target=action.id,
                    message=f"The patient's record lists an allergy: {allergy}. {item.name} "
                    "matches it by name or drug class. Do not give it without a clinician's "
                    "decision.",
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


def record_summary(patient: dict[str, Any] | None) -> str:
    """One line describing the record SpaceDoc used, e.g. "C1 · 46 F · 64 kg · allergies: none"."""
    if not patient:
        return "none"
    p = patient
    parts = [str(p["crew_id"])] if p.get("crew_id") else []
    if p.get("age") is not None or p.get("sex"):
        parts.append(" ".join(str(x) for x in (p.get("age"), p.get("sex")) if x is not None))
    if p.get("weight_kg") is not None:
        parts.append(
            f"{p['weight_kg']:g} kg"
            if isinstance(p["weight_kg"], int | float)
            else str(p["weight_kg"])
        )
    for key in ("allergies", "medications"):
        if key in p:
            parts.append(f"{key}: {', '.join(map(str, p[key])) or 'none'}")
    return " · ".join(parts) or "record without the usual fields"


def patient_text(patient: dict[str, Any] | None) -> str:
    return yaml.safe_dump(patient or {}, sort_keys=True)


def patient_document(patient: dict[str, Any] | None) -> str:
    """The record as plain "field: value" lines, which suit the grounding checker better
    than YAML. Nested fields are joined ("vitals heart rate: 96"); empty lists read "none"."""
    lines: list[str] = []

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                walk(f"{prefix} {k}".strip(), v)
            return
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value) if value else "none"
        lines.append(f"{prefix.replace('_', ' ')}: {value}")

    walk("", patient or {})
    return "\n".join(lines)
