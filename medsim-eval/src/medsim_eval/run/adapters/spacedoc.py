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
DOSES = PACKAGE_ROOT / "library" / "sources" / "usual-adult-doses.json"


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
        self.paused = False
        self.pending_screen: list[dict] = []
        self.exposure: dict[str, str] = {}  # exposure-check answers that are not "No"
        self.env: str | None = None

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
        cond = lib.conditions.get(scenario.patients[0].condition)
        eva = bool(cond and cond.applicability and cond.applicability.eva)
        self.exposure = {"EXP-EVA": "Yes"} if eva else {}
        self.root = workdir / "spacedoc"
        self.cfg = self._overlay(scenario, lib, self.root)
        self.env = None  # started by the first run, with that run's kit

    def _use_env(self, env: str) -> None:
        if env == self.env and self.proc and self.proc.poll() is None:
            return
        self.close()
        # SpaceDoc reads one formulary file by a fixed name: give it this environment's kit.
        src = self.formulary_dir / f"medsim-{env}.yaml"
        if src.exists():
            (self.formulary_dir / "example-transit.yaml").write_text(src.read_text())
        self.env = env
        self._launch()

    def _launch(self) -> None:
        root = self.root
        port = _free_port()
        args = [self.command, "serve", "--port", str(port), "--config", str(self.cfg)]
        if self.demo:
            args.append("--demo")
        log = (root / "server.log").open("a")
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
            if entry.name not in ("crew", "formulary") and not link.exists():
                link.symlink_to(entry.resolve())
        (overlay / "crew").mkdir(exist_ok=True)
        (overlay / "formulary").mkdir(exist_ok=True)
        self._write_formulary(lib, overlay / "formulary")
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

    def _write_formulary(self, lib: Library, folder: Path) -> None:
        """One SpaceDoc formulary per environment, from that environment's kit, so SpaceDoc
        knows what is aboard. Doses are usual adult doses, marked unvalidated."""
        doses = json.loads(DOSES.read_text(encoding="utf-8"))["doses"] if DOSES.exists() else {}
        for env in lib.environments:
            items = {}
            for h in lib.habitats_in(env):
                for i in h.formulary:
                    if i.qty and i.qty > 0 and i.id not in items:
                        items[i.id] = formulary_item(i, doses.get(i.id))
            doc = {
                "ref": f"medsim-{env}",
                "description": f"Kit aboard in {env}, from MedSim Eval's habitat profiles (NASA IMM).",
                "items": list(items.values()),
            }
            (folder / f"medsim-{env}.yaml").write_text(json.dumps(doc, indent=1))
        # Environments with no kit profile keep SpaceDoc's own example list.
        own = self.config.parent / "data" / "formulary" / "example-transit.yaml"
        if own.exists():
            (folder / "example-transit.yaml").write_text(own.read_text())
        self.formulary_dir = folder

    # ---- per run ------------------------------------------------------------------------
    def _post(self, path: str, body: dict | None = None) -> httpx.Response:
        return httpx.post(f"{self.url}{path}", json=body or {}, timeout=self.request_timeout_s)

    def start(self, session: Session) -> None:
        self._use_env(session.env)
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
        self.paused = False
        self.pending_screen = []

    def send(self, text: str) -> Reply:
        t0 = time.monotonic()
        notes, data = [], {}
        if self.paused:
            # The urgent card was acted on (the assessment). Dismiss it so the consult can go on.
            r = self._post(f"/api/consult/{self.consult_id}/resume")
            if r.status_code == 200:
                data["resume"] = r.json()
            self.paused = False
            notes.append("Urgent card dismissed after its assessment, to continue the consult.")
        body: dict = {"text": text}
        if self.pending_screen:
            # SpaceDoc's exposure check is a card with a button per item; answer it that way.
            body["answers"] = [
                {
                    "kind": "screen",
                    "question": s["question"],
                    "screen_id": s["id"],
                    "answer": self.exposure.get(s["id"], "No"),
                }
                for s in self.pending_screen
            ]
            yes = [s["label"] for s in self.pending_screen if self.exposure.get(s["id"]) == "Yes"]
            notes.append(
                "Exposure check answered on SpaceDoc's cards: "
                + (f"Yes to {', '.join(yes)}; No to the rest." if yes else "No to every item.")
            )
            self.pending_screen = []
        r = self._post(f"/api/consult/{self.consult_id}/turn", body)
        r.raise_for_status()
        d = r.json()
        data["turn"] = d
        if d.get("paused"):
            self.paused = True
            urgent = "\n".join(
                f"URGENT: {h['message']}\n" + "\n".join(f"- {s}" for s in h.get("steps", []))
                for h in d.get("red_flags", [])
            )
            notes.append("SpaceDoc showed an urgent card; taken as an emergency: assess now.")
            return self._assess(urgent, data, t0, notes)
        if d.get("error"):
            return Reply(
                f"[SpaceDoc error: {d['error']}]",
                data=data,
                seconds=time.monotonic() - t0,
                notes=notes,
            )
        reply = d.get("reply") or {}
        self.pending_screen = [s for s in d.get("screen", []) if s.get("id")]
        if self.pending_screen:
            notes.append(
                "SpaceDoc showed its exposure check card: "
                + " ".join(s["question"] for s in self.pending_screen)
            )
        if d.get("assess_reason"):
            return self._assess(reply.get("message", ""), data, t0, notes)
        return Reply(
            reply.get("message", ""),
            data=data,
            seconds=time.monotonic() - t0,
            notes=notes,
            directed=[],
            wants_vitals=any(
                q.get("answer_type") == "measurement" for q in reply.get("questions", [])
            )
            or None,
            wants_exam=bool(reply.get("exam_requests")),
        )

    def _assess(self, before: str, data: dict, t0: float, notes: list[str]) -> Reply:
        r = self._post(f"/api/consult/{self.consult_id}/assess")
        r.raise_for_status()
        v = r.json()
        text = "\n\n".join(x for x in (before.strip(), render_assessment(v)) if x)
        # Blocked actions failed SpaceDoc's own checks, so the crew does not carry them out.
        directed = [
            a.get("display_text") or a["action"]["text"]
            for a in v.get("actions", [])
            if a.get("status") != "blocked"
        ]
        return Reply(
            text,
            final=True,
            data={**data, "assessment": v},
            seconds=time.monotonic() - t0,
            notes=notes,
            directed=directed,
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


def formulary_item(i, dose: dict | None) -> dict:
    """A MedSim kit item in SpaceDoc's formulary shape."""
    from medsim_eval.run.crewmember import drug_keywords
    from medsim_eval.run.twin import KitItem

    words = sorted(drug_keywords(KitItem(i.id, i.name, "drug", i.qty)))
    item = {
        "id": i.id,
        "name": i.name.title(),
        "kind": "drug",
        "aliases": words,
        "quantity": i.qty,
        "unit": "units",
        "validation_status": "unvalidated",
    }
    if dose:
        item["allergy_classes"] = dose.get("allergy_classes", [])
        item["dosing"] = {
            # SpaceDoc doses by weight between a floor and a ceiling; usual adult doses are a
            # range, so the weight term only chooses a point inside it.
            "mg_per_kg": round(dose["max_mg"] / 70, 4),
            "min_mg": dose["min_mg"],
            "max_mg": dose["max_mg"],
            "round_to_mg": dose["round_to_mg"],
            "route": dose["route"],
            "interval": dose["interval"],
        }
    return item


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
    todo = [a for a in acts if a.get("status") != "blocked"]
    blocked = [a for a in acts if a.get("status") == "blocked"]
    if todo:
        lines = []
        for a in todo:
            text = a.get("display_text") or a["action"]["text"]
            confirm = " (needs the CMO's confirmation)" if a.get("status") != "ok" else ""
            lines.append(f"- {text}{confirm}")
            if a.get("calc_text"):
                lines.append(f"  calculator: {a['calc_text']}")
        out.append("Actions:\n" + "\n".join(lines))
    if blocked:
        lines = [
            f"- {a.get('display_text') or a['action']['text']}"
            + (f" ({'; '.join(a['reasons'])})" if a.get("reasons") else "")
            for a in blocked
        ]
        out.append("Blocked by SpaceDoc's checks (not to be done):\n" + "\n".join(lines))
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
