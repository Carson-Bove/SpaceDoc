"""Check files against their schema and against each other.

Schema checks catch a malformed file. Cross-reference checks catch a well-formed file that
points at something that doesn't exist: a DRM phase, a crewmember, a CLiFF condition, a base
rubric version. Warnings flag things a reviewer should look at but that don't block a file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from medsim_eval.models import FILE_TYPES, file_type
from medsim_eval.models.condition import ConditionIndex
from medsim_eval.models.drm import DRM
from medsim_eval.models.environment import EnvironmentSet
from medsim_eval.models.habitat import Habitat
from medsim_eval.models.rubric import BaseRubric, ScenarioRubric
from medsim_eval.models.scenario import KNOWN_STATE_VARS, Scenario
from medsim_eval.simtime import parse_duration, parse_offset

# The library that ships with the package (DRMs, habitats, conditions, base rubrics).
DEFAULT_LIBRARY = Path(__file__).resolve().parents[2] / "library"

# Words that make a binary item a judgment call instead of an observation.
VAGUE = re.compile(
    r"\b(appropriate(ly)?|adequate(ly)?|proper(ly)?|reasonabl[ey]|sufficient(ly)?|good)\b", re.I
)


@dataclass
class Issue:
    level: Literal["error", "warning"]
    file: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.file}: {self.message}"


@dataclass
class Library:
    drms: dict[str, DRM] = field(default_factory=dict)
    habitats: dict[str, Habitat] = field(default_factory=dict)
    base_rubrics: dict[str, BaseRubric] = field(default_factory=dict)
    conditions: dict[str, object] = field(default_factory=dict)
    environments: dict[str, object] = field(default_factory=dict)

    def add(self, model: BaseModel) -> None:
        if isinstance(model, DRM):
            self.drms[model.drm_id] = model
        elif isinstance(model, Habitat):
            self.habitats[model.profile_id] = model
        elif isinstance(model, BaseRubric):
            self.base_rubrics[model.ref] = model
        elif isinstance(model, ConditionIndex):
            self.conditions.update({c.cliff_id: c for c in model.conditions})
        elif isinstance(model, EnvironmentSet):
            self.environments.update({e.env: e for e in model.environments})


def _files(paths: list[Path]) -> list[Path]:
    out = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(f for f in p.rglob("*.json") if file_type(f.name)))
        else:
            out.append(p)
    return out


def _format_error(err: ValidationError) -> list[str]:
    msgs = []
    for e in err.errors():
        loc = ".".join(str(x) for x in e["loc"]) or "(file)"
        msgs.append(f"{loc}: {e['msg']}")
    return msgs


def load(path: Path) -> tuple[BaseModel | None, list[Issue]]:
    """Parse one file into its model, or return the reasons it can't be."""
    name = str(path)
    suffix = file_type(path.name)
    if suffix is None:
        known = ", ".join(sorted(FILE_TYPES))
        return None, [Issue("error", name, f"unknown file type; names must end in one of: {known}")]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, [Issue("error", name, f"not readable JSON: {e}")]
    try:
        return FILE_TYPES[suffix].model_validate(data), []
    except ValidationError as e:
        return None, [Issue("error", name, m) for m in _format_error(e)]


def load_library(directory: Path) -> tuple[Library, list[Issue]]:
    lib, issues = Library(), []
    for f in _files([directory]):
        model, errs = load(f)
        issues += errs
        if model is not None:
            lib.add(model)
    return lib, issues


def check_drm(drm: DRM, lib: Library, name: str) -> list[Issue]:
    issues = []
    for p in drm.phases:
        for h in p.habitats:
            if h not in lib.habitats:
                issues.append(Issue("error", name, f"phase {p.id}: unknown habitat profile {h!r}"))
            elif p.env not in lib.habitats[h].envs:
                issues.append(
                    Issue("warning", name, f"phase {p.id}: habitat {h!r} is not listed for {p.env}")
                )
        if not p.habitats:
            issues.append(
                Issue(
                    "warning",
                    name,
                    f"phase {p.id}: no habitat profile; scenarios here can't check equipment",
                )
            )
        if p.eva and p.eva.window_days:
            lo, hi = p.eva.window_days
            start, end = drm.phase_window(p.id)
            if lo < start or hi > end:
                issues.append(
                    Issue(
                        "warning",
                        name,
                        f"phase {p.id}: EVA window {lo:g}–{hi:g} is outside the phase (days {start:g}–{end:g})",
                    )
                )
    for c in drm.crew:
        if c.eva and not any(p.eva and c.crew_id in p.eva.crew for p in drm.phases):
            issues.append(
                Issue("warning", name, f"{c.crew_id} is marked eva but is in no phase's EVA plan")
            )
    return issues


def check_rubric(rubric: ScenarioRubric, lib: Library, name: str) -> list[Issue]:
    issues = []
    base = lib.base_rubrics.get(rubric.base)
    if base is None:
        known = ", ".join(sorted(lib.base_rubrics)) or "none loaded"
        return [Issue("error", name, f"unknown base rubric {rubric.base!r} (known: {known})")]
    if base.status == "superseded":
        issues.append(
            Issue("warning", name, f"base rubric {rubric.base} is superseded; consider migrating")
        )
    domains = {d.id for d in base.domains}
    clash = {g.id for g in rubric.gates} & {g.id for g in base.gates}
    if clash:
        issues.append(Issue("error", name, f"gate ids clash with the base rubric: {sorted(clash)}"))
    for item in rubric.items:
        if item.domain not in domains:
            issues.append(
                Issue(
                    "error",
                    name,
                    f"item {item.id}: unknown domain {item.domain!r} (base has {sorted(domains)})",
                )
            )
        if item.type == "binary" and VAGUE.search(item.text):
            word = VAGUE.search(item.text).group(0)
            issues.append(
                Issue(
                    "warning",
                    name,
                    f"item {item.id}: {word!r} is a judgment call; say what an observer would see",
                )
            )
    return issues


