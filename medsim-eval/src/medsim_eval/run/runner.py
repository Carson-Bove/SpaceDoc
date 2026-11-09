"""Drive one run, and a batch of them (docs/11 §4, §9).

A run has two phases. The consult: the crewmember opens with the scenario's opening statement
and the two talk until the assistant gives its assessment or the turn limit is reached. Then
follow-ups: the clock jumps to the next thing that changes (a new symptom, a complication, or
the re-check the assistant asked for) and the crewmember reports back, up to a limit or the end
of the scenario. Everything is logged with its simulated time.

Output, per run: events.jsonl (every message and twin event), transcript.md, run.json (the run
plan entry, outcome and settings). Per batch: batch.json, a summary of every run.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from medsim_eval.models import Scenario
from medsim_eval.run.adapters import Assistant, Session
from medsim_eval.run.crewmember import Actions, Persona
from medsim_eval.run.plan import RunSpec, plan_runs
from medsim_eval.run.twin import SimpleTwin
from medsim_eval.simtime import format_offset
from medsim_eval.validate import Library


@dataclass
class RunConfig:
    max_turns: int = 12
    max_followups: int = 3
    turn_minutes: int = 3  # simulated time per exchange (reading, doing, replying)
    default_followup_h: float = 12  # when nothing is scheduled and no re-check was asked for


class RunLog:
    def __init__(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        self.folder = folder
        self.events = (folder / "events.jsonl").open("w", encoding="utf-8")
        self.lines: list[str] = []
        self.n = 0

    def event(self, t: str, who: str, text: str = "", **data) -> None:
        self.n += 1
        rec = {"n": self.n, "t": t, "who": who, "text": text, **data}
        self.events.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.events.flush()
        if who in ("crew", "assistant"):
            label = {"crew": "Crewmember", "assistant": "Assistant"}[who]
            self.lines.append(f"**[{self.n}] {t} · {label}:** {text}\n")
        elif who == "twin":
            self.lines.append(f"*[{self.n}] {t} · twin: {text}*\n")

    def close(self, header: str) -> None:
        self.events.close()
        (self.folder / "transcript.md").write_text(
            header + "\n\n" + "\n".join(self.lines), encoding="utf-8"
        )


def run_one(
    sc: Scenario,
    spec: RunSpec,
    lib: Library,
    assistant: Assistant,
    make_crewmember,
    extractor,
    out: Path,
    cfg: RunConfig,
) -> dict:
    twin = SimpleTwin(sc, spec, lib)
    p = sc.patients[0]
    persona = Persona(sc, lib.crew.get(sc.speaker.crew_id), lib.crew.get(p.crew_id))
    crew = make_crewmember(persona, spec)
    log = RunLog(out / spec.run_id)
    started = time.monotonic()
    log.event(
        "T+0",
        "system",
        f"{spec.run_id}: {spec.env} {spec.env_name}, course {spec.course} (side {twin.side})",
        spec=spec.to_dict(),
    )
    assistant.start(
        Session(
            spec.run_id, sc.scenario_id, spec.env, sc.speaker.crew_id, sc.speaker.role, p.crew_id
        )
    )
    turns, finals, errors = 0, 0, 0
    last_acts = Actions()
    twin_seen = 0

    def exchange(message: str) -> tuple[str, bool]:
        nonlocal turns, finals, errors, last_acts, twin_seen
        log.event(format_offset(twin.t), "crew", message)
        try:
            reply = assistant.send(message)
        except Exception as e:  # keep the batch going; the log says what broke
            errors += 1
            log.event(format_offset(twin.t), "system", f"assistant failed: {e}")
            return "", True
        turns += 1
        finals += reply.final
        log.event(
            format_offset(twin.t),
            "assistant",
            reply.text,
            final=reply.final,
            seconds=round(reply.seconds, 2),
            data=reply.data,
        )
        acts = extractor.extract(reply.text, twin.kit_items())
        last_acts = acts
        log.event(format_offset(twin.t), "extract", "", actions=acts.to_dict())
        for tr in acts.treatments:
            twin.give(tr.kit_id, tr.text)
        twin.advance_to(twin.t + cfg.turn_minutes * 60)
        for ev in twin.events[twin_seen:]:
            log.event(
                ev["t"],
                "twin",
                f"{ev['kind']} "
                + ", ".join(f"{k}={v}" for k, v in ev.items() if k not in ("t", "kind")),
                event=ev,
            )
        twin_seen = len(twin.events)
        return reply.text, reply.final

    # Phase 1: the consult.
    message = crew.opening()
    for _ in range(cfg.max_turns):
        text, final = exchange(message)
        if not text:
            break
        if final:
            message = crew.acknowledge(text, twin.observe())
            exchange(message)
            break
        message = crew.reply(text, twin.observe(), last_acts)

    # Phase 2: follow-ups as time passes.
    last_facts = twin.observe()
    for _ in range(cfg.max_followups):
        if errors:
            break
        candidates = [twin.next_change_after(twin.t)]
        if last_acts.recheck_minutes:
            candidates.append(twin.t + last_acts.recheck_minutes * 60)
        nxt = min((c for c in candidates if c), default=None)
        if nxt is None:
            nxt = twin.t + int(cfg.default_followup_h * 3600)
        if nxt > twin.end:
            break
        twin.advance_to(nxt)
        for ev in twin.events[twin_seen:]:
            log.event(
                ev["t"],
                "twin",
                f"{ev['kind']} "
                + ", ".join(f"{k}={v}" for k, v in ev.items() if k not in ("t", "kind")),
                event=ev,
            )
        twin_seen = len(twin.events)
        facts = twin.observe()
        text, _ = exchange(crew.update(facts, last_facts))
        last_facts = facts
        if not text:
            break

    record = assistant.end()
    outcome = twin.outcome()
    result = {
        "run": spec.to_dict(),
        "scenario_id": sc.scenario_id,
        "assistant": assistant.info(),
        "crewmember": getattr(crew, "name", type(crew).__name__),
        "extractor": type(extractor).__name__,
        "config": cfg.__dict__,
        "turns": turns,
        "assessments": finals,
        "errors": errors,
        "wall_seconds": round(time.monotonic() - started, 1),
        "outcome": outcome,
        "assistant_record": record,
    }
    (out / spec.run_id / "run.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    log.close(
        f"# {sc.scenario_id} · {spec.run_id}\n\n{spec.env} {spec.env_name} · course {spec.course} "
        f"(side {twin.side}) · course reached: {outcome['course_reached']} · complications: "
        f"{outcome['complications'] or 'none'}"
    )
    return result


def run_batch(
    scenarios: list[Scenario],
    lib: Library,
    assistant: Assistant,
    make_crewmember,
    extractor,
    out_root: Path,
    cfg: RunConfig,
    only: int | None = None,
    base_seed: int = 0,
    progress=print,
) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    batch = out_root / f"{stamp}-{assistant.name}"
    batch.mkdir(parents=True, exist_ok=True)
    summary = []
    try:
        for sc in scenarios:
            folder = batch / sc.scenario_id
            folder.mkdir(exist_ok=True)
            progress(f"{sc.scenario_id}: preparing {assistant.name}")
            assistant.prepare(sc, lib, folder)
            specs = plan_runs(sc, lib, base_seed)[:only] if only else plan_runs(sc, lib, base_seed)
            for spec in specs:
                progress(f"{sc.scenario_id} {spec.run_id}: running")
                r = run_one(sc, spec, lib, assistant, make_crewmember, extractor, folder, cfg)
                summary.append(
                    {
                        "scenario_id": sc.scenario_id,
                        "run_id": spec.run_id,
                        "env": spec.env,
                        "course": spec.course,
                        "course_reached": r["outcome"]["course_reached"],
                        "complications": r["outcome"]["complications"],
                        "turns": r["turns"],
                        "assessments": r["assessments"],
                        "errors": r["errors"],
                        "wall_seconds": r["wall_seconds"],
                    }
                )
                progress(
                    f"  {r['turns']} turns, course reached {r['outcome']['course_reached']}, "
                    f"complications {list(r['outcome']['complications']) or 'none'}, {r['wall_seconds']} s"
                )
    finally:
        assistant.close()
        (batch / "batch.json").write_text(
            json.dumps({"assistant": assistant.info(), "runs": summary}, indent=1), encoding="utf-8"
        )
    return batch
