"""Generate library/habitats/*.habitat.json from the IMM kit table and the profile specs below.

The habitat files are generated: change PROFILES or CAPABILITIES here, then re-run. The kit
table comes from scripts/extract_imm_kits.py (library/sources/imm-medkits.json).

Usage:
    python medsim-eval/scripts/build_habitats.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "library"
IMM_URL = "https://www.nasa.gov/integrated-medical-model-documentation/"

SRC = {
    "iss": {
        "doc": "IMM SR S-20190528-412 (2024 Lunar), Table 3, ISS quantity (reference)",
        "url": IMM_URL,
    },
    "orion_mass_volume": {
        "doc": "IMM SR S-20180815-406 (Orion Medical Kit Contents), Table 2, 20 lb + 13,721 cm3 optimized kit",
        "url": IMM_URL,
    },
    "lunar_7_5d": {
        "doc": "IMM SR S-20190528-412 (2024 Lunar), Table 3, 7.5-day lunar optimized kit",
        "url": IMM_URL,
    },
    "cislunar": {
        "doc": "IMM SR S-20170623-384 (Medical Risk for Five Cis-lunar Missions): modelled with the ISS MedCap",
        "url": IMM_URL,
    },
    "dsh": {
        "doc": "IMM Deep Space Habitat service request: modelled with the ISS MedCap",
        "url": IMM_URL,
    },
    "mars": {
        "doc": "IMM SR S-20200303-423 and S-20210809-441 (Mars DRMs): modelled with the ISS MedCap, no resupply",
        "url": IMM_URL,
    },
    "abc": {
        "doc": "Ruttley T, et al. Back to Stay: NASA's Campaign to Sustainably Return Humans to the Moon. IAC-21,B3,1,6,x62781, 2021 (NTRS 20210022242)",
        "url": "https://ntrs.nasa.gov/citations/20210022242",
    },
    "cliff_appendicitis": {
        "doc": "IMM CLiFF ICL8 Appendicitis (2023), Capability Resource Table overview",
        "url": IMM_URL,
    },
    "cpr_0g": {
        "doc": "Hinkelbein J, et al. CPR during spaceflight: a guideline for CPR in microgravity. Scand J Trauma Resusc Emerg Med 2020;28:108",
        "url": "https://doi.org/10.1186/s13049-020-00793-y",
    },
    "cpr_hypog": {
        "doc": "Overbeek R, et al. Effectiveness of CPR in Hypogravity Conditions: A Systematic Review. Life (Basel) 2022;12(12):1958",
        "url": "https://doi.org/10.3390/life12121958",
    },
}

# Capabilities that follow from what is in the kit: (id, name, any-of resource names).
KIT_CAPABILITIES = [
    ("ultrasound", "Point-of-care ultrasound", ["ULTRASOUND MACHINE"]),
    ("defibrillation", "Defibrillation (AED)", ["AED"]),
    ("ecg_bp_monitoring", "ECG and blood pressure monitor", ["BLOOD PRESSURE /ECG MONITOR"]),
    ("pulse_oximetry", "Pulse oximetry", ["BLOOD OXIMETER"]),
    ("bag_valve_mask", "Bag-valve-mask ventilation", ["AMBU BAG AND MASK"]),
    ("advanced_airway", "Advanced airway (intubating LMA)", ["ILMA HARDWARE"]),
    (
        "mechanical_ventilation",
        "Mechanical ventilation",
        ["VOS INTUBATED PATIENT HARDWARE (VENTILATOR/RESPIRATOR)"],
    ),
    ("oxygen", "Supplemental oxygen", ["VARIABLE OXYGEN SYSTEM"]),
    ("iv_fluids", "IV fluid resuscitation", ["IV FLUID 1L (1000ML)"]),
    ("io_access", "Intraosseous access", ["INTRAOSSEOUS INJECTION DEVICE"]),
    ("suction", "Suction", ["SUCTION DEVICE"]),
    (
        "wound_closure",
        "Wound closure (sutures, staples, glue)",
        ["NYLON SUTURE 2.0", "SKIN STAPLER", "DERMABOND APPLICATOR 0.5ML"],
    ),
    (
        "urinary_catheter",
        "Urinary catheterization",
        ["URINE CATHETER STRAIGHT", "URINE CATHETER FOLEY", "URINE CATHETER SHORT"],
    ),
    ("urine_dipstick", "Urine dipstick", ["URINE CHEMSTRIPS"]),
    (
        "dental_extraction",
        "Dental extraction",
        ["DENTAL FORCEPS-10S (A)", "DENTAL FORCEPS-151A (B)", "DENTAL FORCEPS-17 (C)"],
    ),
    ("eye_irrigation", "Eye irrigation", ["SPACE STATION EYE WASH", "EYE WASH GOGGLES & TUBING"]),
    ("eye_exam", "Ophthalmoscopy", ["PANOPTIC OPHTHALMOSCOPE"]),
    ("otoscopy", "Otoscopy", ["OTOSCOPE HEAD"]),
    ("patient_restraint", "Crew Medical Restraint System", ["CMRS"]),
    (
        "procedural_sedation",
        "Procedural sedation (ketamine)",
        ["KETAMINE 50 MG/ML, 10 ML MULTI DOSE VIAL"],
    ),
    ("pregnancy_test", "Urine pregnancy test", ["EPT"]),
]


def fixed_capabilities(gravity_g: float, kit_source: dict | None) -> list[dict]:
    """Capabilities that don't come from the kit list: gravity-dependent ones and known gaps."""
    caps = []
    if gravity_g == 0:
        caps.append(
            {
                "id": "cpr_manual",
                "name": "Manual CPR",
                "status": "adapted",
                "note": "Needs a restrained patient (CMRS) or the Evetts-Russomano or handstand method",
                "source": SRC["cpr_0g"],
            }
        )
        caps.append(
            {
                "id": "gravity_iv_drip",
                "name": "Gravity-fed IV drip",
                "status": "unavailable",
                "note": "No gravity to drive flow; use a pressure infuser",
                "assumption": True,
            }
        )
    else:
        caps.append(
            {
                "id": "cpr_manual",
                "name": "Manual CPR",
                "status": "adapted",
                "note": "In lunar and Mars gravity compressions often fall short of guideline depth, more so for "
                "lighter rescuers; rotate rescuers in under 1 minute",
                "source": SRC["cpr_hypog"],
            }
        )
        caps.append(
            {
                "id": "gravity_iv_drip",
                "name": "Gravity-fed IV drip",
                "status": "adapted",
                "note": "Some gravity to drive flow, but slower than on Earth; a pressure infuser may still be needed",
                "assumption": True,
            }
        )
    caps += [
        {
            "id": "major_surgery",
            "name": "Major surgery (e.g. appendectomy)",
            "status": "unavailable",
            "note": "Outside the exploration treatment scope in the IMM CLiFFs",
            "source": SRC["cliff_appendicitis"],
        },
        {
            "id": "ct_xray",
            "name": "CT or X-ray imaging",
            "status": "unavailable",
            "note": "CT 'will likely not be available' per the IMM CLiFFs",
            "source": SRC["cliff_appendicitis"],
        },
        {
            "id": "blood_labs",
            "name": "Blood tests (CBC with differential, metabolic panel)",
            "status": "unknown",
            "note": "Not in the IMM kit lists; the 2023 CLiFFs assume these will be possible on exploration missions",
            "source": SRC["cliff_appendicitis"],
        },
        {
            "id": "blood_transfusion",
            "name": "Blood transfusion",
            "status": "unavailable",
            "note": "No blood products in any IMM kit list",
            "assumption": kit_source is None,
            **({"source": kit_source} if kit_source else {}),
        },
    ]
    return caps


