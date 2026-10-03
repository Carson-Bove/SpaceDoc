"""Demo mode: a scripted stand-in for the LLM so the GUI and tests run without Ollama.

The scripted drafts deliberately include mistakes a real model makes (an unsupported claim,
an invented statistic, a dose written by the model, an expired drug, an evacuation that isn't
possible, a summary that says more than the checked answer) so you can watch the verification layer catch them.
"""

from __future__ import annotations

import json
import re

from spacedoc.answer.schema import DraftAnswer
from spacedoc.llm.client import ChatResult

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


def _flank(messages) -> DraftAnswer:
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
            "id": "A3",
            # The model writes its own dose; SpaceDoc replaces it with the calculator's.
            "text": "Acetaminophen 650 mg oral for pain",
            "kind": "medication",
            "item": "acetaminophen",
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
    return DraftAnswer(
        # The second sentence repeats the evacuation that is not possible on this mission; the
        # summary check removes it because the action behind it is blocked.
        summary=(
            "Colicky flank pain radiating to the groin points to a kidney stone; fever with flank "
            "pain may indicate infection behind an obstructing stone. Arrange evacuation to a "
            "hospital if fever develops."
        ),
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


DEMO_NOTES = (
    "[SCRIPTED DEMO NOTES] Pain is colicky, in the right flank and moves toward the groin. "
    "That pattern points to a kidney stone more than a muscle strain, even though the crewmember "
    "suspects a pulled muscle. S1 describes the colicky pain and S2 links stones to bone loss in "
    "spaceflight. Fever would change things: an infected obstructed stone is the must-not-miss "
    "diagnosis, so ask about fever and chills. Ultrasound can look for hydronephrosis. For pain, "
    "request the weight-based acetaminophen calculator rather than writing a dose. Evacuation is "
    "not possible on this mission, so I should not suggest it. I assume the record is complete."
)

DEMO_SUMMARY = {
    "findings_weighed": [
        "Colicky right flank pain radiating to the groin",
        "Crewmember suspects a pulled muscle",
    ],
    "diagnoses_considered": [
        {"condition": "Kidney stone", "stance": "favored", "why": "colicky pain pattern"},
        {
            "condition": "Infected obstructed stone",
            "stance": "considered",
            "why": "must-not-miss if fever develops",
        },
        {"condition": "Muscle strain", "stance": "ruled out", "why": "pattern fits a stone better"},
    ],
    "sources_relied_on": ["S1: colicky pain pattern", "S2: stone risk from bone loss"],
    "assumptions": ["The patient record is complete"],
    "uncertainties": ["No temperature trend yet"],
    "points_for_reviewer": [
        "The notes say evacuation is not possible, but the draft answer still proposed it",
    ],
}


CONSULT_NOTES = (
    "[SCRIPTED DEMO NOTES] Flank pain that comes in waves points to a stone, but fever would "
    "mean an infected obstructed stone. Ask about fever first, then blood in the urine."
)


def _consult_turn(messages) -> ChatResult:
    """Scripted consult replies: one round of questions, then ready to assess.

    The first reply also asks for a CT scan, which is not aboard, so the equipment check can
    be seen catching it. Every reply carries thinking notes; the engine keeps them only when
    deep log is on.
    """
    answers = [m["content"].lower() for m in messages if m["role"] == "user"]
    first = answers[0] if answers else ""
    stone = any(w in first for w in ("flank", "kidney", "side", "groin"))
    if len(answers) == 1:
        reply = {
            "urgent": {"flag": False, "reason": ""},
            "facts": [{"item": "presenting problem", "value": first[:120]}],
            "working_ddx": (
                [
                    {
                        "condition": "Kidney stone",
                        "likelihood": "high",
                        "why": "colicky flank pain",
                    },
                    {
                        "condition": "Infected obstructed stone",
                        "likelihood": "must not miss",
                        "why": "needs fever excluded",
                    },
                    {
                        "condition": "Muscle strain",
                        "likelihood": "low",
                        "why": "pain comes in waves",
                    },
                ]
                if stone
                else [{"condition": "Not yet clear", "likelihood": "moderate", "why": "few facts"}]
            ),
            "questions": [
                {
                    "text": "Any fever or chills?",
                    "why": "fever changes urgency",
                    "answer_type": "yes_no",
                },
                {
                    "text": "Any blood in the urine?",
                    "why": "supports a stone",
                    "answer_type": "yes_no",
                },
            ],
            "exam_requests": [
                {"text": "Measure temperature", "equipment": ["thermometer"], "why": "fever"},
                {"text": "CT scan of the abdomen", "equipment": ["ct_scanner"], "why": "confirm"},
            ],
            "ready_to_assess": False,
        }
    else:
        reply = {
            "facts": [{"item": "answers", "value": answers[-1][:120]}],
            "working_ddx": [
                {"condition": "Kidney stone", "likelihood": "high", "why": "pattern and answers"}
            ],
            "questions": [],
            "ready_to_assess": True,
        }
    return ChatResult(text=json.dumps(reply), seconds=0.0, thinking=CONSULT_NOTES)


def demo_responder(messages, schema) -> str | ChatResult:
    if messages and messages[0]["content"].startswith("You summarize the private reasoning"):
        return json.dumps(DEMO_SUMMARY)
    if messages and "You are running a consult" in " ".join(messages[0]["content"].split()):
        return _consult_turn(messages)
    text = " ".join(m["content"] for m in messages).lower()
    question = (
        messages[1]["content"].split("Question from the crew:")[-1].lower()
        if len(messages) > 1
        else ""
    )
    if any(w in question for w in ("flank", "kidney", "side", "groin")):
        draft = _flank(messages)
        return ChatResult(text=json.dumps(draft.model_dump()), seconds=0.0, thinking=DEMO_NOTES)
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
