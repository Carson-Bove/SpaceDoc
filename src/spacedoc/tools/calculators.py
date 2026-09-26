"""Deterministic clinical calculators (component C-06).

Requirement SR-02: every number SpaceDoc shows for a dose, rate or score comes from here,
never from the language model. Each result carries a `calc_id` that the answer must cite.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from spacedoc.tools.formulary import Formulary


class CalcError(ValueError):
    """Raised for invalid or out-of-range calculator input."""


class CalcResult(BaseModel):
    calc_id: str
    calculator: str
    inputs: dict[str, Any]
    value: float
    unit: str
    text: str
    warnings: list[str] = []


def _calc_id(name: str, inputs: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps([name, inputs], sort_keys=True).encode()).hexdigest()
    return f"calc-{digest[:8]}"


def _result(name: str, inputs: dict, value: float, unit: str, text: str, warnings=None):
    return CalcResult(
        calc_id=_calc_id(name, inputs),
        calculator=name,
        inputs=inputs,
        value=value,
        unit=unit,
        text=text,
        warnings=warnings or [],
    )


def _fmt(x: float) -> str:
    return f"{x:g}"


def weight_based_dose(formulary: Formulary, drug: str, weight_kg: float) -> CalcResult:
    """Single dose = mg/kg × weight, clamped to the formulary's min/max, rounded to a
    dose the onboard product can deliver (e.g. whole tablets)."""
    if not 30 <= weight_kg <= 200:
        raise CalcError(f"weight_kg={weight_kg} is outside the adult range this calculator accepts")
    item = formulary.find(drug)
    if item is None:
        raise CalcError(f"{drug} is not in the formulary")
    if item.dosing is None:
        raise CalcError(f"No dosing table entry for {item.name}")
    d = item.dosing
    raw = d.mg_per_kg * weight_kg
    capped = min(raw, d.max_mg)
    if d.min_mg is not None:
        capped = max(capped, d.min_mg)
    dose = math.floor(capped / d.round_to_mg) * d.round_to_mg
    if dose <= 0:
        raise CalcError(f"Computed dose for {item.name} rounds to zero")
    warnings = []
    if raw > d.max_mg:
        warnings.append(f"Capped at the maximum single dose of {_fmt(d.max_mg)} mg")
    if item.validation_status != "clinician-validated":
        warnings.append("Dosing table entry is NOT clinician-validated")
    interval = f", {d.interval}" if d.interval else ""
    inputs = {"drug": item.id, "weight_kg": weight_kg}
    text = f"{item.name} {_fmt(dose)} mg {d.route}{interval}"
    return _result("weight_based_dose", inputs, dose, "mg", text, warnings)


_MASS = {"mcg": 1e-6, "mg": 1e-3, "g": 1.0, "kg": 1e3, "lb": 453.59237}


def convert_units(value: float, from_unit: str, to_unit: str) -> CalcResult:
    f, t = from_unit.lower(), to_unit.lower()
    inputs = {"value": value, "from_unit": f, "to_unit": t}
    if f in _MASS and t in _MASS:
        out = value * _MASS[f] / _MASS[t]
    elif (f, t) == ("c", "f"):
        out = value * 9 / 5 + 32
    elif (f, t) == ("f", "c"):
        out = (value - 32) * 5 / 9
    elif (f, t) == ("mg/dl_glucose", "mmol/l_glucose"):
        out = value / 18.016
    elif (f, t) == ("mmol/l_glucose", "mg/dl_glucose"):
        out = value * 18.016
    else:
        raise CalcError(f"Unsupported conversion {from_unit} -> {to_unit}")
    out = round(out, 2)
    return _result("convert_units", inputs, out, t, f"{_fmt(value)} {f} = {_fmt(out)} {t}")


def glasgow_coma_scale(eye: int, verbal: int, motor: int) -> CalcResult:
    for name, v, hi in (("eye", eye, 4), ("verbal", verbal, 5), ("motor", motor, 6)):
        if not 1 <= v <= hi:
            raise CalcError(f"GCS {name} must be 1-{hi}, got {v}")
    total = eye + verbal + motor
    inputs = {"eye": eye, "verbal": verbal, "motor": motor}
    return _result(
        "glasgow_coma_scale", inputs, total, "points", f"GCS {total} (E{eye} V{verbal} M{motor})"
    )


def qsofa(respiratory_rate: float, systolic_bp: float, altered_mentation: bool) -> CalcResult:
    score = int(respiratory_rate >= 22) + int(systolic_bp <= 100) + int(bool(altered_mentation))
    inputs = {
        "respiratory_rate": respiratory_rate,
        "systolic_bp": systolic_bp,
        "altered_mentation": bool(altered_mentation),
    }
    warnings = (
        ["qSOFA >= 2: higher risk of poor outcome if infection is present"] if score >= 2 else []
    )
    return _result("qsofa", inputs, score, "points", f"qSOFA {score}/3", warnings)


def maintenance_fluids_421(weight_kg: float) -> CalcResult:
    """Holliday-Segar '4-2-1' hourly maintenance rate."""
    if not 0 < weight_kg <= 200:
        raise CalcError(f"weight_kg={weight_kg} out of range")
    rate = 4 * min(weight_kg, 10) + 2 * min(max(weight_kg - 10, 0), 10) + max(weight_kg - 20, 0)
    inputs = {"weight_kg": weight_kg}
    return _result(
        "maintenance_fluids_421", inputs, rate, "mL/h", f"Maintenance fluids {_fmt(rate)} mL/h"
    )


# Registry: what the LLM may request, with argument descriptions for the prompt.
CALCULATORS: dict[str, tuple[Callable[..., CalcResult], str]] = {
    "weight_based_dose": (
        weight_based_dose,
        "drug (formulary name); weight is taken from the record",
    ),
    "convert_units": (convert_units, "value, from_unit, to_unit (mcg/mg/g/kg/lb, c/f, glucose)"),
    "glasgow_coma_scale": (glasgow_coma_scale, "eye 1-4, verbal 1-5, motor 1-6"),
    "qsofa": (qsofa, "respiratory_rate, systolic_bp, altered_mentation (true/false)"),
    "maintenance_fluids_421": (maintenance_fluids_421, "weight is taken from the record"),
}


def run_calculator(
    name: str, args: dict[str, Any], formulary: Formulary, patient: dict[str, Any] | None
) -> CalcResult:
    """Dispatch an LLM calculator request. Patient weight always comes from the record,
    never from the model, so a hallucinated weight cannot reach a dose."""
    if name not in CALCULATORS:
        raise CalcError(f"Unknown calculator {name!r}")
    fn, _ = CALCULATORS[name]
    args = dict(args)
    warnings: list[str] = []
    if name in {"weight_based_dose", "maintenance_fluids_421"}:
        weight = (patient or {}).get("weight_kg")
        if weight is None:
            raise CalcError("Patient weight is not in the record; measure and record it first")
        if "weight_kg" in args and float(args["weight_kg"]) != float(weight):
            warnings.append(
                f"Model-supplied weight {args['weight_kg']} ignored; record says {weight}"
            )
        args["weight_kg"] = float(weight)
    if name == "weight_based_dose":
        result = fn(formulary, **args)
    else:
        result = fn(**args)
    result.warnings = warnings + result.warnings
    return result


def describe_calculators() -> str:
    return "\n".join(f"- {name}: {desc}" for name, (_, desc) in CALCULATORS.items())
