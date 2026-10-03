from urllib.parse import quote

from fastapi.testclient import TestClient

from spacedoc.demo import DEMO_PATIENT
from spacedoc.web.app import create_app


def test_api_roundtrip(demo_system):
    client = TestClient(create_app(demo_system))
    assert "SpaceDoc" in client.get("/").text
    status = client.get("/api/status").json()
    assert status["demo"] and status["chunks"] == 3
    assert len(client.get("/api/env").json()) == 5
    r = client.post(
        "/api/ask", json={"question": "flank pain", "tier": "T4", "patient": DEMO_PATIENT}
    )
    assert r.status_code == 200 and r.json()["claims"]
    chunk_id = r.json()["passages"][0]["chunk_id"]
    assert client.get(f"/api/chunk/{quote(chunk_id, safe='')}").json()["chunk_id"] == chunk_id
    assert client.post("/api/ask", json={"question": " "}).status_code == 400
    assert client.post("/api/ask", json={"question": "x", "tier": "T9"}).status_code == 400


def test_consult_api_roundtrip(demo_system, tmp_path):
    demo_system.settings.audit_path = tmp_path / "audit" / "audit.jsonl"
    client = TestClient(create_app(demo_system))
    roster = client.get("/api/roster").json()
    assert [m["crew_id"] for m in roster] == ["C1", "C2", "C3", "C4"]

    start = {"user": "C1", "patient": "C3", "tier": "T4", "practice": True, "scenario_id": "SO-1"}
    c = client.post("/api/consult", json=start).json()
    cid = c["consult_id"]
    assert c["practice"] and c["patient"] == "C3 (Flight engineer)" and not c["patient_is_user"]

    t1 = client.post(f"/api/consult/{cid}/turn", json={"text": "flank pain in waves"}).json()
    assert len(t1["reply"]["questions"]) == 2 and t1["assess_reason"] is None
    assert any(x["missing"] == ["ct_scanner"] for x in t1["exam_checks"])
    assert t1["timing_line"].startswith("⏱")
    t2 = client.post(f"/api/consult/{cid}/turn", json={"text": "Yes fever"}).json()
    assert t2["assess_reason"] == "SpaceDoc has enough information to assess."

    v = client.post(f"/api/consult/{cid}/assess").json()
    assert v["audit_id"] and v["question"].startswith("Consult about C3")
    record = client.get(f"/api/consult/{cid}/record").json()
    assert "## Assessment 1" in record["markdown"] and "Question turns: 2" in record["timing"]
    end = client.post(f"/api/consult/{cid}/end").json()
    assert end["path"].endswith(f"{cid}.md") and (tmp_path / "audit" / "consults").exists()


def test_consult_api_red_flag_and_errors(demo_system):
    client = TestClient(create_app(demo_system))
    cid = client.post("/api/consult", json={"user": "C4", "patient": "self"}).json()["consult_id"]
    paused = client.post(f"/api/consult/{cid}/turn", json={"text": "I can't breathe"}).json()
    assert paused["paused"] and paused["red_flags"][0]["rule_id"] == "RF-BREATHING"
    assert client.post(f"/api/consult/{cid}/turn", json={"text": "more"}).status_code == 409
    resumed = client.post(f"/api/consult/{cid}/resume").json()
    assert resumed["red_flags_dismissed"] and resumed["reply"]
    assert client.post(f"/api/consult/{cid}/resume").status_code == 409

    assert client.post("/api/consult", json={"user": "C9", "patient": "self"}).status_code == 400
    assert client.post("/api/consult/audit-999/turn", json={"text": "x"}).status_code == 404
    assert client.post(f"/api/consult/{cid}/turn", json={"text": "  "}).status_code == 400


def test_consult_api_takes_structured_answers(demo_system):
    client = TestClient(create_app(demo_system))
    cid = client.post("/api/consult", json={"user": "C1", "patient": "C3"}).json()["consult_id"]
    client.post(f"/api/consult/{cid}/turn", json={"text": "flank pain in waves"})
    body = {
        "text": "",
        "answers": [
            {
                "kind": "screen",
                "question": "Any cabin atmosphere alarm (CO2, ammonia, smoke) or unusual smell?",
                "answer": "No",
                "screen_id": "EXP-ATMOS",
            }
        ],
        "exams": [{"request": "Measure temperature", "result": "37.2 C"}],
    }
    t = client.post(f"/api/consult/{cid}/turn", json=body).json()
    assert not t["paused"] and t["reply"]
    assert t["user_text"].startswith("Exposure check: Any cabin atmosphere alarm")
    assert client.post(f"/api/consult/{cid}/turn", json={"text": " "}).status_code == 400
