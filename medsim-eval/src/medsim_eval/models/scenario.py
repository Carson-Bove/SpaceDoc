"""Scenario: a medical case (docs/11 §4.3).

A scenario no longer names a mission. It says where the case *can* happen; the runner places it
in representative missions for those environments, so one case is tested across environments.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from medsim_eval.models.chart import Chart
from medsim_eval.models.common import (
    Duration,
    Env,
    Id,
    Offset,
    Strict,
    Timed,
    Versioned,
    check_duration,
    check_offset,
)

Status = Literal["draft", "in_review", "physiology_review", "approved", "retired"]
ALL_ENVS: list[Env] = ["T1", "T2", "T3", "T4", "T5"]

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

# What can be wrong with the speaker's input, for input_quality above 1.
INPUT_PROBLEMS = {
    "vague": "describes things loosely",
    "wrong_terms": "uses the wrong words for body parts, drugs or devices",
    "missing_details": "leaves things out unless asked directly",
    "misread_numbers": "reads or reports numbers wrongly",
    "contradictory": "contradicts what they said earlier",
    "panicked": "rushed, repeats themself, hard to keep on track",
}


class Author(Strict):
    name: str = Field(description="Full name")
    contact: str = Field(description="Email or phone")


class TimelineEntry(Timed):
    """One point in the course of illness."""

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


class Inject(Timed):
    """A mission event dropped into the run, as in a launch-readiness sim."""

    kind: EventKind
    duration: Duration | None = None
    target: str | None = Field(None, description="Equipment, drug or crew id affected, if any")
    text: str | None = None

    @field_validator("duration")
    @classmethod
    def _d(cls, v: str | None) -> str | None:
        return check_duration(v) if v is not None else v


class ActionRef(Strict):
    """Something the assistant can direct. `refs` names kit items when it matters (any of them)."""

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
    refs: list[str] = Field(default=[], description="Kit item ids; any one of them counts")
    text: str | None = Field(None, description="Plain-words description for reviewers")


class TimeCritical(Strict):
    """The standard course rule: on time pushes toward the best case, late toward the worst."""

    action: ActionRef
    by: Offset

    @field_validator("by")
    @classmethod
    def _by(cls, v: str) -> str:
        return check_offset(v)

    @model_validator(mode="after")
    def _said(self) -> TimeCritical:
        if not self.action.refs and not self.action.text:
            raise ValueError("say what counts: pick kit items or describe it")
        return self


class GroundTruth(Strict):
    diagnosis: str | None = Field(
        None, description="Defaults to the IMM condition's name; set to word it differently"
    )
    etiology: str = Field(description="The cause, e.g. obstructing appendicolith")
    differential: list[str] = Field(default=[], description="Ranked, most likely first")
    must_not_miss: list[str] = []
    synonyms: dict[str, list[str]] = Field(
        default={}, description="diagnosis or etiology -> other names that count as a match"
    )


class PatientCase(Strict):
    crew_id: Id = Field(description="Crewmember from the roster")
    condition: Id = Field(description="IMM condition id from the CLiFF index")
    chart: Chart = Field(description="The chart as it stands for this case")
    timeline: list[TimelineEntry] = Field(
        default=[], description="Medical timeline / course of illness"
    )
    time_critical: list[TimeCritical] = []
    ground_truth: GroundTruth


class Familiarity(Strict):
    """1 = none, 5 = expert."""

    medicine: int | None = Field(None, ge=1, le=5)
    equipment: int | None = Field(None, ge=1, le=5)
    assistant: int | None = Field(None, ge=1, le=5)


class HistoryIfAsked(Strict):
    if_asked: str = Field(description="e.g. whether the pain moves")
    says: str = Field(description="e.g. it started around the belly button, now it's lower right")


class Speaker(Strict):
    """The crewmember the assistant talks to, played by an AI from their roster entry."""

    crew_id: Id
    role: Literal["patient", "cmo", "crew"] = Field(
        description="patient: the patient themself; cmo: the crew medical officer; crew: another crewmember helping"
    )
    opening: str = Field(description="Chief complaint (patient) or opening question (CMO, crew)")
    emergent: bool = Field(False, description="Acts under time pressure; changes behaviour only")
    input_quality: int = Field(1, ge=1, le=5, description="1 clear and accurate … 5 very poor")
    input_problems: list[str] = Field(
        default=[], description="Which kinds of poor input, see INPUT_PROBLEMS"
    )
    familiarity: Familiarity = Field(
        default_factory=Familiarity, description="Overrides the roster"
    )
    behaviour: str | None = None
    additional_history: list[HistoryIfAsked] = []

    @model_validator(mode="after")
    def _problems(self) -> Speaker:
        unknown = set(self.input_problems) - set(INPUT_PROBLEMS)
        if unknown:
            raise ValueError(
                f"unknown input problems {sorted(unknown)}; use {sorted(INPUT_PROBLEMS)}"
            )
        if self.input_quality == 1 and self.input_problems:
            raise ValueError(
                "input quality 1 means clear input; remove the input problems or raise the level"
            )
        return self


class Review(Strict):
    status: Status = "draft"
    reviewers: list[str] = []
    physiology_review: Literal["not_needed", "requested", "done"] = "not_needed"
    notes_for_physiologist: str | None = None
    notes: str | None = None


class Scenario(Versioned):
    scenario_id: Id
    title: str = Field(description="Chief complaint, in a few words")
    authors: list[Author] = Field(min_length=1)
    symptoms: list[str] = Field(default=[], description="ICD-10-CM symptom codes, e.g. R10.31")
    environments: list[Env] = Field(
        default_factory=lambda: list(ALL_ENVS), min_length=1, description="Where this can happen"
    )
    patients: list[PatientCase] = Field(
        min_length=1, description="One today; several for triage later"
    )
    speaker: Speaker
    injects: list[Inject] = []
    complicators: str | None = Field(
        None, description="Free text: anything that makes this case harder"
    )
    rubric: str = Field(description="Rubric file name, relative to this file")
    duration: Duration = Field("3d", description="How long to simulate before the run ends")
    review: Review = Field(default_factory=Review)
    tags: list[str] = []

    @field_validator("duration")
    @classmethod
    def _dur(cls, v: str) -> str:
        return check_duration(v)

    @model_validator(mode="after")
    def _consistent(self) -> Scenario:
        if len(set(self.environments)) != len(self.environments):
            raise ValueError("environments are listed twice")
        ids = [p.crew_id for p in self.patients]
        if len(ids) != len(set(ids)):
            raise ValueError("each patient must be a different crewmember")
        if self.speaker.role == "patient" and self.speaker.crew_id not in ids:
            raise ValueError("the speaker is the patient, so speaker.crew_id must be a patient")
        if self.speaker.role != "patient" and self.speaker.crew_id in ids:
            raise ValueError(
                f"{self.speaker.crew_id} is a patient; set the speaker's role to patient"
            )
        return self
