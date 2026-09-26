"""Environment context (component C-12): the single source of truth for mission state."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class EnvironmentContext(BaseModel):
    tier: str
    name: str
    gravity_g: float
    one_way_delay_s: float
    link_available: bool = True
    evacuation: str = Field(description="Time to definitive care, e.g. 'hours', 'days', 'none'")
    mission_day: int | None = None
    formulary_ref: str
    equipment: list[str] = []
    notes: str = ""

    @property
    def tags(self) -> set[str]:
        """Tags used to filter and boost retrieval and to select rules."""
        tags = {self.tier.lower()}
        if self.gravity_g < 0.05:
            tags.add("microgravity")
        elif self.gravity_g < 0.9:
            tags.add("partial-gravity")
        if self.one_way_delay_s > 60:
            tags.add("delayed-comm")
        if self.evacuation == "none":
            tags.add("no-evacuation")
        if self.tier in {"T4", "T5"}:
            tags.add("long-duration")
        return tags

    def summary(self) -> str:
        delay = (
            f"{self.one_way_delay_s:.0f} s"
            if self.one_way_delay_s < 120
            else f"{self.one_way_delay_s / 60:.0f} min"
        )
        day = f", mission day {self.mission_day}" if self.mission_day else ""
        return (
            f"{self.tier} {self.name}: gravity {self.gravity_g:g} g, one-way comm delay {delay}, "
            f"Earth link {'up' if self.link_available else 'DOWN'}, "
            f"evacuation to definitive care: {self.evacuation}{day}."
        )

    def prompt_summary(self) -> str:
        """Summary plus the equipment list, for the model prompt."""
        return f"{self.summary()} Equipment aboard: {', '.join(self.equipment) or 'none listed'}."


def load_environment(tier: str, data_dir: Path, **overrides) -> EnvironmentContext:
    path = data_dir / "environments" / f"{tier.upper()}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No environment preset for tier {tier!r} ({path})")
    raw = yaml.safe_load(path.read_text())
    raw.update({k: v for k, v in overrides.items() if v is not None})
    return EnvironmentContext(**raw)


def list_tiers(data_dir: Path) -> list[EnvironmentContext]:
    return [
        EnvironmentContext(**yaml.safe_load(p.read_text()))
        for p in sorted((data_dir / "environments").glob("T*.yaml"))
    ]
