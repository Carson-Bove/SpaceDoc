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
from medsim_eval.models.condition import Condition, ConditionIndex
from medsim_eval.models.crew import CrewRoster, CrewTwin
from medsim_eval.models.drm import DRM
from medsim_eval.models.environment import Environment, EnvironmentSet
from medsim_eval.models.habitat import Habitat
from medsim_eval.models.physiology import Physiology
from medsim_eval.models.reference import Encyclopedia, SymptomList
from medsim_eval.models.rubric import BaseRubric, ScenarioRubric
from medsim_eval.models.scenario import KNOWN_STATE_VARS, Scenario
from medsim_eval.simtime import parse_duration, parse_offset

# The library that ships with the package (DRMs, habitats, conditions, crew, base rubrics…).
DEFAULT_LIBRARY = Path(__file__).resolve().parents[2] / "library"

# Words that make a binary item a judgment call instead of an observation.
VAGUE = re.compile(
    r"\b(appropriate(ly)?|adequate(ly)?|proper(ly)?|reasonabl[ey]|sufficient(ly)?|good)\b", re.I
)


# Conditions a crewmember can't have after a given operation: condition id -> surgery words.
RULED_OUT_BY_SURGERY = {
    "appendicitis": ("appendectomy",),
    "cholelithiasis-biliary-colic-acute": ("cholecystectomy",),
}


@dataclass
class Issue:
    level: Literal["error", "warning", "info"]
    file: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.file}: {self.message}"


@dataclass
class Library:
    drms: dict[str, DRM] = field(default_factory=dict)
    habitats: dict[str, Habitat] = field(default_factory=dict)
    base_rubrics: dict[str, BaseRubric] = field(default_factory=dict)
    conditions: dict[str, Condition] = field(default_factory=dict)
    environments: dict[str, Environment] = field(default_factory=dict)
    crew: dict[str, CrewTwin] = field(default_factory=dict)
    physiology: list[Physiology] = field(default_factory=list)
    symptoms: set[str] = field(default_factory=set)
    encyclopedia: list[Encyclopedia] = field(default_factory=list)

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
        elif isinstance(model, CrewRoster):
            self.crew.update({c.crew_id: c for c in model.crew})
        elif isinstance(model, Physiology):
            self.physiology.append(model)
        elif isinstance(model, SymptomList):
            self.symptoms.update(s.code for s in model.symptoms)
        elif isinstance(model, Encyclopedia):
            self.encyclopedia.append(model)

    def habitats_in(self, env: str) -> list[Habitat]:
        """The habitats where a case runs in this environment (its representative DRM phase)."""
        e = self.environments.get(env)
        drm = self.drms.get(e.representative.drm) if e and e.representative else None
        phase = (
            next((p for p in drm.phases if p.id == e.representative.phase), None) if drm else None
        )
        return [self.habitats[h] for h in (phase.habitats if phase else []) if h in self.habitats]


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
    if (
        suffix == ".scenario.json"
        and isinstance(data, dict)
        and data.get("schema_version") == "0.1"
    ):
        return None, [
            Issue("error", name, "this is a v0.1 scenario; convert it with `medsim migrate` first")
        ]
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
            Issue(
                "warning",
                name,
                f"base rubric {rubric.base} is superseded; update base to the current version",
            )
        )
    domains = {d.id for d in base.domains}
    clash = {g.id for g in rubric.gates} & {g.id for g in base.gates}
    if clash:
        issues.append(
            Issue(
                "error",
                name,
                f"critical-error (gate) ids duplicate the base rubric: {sorted(clash)}",
            )
        )
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
                    f"item {item.id}: {word!r} is not observable; state the specific action",
                )
            )
    return issues


