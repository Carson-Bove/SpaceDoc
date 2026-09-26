"""SpaceOSCE case format (see docs/08 §2 and docs/spaceosce-authoring-guide.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class CaseEnvironment(BaseModel):
    tier: str
    mission_day: int | None = None
    link_available: bool | None = None


class GroundTruth(BaseModel):
    primary_dx: str | None = None
    synonyms: dict[str, list[str]] = Field(
        default={}, description="condition -> other names that count as a match"
    )
    acceptable_differential: list[str] = []
    must_not_miss: list[str] = []


class CheckItem(BaseModel):
    id: str
    text: str = Field(description="What the rater looks for, in plain words")
    weight: float = 1.0
    auto_patterns: list[str] = Field(
        default=[],
        description="Optional regexes; if any matches the shown answer the item is auto-scored",
    )


class Case(BaseModel):
    case_id: str
    title: str
    status: Literal["draft", "approved", "retired"] = "draft"
    authors: list[str] = []
    reviewers: list[str] = []
    split: Literal["dev", "heldout"] = "dev"
    environment: CaseEnvironment
    user_role: str = "cmo"
    patient: dict[str, Any] = {}
    presentation: str = Field(description="What the user tells SpaceDoc (single turn in Phase 1)")
    script: dict[str, str] = Field(default={}, description="Standardized-patient answers (Phase 3)")
    ground_truth: GroundTruth = GroundTruth()
    expected_abstain: bool = False
    critical_actions: list[CheckItem] = []
    harmful_actions: list[CheckItem] = []
    communication_targets: list[str] = []
    tags: list[str] = []
    notes: str = ""


def load_cases(directory: Path) -> list[Case]:
    cases = []
    for path in sorted(directory.rglob("*.yaml")):
        cases.append(Case(**yaml.safe_load(path.read_text())))
    return cases
