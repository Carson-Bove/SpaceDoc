"""Assistant adapters (docs/11 §8): one small class per assistant, behind one interface.

The harness never imports an assistant's code. An adapter turns a run into the assistant's own
way of being used: starting a session, sending what the crewmember says, getting its reply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from medsim_eval.models import Scenario
from medsim_eval.validate import Library


@dataclass
class Session:
    run_id: str
    scenario_id: str
    env: str
    speaker_crew_id: str
    speaker_role: str  # patient | cmo | crew
    patient_crew_id: str


@dataclass
class Reply:
    text: str
    final: bool = False  # the assistant gave its assessment or plan
    data: dict = field(default_factory=dict)  # the raw reply, for the log
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)  # what the adapter did, for the log
    # When the assistant gives these as data, the runner uses them instead of reading the text:
    directed: list[str] | None = None  # actions the crew should carry out
    wants_vitals: bool | None = None
    wants_exam: bool | None = None


class Assistant:
    """Base class. `prepare` once per scenario, then `start` / `send` / `end` per run."""

    name = "assistant"

    def info(self) -> dict:
        return {"name": self.name}

    def prepare(self, scenario: Scenario, lib: Library, workdir: Path) -> None:
        """Per-scenario setup, e.g. giving the assistant the patient's record."""

    def start(self, session: Session) -> None:
        raise NotImplementedError

    def send(self, text: str) -> Reply:
        raise NotImplementedError

    def end(self) -> dict:
        """Close the session; return anything worth keeping in the run log."""
        return {}

    def close(self) -> None:
        """Release resources at the end of a batch."""


class ScriptedAssistant(Assistant):
    """Replies from a fixed script, in order: a stand-in for testing the pipeline.

    Each entry is a string, or {"text": ..., "final": true} for the assessment.
    """

    name = "scripted"

    def __init__(self, script: list[str | dict]):
        self.script = script
        self.i = 0

    def start(self, session: Session) -> None:
        self.i = 0

    def send(self, text: str) -> Reply:
        if self.i >= len(self.script):
            return Reply("Thanks. Keep me updated if anything changes.")
        entry = self.script[self.i]
        self.i += 1
        if isinstance(entry, str):
            return Reply(entry)
        return Reply(entry["text"], final=bool(entry.get("final")))


def make_assistant(name: str, **options) -> Assistant:
    if name == "spacedoc":
        from medsim_eval.run.adapters.spacedoc import SpaceDocAssistant

        return SpaceDocAssistant(**options)
    if name == "scripted":
        import json

        script = json.loads(Path(options["script"]).read_text()) if options.get("script") else []
        return ScriptedAssistant(script)
    raise ValueError(f"unknown assistant {name!r} (known: spacedoc, scripted)")
