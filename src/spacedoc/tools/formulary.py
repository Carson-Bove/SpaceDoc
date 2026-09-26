"""Onboard formulary and inventory (component C-07)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


class Dosing(BaseModel):
    """Weight-based single-dose parameters. Must be entered and validated by clinicians."""

    mg_per_kg: float
    min_mg: float | None = None
    max_mg: float
    round_to_mg: float = 1.0
    route: str
    interval: str | None = None  # descriptive, e.g. "every 6 hours as needed"


class FormularyItem(BaseModel):
    id: str
    name: str
    kind: Literal["drug", "device", "supply"]
    aliases: list[str] = []
    form: str | None = None
    strength: str | None = None
    quantity: float
    unit: str
    expiry: date | None = None
    dosing: Dosing | None = None
    substitutes: list[str] = []
    validation_status: Literal["unvalidated", "clinician-validated"] = "unvalidated"

    def names(self) -> list[str]:
        return [self.name.lower(), self.id.lower(), *(a.lower() for a in self.aliases)]


class Availability(BaseModel):
    status: Literal["available", "low", "expired", "depleted", "not_aboard"]
    item: FormularyItem | None = None
    message: str


class Formulary(BaseModel):
    ref: str
    description: str = ""
    items: list[FormularyItem]

    @classmethod
    def load(cls, ref: str, data_dir: Path) -> Formulary:
        path = data_dir / "formulary" / f"{ref}.yaml"
        return cls(**yaml.safe_load(path.read_text()))

    def find(self, name: str) -> FormularyItem | None:
        key = name.strip().lower()
        for item in self.items:
            if key in item.names():
                return item
        return None

    def availability(self, name: str, today: date | None = None) -> Availability:
        today = today or date.today()
        item = self.find(name)
        if item is None:
            return Availability(
                status="not_aboard", message=f"{name} is not in the onboard formulary"
            )
        if item.expiry and item.expiry < today:
            return Availability(
                status="expired", item=item, message=f"{item.name} expired on {item.expiry}"
            )
        if item.quantity <= 0:
            return Availability(status="depleted", item=item, message=f"{item.name} is used up")
        if item.quantity <= 2:
            return Availability(
                status="low",
                item=item,
                message=f"Only {item.quantity:g} {item.unit} of {item.name} left",
            )
        return Availability(status="available", item=item, message=f"{item.name} is aboard")

    def prompt_summary(self) -> str:
        """Compact list for the LLM prompt: names only, no doses (doses come from calculators)."""
        lines = []
        for item in self.items:
            extra = f" ({item.form} {item.strength})" if item.form and item.strength else ""
            lines.append(f"- {item.name}{extra} [{item.kind}]")
        return "\n".join(lines)
