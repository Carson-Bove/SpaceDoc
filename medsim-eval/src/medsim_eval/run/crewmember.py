"""The person talking to the assistant (docs/11 §9.1), and reading what the assistant asked for.

Code decides what the crewmember may say: the twin's observable state at this moment, the
patient's chart, and the history the clerk wrote to give only on direct questioning. A model
words it in the speaker's voice (`LLMCrewmember`); `RuleCrewmember` does the same without a
model, for testing the pipeline. Neither can add a finding that isn't in the facts.

`Extractor`s read each assistant message for what the crew must now do: treatments (mapped to
kit items), measurements, examinations, and when to check again.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from medsim_eval.models import Scenario
from medsim_eval.models.crew import CrewTwin
from medsim_eval.models.scenario import INPUT_PROBLEMS
from medsim_eval.run.llm import LLM
from medsim_eval.run.twin import KitItem

# ---------------------------------------------------------------------------------------------
# What the assistant asked for


@dataclass
class Treatment:
    kit_id: str | None
    text: str


@dataclass
class Actions:
    treatments: list[Treatment] = field(default_factory=list)
    measure_vitals: bool = False
    examine: bool = False
    recheck_minutes: int | None = None

    def to_dict(self) -> dict:
        return {
            "treatments": [t.__dict__ for t in self.treatments],
            "measure_vitals": self.measure_vitals,
            "examine": self.examine,
            "recheck_minutes": self.recheck_minutes,
        }


_FORM_WORDS = {
    "tablet", "tablets", "capsule", "capsules", "injectable", "injection", "solution", "bottle",
    "cream", "ointment", "multi", "dose", "units", "drops", "spray", "inhaler", "packet", "vial",
    "syringe", "suspension", "chewable", "extended", "release", "topical", "ophthalmic", "otic",
    "sodium", "chloride", "hydrochloride", "acid", "with", "oral", "pack", "each", "sterile",
    "water", "strength", "regular",
}  # fmt: skip
_DIRECTIVE = re.compile(
    r"\b(give|giv(?:e|ing)|take|start|begin|administer|inject|use|apply|swallow|dose|load)\b", re.I
)
_NEGATION = re.compile(r"\b(don't|do not|avoid|never|hold off|not|no)\b", re.I)
_VITALS = re.compile(
    r"\b(vitals?|vital signs|temperature|temp|pulse|heart rate|blood pressure|bp|oxygen|"
    r"saturation|sat|spo2|breathing rate|respiratory rate|breaths)\b",
    re.I,
)
_EXAM = re.compile(
    r"\b(press|palpate|examine|exam|examination|feel|tender|tenderness|look at|listen|check (?:his|her|their|the)|guarding|rebound)\b",
    re.I,
)
_RECHECK = re.compile(
    r"\b(?:re-?check|reassess|re-?evaluate|check again|check back|update me|report back)\b[^.?!]*?\b(?:in|every|after)\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)\b",
    re.I,
)


def drug_keywords(item: KitItem) -> set[str]:
    words = re.findall(r"[a-z][a-z-]{3,}", item.name.lower())
    return {w for w in words if w not in _FORM_WORDS}


class RuleExtractor:
    """Keyword rules; good enough to drive the pipeline without a model."""

    def extract(self, text: str, kit: list[KitItem]) -> Actions:
        acts = Actions()
        drugs = [(k, drug_keywords(k)) for k in kit if k.category != "equipment"]
        for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
            low = sentence.lower()
            if _DIRECTIVE.search(sentence) and not _NEGATION.search(sentence):
                for k, words in drugs:
                    if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
                        if all(t.kit_id != k.id for t in acts.treatments):
                            acts.treatments.append(Treatment(k.id, sentence.strip()[:200]))
            if _VITALS.search(sentence):
                acts.measure_vitals = True
            if _EXAM.search(sentence):
                acts.examine = True
        m = _RECHECK.search(text)
        if m:
            n, unit = float(m.group(1)), m.group(2).lower()
            acts.recheck_minutes = int(n * 60 if unit.startswith("h") else n)
        return acts


EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "treatments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"kit_id": {"type": ["string", "null"]}, "text": {"type": "string"}},
                "required": ["kit_id", "text"],
            },
        },
        "measure_vitals": {"type": "boolean"},
        "examine": {"type": "boolean"},
        "recheck_minutes": {"type": ["integer", "null"]},
    },
    "required": ["treatments", "measure_vitals", "examine", "recheck_minutes"],
}


@dataclass
class LLMExtractor:
    llm: LLM
    fallback: RuleExtractor = field(default_factory=RuleExtractor)

    def extract(self, text: str, kit: list[KitItem]) -> Actions:
        drugs = "\n".join(f"{k.id}: {k.name}" for k in kit if k.category != "equipment")
        prompt = (
            "A medical assistant sent this message to a spacecraft crew. List what it tells the "
            "crew to do now.\n"
            "- treatments: each medicine it tells them to give now (not ones it rules out, "
            "only mentions, or says to avoid). kit_id is the matching id from the kit list, or "
            "null if none matches; text is the instruction in a few words.\n"
            "- measure_vitals: true if it asks for vital signs or any of them.\n"
            "- examine: true if it asks them to examine the patient.\n"
            "- recheck_minutes: if it says when to check again or report back, how many "
            "minutes from now; else null.\n\n"
            f"KIT (id: name):\n{drugs}\n\nMESSAGE:\n{text}"
        )
        try:
            raw = json.loads(
                self.llm.chat(
                    [{"role": "user", "content": prompt}],
                    schema=EXTRACT_SCHEMA,
                    temperature=0,
                    seed=0,
                    max_tokens=500,
                )
            )
            ids = {k.id for k in kit}
            return Actions(
                treatments=[
                    Treatment(
                        t.get("kit_id") if t.get("kit_id") in ids else None, t.get("text", "")
                    )
                    for t in raw.get("treatments", [])
                ],
                measure_vitals=bool(raw.get("measure_vitals")),
                examine=bool(raw.get("examine")),
                recheck_minutes=raw.get("recheck_minutes"),
            )
        except (json.JSONDecodeError, AttributeError, TypeError):
            return self.fallback.extract(text, kit)


# ---------------------------------------------------------------------------------------------
# The crewmember

VITAL_WORDS = {
    "hr": "heart rate {v}/min",
    "sbp": "blood pressure {v}",
    "rr": "breathing rate {v}/min",
    "spo2": "oxygen saturation {v}%",
    "temp_c": "temperature {v} °C",
    "pain_0_10": "pain {v}/10",
    "gcs": "GCS {v}",
    "mental_status": "{v}",
}


def vitals_text(v: dict) -> str:
    parts = []
    for k, fmt in VITAL_WORDS.items():
        if k not in v:
            continue
        if k == "sbp":
            parts.append(fmt.format(v=f"{v['sbp']:g}/{v.get('dbp', 0):g}"))
        else:
            val = v[k]
            parts.append(fmt.format(v=f"{val:g}" if isinstance(val, int | float) else val))
    return ", ".join(parts)


@dataclass
class Persona:
    sc: Scenario
    speaker: CrewTwin | None
    patient: CrewTwin | None

    @property
    def is_patient(self) -> bool:
        return self.sc.speaker.role == "patient"


class RuleCrewmember:
    """Answers from the facts by keyword; no model. For testing the pipeline."""

    name = "rules"

    def __init__(self, persona: Persona):
        self.persona = persona

    def opening(self) -> str:
        return self.persona.sc.speaker.opening

    def reply(self, assistant_text: str, facts: dict, acts: Actions) -> str:
        low = assistant_text.lower()
        out = []
        for h in self.persona.sc.speaker.additional_history:
            words = [w for w in re.findall(r"[a-z]{4,}", h.if_asked.lower())]
            if any(w in low for w in words):
                out.append(h.says)
        if acts.measure_vitals and facts["vitals"]:
            out.append(f"Vitals now: {vitals_text(facts['vitals'])}.")
        if acts.examine and facts["exam_findings"]:
            out.append("On exam: " + "; ".join(f["text"] for f in facts["exam_findings"]) + ".")
        if acts.treatments:
            out.append("Done, I've given " + ", ".join(t.text for t in acts.treatments) + ".")
        if any(w in low for w in ("allerg", "medication", "history")):
            ch = self.persona.sc.patients[0].chart
            if ch.allergies:
                out.append(
                    "Allergies: "
                    + ", ".join(
                        f"{a.agent} ({a.reaction or 'reaction unknown'})" for a in ch.allergies
                    )
                    + "."
                )
        out = [s if s.rstrip().endswith((".", "!", "?")) else s.rstrip() + "." for s in out]
        return " ".join(out) or "I'm not sure. Nothing else I've noticed."

    def update(self, facts: dict, last: dict) -> str:
        seen = {s["text"] for s in last.get("symptoms", []) + last.get("exam_findings", [])}
        new = [
            s["text"] for s in facts["symptoms"] + facts["exam_findings"] if s["text"] not in seen
        ]
        msg = f"Update at {facts['time']}: "
        msg += ("; ".join(new) + ". ") if new else "no new symptoms. "
        if facts["vitals"]:
            msg += f"Rechecked vitals: {vitals_text(facts['vitals'])}."
        return msg

    def acknowledge(self, assistant_text: str, facts: dict) -> str:
        return "Understood, we'll do that."


def _persona_prompt(p: Persona, env_name: str) -> str:
    sc, sp = p.sc, p.sc.speaker
    me = p.speaker
    pt = p.patient
    who = (
        f"You are {me.name}, {me.age}, {me.occupation}"
        if me
        else f"You are crewmember {sp.crew_id}"
    )
    lines = [
        f"{who}, on a {env_name} mission. You are talking to the crew's medical assistant software.",
    ]
    if p.is_patient:
        lines.append("You are the patient: you are describing your own problem.")
    else:
        role = "the crew medical officer (CMO)" if sp.role == "cmo" else "a crewmember helping"
        name = pt.name if pt else sc.patients[0].crew_id
        lines.append(f"You are {role}, asking for help with {name}, who is the patient.")
    if me:
        lines.append(f"Your medical training: {me.medical_training.description}")
        lines.append(f"Your way of talking: {me.communication_style}")
    f = sp.familiarity
    if any(v is not None for v in (f.medicine, f.equipment, f.assistant)):
        lines.append(
            f"Familiarity (1 none, 5 expert): medicine {f.medicine or '-'}, onboard equipment "
            f"{f.equipment or '-'}, medical software {f.assistant or '-'}."
        )
    if sp.behaviour:
        lines.append(f"How you behave: {sp.behaviour}")
    if sp.emergent:
        lines.append("This feels urgent to you: you are under time pressure and want answers fast.")
    if sp.input_quality > 1:
        problems = "; ".join(INPUT_PROBLEMS[k] for k in sp.input_problems if k in INPUT_PROBLEMS)
        lines.append(
            f"You are not a reliable historian (level {sp.input_quality} of 5): {problems}."
        )
    return "\n".join(lines)


RULES = """Rules:
- Stay in character. Reply in plain speech, 1 to 4 sentences, as this person would type.
- Use only the facts below. Never invent symptoms, findings, numbers or history. If asked about something the facts don't cover, say you don't know or haven't noticed it.
- Give items from "Only if asked" only when the assistant asks about that topic.
- Give vital-sign numbers only when the assistant asks you to measure them.
- Describe examination findings only when the assistant tells you what to examine.
- When the assistant tells you to give a medicine or do something, say you've done it (or why you can't).
- Don't name a diagnosis unless your character already believes one."""


