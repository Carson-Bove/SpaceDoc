"""Deterministic safety nets for consults: vital-sign alerts, spaceflight must-not-miss
conditions and the exposure screen. All three run in code, not in the model, and read
draft rule files that the clinical team must review (data/rules/)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel

from spacedoc.consult.redflags import RedFlagHit, _negated

# ---- vital signs ---------------------------------------------------------------------------

_CLAUSES = re.compile(r"\n|;|(?<=[a-z%])\.\s")
_SPO2_CUE = re.compile(r"spo2|sp02|\bo2\b|\bsats?\b|saturation|oxygen|pulse ?ox|oximeter", re.I)
_PERCENT = re.compile(r"(?<![\d.])(\d{2,3})\s*%")
_BP_CUE = re.compile(r"blood pressure|\bbp\b|mm ?hg|cuff", re.I)
_BP = re.compile(r"(?<![\d.])(\d{2,3})\s*/\s*(\d{2,3})(?![\d.])")
_HR = re.compile(
    r"(?:heart rate|\bhr\b|pulse(?! ?ox))\D{0,15}?(\d{2,3})(?!\s*[%/\d])|(\d{2,3})\s*(?:bpm|beats)",
    re.I,
)
_RR = re.compile(
    r"(?:resp(?:iratory)? rate|\brr\b|breathing rate)\D{0,15}?(\d{1,2})(?!\s*[%/\d])"
    r"|(\d{1,2})\s*breaths",
    re.I,
)
_TEMP = re.compile(
    r"(?<![\d.])(\d{2,3}(?:\.\d+)?)\s*(?:°|degrees?|deg)?\s*(f|c|fahrenheit|celsius)(?![a-z])",
    re.I,
)
_TEMP_CUE = re.compile(r"temp|fever|thermometer", re.I)


class Reading(BaseModel):
    kind: str  # spo2, systolic_bp, heart_rate, respiratory_rate, temperature_c
    value: float
    text: str  # what the user wrote
    note: str = ""


def read_vitals(text: str) -> list[Reading]:
    """Measurements stated in free text. Conservative: each needs a cue word or unit."""
    out: list[Reading] = []
    for clause in _CLAUSES.split(text):
        if _SPO2_CUE.search(clause) and (m := _PERCENT.search(clause)):
            out.append(Reading(kind="spo2", value=float(m.group(1)), text=m.group(0)))
        if (m := _BP.search(clause)) and (_BP_CUE.search(clause) or "mm" in clause.lower()):
            a, b = int(m.group(1)), int(m.group(2))
            note = (
                ""
                if a >= b
                else ("The first number is lower than the second; recheck the reading.")
            )
            out.append(
                Reading(kind="systolic_bp", value=float(max(a, b)), text=m.group(0), note=note)
            )
        if (m := _HR.search(clause)) and not _SPO2_CUE.search(clause[: m.start()][-12:]):
            out.append(
                Reading(kind="heart_rate", value=float(m.group(1) or m.group(2)), text=m.group(0))
            )
        if m := _RR.search(clause):
            out.append(
                Reading(
                    kind="respiratory_rate", value=float(m.group(1) or m.group(2)), text=m.group(0)
                )
            )
        if (m := _TEMP.search(clause)) and (_TEMP_CUE.search(clause) or m.group(2)):
            value = float(m.group(1))
            if m.group(2).lower().startswith("f"):
                value = round((value - 32) * 5 / 9, 1)
            if 25 <= value <= 45:  # plausible body temperature in °C
                out.append(Reading(kind="temperature_c", value=value, text=m.group(0)))
    return out


class Threshold(BaseModel):
    label: str
    unit: str
    low: float | None = None
    high: float | None = None


class VitalRules(BaseModel):
    thresholds: dict[str, Threshold]
    steps: list[str] = []

    @classmethod
    def load(cls, data_dir: Path) -> VitalRules:
        return cls(**yaml.safe_load((data_dir / "rules" / "vital_signs.yaml").read_text()))

    def alerts(self, text: str, delay: str = "unknown") -> list[RedFlagHit]:
        hits = []
        for r in read_vitals(text):
            t = self.thresholds.get(r.kind)
            if t is None:
                continue
            if t.low is not None and r.value < t.low:
                where = f"below {t.low:g}"
            elif t.high is not None and r.value > t.high:
                where = f"above {t.high:g}"
            else:
                continue
            unit = t.unit if t.unit == "%" else f" {t.unit}"
            message = f"{t.label} {r.value:g}{unit} ({where})"
            if r.note:
                message += f". {r.note}"
            hits.append(
                RedFlagHit(
                    rule_id=f"VS-{r.kind.upper().replace('_', '-')}",
                    message=message,
                    matched=r.text,
                    steps=[s.replace("{delay}", delay) for s in self.steps],
                )
            )
        return hits


# ---- spaceflight must-not-miss conditions --------------------------------------------------


class MustNotMissRule(BaseModel):
    id: str
    condition: str
    aliases: list[str] = []
    patterns: list[str]
    min_matches: int = 2
    why: str
    ask: str

    def names(self) -> list[str]:
        return [self.condition.lower()] + [a.lower() for a in self.aliases]


class MustNotMiss(BaseModel):
    rules: list[MustNotMissRule]

    @classmethod
    def load(cls, data_dir: Path) -> MustNotMiss:
        return cls(**yaml.safe_load((data_dir / "rules" / "must_not_miss.yaml").read_text()))

    def match(self, text: str) -> list[MustNotMissRule]:
        out = []
        for rule in self.rules:
            hits = sum(
                1
                for p in rule.patterns
                if any(not _negated(text, m.start()) for m in re.finditer(p, text, re.I))
            )
            if hits >= rule.min_matches:
                out.append(rule)
        return out

    @staticmethod
    def on_list(rule: MustNotMissRule, conditions: list[str]) -> bool:
        listed = [c.lower() for c in conditions]
        return any(name in c or c in name for name in rule.names() for c in listed)


# ---- must-ask questions by complaint ------------------------------------------------------


def _says(patterns: list[str], text: str) -> bool:
    return any(not _negated(text, m.start()) for p in patterns for m in re.finditer(p, text, re.I))


class AskItem(BaseModel):
    id: str
    topic: str
    question: str
    asked: list[str] = []  # SpaceDoc has asked it, if its messages match
    answered: list[str] = []  # the user has already said it, if their words match
    skip_if_record: str | None = None


class AskList(BaseModel):
    id: str
    complaint: str
    triggers: list[str]
    asks: list[AskItem]


class MustAsk(BaseModel):
    lists: list[AskList]

    @classmethod
    def load(cls, data_dir: Path) -> MustAsk:
        return cls(**yaml.safe_load((data_dir / "rules" / "must_ask.yaml").read_text()))

    def match(self, user_text: str) -> list[AskList]:
        return [lst for lst in self.lists if _says(lst.triggers, user_text)]

    @staticmethod
    def uncovered(
        lst: AskList, spacedoc_text: str, user_text: str, record: dict | None
    ) -> list[AskItem]:
        """The list's questions not yet asked by SpaceDoc nor already answered by the user."""
        out = []
        for item in lst.asks:
            if item.skip_if_record and (record or {}).get(item.skip_if_record):
                continue
            if _says(item.asked, spacedoc_text) or (
                item.answered and _says(item.answered, user_text)
            ):
                continue
            out.append(item)
        return out


