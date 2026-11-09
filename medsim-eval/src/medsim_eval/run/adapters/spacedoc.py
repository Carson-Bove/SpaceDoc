"""SpaceDoc, over its consult API (the same calls its web page makes).

For each scenario the adapter starts SpaceDoc's server with a crew roster made from MedSim's
roster, with the scenario's chart for the patient, so SpaceDoc knows the patient's record the
way it would aboard. Everything else (models, corpus, formulary, rules) is SpaceDoc's own,
read from its spacedoc.toml. Consults are practice consults, tagged with the scenario ID.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import tomllib
from pathlib import Path

import httpx

from medsim_eval.models import Scenario
from medsim_eval.models.chart import Chart
from medsim_eval.run.adapters import Assistant, Reply, Session
from medsim_eval.validate import Library

PACKAGE_ROOT = Path(__file__).resolve().parents[4]


def default_config() -> Path:
    return Path(os.environ.get("SPACEDOC_CONFIG", PACKAGE_ROOT.parent / "spacedoc.toml"))


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return repr(v)
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_toml_value(x)}" for k, x in v.items()) + " }"
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v))


def record(chart: Chart, twin) -> dict:
    """A MedSim chart in SpaceDoc's crew-record shape."""
    return {
        "age": twin.age,
        "sex": twin.sex,
        "weight_kg": twin.weight_kg,
        "allergies": [
            f"{a.agent} ({a.reaction})" if a.reaction else a.agent for a in chart.allergies
        ],
        "medications": [
            " ".join(x for x in (m.name, m.dose, m.frequency) if x) for m in chart.medications
        ],
        "history": list(chart.past_medical) + [f"surgery: {s}" for s in chart.past_surgical],
        "immunizations": list(chart.immunizations),
        "social_history": chart.social_history or "",
    }


