"""Rubrics (docs/11 §5).

The *base rubric* (e.g. general@0.1) holds what is the same for every scenario: safety gates,
the 1–5 domains with anchors, and the outcome measures. It is versioned; each scenario rubric
pins the base version it was written against, so updating the base never silently changes
old scores. A *scenario rubric* adds scenario-specific gates and checklist items.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from medsim_eval.models.common import Id, Offset, Strict, Versioned, check_offset


class Gate(Strict):
    id: Id
    text: str = Field(description="A never event: any occurrence fails the run")


class Anchors(Strict):
    """Written descriptions of what a 1, a 3 and a 5 look like. 2 and 4 sit between them."""

    one: str = Field(alias="1")
    three: str = Field(alias="3")
    five: str = Field(alias="5")

    model_config = {"extra": "forbid", "populate_by_name": True}


class Domain(Strict):
    id: Id
    name: str
    description: str
    anchors: Anchors


class OutcomeMeasure(Strict):
    id: Id
    name: str
    description: str
    unit: str | None = None


class BaseRubric(Versioned):
    rubric_id: Id
    version: str = Field(pattern=r"^\d+\.\d+$")
    status: Literal["draft", "approved", "superseded"] = "draft"
    title: str
    gates: list[Gate]
    domains: list[Domain]
    outcomes: list[OutcomeMeasure]
    changelog: list[str] = []

    @property
    def ref(self) -> str:
        return f"{self.rubric_id}@{self.version}"

    @model_validator(mode="after")
    def _unique(self) -> BaseRubric:
        for name in ("gates", "domains", "outcomes"):
            ids = [x.id for x in getattr(self, name)]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name}: ids must be unique")
        return self


class ChecklistItem(Strict):
    id: Id
    text: str = Field(description="Observable behaviour, in plain words")
    type: Literal["binary", "rating"] = Field(
        "binary", description="binary: met / not met. rating: 1–5 against anchors you write"
    )
    weight: int = Field(
        ge=-10, le=10, description="+ for things to do, − for things not to do; not 0"
    )
    by: Offset | None = Field(None, description="Deadline in simulated time, e.g. T+2h")
    domain: Id = Field(description="Which base-rubric domain this informs, e.g. D3")
    anchors: Anchors | None = Field(None, description="Required for rating items")
    rationale: str | None = None

    @field_validator("by")
    @classmethod
    def _by(cls, v: str | None) -> str | None:
        return check_offset(v) if v is not None else v

    @model_validator(mode="after")
    def _shape(self) -> ChecklistItem:
        if self.weight == 0:
            raise ValueError("weight must not be 0")
        if self.type == "rating":
            if self.anchors is None:
                raise ValueError("rating items need anchors for 1, 3 and 5")
            if self.weight < 0:
                raise ValueError("rating items take a positive weight; write harms as binary items")
        elif self.anchors is not None:
            raise ValueError("binary items do not take anchors")
        return self


class ScenarioRubric(Versioned):
    rubric_id: Id
    scenario_id: Id
    base: str = Field(
        pattern=r"^[A-Za-z0-9._-]+@\d+\.\d+$", description="Base rubric, e.g. general@0.1"
    )
    gates: list[Gate] = Field(
        default=[], description="Scenario-specific never events, added to the base gates"
    )
    items: list[ChecklistItem] = Field(min_length=1)
    must_not_miss_tested: bool = Field(
        True,
        description="Score each ground-truth must-not-miss diagnosis as considered or excluded",
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _unique(self) -> ScenarioRubric:
        ids = [g.id for g in self.gates] + [i.id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("gate and item ids must be unique")
        if not any(i.weight > 0 for i in self.items):
            raise ValueError("at least one item needs a positive weight")
        return self
