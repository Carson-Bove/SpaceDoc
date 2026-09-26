"""Demo mode: a scripted stand-in for the LLM so the GUI and tests run without Ollama.

The scripted drafts deliberately include mistakes a real model makes (an unsupported claim,
an invented statistic, an expired drug, an evacuation that isn't possible) so you can watch
the verification layer catch them.
"""

from __future__ import annotations

import json
import re

from spacedoc.answer.schema import DraftAnswer

DEMO_PATIENT = {
    "crew_id": "C3",
    "age": 34,
    "sex": "M",
    "weight_kg": 78,
    "allergies": [],
    "medications": [],
    "presenting_complaint": "right flank pain for 6 hours, radiating to the groin",
    "vitals": {"heart_rate": 96, "temperature_c": 37.1},
}


def _cid(messages, needle: str) -> str:
    """Find the passage ID whose text contains `needle` in the prompt."""
    user = messages[1]["content"] if len(messages) > 1 else ""
    for m in re.finditer(
        r"\[(S\d+)\] \([^)]*\)\n(.*?)(?=\n\n\[S\d+\]|\n\nPatient record:)", user, re.S
    ):
        if needle.lower() in m.group(2).lower():
            return m.group(1)
    return "S99"  # deliberately invalid -> the verifier reports a bad citation


def _flank(messages, calc_id: str | None) -> DraftAnswer:
    s_colic = _cid(messages, "colicky flank pain")
    s_space = _cid(messages, "bone demineralization")
    s_us = _cid(messages, "hydronephrosis")
    s_fever = _cid(messages, "fever together")
    actions = [
        {
            "id": "A1",
            "text": "Renal point-of-care ultrasound to look for hydronephrosis",
            "kind": "test",
            "equipment": ["ultrasound"],
            "risk_tier": "R2",
        },
        {
            "id": "A2",
            "text": "Tamsulosin to help stone passage",
            "kind": "medication",
            "item": "tamsulosin",
            "risk_tier": "R2",
        },
        {
            "id": "A4",
            "text": "Evacuate to a hospital if fever develops",
            "kind": "escalate",
            "risk_tier": "R3",
        },
        {
            "id": "A5",
            "text": "Monitor temperature and report any fever or chills immediately",
            "kind": "monitor",
            "equipment": ["thermometer"],
            "risk_tier": "R1",
        },
    ]
    if calc_id:
        actions.insert(
            1,
            {
                "id": "A3",
                "text": "Acetaminophen 1000 mg oral for pain",
                "kind": "medication",
                "item": "acetaminophen",
                "calc_ref": calc_id,
                "risk_tier": "R2",
            },
        )
    return DraftAnswer(
        summary="The presentation is most consistent with a kidney stone; infection must be excluded.",
        claims=[
            {
                "id": "C1",
                "kind": "sourced",
                "citations": [s_colic],
                "text": "Kidney stones typically cause colicky flank pain that may radiate to the groin.",
            },
            {
                "id": "C2",
                "kind": "sourced",
                "citations": [s_space],
                "text": "Spaceflight increases kidney stone risk because bone demineralization raises urinary calcium.",
            },
            {
                "id": "C3",
                "kind": "sourced",
                "citations": [s_colic],
                "text": "Kidney stones in spaceflight pass without treatment in 95% of cases.",
            },
            {
                "id": "C4",
                "kind": "sourced",
                "citations": [s_us],
                "text": "Tamsulosin is the definitive cure for every kidney stone.",
            },
            {
                "id": "C5",
                "kind": "sourced",
                "citations": [s_fever],
                "text": "Fever together with flank pain may indicate infection behind an obstructing stone.",
            },
            {
                "id": "C6",
                "kind": "patient",
                "text": "The pain started 6 hours ago and radiates to the groin.",
            },
            {
                "id": "C7",
                "kind": "reasoning",
                "text": "The colicky pattern and radiation fit a stone better than a muscle strain.",
            },
        ],
        differential=[
            {"condition": "Nephrolithiasis", "likelihood": "high", "citations": [s_colic]},
            {"condition": "Pyelonephritis", "likelihood": "moderate", "citations": [s_fever]},
            {"condition": "Musculoskeletal back pain", "likelihood": "low"},
        ],
        actions=actions,
        calc_requests=[]
        if calc_id
        else [{"calculator": "weight_based_dose", "args": {"drug": "acetaminophen"}}],
        uncertainty="moderate",
        missing_info=["Urine dipstick result", "Temperature trend"],
    )


def _eye(messages) -> DraftAnswer:
    s_float = _cid(messages, "floats in the cabin")
    s_fluor = _cid(messages, "fluorescein")
    s_irr = _cid(messages, "contained system")
    return DraftAnswer(
        summary="A corneal foreign body or abrasion is likely; examine with fluorescein.",
        claims=[
            {
                "id": "C1",
                "kind": "sourced",
                "citations": [s_float],
                "text": "In microgravity, debris floats in the cabin, so eye foreign bodies are a recurring problem.",
            },
            {
                "id": "C2",
                "kind": "sourced",
                "citations": [s_fluor],
                "text": "Fluorescein staining under blue light shows corneal abrasions as bright green areas.",
            },
            {
                "id": "C3",
                "kind": "sourced",
                "citations": [s_irr],
                "text": "Eye irrigation in microgravity should use a contained system.",
            },
        ],
        differential=[
            {"condition": "Corneal foreign body", "likelihood": "high"},
            {"condition": "Corneal abrasion", "likelihood": "moderate"},
        ],
        actions=[
            {
                "id": "A1",
                "text": "Fluorescein exam of the affected eye",
                "kind": "test",
                "equipment": ["fluorescein_strips"],
                "risk_tier": "R2",
            },
            {
                "id": "A2",
                "text": "Irrigate the eye with the contained eye irrigation kit",
                "kind": "procedure",
                "equipment": ["eye_irrigation_kit"],
                "risk_tier": "R2",
            },
        ],
        uncertainty="low",
    )


def demo_responder(messages, schema) -> str:
    text = " ".join(m["content"] for m in messages).lower()
    question = (
        messages[1]["content"].split("Question from the crew:")[-1].lower()
        if len(messages) > 1
        else ""
    )
    calc = (
        re.search(r"- (calc-[0-9a-f]{8}):", messages[-1]["content"])
        if "Calculator results" in messages[-1]["content"]
        else None
    )
    if any(w in question for w in ("flank", "kidney", "side", "groin")):
        draft = _flank(messages, calc.group(1) if calc else None)
    elif "eye" in question:
        draft = _eye(messages)
    else:
        draft = DraftAnswer(
            summary="The knowledge base does not cover this question.",
            uncertainty="high",
            abstain=True,
            missing_info=["Relevant sources on this topic in the knowledge base"],
        )
    del text
    return json.dumps(draft.model_dump())
