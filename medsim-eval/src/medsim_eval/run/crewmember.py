"""The person talking to the assistant (docs/11 §9.1), and reading what the assistant asked for.

Code decides what the crewmember may say: the twin's observable state at this moment, the
patient's chart, and the history the clerk wrote to give only on direct questioning. A local
model only picks which facts the assistant asked about (`FactCrewmember`); the reply is the
clerk's own words. `RuleCrewmember` does the same by keyword, without a model. Neither can add a
finding that isn't in the facts. (A 3B model that worded replies itself invented exposures and
changed numbers in a real run, so no model writes the crewmember's text for now.)

`Extractor`s read each assistant message for what the crew must now do: treatments (mapped to
kit items), measurements, examinations, and when to check again.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from medsim_eval.models import Scenario
from medsim_eval.models.crew import CrewTwin
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
    r"\b(press|palpate|examine|exam|examination|tender|tenderness|look at (?:his|her|their|the)|listen to|guarding|rebound)\b",
    re.I,
)
_RECHECK = re.compile(
    r"\b(?:re-?check|reassess|re-?evaluate|check again|check back|update me|report back)\b[^.?!]*?\b(?:in|every|after)\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m)\b",
    re.I,
)


def drug_keywords(item: KitItem) -> set[str]:
    words = re.findall(r"[a-z][a-z-]{3,}", item.name.lower())
    return {w for w in words if w not in _FORM_WORDS}


def match_kit(text: str, kit: list[KitItem]) -> list[KitItem]:
    """Kit drugs named in the text: for each drug word, the item it describes most exactly."""
    low = text.lower()
    best: dict[str, tuple[float, KitItem]] = {}
    for k in kit:
        if k.category == "equipment":
            continue
        words = drug_keywords(k)
        hits = [w for w in words if re.search(rf"\b{re.escape(w)}\b", low)]
        for w in hits:
            score = len(hits) / len(words)
            if w not in best or score > best[w][0]:
                best[w] = (score, k)
    out: list[KitItem] = []
    for _, k in best.values():
        if k not in out:
            out.append(k)
    return out


class RuleExtractor:
    """Reads a message for what the crew must do, by rules: a medicine counts only if the kit
    item's name is in a sentence that tells the crew to give it."""

    def extract(self, text: str, kit: list[KitItem]) -> Actions:
        acts = Actions()
        for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
            if _DIRECTIVE.search(sentence) and not _NEGATION.search(sentence):
                for k in match_kit(sentence, kit):
                    if all(x.kit_id != k.id for x in acts.treatments):
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

    def update(self, facts: dict, last: dict, done: list[str] | None = None) -> str:
        seen = {s["text"] for s in last.get("symptoms", []) + last.get("exam_findings", [])}
        new = [
            s["text"] for s in facts["symptoms"] + facts["exam_findings"] if s["text"] not in seen
        ]
        msg = f"Update at {facts['time']}: "
        msg += ("; ".join(new) + ". ") if new else "no new symptoms. "
        if done:
            msg += f"Done since we last spoke: {'; '.join(done)}. "
        if facts["vitals"]:
            msg += f"Rechecked vitals: {vitals_text(facts['vitals'])}."
        return msg


@dataclass
class Fact:
    id: str
    topic: str
    text: str


def chart_facts(persona: Persona) -> list[Fact]:
    ch = persona.sc.patients[0].chart
    allergies = (
        "no known drug allergies"
        if ch.nkda and not ch.allergies
        else ", ".join(f"{a.agent} ({a.reaction or 'reaction not recorded'})" for a in ch.allergies)
    )
    meds = ", ".join(
        " ".join(x for x in (m.name, m.dose, m.frequency) if x) for m in ch.medications
    )
    out = [
        Fact("C1", "allergies", f"Allergies: {allergies or 'none recorded'}"),
        Fact("C2", "regular medications", f"Regular medications: {meds or 'none'}"),
        Fact(
            "C3", "past medical history", f"Past illnesses: {', '.join(ch.past_medical) or 'none'}"
        ),
        Fact("C4", "past surgery", f"Past surgery: {', '.join(ch.past_surgical) or 'none'}"),
    ]
    if ch.social_history:
        out.append(Fact("C5", "smoking, alcohol, exercise", f"Social history: {ch.social_history}"))
    return out


def fact_list(persona: Persona, facts: dict, acts: Actions) -> list[Fact]:
    """Everything the crewmember could truthfully say right now, one item each."""
    out = [
        Fact(f"H{i}", h.if_asked, h.says)
        for i, h in enumerate(persona.sc.speaker.additional_history, 1)
    ]
    out += [Fact(f"S{i}", "current symptom", s["text"]) for i, s in enumerate(facts["symptoms"], 1)]
    out += chart_facts(persona)
    if acts.examine:
        out += [
            Fact(f"E{i}", "finding on examination", f["text"])
            for i, f in enumerate(facts["exam_findings"], 1)
        ]
    return out


def _keywords(text: str) -> set[str]:
    stop = {"what", "when", "where", "which", "that", "this", "with", "have", "from", "about", "does", "your", "there", "been", "they", "them", "then", "than", "also", "more", "some", "started", "start"}  # fmt: skip
    return {w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in stop}


def rule_select(assistant_text: str, items: list[Fact]) -> set[str]:
    """Facts whose topic words appear in the assistant's message."""
    asked = _keywords(assistant_text)
    stems = {w[:5] for w in asked}
    picked = set()
    for f in items:
        if f.id.startswith(("H", "C")) and any(w[:5] in stems for w in _keywords(f.topic)):
            picked.add(f.id)
    return picked


