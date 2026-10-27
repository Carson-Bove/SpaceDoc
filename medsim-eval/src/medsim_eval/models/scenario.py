"""Scenario: one medical event, in one DRM phase, for one crewmember (docs/11 §4.3)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from medsim_eval.models.common import (
    Duration,
    Id,
    Offset,
    Strict,
    Timed,
    Versioned,
    check_duration,
    check_offset,
)

Status = Literal["draft", "in_review", "physiology_review", "approved", "retired"]

# Twin state variables the validator knows. Others are allowed but warned about, so the
# physiologist can decide whether to add them.
KNOWN_STATE_VARS = {
    "hr": "heart rate, /min",
    "sbp": "systolic blood pressure, mmHg",
    "dbp": "diastolic blood pressure, mmHg",
    "rr": "respiratory rate, /min",
    "spo2": "oxygen saturation, %",
    "temp_c": "temperature, °C",
    "pain_0_10": "pain score",
    "gcs": "Glasgow Coma Scale",
    "glucose_mmol_l": "blood glucose, mmol/L",
    "wbc_10e9_l": "white cell count, 10^9/L",
    "hgb_g_dl": "haemoglobin, g/dL",
    "lactate_mmol_l": "lactate, mmol/L",
    "urine_output_ml_h": "urine output, mL/h",
    "mental_status": "alert | confused | drowsy | unresponsive",
}


class Condition(Strict):
    cliff_id: Id = Field(description="Condition id from the CLiFF index")
    course: Literal["auto", "best_case", "worst_case"] = Field(
        "auto",
        description="auto: the twin picks best/worst case from the CLiFF probabilities and the "
        "assistant's actions. Fixing it forces that course",
    )


class TimelineEntry(Timed):
    kind: Literal["symptom", "finding", "keyframe", "note"]
    text: str | None = None
    state: dict[str, float | bool | str] = Field(
        default={}, description="Twin state at this time (keyframes): e.g. {temp_c: 38.1, hr: 104}"
    )
    when: Literal["always", "treated", "untreated"] = Field(
        "always", description="Only applies if the patient has / has not been treated by then"
    )

    @model_validator(mode="after")
    def _shape(self) -> TimelineEntry:
        if self.kind == "keyframe" and not self.state:
            raise ValueError("a keyframe needs at least one state value")
        if self.kind != "keyframe" and not self.text:
            raise ValueError(f"a {self.kind} entry needs text")
        return self


EventKind = Literal[
    "solar_particle_event",
    "dust_storm",
    "comm_blackout",
    "comm_degraded",
    "equipment_failure",
    "consumable_loss",
    "power_reduction",
    "crew_unavailable",
    "eva_in_progress",
    "other",
]


class Event(Timed):
    kind: EventKind
    duration: Duration | None = None
    target: str | None = Field(None, description="Equipment, drug or crew id affected, if any")
    text: str | None = None

    @field_validator("duration")
    @classmethod
    def _d(cls, v: str | None) -> str | None:
        return check_duration(v) if v is not None else v


class ActionRef(Strict):
    """Something the assistant can direct. `ref` names the drug, test or equipment when it matters."""

    kind: Literal[
        "exam",
        "test",
        "imaging",
        "treatment",
        "procedure",
        "monitoring",
        "ground_consult",
        "rtdc",
        "other",
    ]
    ref: str | None = Field(None, description="e.g. a formulary or equipment id from the habitat")
    text: str | None = Field(None, description="Plain-words description for reviewers")


class Trigger(Strict):
    type: Literal["action_by", "no_action_by", "state"]
    action: ActionRef | None = None
    by: Offset | None = None
    var: str | None = None
    op: Literal["<", "<=", ">", ">=", "==", "!="] | None = None
    value: float | bool | str | None = None

    @field_validator("by")
    @classmethod
    def _by(cls, v: str | None) -> str | None:
        return check_offset(v) if v is not None else v

    @model_validator(mode="after")
    def _shape(self) -> Trigger:
        if self.type in ("action_by", "no_action_by"):
            if self.action is None or self.by is None:
                raise ValueError(f"{self.type} needs action and by")
        elif self.var is None or self.op is None or self.value is None:
            raise ValueError("state trigger needs var, op and value")
        return self


class Effect(Strict):
    course: Literal["best_case", "worst_case"] | None = Field(None, description="Force the course")
    course_bias: float | None = Field(
        None, ge=-1, le=1, description="Nudge toward best (+) or worst (-) case without forcing it"
    )
    event: Event | None = Field(None, description="Inject an event")
    state: dict[str, float | bool | str] = Field(default={}, description="Set twin state values")
    note: str | None = None

    @model_validator(mode="after")
    def _nonempty(self) -> Effect:
        if (
            self.course is None
            and self.course_bias is None
            and self.event is None
            and not self.state
        ):
            raise ValueError("an effect must change something: course, course_bias, event or state")
        return self


class Branch(Strict):
    id: Id
    when: Trigger
    then: Effect
    note: str | None = None


class UserAgent(Strict):
    """The crewmember the assistant talks to, played by an LLM."""

    role: Literal["cmo", "crew", "patient"] = Field(
        description="cmo: the crew medical officer; crew: another crewmember helping; patient: the patient themself"
    )
    name: str | None = None
    knowledge: str = Field(description="Medical training, in plain words")
    facts: dict[str, str] = Field(
        default={}, description="What the persona knows and will say if asked (history, timing, …)"
    )
    behaviour: str | None = Field(
        None, description="How they act: reluctant, anxious, downplays pain, …"
    )


class GroundTruth(Strict):
    primary_dx: str
    synonyms: dict[str, list[str]] = {}
    acceptable_differential: list[str] = []
    must_not_miss: list[str] = []


class Scenario(Versioned):
    scenario_id: Id
    title: str
    status: Status = "draft"
    authors: list[str] = Field(min_length=1)
    reviewers: list[str] = []
    physiology_review: Literal["not_needed", "requested", "done"] = "not_needed"
    drm: Id
    phase: Id
    mission_day: float = Field(ge=0)
    crewmember: Id
    condition: Condition
    patient: dict[str, Any] = Field(
        default={},
        description="Overrides and extras: age, weight_kg, allergies, medications, history",
    )
    presentation: str = Field(description="What the user agent says first")
    timeline: list[TimelineEntry] = []
    events: list[Event] = []
    branches: list[Branch] = []
    complicators: str | None = Field(
        None, description="Free text: anything that makes this case harder"
    )
    user_agent: UserAgent
    ground_truth: GroundTruth
    rubric: str = Field(description="Rubric file name, relative to this file")
    duration: Duration = Field("3d", description="How long to simulate before the run ends")
    tags: list[str] = []
    notes_for_physiologist: str | None = None
    notes: str | None = None

    @field_validator("duration")
    @classmethod
    def _dur(cls, v: str) -> str:
        return check_duration(v)

    @model_validator(mode="after")
    def _ids(self) -> Scenario:
        ids = [b.id for b in self.branches]
        if len(ids) != len(set(ids)):
            raise ValueError("branch ids must be unique")
        return self
