"""A medical chart in the history-and-physical layout clerks learn in school.

Shared by the crew roster (each crewmember's standing chart) and scenarios (the chart as it
stands for one case, which a clerk may adjust).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from medsim_eval.models.common import Strict


class Medication(Strict):
    name: str = Field(description="Generic name, e.g. loratadine")
    form: str | None = Field(None, description="Form or route: tablet, capsule, IV, inhaler…")
    dose: str = Field(description="e.g. 10 mg")
    frequency: str = Field(description="e.g. once daily, as needed")
    indication: str | None = None


class Allergy(Strict):
    agent: str = Field(description="e.g. penicillin, tree pollen")
    kind: Literal["drug", "food", "environmental", "other"] = "drug"
    reaction: str | None = Field(None, description="e.g. rash, hives, anaphylaxis")


class Chart(Strict):
    past_medical: list[str] = []
    past_surgical: list[str] = []
    medications: list[Medication] = []
    allergies: list[Allergy] = []
    nkda: bool = Field(False, description="No known drug allergies")
    family_history: list[str] = Field(default=[], description="Optional")
    social_history: str | None = None
    immunizations: list[str] = Field(default=[], description="e.g. tetanus booster 2023")

    @model_validator(mode="after")
    def _nkda(self) -> Chart:
        drugs = [a.agent for a in self.allergies if a.kind == "drug"]
        if self.nkda and drugs:
            raise ValueError(f"marked NKDA but lists drug allergies: {drugs}")
        return self