def join_points(points: list[str]) -> str:
    return " ".join(p if p.rstrip().endswith((".", "!", "?")) else p.rstrip() + "." for p in points)


SELECT_SYSTEM = (
    "You check whether a message asks about a topic. Answer yes if any question in the message "
    "is about that topic, even in different words. Answer no if the message does not ask about it."
)
# Worked examples steer a small model far better than rules do (measured: 27 of 27 asked-for
# facts found, about 1 in 8 unasked facts offered; with rules alone it found 1 of 13).
SELECT_SHOTS = [
    ("Does she have a cough or a sore throat? Any fever?", "cough", "yes"),
    ("Does she have a cough or a sore throat? Any fever?", "allergies", "no"),
    ("When did the headache begin, and has it got worse?", "when it started", "yes"),
    ("Please check her pulse and tell me the number.", "past surgery", "no"),
    ("Has he been sick or had loose stools?", "vomiting", "yes"),
    ("Has he been sick or had loose stools?", "regular medications", "no"),
    ("What tablets is she on?", "regular medications", "yes"),
    ("Thanks, give me a moment to check.", "when it started", "no"),
]
SELECT_SCHEMA = {
    "type": "object",
    "properties": {"asks": {"enum": ["yes", "no"]}},
    "required": ["asks"],
}
NOTHING = "Nothing else that I've noticed."


class FactCrewmember:
    """Answers only from the scenario's facts, in the clerk's own words.

    A local model decides one thing: for each fact, whether the assistant's message asks about
    it. It writes no text of its own, so it cannot invent a symptom, an event or a number. Vital
    signs are added by code when the assistant asks for them, and a question no fact answers
    gets "nothing else noticed".
    """

    def __init__(self, persona: Persona, llm: LLM, seed: int = 0):
        self.persona, self.llm, self.seed = persona, llm, seed
        self.name = f"facts ({llm.model})"
        self.said: set[str] = set()
        self.log: list[dict] = []

    def opening(self) -> str:
        return self.persona.sc.speaker.opening

    def _asks(self, message: str, topic: str) -> bool:
        m = [{"role": "system", "content": SELECT_SYSTEM}]
        for msg, top, ans in SELECT_SHOTS:
            m.append({"role": "user", "content": f'MESSAGE: "{msg}"\nTOPIC: {top}'})
            m.append({"role": "assistant", "content": json.dumps({"asks": ans})})
        m.append({"role": "user", "content": f'MESSAGE: "{message}"\nTOPIC: {topic}'})
        try:
            out = self.llm.chat(
                m, schema=SELECT_SCHEMA, temperature=0, seed=self.seed, max_tokens=10
            )
            return json.loads(out).get("asks") == "yes"
        except (json.JSONDecodeError, AttributeError, TypeError):
            return False

    def reply(self, assistant_text: str, facts: dict, acts: Actions) -> str:
        items = fact_list(self.persona, facts, acts)
        picked = rule_select(assistant_text, items)
        if "?" in assistant_text:
            for f in items:
                topic = f.topic if f.id[0] in "HC" else f.text
                if f.id not in picked and self._asks(assistant_text, topic):
                    picked.add(f.id)
        # The clerk's own answer on a topic replaces the chart line on the same topic.
        clerk_topics = {f.topic.lower() for f in items if f.id in picked and f.id[0] == "H"}
        picked -= {f.id for f in items if f.id[0] == "C" and f.topic.lower() in clerk_topics}
        # A symptom is said once; history is given again if asked again.
        chosen = [f for f in items if f.id in picked and not (f.id[0] == "S" and f.id in self.said)]
        self.said |= {f.id for f in chosen}
        said = [f"{f.topic.capitalize()}: {f.text}" if f.id[0] == "H" else f.text for f in chosen]
        parts = [join_points(said)] if chosen else []
        if acts.examine and not any(f.id[0] == "E" for f in chosen):
            parts.append("I examined as you asked and found nothing abnormal.")
        if acts.measure_vitals and facts["vitals"]:
            parts.append(f"Vital signs now: {vitals_text(facts['vitals'])}.")
        if "?" in assistant_text and (not chosen or assistant_text.count("?") > len(chosen)):
            parts.append(NOTHING)
        self.log.append({"selected": sorted(picked), "used": [f.id for f in chosen]})
        return " ".join(parts) or NOTHING

    def update(self, facts: dict, last: dict, done: list[str] | None = None) -> str:
        seen = {s["text"] for s in last.get("symptoms", []) + last.get("exam_findings", [])}
        new = [
            s["text"] for s in facts["symptoms"] + facts["exam_findings"] if s["text"] not in seen
        ]
        parts = [f"Update, {_elapsed(facts['time'])} after my first message."]
        parts.append(join_points(new) if new else "No new symptoms.")
        if done:
            parts.append(f"Done since we last spoke: {'; '.join(done)}.")
        if facts["vitals"]:
            parts.append(f"Vital signs now: {vitals_text(facts['vitals'])}.")
        return " ".join(parts)


def _elapsed(offset: str) -> str:
    m = re.fullmatch(r"T\+(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?", offset)
    if not m or not any(m.groups()):
        return "just"
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    parts = [
        f"{d} day{'s' if d != 1 else ''}" if d else "",
        f"{h} hour{'s' if h != 1 else ''}" if h else "",
        f"{mi} minutes" if mi and not d else "",
    ]
    return " ".join(p for p in parts if p)