PROFILES = [
    {
        "profile_id": "iss",
        "name": "International Space Station (US medical kit as modelled by the IMM)",
        "kind": "station",
        "envs": ["T1"],
        "gravity_g": 0.0,
        "status": "operational",
        "kit_column": "iss",
        "kit": {
            "mass_kg": 115.25,
            "volume_cm3": 526418,
            "source": {"doc": "IMM SR S-20180815-406, ISS-based baseline kit", "url": IMM_URL},
        },
        "notes": "Quantities are the IMM's ISS reference set, not a current manifest. Fuller hardware detail: "
        "ISS CHeCS Medical Hardware Catalog v10 (NTRS 20110022379).",
    },
    {
        "profile_id": "orion",
        "name": "Orion crew vehicle (IMM optimized kit)",
        "kind": "vehicle",
        "envs": ["T1", "T2"],
        "gravity_g": 0.0,
        "crew_capacity": 4,
        "status": "in_development",
        "kit_column": "orion_mass_volume",
        "kit": {"mass_kg": 7.75, "volume_cm3": 13895, "source": SRC["orion_mass_volume"]},
        "notes": "The IMM's 20 lb / 13,721 cm3 optimized kit, which the 2024 Lunar request reused for Orion. "
        "A 20 lb kit with no volume limit (9.25 kg) adds IV fluid, a SAM splint and the variable oxygen system. "
        "An optimizer result, not the flown kit. Check Orion's current flight status before citing it.",
    },
    {
        "profile_id": "lunar-lander",
        "name": "Lunar lander, ~1-week surface stay (IMM 7.5-day kit)",
        "kind": "lander",
        "envs": ["T3"],
        "gravity_g": 0.166,
        "crew_capacity": 2,
        "status": "in_development",
        "kit_column": "lunar_7_5d",
        "kit": {"mass_kg": 2.37, "volume_cm3": 6430, "source": SRC["lunar_7_5d"]},
        "sources": [SRC["abc"]],
        "notes": "Early Artemis: two crew descend for about a week on the surface (Ruttley 2021). Assigning the IMM "
        "7.5-day kit to the lander is our assumption; the IMM paired it with the Orion kit.",
    },
    {
        "profile_id": "cislunar-orbiter",
        "name": "Cislunar orbiting habitat (Gateway-class, ISS MedCap as modelled by the IMM)",
        "kind": "station",
        "envs": ["T2"],
        "gravity_g": 0.0,
        "status": "concept",
        "kit_column": "iss",
        "kit_source": SRC["cislunar"],
        "sources": [SRC["cislunar"], SRC["abc"]],
        "notes": "No published medical fit-out for Gateway. The IMM modelled cislunar missions with the ISS medical "
        "capability, so that is used here. Gateway's programme status should be re-checked.",
    },
    {
        "profile_id": "deep-space-habitat",
        "name": "Deep-space transit habitat (ISS MedCap as modelled by the IMM)",
        "kind": "vehicle",
        "envs": ["T2", "T4"],
        "gravity_g": 0.0,
        "status": "concept",
        "kit_column": "iss",
        "kit_source": SRC["dsh"],
        "sources": [SRC["dsh"], SRC["mars"]],
        "notes": "No published medical fit-out. The IMM modelled the Deep Space Habitat and Mars transit with the "
        "ISS medical capability and no resupply.",
    },
    {
        "profile_id": "mars-surface-habitat",
        "name": "Mars surface habitat (ISS MedCap as modelled by the IMM)",
        "kind": "surface_habitat",
        "envs": ["T5"],
        "gravity_g": 0.38,
        "status": "concept",
        "kit_column": "iss",
        "kit_source": SRC["mars"],
        "sources": [SRC["mars"]],
        "notes": "No published medical fit-out. The IMM Mars DRMs carry the ISS medical capability through the "
        "whole mission, surface stay included.",
    },
    {
        "profile_id": "lunar-surface-habitat",
        "name": "Lunar surface habitat (Artemis Base Camp concept)",
        "kind": "surface_habitat",
        "envs": ["T3"],
        "gravity_g": 0.166,
        "crew_capacity": 4,
        "status": "concept",
        "kit_column": None,
        "sources": [SRC["abc"]],
        "extra_capabilities": [
            {
                "id": "medical_area",
                "name": "Medical space",
                "status": "available",
                "note": "Listed among the habitat's capabilities; no detail published",
                "source": SRC["abc"],
            }
        ],
        "notes": "Hosts 2–4 crew for 1–2 month expeditions (Ruttley 2021). No medical inventory published; equipment "
        "is empty until one is. Scenarios here should state what is aboard in their complicators.",
    },
    {
        "profile_id": "lunar-pressurized-rover",
        "name": "Lunar pressurized rover (Artemis Base Camp concept)",
        "kind": "rover",
        "envs": ["T3"],
        "gravity_g": 0.166,
        "status": "concept",
        "kit_column": None,
        "sources": [SRC["abc"]],
        "extra_capabilities": [
            {
                "id": "injury_treatment",
                "name": "Treatment of injuries",
                "status": "available",
                "note": "Listed among the rover's capabilities; no detail published",
                "source": SRC["abc"],
            }
        ],
        "notes": "For longer excursions away from the habitat, with a suitport (Ruttley 2021). No medical inventory "
        "published.",
    },
]


