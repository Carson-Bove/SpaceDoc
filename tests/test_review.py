"""Thinking notes in the audit log and reasoning summaries for clinical review."""

import json

import pytest
from fastapi.testclient import TestClient

from spacedoc.audit.log import AuditLog
from spacedoc.config import REPO_ROOT
from spacedoc.demo import DEMO_NOTES, DEMO_PATIENT
from spacedoc.eval.cases import load_cases
from spacedoc.eval.runner import run_cases, write_report
from spacedoc.llm.client import FakeLLM, GenParams
from spacedoc.review.summary import LABEL, NoReasoning, ReasoningReviewer
from spacedoc.web.app import create_app

FLANK = "Sharp right flank pain that moves toward my groin"


def test_thinking_notes_are_kept_in_the_audit_log(demo_system, env_t4):
    v = demo_system.orchestrator.ask(FLANK, env_t4, DEMO_PATIENT)
    assert v.reasoning_available
    entry = demo_system.orchestrator.audit.get(v.audit_id)
    notes = entry["payload"]["thinking"]
    assert [n["pass"] for n in notes] == ["draft"]  # the finalize pass does not think
    assert notes[0]["thinking"] == DEMO_NOTES
    assert "DEMO NOTES" not in v.model_dump_json()  # never part of the crew-facing answer


def test_summary_is_made_once_and_saved(demo_system, env_t4):
    v = demo_system.orchestrator.ask(FLANK, env_t4, DEMO_PATIENT)
    reviewer = demo_system.reviewer
    calls_before = len(reviewer.llm.calls)
    first = reviewer.summarize(v.audit_id)
    assert first.label == LABEL and first.summary.diagnoses_considered
    assert first.summary.points_for_reviewer
    second = reviewer.summarize(v.audit_id)
    assert second.summary_audit_id == first.summary_audit_id
    assert len(reviewer.llm.calls) == calls_before + 1  # the second request used the saved one
    assert demo_system.orchestrator.audit.verify() == (True, None)


def test_answers_without_notes_have_nothing_to_review(demo_system, env_t4):
    v = demo_system.orchestrator.ask("Something in my eye", env_t4, None)
    assert not v.reasoning_available
    with pytest.raises(NoReasoning):
        demo_system.reviewer.summarize(v.audit_id)


def test_long_notes_are_shortened_to_fit(tmp_path):
    audit = AuditLog(tmp_path / "a.jsonl")
    notes = [{"pass": "draft", "attempt": 1, "thinking": "step " * 20000}]
    audit_id = audit.append("ask", {"question": "q", "draft": {}, "thinking": notes})
    reply = json.dumps({"findings_weighed": ["x"]})
    llm = FakeLLM([reply])
    reviewer = ReasoningReviewer(llm, audit, GenParams(num_ctx=4096, max_tokens=512), "m")
    stored = reviewer.summarize(audit_id)
    assert stored.notes_shortened
    prompt = llm.calls[0][1]["content"]
    assert "middle of the notes omitted" in prompt and len(prompt) < 4096 * 3


def consult_assessment(client, text):
    cid = client.post("/api/consult", json={"user": "C1", "patient": "C3"}).json()["consult_id"]
    client.post(f"/api/consult/{cid}/turn", json={"text": text})
    return client.post(f"/api/consult/{cid}/assess").json()


def test_review_api(demo_system):
    client = TestClient(create_app(demo_system))
    v = consult_assessment(client, FLANK)
    assert v["reasoning_available"]
    audit_id = v["audit_id"]

    before = client.get(f"/api/review/{audit_id}").json()
    assert before["summary"] is None and before["passes"] == ["draft"]
    made = client.post(f"/api/review/{audit_id}/summarize").json()
    assert made["summary"]["diagnoses_considered"][0]["stance"] == "favored"
    after = client.get(f"/api/review/{audit_id}").json()
    assert after["summary"]["summary_audit_id"] == made["summary_audit_id"]
    notes = client.get(f"/api/review/{audit_id}/notes").json()
    assert notes["notes"][0]["thinking"] == DEMO_NOTES

    assert client.get("/api/review/audit-999999").status_code == 404
    eye = consult_assessment(client, "Something in my eye")
    assert client.post(f"/api/review/{eye['audit_id']}/summarize").status_code == 404


def test_eval_report_includes_summaries(demo_system, tmp_path):
    rows = run_cases(demo_system, load_cases(REPO_ROOT / "cases"))
    flank = next(r for r in rows if r["case_id"] == "SO-0001")
    assert flank["reasoning_summary"]["summary"]["findings_weighed"]
    report = write_report(rows, tmp_path / "run", "demo").read_text()
    assert "## Reasoning summaries (for clinical review)" in report
    assert "### SO-0001" in report and "Points for the reviewer" in report

    plain = run_cases(demo_system, load_cases(REPO_ROOT / "cases"), summaries=False)
    assert not any("reasoning_summary" in r for r in plain)
