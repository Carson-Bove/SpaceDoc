"""Build the offline scenario-authoring form: one HTML file with the library inside it.

The form needs no server and no internet. Rebuild it (`medsim build-form`) whenever the library
changes, so clerks always pick from the current conditions, crew, kits and rubric.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path

from medsim_eval import SCHEMA_VERSION
from medsim_eval.models.scenario import INPUT_PROBLEMS, KNOWN_STATE_VARS, ActionRef, EventKind
from medsim_eval.validate import DEFAULT_LIBRARY, RULED_OUT_BY_SURGERY, load_library

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = PACKAGE_ROOT / "form" / "template.html"
DEFAULT_OUT = PACKAGE_ROOT / "dist" / "scenario-builder.html"


def _version_key(ref: str) -> tuple[int, ...]:
    return tuple(int(x) for x in ref.split("@", 1)[1].split("."))


def bundle(library_dir: Path = DEFAULT_LIBRARY) -> dict:
    """The parts of the library the form shows, as plain JSON."""
    lib, issues = load_library(library_dir)
    errors = [str(i) for i in issues if i.level == "error"]
    if errors:
        raise ValueError(
            "library has errors; fix them before building the form:\n" + "\n".join(errors)
        )

    def item(i) -> dict:
        return {"id": i.id, "name": i.name, "qty": i.qty, "category": i.category}

    habitats = []
    for h in lib.habitats.values():
        habitats.append(
            {
                "profile_id": h.profile_id,
                "name": h.name,
                "status": h.status,
                "gravity_g": h.gravity_g,
                "kit": h.kit.model_dump(exclude_none=True) if h.kit else None,
                "equipment": [item(i) for i in h.equipment],
                "formulary": [item(i) for i in h.formulary],
                "capabilities": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "status": c.status,
                        "note": c.note,
                        "assumption": c.assumption,
                    }
                    for c in h.capabilities
                ],
                "notes": h.notes,
            }
        )
    bases = sorted(lib.base_rubrics.values(), key=lambda b: _version_key(b.ref))
    environments = []
    for e in lib.environments.values():
        env = e.model_dump(mode="json", exclude_none=True)
        env["habitats"] = [h.profile_id for h in lib.habitats_in(e.env)]
        environments.append(env)
    return {
        "schema_version": SCHEMA_VERSION,
        "environments": environments,
        "habitats": habitats,
        "conditions": [
            c.model_dump(mode="json", exclude_none=True) for c in lib.conditions.values()
        ],
        "crew": [c.model_dump(mode="json", exclude_none=True) for c in lib.crew.values()],
        "physiology": [p.model_dump(mode="json", exclude_none=True) for p in lib.physiology],
        "symptoms": [s for doc in _symptom_docs(library_dir) for s in doc],
        "encyclopedia": [
            e.model_dump(mode="json", exclude_none=True)
            for enc in lib.encyclopedia
            for e in enc.entries
        ],
        "base_rubrics": [b.model_dump(mode="json", by_alias=True) | {"ref": b.ref} for b in bases],
        "state_vars": KNOWN_STATE_VARS,
        "input_problems": INPUT_PROBLEMS,
        "ruled_out_by_surgery": RULED_OUT_BY_SURGERY,
        "enums": {
            "event_kinds": list(typing.get_args(EventKind)),
            "action_kinds": list(typing.get_args(ActionRef.model_fields["kind"].annotation)),
        },
    }


def _symptom_docs(library_dir: Path) -> list[list[dict]]:
    """Symptoms with their names (the Library keeps only the codes)."""
    return [
        json.loads(p.read_text(encoding="utf-8"))["symptoms"]
        for p in sorted(library_dir.rglob("*.symptoms.json"))
    ]


def render(library_dir: Path = DEFAULT_LIBRARY) -> str:
    data = json.dumps(bundle(library_dir), ensure_ascii=False, separators=(",", ":"))
    # Keep the JSON from closing the <script> element it sits in.
    data = data.replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("__LIBRARY__", data)


def build(out: Path = DEFAULT_OUT, library_dir: Path = DEFAULT_LIBRARY) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(library_dir), encoding="utf-8")
    return out