def check_crew(roster: CrewRoster, lib: Library, name: str) -> list[Issue]:
    """Every baseline should sit inside the reference ranges."""
    issues = []
    ranges = [r for p in lib.physiology for r in p.ranges]
    for c in roster.crew:
        for var, value in c.baseline.model_dump().items():
            for r in ranges:
                if (
                    r.var == var
                    and (r.sex is None or r.sex == c.sex)
                    and not r.low <= value <= r.high
                ):
                    issues.append(
                        Issue(
                            "warning",
                            name,
                            f"{c.crew_id}: baseline {var} {value:g} is outside the reference range "
                            f"{r.low:g}–{r.high:g} {r.unit}",
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

    end = parse_duration(sc.duration)
    people = {p.crew_id for p in sc.patients} | {sc.speaker.crew_id}
    for cid in sorted(people):
        if lib.crew and cid not in lib.crew:
            err(f"{cid!r} is not in the crew roster")
    if lib.symptoms:
        for code in sc.symptoms:
            if code not in lib.symptoms:
                err(f"symptom code {code!r} is not in the ICD-10-CM symptom list")

    for p in sc.patients:
        cond = lib.conditions.get(p.condition)
        if lib.conditions and cond is None:
            err(f"{p.crew_id}: unknown condition {p.condition!r}; not in the IMM condition index")
        twin = lib.crew.get(p.crew_id)
        surgery = list(p.chart.past_surgical) + (list(twin.chart.past_surgical) if twin else [])
        for word in RULED_OUT_BY_SURGERY.get(p.condition, ()):
            if any(word in h.lower() for h in surgery):
                err(f"{p.crew_id}: prior {word} excludes {p.condition}")
        if p.ground_truth.etiology.startswith("TODO"):
            warn(f"{p.crew_id}: etiology not entered")
        if cond and cond.applicability:
            app = cond.applicability
            if twin and app.sex != "any" and twin.sex != app.sex:
                sex = {"F": "female", "M": "male"}[app.sex]
                err(f"{p.crew_id}: {cond.name} applies to {sex} patients only")
            outside = [e for e in sc.environments if e not in app.envs]
            if outside:
                warn(
                    f"{cond.name}: {', '.join(outside)} outside CLiFF incidence "
                    f"(segment: {app.segment}); deselect, or justify under complicators"
                )
        for e in p.timeline:
            if parse_offset(e.t) > end:
                warn(f"{p.crew_id}: {e.kind} at {e.t} falls after the case ends ({sc.duration})")
            for var in e.state:
                if var not in KNOWN_STATE_VARS:
                    warn(
                        f"{p.crew_id}: keyframe at {e.t}: {var!r} is not a recognised state variable"
                    )
        for tc in p.time_critical:
            if parse_offset(tc.by) > end:
                warn(f"{p.crew_id}: time-critical deadline {tc.by} falls after the case ends")
            for env in sc.environments:
                aboard = {i.id for h in lib.habitats_in(env) for i in [*h.equipment, *h.formulary]}
                if tc.action.refs and lib.habitats_in(env) and not set(tc.action.refs) & aboard:
                    warn(
                        f"{p.crew_id}: time-critical intervention not possible in {env}; "
                        f"none of {tc.action.refs} is aboard"
                    )

    for inj in sc.injects:
        if parse_offset(inj.t) > end:
            warn(f"inject {inj.kind} at {inj.t} falls after the case ends ({sc.duration})")

    if sc.review.status == "approved":
        if not sc.review.reviewers:
            err("status approved requires at least one named reviewer")
        if sc.review.physiology_review == "requested":
            err("status approved, but the requested physiology review is not done")

    if rubric is not None:
        if rubric.scenario_id != sc.scenario_id:
            err(f"rubric {sc.rubric} belongs to {rubric.scenario_id!r}, not {sc.scenario_id!r}")
        ids = {p.crew_id for p in sc.patients}
        for item in rubric.items:
            if item.by and parse_offset(item.by) > end:
                warn(f"rubric item {item.id}: deadline {item.by} falls after the case ends")
            if item.patient and item.patient not in ids:
                err(f"rubric item {item.id}: {item.patient!r} is not a patient in this case")
            if item.requires:
                for env in sc.environments:
                    aboard = {
                        i.id for h in lib.habitats_in(env) for i in [*h.equipment, *h.formulary]
                    }
                    if lib.habitats_in(env) and not set(item.requires) & aboard:
                        issues.append(
                            Issue(
                                "info",
                                name,
                                f"rubric item {item.id}: not applicable in {env} (required equipment not aboard)",
                            )
                        )
    return issues


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
        elif isinstance(model, CrewRoster):
            issues += check_crew(model, lib, name)
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
