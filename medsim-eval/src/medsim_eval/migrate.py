"""Convert v0.1 scenarios and rubrics to v0.2.

v0.1 placed a case in one DRM phase with a DRM crewmember. v0.2 scenarios are mission-free and
use the crew roster, so migration has to make some choices; each one is written into the
scenario's review notes so the author can check it:

  * the patient becomes the roster crewmember of the same sex closest in age;
  * the speaker becomes the patient, or a roster CMO (or crewmember) who isn't the patient;
  * environments become every one the condition's CLiFF allows;
  * branches that set a deadline for an action become time-critical treatments; others are dropped;
  * facts become "additional history if asked";
  * the etiology is left as a TODO, since v0.1 had no field for it.
"""

from __future__ import annotations

import json
from pathlib import Path

from medsim_eval.models.scenario import ALL_ENVS
from medsim_eval.validate import Library

TODO_ETIOLOGY = "TODO: add the etiology"


def _pick(lib: Library, sex: str | None, age: float | None, exclude: set[str]) -> str:
    pool = [
        c for c in lib.crew.values() if c.crew_id not in exclude and (sex is None or c.sex == sex)
    ]
    pool = pool or [c for c in lib.crew.values() if c.crew_id not in exclude]
    return min(pool, key=lambda c: abs(c.age - (age or c.age))).crew_id


def migrate_scenario(old: dict, lib: Library) -> tuple[dict, list[str]]:
    notes: list[str] = []
    cond_id = old["condition"]["cliff_id"]
    cond = lib.conditions.get(cond_id)
    drm = lib.drms.get(old.get("drm", ""))
    old_crew = next(
        (c for c in (drm.crew if drm else []) if c.crew_id == old.get("crewmember")), None
    )
    patient_info = old.get("patient", {})
    patient_id = _pick(lib, old_crew.sex if old_crew else None, patient_info.get("age"), set())
    twin = lib.crew[patient_id]
    notes.append(
        f"Patient {old.get('crewmember')} of {old.get('drm')} became roster crewmember {patient_id} ({twin.name})."
    )

    chart = twin.chart.model_dump(exclude_none=True)
    extra_allergies = [a for a in patient_info.get("allergies", []) if a]
    if extra_allergies:
        chart["allergies"] = chart.get("allergies", []) + [
            {"agent": a, "kind": "drug"} for a in extra_allergies
        ]
        chart["nkda"] = False
        notes.append(
            "Allergies from v0.1 were added to the chart as drug allergies; check their reaction."
        )
    chart["past_medical"] = chart.get("past_medical", []) + list(patient_info.get("history", []))
    if patient_info.get("medications"):
        notes.append(
            f"v0.1 medications {patient_info['medications']} need name, form, dose and frequency."
        )

    time_critical, dropped = [], 0
    for b in old.get("branches", []):
        when = b.get("when", {})
        if when.get("type") == "action_by" and when.get("action") and when.get("by"):
            act = when["action"]
            time_critical.append(
                {
                    "action": {
                        "kind": act.get("kind", "treatment"),
                        "refs": [act["ref"]] if act.get("ref") else [],
                        "text": act.get("text") or act.get("ref") or act.get("kind"),
                    },
                    "by": when["by"],
                }
            )
        else:
            dropped += 1
    if dropped:
        notes.append(f"{dropped} branch(es) other than 'action by a time' were dropped.")

    ua = old.get("user_agent", {})
    role = ua.get("role", "crew")
    if role == "patient":
        speaker_id = patient_id
    else:
        trained = [
            c.crew_id
            for c in lib.crew.values()
            if c.crew_id != patient_id
            and c.medical_training.level == ("cmo" if role == "cmo" else "basic")
        ]
        speaker_id = trained[0] if trained else _pick(lib, None, None, {patient_id})
    if ua.get("knowledge"):
        notes.append(
            f"The v0.1 speaker's training ('{ua['knowledge']}') now comes from roster entry {speaker_id}."
        )

    envs = list(cond.applicability.envs) if cond and cond.applicability else list(ALL_ENVS)
    gt = old.get("ground_truth", {})
    authors = [{"name": a, "contact": "not given"} for a in old.get("authors", [])]
    notes.append("Authors need contact details.")
    review_notes = "Migrated from v0.1: " + " ".join(notes)
    new = {
        "schema_version": "0.2",
        "scenario_id": old["scenario_id"],
        "title": old["title"],
        "authors": authors,
        "symptoms": [],
        "environments": envs,
        "patients": [
            {
                "crew_id": patient_id,
                "condition": cond_id,
                "chart": chart,
                "timeline": old.get("timeline", []),
                "time_critical": time_critical,
                "ground_truth": {
                    "etiology": TODO_ETIOLOGY,
                    "differential": gt.get("acceptable_differential", []),
                    "must_not_miss": gt.get("must_not_miss", []),
                    "synonyms": gt.get("synonyms", {}),
                },
            }
        ],
        "speaker": {
            "crew_id": speaker_id,
            "role": role,
            "opening": old.get("presentation", ""),
            "behaviour": ua.get("behaviour"),
            "additional_history": [
                {"if_asked": k.replace("_", " "), "says": v} for k, v in ua.get("facts", {}).items()
            ],
        },
        "injects": old.get("events", []),
        "complicators": old.get("complicators"),
        "rubric": old["rubric"],
        "duration": old.get("duration", "3d"),
        "review": {
            "status": "draft",
            "reviewers": old.get("reviewers", []),
            "physiology_review": old.get("physiology_review", "not_needed"),
            "notes_for_physiologist": old.get("notes_for_physiologist"),
            "notes": "\n".join(x for x in (old.get("notes"), review_notes) if x),
        },
        "tags": old.get("tags", []),
    }
    if new["speaker"]["behaviour"] is None:
        del new["speaker"]["behaviour"]
    return new, notes


def migrate_rubric(old: dict, latest_base: str) -> dict:
    new = dict(old)
    new["schema_version"] = "0.2"
    if old.get("base", "").startswith("general@") and old["base"] != latest_base:
        new["base"] = latest_base
    return new


def migrate_file(path: Path, lib: Library, latest_base: str) -> list[str]:
    """Migrate a scenario and its rubric in place, keeping a .v0.1.bak copy of each."""
    old = json.loads(path.read_text(encoding="utf-8"))
    if old.get("schema_version") != "0.1":
        return [f"{path}: already v{old.get('schema_version')}, skipped"]
    new, notes = migrate_scenario(old, lib)
    rubric_path = path.parent / old["rubric"]
    path.with_name(path.name + ".v0.1.bak").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    path.write_text(json.dumps(new, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if rubric_path.exists():
        r_old = json.loads(rubric_path.read_text(encoding="utf-8"))
        rubric_path.with_name(rubric_path.name + ".v0.1.bak").write_text(
            rubric_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        rubric_path.write_text(
            json.dumps(migrate_rubric(r_old, latest_base), indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return [f"{path}: migrated"] + [f"  {n}" for n in notes]
