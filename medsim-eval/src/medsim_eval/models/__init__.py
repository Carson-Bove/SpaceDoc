"""File formats. Each top-level model is one file type; see FILE_TYPES."""

from medsim_eval.models.condition import ConditionIndex
from medsim_eval.models.drm import DRM
from medsim_eval.models.environment import EnvironmentSet
from medsim_eval.models.habitat import Habitat
from medsim_eval.models.rubric import BaseRubric, ScenarioRubric
from medsim_eval.models.scenario import Scenario

# File-name suffix -> model. The suffix is how the validator and the form tell files apart.
FILE_TYPES = {
    ".drm.json": DRM,
    ".habitat.json": Habitat,
    ".scenario.json": Scenario,
    ".rubric.json": ScenarioRubric,
    ".base-rubric.json": BaseRubric,
    ".conditions.json": ConditionIndex,
    ".environments.json": EnvironmentSet,
}


def file_type(name: str) -> str | None:
    """Longest matching suffix, so '.base-rubric.json' wins over '.rubric.json'."""
    matches = [s for s in FILE_TYPES if name.endswith(s)]
    return max(matches, key=len) if matches else None


__all__ = [
    "DRM",
    "BaseRubric",
    "ConditionIndex",
    "EnvironmentSet",
    "FILE_TYPES",
    "Habitat",
    "Scenario",
    "ScenarioRubric",
    "file_type",
]