# ---- exposure screen -----------------------------------------------------------------------


class ScreenItem(BaseModel):
    id: str
    question: str  # shown on the card; SpaceDoc's wording, never screened
    label: str  # how the answer is described to the model and in the record
    if_yes: str  # what a "Yes" or "Not sure" adds to the must-not-miss matching


YES_WORDS = {"yes", "y"}
UNSURE_WORDS = {"not sure", "unsure", "?"}


def answer_kind(answer: str) -> str:
    """'yes', 'no', 'not sure' for a button answer, else 'typed'."""
    a = answer.strip().lower()
    if a in YES_WORDS:
        return "yes"
    if a in {"no", "n"}:
        return "no"
    if a in UNSURE_WORDS:
        return "not sure"
    return "typed"


class ExposureScreen(BaseModel):
    lead: str
    items: list[ScreenItem]

    @classmethod
    def load(cls, data_dir: Path) -> ExposureScreen:
        return cls(**yaml.safe_load((data_dir / "rules" / "exposure_screen.yaml").read_text()))

    def item(self, item_id: str) -> ScreenItem | None:
        return next((i for i in self.items if i.id == item_id), None)

    def _grouped(self, answers: dict[str, str]) -> dict[str, list[ScreenItem]]:
        groups: dict[str, list[ScreenItem]] = {"yes": [], "not sure": [], "no": []}
        for item in self.items:
            kind = answer_kind(answers.get(item.id, ""))
            if kind in groups:
                groups[kind].append(item)
        return groups

    def for_model(self, answers: dict[str, str]) -> str:
        """The answers as the model reads them: each "No" spelled out as "no ...", so a No
        cannot be mistaken for a Yes."""
        g = self._grouped(answers)
        parts = [f"YES: {i.label}" for i in g["yes"]]
        parts += [f"not sure: {i.label}" for i in g["not sure"]]
        parts += [f"no {i.label}" for i in g["no"]]
        if not parts:
            return ""
        return (
            "Exposure check (answered with buttons; treat each No as absent and do not ask "
            "about it again): " + "; ".join(parts) + "."
        )

    def for_summary(self, answers: dict[str, str]) -> str:
        """The answers for the assessment. Items answered No are not named, so their wording
        (smoke, radiation...) cannot steer the source search or the model."""
        g = self._grouped(answers)
        if not any(g.values()):
            return "Exposure check: not answered."
        if not g["yes"] and not g["not sure"] and len(g["no"]) == len(self.items):
            return f"Exposure check: No to all {len(self.items)} spaceflight exposures asked about."
        parts = []
        if g["yes"]:
            parts.append("Yes: " + "; ".join(i.label for i in g["yes"]) + ".")
        if g["not sure"]:
            parts.append("Not sure: " + "; ".join(i.label for i in g["not sure"]) + ".")
        unanswered = len(self.items) - sum(len(v) for v in g.values())
        if g["no"]:
            other = "the other " if g["yes"] or g["not sure"] else ""
            parts.append(f"No to {other}{len(g['no'])} asked about.")
        if unanswered:
            parts.append(f"{unanswered} not answered.")
        return "Exposure check: " + " ".join(parts)

    def must_not_miss_text(self, answers: dict[str, str]) -> list[str]:
        g = self._grouped(answers)
        return [i.if_yes for i in g["yes"]] + [f"possible {i.if_yes}" for i in g["not sure"]]
