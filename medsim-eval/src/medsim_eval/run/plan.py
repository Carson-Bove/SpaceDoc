"""The run plan: which runs a scenario gets (docs/11 §4, §12).

Each environment the scenario selects, and where its condition can occur, is run on the CLiFF's
best and worst course; then 2 more runs leave the course to the CLiFF's own odds. That is up to
12 runs for a scenario that can happen everywhere.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Literal

from medsim_eval.models import Scenario
from medsim_eval.validate import Library

Course = Literal["best", "worst", "cliff"]
CLIFF_ODDS_RUNS = 2


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    scenario_id: str
    env: str
    env_name: str
    course: Course
    seed: int
    drm: str | None
    phase: str | None
    habitats: tuple[str, ...]
    gravity_g: float
    one_way_delay_s: tuple[float, float]

    def to_dict(self) -> dict:
        return asdict(self)


def run_envs(sc: Scenario, lib: Library) -> list[str]:
    """The scenario's environments where its condition can occur, in T1..T5 order."""
    envs = list(sc.environments)
    cond = lib.conditions.get(sc.patients[0].condition)
    if cond and cond.applicability:
        envs = [e for e in envs if e in cond.applicability.envs] or envs
    default = {e for e, x in lib.environments.items() if x.default_run} or set(envs)
    return sorted(e for e in envs if e in default)


def seed_for(scenario_id: str, run_id: str, base_seed: int) -> int:
    digest = hashlib.sha256(f"{scenario_id}/{run_id}/{base_seed}".encode()).hexdigest()
    return int(digest[:8], 16)


def plan_runs(sc: Scenario, lib: Library, base_seed: int = 0) -> list[RunSpec]:
    envs = run_envs(sc, lib)
    slots: list[tuple[str, Course]] = [(e, c) for c in ("best", "worst") for e in envs]
    # The CLiFF-odds runs go to the first environments in order, wrapping if there are few.
    slots += [(envs[i % len(envs)], "cliff") for i in range(CLIFF_ODDS_RUNS)]
    runs = []
    for n, (env, course) in enumerate(slots, 1):
        e = lib.environments.get(env)
        run_id = f"r{n:02d}-{env}-{course}"
        runs.append(
            RunSpec(
                run_id=run_id,
                scenario_id=sc.scenario_id,
                env=env,
                env_name=e.name if e else env,
                course=course,
                seed=seed_for(sc.scenario_id, run_id, base_seed),
                drm=e.representative.drm if e and e.representative else None,
                phase=e.representative.phase if e and e.representative else None,
                habitats=tuple(h.profile_id for h in lib.habitats_in(env)),
                gravity_g=e.gravity_g if e else 0.0,
                one_way_delay_s=tuple(e.one_way_delay_s) if e else (0.0, 0.0),
            )
        )
    return runs