def check_scenario(
    sc: Scenario, lib: Library, name: str, rubric: ScenarioRubric | None
) -> list[Issue]:
    issues: list[Issue] = []

    def err(msg: str) -> None:
        issues.append(Issue("error", name, msg))

    def warn(msg: str) -> None:
        issues.append(Issue("warning", name, msg))

    drm = lib.drms.get(sc.drm)
    if drm is None:
        err(f"unknown DRM {sc.drm!r}")
    else:
        phase = next((p for p in drm.phases if p.id == sc.phase), None)
        if phase is None:
            err(f"DRM {sc.drm} has no phase {sc.phase!r} (phases: {[p.id for p in drm.phases]})")
        else:
            start, end = drm.phase_window(sc.phase)
            if not start <= sc.mission_day < end:
                err(
                    f"mission_day {sc.mission_day:g} is outside phase {sc.phase} (days {start:g} to {end:g})"
                )
            _check_refs(sc, [lib.habitats[h] for h in phase.habitats if h in lib.habitats], warn)
        if sc.crewmember not in {c.crew_id for c in drm.crew}:
            err(f"crewmember {sc.crewmember!r} is not in DRM {sc.drm}")

    if lib.conditions and sc.condition.cliff_id not in lib.conditions:
        err(f"unknown condition {sc.condition.cliff_id!r}; pick one from the CLiFF index")

    end = parse_duration(sc.duration)
    for e in [*sc.timeline, *sc.events]:
        if parse_offset(e.t) > end:
            warn(f"{e.kind} at {e.t} is after the scenario ends ({sc.duration})")
    for entry in sc.timeline:
        for var in entry.state:
            if var not in KNOWN_STATE_VARS:
                warn(f"keyframe at {entry.t}: {var!r} is not a known state variable")
    for b in sc.branches:
        if b.when.type == "state" and b.when.var not in KNOWN_STATE_VARS:
            warn(f"branch {b.id}: {b.when.var!r} is not a known state variable")

    if sc.status == "approved":
        if not sc.reviewers:
            err("approved scenarios need at least one reviewer")
        if sc.physiology_review == "requested":
            err("physiology review was requested but isn't done")

    if rubric is not None:
        if rubric.scenario_id != sc.scenario_id:
            err(f"rubric {sc.rubric} is for {rubric.scenario_id!r}, not {sc.scenario_id!r}")
        for item in rubric.items:
            if item.by and parse_offset(item.by) > end:
                warn(f"rubric item {item.id}: deadline {item.by} is after the scenario ends")
    return issues


def _check_refs(sc: Scenario, habitats: list[Habitat], warn) -> None:
    """Treatments and equipment named in branches and events should exist aboard."""
    if not habitats:
        return
    aboard = {i.id for h in habitats for i in [*h.equipment, *h.formulary]}
    for b in sc.branches:
        act = b.when.action
        if (
            act
            and act.ref
            and act.kind in ("treatment", "test", "imaging", "procedure")
            and act.ref not in aboard
        ):
            warn(
                f"branch {b.id}: {act.ref!r} is not in this phase's habitat equipment or formulary"
            )
    for e in sc.events:
        if (
            e.kind in ("equipment_failure", "consumable_loss")
            and e.target
            and e.target not in aboard
        ):
            warn(
                f"event at {e.t}: {e.target!r} is not in this phase's habitat equipment or formulary"
            )


def validate(paths: list[Path], library_dir: Path = DEFAULT_LIBRARY) -> list[Issue]:
    lib, issues = load_library(library_dir)
    files = _files(paths)
    loaded: dict[Path, BaseModel] = {}
    for f in files:
        if f.resolve().is_relative_to(library_dir.resolve()):
            # Already loaded with the library; reload only to report its errors once.
            model, errs = load(f)
            if model is not None:
                loaded[f] = model
            continue
        model, errs = load(f)
        issues += errs
        if model is not None:
            loaded[f] = model
            lib.add(model)

    for f, model in loaded.items():
        name = str(f)
        if isinstance(model, DRM):
            issues += check_drm(model, lib, name)
        elif isinstance(model, ScenarioRubric):
            issues += check_rubric(model, lib, name)
        elif isinstance(model, Scenario):
            rubric_path = f.parent / model.rubric
            rubric = None
            if not rubric_path.exists():
                issues.append(
                    Issue(
                        "error",
                        name,
                        f"rubric file {model.rubric!r} not found next to the scenario",
                    )
                )
            elif rubric_path in loaded:
                rubric = loaded[rubric_path]
            else:
                # Scenario passed on its own: check its rubric too.
                rubric, errs = load(rubric_path)
                issues += errs
                if isinstance(rubric, ScenarioRubric):
                    issues += check_rubric(rubric, lib, str(rubric_path))
            issues += check_scenario(model, lib, name, rubric)
    return issues