def slug(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")[:80]


def build(spec: dict, kit: list[dict]) -> dict:
    col = spec.get("kit_column")
    source = spec.get("kit_source") or (SRC[col] if col else None)
    equipment, formulary, aboard = [], [], set()
    for r in kit if col else []:
        q = r[col]
        if not q or q["qty"] <= 0:
            continue
        aboard.add(r["name"])
        item = {
            "id": slug(r["name"]),
            "name": r["name"],
            "category": r["category"],
            "qty": q["qty"],
            "source": source,
        }
        if "optimizer" in q:
            item["note"] = f"Optimizer value {q['optimizer']:g}, rounded up by NASA"
        (formulary if r["category"] in ("drug", "fluid") else equipment).append(item)
    caps = []
    if col:
        for cid, name, needs in KIT_CAPABILITIES:
            present = any(n in aboard for n in needs)
            caps.append(
                {
                    "id": cid,
                    "name": name,
                    "status": "available" if present else "unavailable",
                    "source": source,
                }
            )
    caps += fixed_capabilities(spec["gravity_g"], source if col else None)
    caps += spec.get("extra_capabilities", [])
    out = {
        "schema_version": "0.1",
        "profile_id": spec["profile_id"],
        "name": spec["name"],
        "kind": spec["kind"],
        "envs": spec["envs"],
        "gravity_g": spec["gravity_g"],
        "status": spec["status"],
    }
    if "crew_capacity" in spec:
        out["crew_capacity"] = spec["crew_capacity"]
    out["sources"] = spec.get("sources", []) or ([source] if source else [])
    if spec.get("kit"):
        out["kit"] = spec["kit"]
    out |= {
        "equipment": equipment,
        "formulary": formulary,
        "capabilities": caps,
        "notes": spec["notes"],
    }
    return out


def main() -> None:
    kit = json.loads((LIB / "sources" / "imm-medkits.json").read_text(encoding="utf-8"))[
        "resources"
    ]
    folder = LIB / "habitats"
    folder.mkdir(parents=True, exist_ok=True)
    for spec in PROFILES:
        doc = build(spec, kit)
        path = folder / f"{spec['profile_id']}.habitat.json"
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(
            f"wrote {path}: {len(doc['equipment'])} equipment, {len(doc['formulary'])} formulary, {len(doc['capabilities'])} capabilities"
        )


if __name__ == "__main__":
    main()
