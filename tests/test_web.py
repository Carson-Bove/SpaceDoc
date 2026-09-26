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