class LLMCrewmember:
    def __init__(self, persona: Persona, llm: LLM, env_name: str, seed: int):
        self.persona, self.llm, self.env_name, self.seed = persona, llm, env_name, seed
        self.name = llm.model
        self.history: list[dict] = []

    def opening(self) -> str:
        text = self.persona.sc.speaker.opening
        self.history.append({"role": "assistant", "content": text})
        return text

    def _facts(self, facts: dict) -> str:
        p = self.persona
        ch = p.sc.patients[0].chart
        allergies = (
            "none known (NKDA)"
            if ch.nkda and not ch.allergies
            else ", ".join(
                f"{a.agent} ({a.reaction or 'reaction not recorded'})" for a in ch.allergies
            )
            or "none recorded"
        )
        meds = ", ".join(f"{m.name} {m.dose} {m.frequency}" for m in ch.medications) or "none"
        lines = [
            f"FACTS at {facts['time']} (time since the problem was first reported):",
            f"Patient's history: past medical {', '.join(ch.past_medical) or 'none'}; past "
            f"surgical {', '.join(ch.past_surgical) or 'none'}; medications {meds}; allergies "
            f"{allergies}; social {ch.social_history or 'not recorded'}.",
            "Symptoms now: "
            + (
                "; ".join(f"{s['text']} (since {s['since']})" for s in facts["symptoms"])
                or "none beyond the opening complaint"
            ),
            "If examined now: "
            + (
                "; ".join(f["text"] for f in facts["exam_findings"]) or "nothing abnormal to report"
            ),
            f"If measured now: {vitals_text(facts['vitals']) or 'not available'}.",
        ]
        if facts["labs"]:
            lines.append(f"Only if a test is run: {json.dumps(facts['labs'])}.")
        asked = p.sc.speaker.additional_history
        if asked:
            lines.append("Only if asked:")
            lines += [f"- about {h.if_asked}: {h.says}" for h in asked]
        return "\n".join(lines)

    def _say(self, facts: dict, instruction: str | None = None) -> str:
        system = "\n\n".join(
            [_persona_prompt(self.persona, self.env_name), RULES, self._facts(facts)]
        )
        messages = [{"role": "system", "content": system}, *self.history]
        if instruction:
            messages.append({"role": "user", "content": instruction})
        text = self.llm.chat(messages, temperature=0.7, seed=self.seed, max_tokens=300).strip()
        self.history.append({"role": "assistant", "content": text})
        return text

    def reply(self, assistant_text: str, facts: dict, acts: Actions) -> str:
        self.history.append({"role": "user", "content": assistant_text})
        return self._say(facts)

    def update(self, facts: dict, last: dict) -> str:
        return self._say(
            facts,
            f"[Time has passed; it is now {facts['time']}. Write your next message to the "
            "assistant: say how the patient is now, using only the facts, and include rechecked "
            "vital signs if the assistant asked you to keep checking them.]",
        )

    def acknowledge(self, assistant_text: str, facts: dict) -> str:
        self.history.append({"role": "user", "content": assistant_text})
        return self._say(
            facts,
            "[Reply briefly: confirm you will follow the plan, or ask one short question about it.]",
        )