class SpaceDocAssistant(Assistant):
    name = "spacedoc"

    def __init__(
        self,
        config: Path | None = None,
        demo: bool = False,
        command: str = "spacedoc",
        extra_args: list[str] | None = None,
        startup_timeout_s: float = 120,
        request_timeout_s: float = 1800,
    ):
        self.config = Path(config) if config else default_config()
        self.demo, self.command = demo, command
        self.extra_args = extra_args or []
        self.startup_timeout_s, self.request_timeout_s = startup_timeout_s, request_timeout_s
        self.proc: subprocess.Popen | None = None
        self.url = ""
        self.consult_id: str | None = None
        self.status: dict = {}

    def info(self) -> dict:
        s = self.status
        return {
            "name": self.name,
            "demo": self.demo,
            "model": s.get("model"),
            "consult_model": s.get("consult_model"),
            "checker": s.get("checker"),
            "config": str(self.config),
        }

    # ---- per scenario: overlay data with this scenario's patient, then (re)start ----------
    def prepare(self, scenario: Scenario, lib: Library, workdir: Path) -> None:
        self.close()
        root = workdir / "spacedoc"
        cfg = self._overlay(scenario, lib, root)
        port = _free_port()
        args = [self.command, "serve", "--port", str(port), "--config", str(cfg)]
        if self.demo:
            args.append("--demo")
        log = (root / "server.log").open("w")
        self.proc = subprocess.Popen(args + self.extra_args, stdout=log, stderr=subprocess.STDOUT)
        self.url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + self.startup_timeout_s
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"SpaceDoc exited at startup; see {root / 'server.log'}")
            try:
                self.status = httpx.get(f"{self.url}/api/status", timeout=5).json()
                problems = self.status.get("model_problems") or []
                if problems:
                    raise RuntimeError("SpaceDoc's models are not ready: " + "; ".join(problems))
                return
            except httpx.HTTPError:
                time.sleep(0.5)
        raise RuntimeError(f"SpaceDoc did not start within {self.startup_timeout_s:.0f} s")

    def _overlay(self, sc: Scenario, lib: Library, root: Path) -> Path:
        raw = tomllib.loads(self.config.read_text()) if self.config.exists() else {}
        base = self.config.parent
        data = Path(raw.get("data_dir", "data"))
        data = data if data.is_absolute() else base / data
        out = dict(raw)
        for k, v in raw.items():  # paths in SpaceDoc's config are relative to it
            if isinstance(v, str) and k.endswith(("_path", "_dir", "_file")):
                out[k] = str(Path(v) if Path(v).is_absolute() else (base / v).resolve())
        overlay = root / "data"
        out["data_dir"] = str(overlay.resolve())
        out["audit_path"] = str((root / "audit" / "audit.jsonl").resolve())
        overlay.mkdir(parents=True, exist_ok=True)
        for entry in data.iterdir():
            link = overlay / entry.name
            if entry.name != "crew" and not link.exists():
                link.symlink_to(entry.resolve())
        (overlay / "crew").mkdir(exist_ok=True)
        p = sc.patients[0]
        crew = []
        for c in lib.crew.values():
            role = c.medical_role
            if c.crew_id == sc.speaker.crew_id and sc.speaker.role == "cmo":
                role = "cmo"
            chart = p.chart if c.crew_id == p.crew_id else c.chart
            crew.append(
                {
                    "crew_id": c.crew_id,
                    "role": c.occupation,
                    "medical_role": role,
                    "record": record(chart, c),
                }
            )
        # JSON is valid YAML, so SpaceDoc's roster loader reads this as is.
        (overlay / "crew" / "roster.yaml").write_text(json.dumps({"crew": crew}, indent=1))
        cfg = root / "spacedoc.toml"
        cfg.write_text("".join(f"{k} = {_toml_value(v)}\n" for k, v in out.items()))
        return cfg

    # ---- per run ------------------------------------------------------------------------
    def _post(self, path: str, body: dict | None = None) -> httpx.Response:
        return httpx.post(f"{self.url}{path}", json=body or {}, timeout=self.request_timeout_s)

    def start(self, session: Session) -> None:
        patient = "self" if session.speaker_role == "patient" else session.patient_crew_id
        r = self._post(
            "/api/consult",
            {
                "user": session.speaker_crew_id,
                "patient": patient,
                "tier": session.env,
                "practice": True,
                "scenario_id": session.scenario_id,
            },
        )
        r.raise_for_status()
        self.consult_id = r.json()["consult_id"]

    def send(self, text: str) -> Reply:
        t0 = time.monotonic()
        r = self._post(f"/api/consult/{self.consult_id}/turn", {"text": text})
        if r.status_code == 409:  # an urgent card is waiting: treat it as an emergency
            return self._assess("", {"status": 409, "detail": r.text}, t0)
        r.raise_for_status()
        d = r.json()
        if d.get("paused"):
            urgent = "\n".join(
                f"URGENT: {h['message']}\n" + "\n".join(f"- {s}" for s in h.get("steps", []))
                for h in d.get("red_flags", [])
            )
            return self._assess(urgent, {"turn": d}, t0)
        if d.get("error"):
            return Reply(
                f"[SpaceDoc error: {d['error']}]", data={"turn": d}, seconds=time.monotonic() - t0
            )
        reply = d.get("reply") or {}
        text_out = reply.get("message", "")
        screen = [s["question"] for s in d.get("screen", []) if s.get("question")]
        if screen:
            text_out += "\n\nExposure check: " + " ".join(screen)
        if d.get("assess_reason"):
            return self._assess(text_out, {"turn": d}, t0)
        return Reply(text_out, data={"turn": d}, seconds=time.monotonic() - t0)

    def _assess(self, before: str, data: dict, t0: float) -> Reply:
        r = self._post(f"/api/consult/{self.consult_id}/assess")
        r.raise_for_status()
        v = r.json()
        text = "\n\n".join(x for x in (before.strip(), render_assessment(v)) if x)
        return Reply(
            text, final=True, data={**data, "assessment": v}, seconds=time.monotonic() - t0
        )

    def end(self) -> dict:
        if not self.consult_id:
            return {}
        try:
            r = self._post(f"/api/consult/{self.consult_id}/end").json()
            return {"record_path": r.get("path"), "record": r.get("markdown")}
        except httpx.HTTPError as e:
            return {"error": str(e)}
        finally:
            self.consult_id = None

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def render_assessment(v: dict) -> str:
    """SpaceDoc's checked assessment as the crew would read it."""
    out = []
    if v.get("abstained"):
        out.append(
            f"SpaceDoc cannot give a reliable answer: {v.get('abstain_reason') or ''}".strip()
        )
    if v.get("summary"):
        out.append(v["summary"])
    if v.get("next_steps"):
        out.append("What to do now:\n" + "\n".join(f"- {s}" for s in v["next_steps"]))
    dx = v.get("differential") or []
    if dx:
        out.append(
            "Differential: " + "; ".join(f"{d['condition']} ({d['likelihood']})" for d in dx)
        )
    acts = v.get("actions") or []
    if acts:
        lines = []
        for a in acts:
            text = a.get("display_text") or a["action"]["text"]
            status = {
                "ok": "",
                "requires_confirmation": " (needs confirmation)",
                "blocked": " (blocked)",
            }
            lines.append(f"- {text}{status.get(a.get('status'), '')}")
            if a.get("calc_text"):
                lines.append(f"  calculator: {a['calc_text']}")
        out.append("Actions:\n" + "\n".join(lines))
    claims = [c["claim"]["text"] for c in v.get("claims", []) if c.get("shown")]
    if claims:
        out.append("Findings:\n" + "\n".join(f"- {c}" for c in claims))
    if v.get("uncertainty"):
        out.append(f"Uncertainty: {v['uncertainty']}")
    return "\n\n".join(out)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
