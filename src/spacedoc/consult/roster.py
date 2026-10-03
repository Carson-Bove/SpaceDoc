"""The crew roster: who is using SpaceDoc, and who the patient is."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

CLINICAL_ROLES = {"cmo", "backup_cmo"}


class CrewMember(BaseModel):
    crew_id: str
    role: str
    medical_role: Literal["cmo", "backup_cmo", "crew"] = "crew"
    record: dict[str, Any] = {}

    @property
    def is_clinical(self) -> bool:
        return self.medical_role in CLINICAL_ROLES

    def label(self) -> str:
        med = {"cmo": "CMO", "backup_cmo": "backup CMO", "crew": "crew"}[self.medical_role]
        return f"{self.crew_id} · {self.role} · {med}"


def load_roster(data_dir: Path) -> dict[str, CrewMember]:
    raw = yaml.safe_load((data_dir / "crew" / "roster.yaml").read_text())
    members = [CrewMember(**m) for m in raw["crew"]]
    return {m.crew_id: m for m in members}
