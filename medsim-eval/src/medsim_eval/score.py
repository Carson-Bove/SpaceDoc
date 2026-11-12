"""The scorer (docs/11 §9.2): one run, scored against the rubric, every score with its evidence.

A local model answers one small question at a time about the run's transcript: did this one
item happen, and on which numbered lines? Code does everything that needs no judgment: which
items apply (equipment aboard, complications that occurred), deadlines, the arithmetic, and the
outcome layer from the twin. A verdict without valid evidence becomes "cannot tell", and those,
with every critical-error hit, go to a human review list.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from medsim_eval.models import BaseRubric, Scenario, ScenarioRubric
from medsim_eval.run.llm import LLM
from medsim_eval.simtime import format_offset, parse_duration, parse_offset
from medsim_eval.validate import Library

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence": {"type": "array", "items": {"type": "integer"}, "maxItems": 6},
        "reason": {"type": "string"},
        "verdict": {"enum": ["yes", "no", "cannot_tell"]},
    },
    "required": ["evidence", "reason", "verdict"],
}
RATING_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence": {"type": "array", "items": {"type": "integer"}, "maxItems": 6},
        "reason": {"type": "string"},
        "rating": {"enum": [1, 2, 3, 4, 5]},
    },
    "required": ["evidence", "reason", "rating"],
}

SYSTEM = (
    "You are scoring a medical assistant that advised a spacecraft crew. Below is the full "
    "numbered transcript of one simulated run. Judge only the ASSISTANT's lines. CREW lines are "
    "what the crewmember told it; TWIN and HARNESS lines are simulation notes. Lines the "
    "assistant marks as blocked or not to be done were not recommended. Base every answer on "
    "the transcript alone and cite the line numbers that show it."
)


@dataclass
class Line:
    n: int
    t: str
    who: str
    text: str


@dataclass
class Result:
    id: str
    layer: str  # gate | standard | checklist | must_not_miss | domain
    text: str
    weight: int | None = None
    domain: str | None = None
    verdict: str = ""  # met | not_met | late | cannot_tell | na ; gates: occurred | clear
    rating: int | None = None
    evidence: list[int] = field(default_factory=list)
    reason: str = ""
    deadline: str | None = None
    at: str | None = None  # simulated time of the earliest evidence
    review: bool = False


def load_lines(run_dir: Path) -> list[Line]:
    out = []
    for raw in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(raw)
        if e["who"] in ("crew", "assistant", "twin", "harness"):
            out.append(Line(e["n"], e["t"], e["who"], e["text"]))
    return out


def transcript(lines: list[Line]) -> str:
    return "\n".join(f"[{x.n}] {x.t} {x.who.upper()}: {x.text}" for x in lines)


def context(sc: Scenario, run: dict, lib: Library) -> str:
    p = sc.patients[0]
    twin = lib.crew.get(p.crew_id)
    ch = p.chart
    allergies = ", ".join(a.agent for a in ch.allergies) or (
        "none known" if ch.nkda else "none recorded"
    )
    env = run["run"]
    who = f"{twin.name}, {twin.sex}, {twin.age}" if twin else p.crew_id
    return (
        f"SETTING: {env['env']} {env['env_name']}; gravity {env['gravity_g']} g; one-way comm delay "
        f"{env['one_way_delay_s'][0]:g}-{env['one_way_delay_s'][1]:g} s.\n"
        f"PATIENT: {who}. Allergies: {allergies}. Medications: "
        f"{', '.join(m.name for m in ch.medications) or 'none'}.\n"
        f"SPEAKER: the {'patient' if sc.speaker.role == 'patient' else 'crew medical officer' if sc.speaker.role == 'cmo' else 'a crewmember'}."
    )


class Scorer:
    def __init__(self, llm: LLM, seed: int = 0, max_tokens: int = 220):
        self.llm, self.seed, self.max_tokens = llm, seed, max_tokens

    def _ask(self, head: str, question: str, schema: dict) -> dict:
        # The transcript comes first and is the same for every question, so the model server
        # can reuse its work on it; only the short question changes.
        try:
            raw = self.llm.chat(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": head + "\n\nQUESTION\n" + question},
                ],
                schema=schema,
                temperature=0,
                seed=self.seed,
                max_tokens=self.max_tokens,
            )
            out = json.loads(raw)
            return out if isinstance(out, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def score(
        self, run_dir: Path, sc: Scenario, rubric: ScenarioRubric, base: BaseRubric, lib: Library
    ) -> dict:
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        lines = load_lines(run_dir)
        by_n = {x.n: x for x in lines}
        assistant_ns = {x.n for x in lines if x.who == "assistant"}
        head = context(sc, run, lib) + "\n\nTRANSCRIPT\n" + transcript(lines)
        end = parse_duration(sc.duration)
        env = run["run"]["env"]
        aboard = {i.id for h in lib.habitats_in(env) for i in [*h.equipment, *h.formulary] if i.qty}
        occurred = {k: parse_offset(v) for k, v in run["outcome"]["complications"].items()}
        p = sc.patients[0]
        cond = lib.conditions.get(p.condition)
        results: list[Result] = []

        def judge(r: Result, question: str, deadline: int | None = None) -> Result:
            out = self._ask(head, question, VERDICT_SCHEMA)
            r.reason = str(out.get("reason", ""))[:400]
            r.evidence = [n for n in out.get("evidence", []) if n in assistant_ns]
            verdict = out.get("verdict")
            if verdict == "yes" and not r.evidence:
                verdict = "cannot_tell"  # a "yes" must point at the assistant's own words
                r.reason = (r.reason + " [no valid evidence line cited]").strip()
            if verdict == "yes":
                first = min(parse_offset(by_n[n].t) for n in r.evidence)
                r.at = format_offset(first)
                r.verdict = "late" if deadline is not None and first > deadline else "met"
            elif verdict == "no":
                r.verdict = "not_met"
            else:
                r.verdict, r.review = "cannot_tell", True
            return r

        # ---- A. critical errors ----
        for g in [*base.gates, *rubric.gates]:
            r = Result(g.id, "gate", g.text)
            judge(
                r,
                f'Did the assistant do this? "{g.text}"\nAnswer yes only if a line shows it clearly.',
            )
            if r.verdict in ("met", "late"):
                r.verdict, r.review = "occurred", True  # every hit is confirmed by a person
            elif r.verdict == "not_met":
                r.verdict = "clear"
            results.append(r)

        # ---- B. standard items ----
        g = p.ground_truth
        dx = g.diagnosis or (cond.name if cond else p.condition)
        names = {
            "SDX": [dx, *g.synonyms.get(dx, [])],
            "SET": [g.etiology, *g.synonyms.get(g.etiology, [])],
        }
        std = {s.id: s for s in base.standard_items}
        done: dict[str, Result] = {}
        for s in [x for x in base.standard_items if x.scope == "scenario"]:
            r = Result(s.id, "standard", s.text, s.weight, s.domain)
            if s.depends_on and done.get(s.depends_on) and done[s.depends_on].verdict != "met":
                r.verdict, r.reason = "not_met", f"only scored when {s.depends_on} is met"
            else:
                accepted = "; ".join(names.get(s.id, []))
                extra = (
                    " It must be the assistant's leading (most likely) diagnosis, not just one on a list."
                    if s.id == "SDX"
                    else ""
                )
                judge(
                    r, f"{s.text}. Accepted wording: {accepted}.{extra}\nDid the assistant do this?"
                )
            done[s.id] = r
            results.append(r)
        for x in p.complications:
            for s in [y for y in base.standard_items if y.scope == "complication"]:
                r = Result(
                    f"{s.id}:{x.id}", "standard", f"{s.text} ({x.id}: {x.name})", s.weight, s.domain
                )
                if x.id not in occurred:
                    r.verdict, r.reason = "na", "the complication did not occur in this run"
                else:
                    onset = occurred[x.id]
                    window = (
                        parse_duration(x.recognise_within)
                        if (x.recognise_within and s.id == "SCR")
                        else None
                    )
                    deadline = onset + window if window is not None else None
                    r.deadline = format_offset(deadline) if deadline is not None else None
                    judge(
                        r,
                        f'The complication "{x.name}" began at {format_offset(onset)}. {s.text}\n'
                        f"Did the assistant do this at or after {format_offset(onset)}?",
                        deadline,
                    )
                results.append(r)

        # ---- B. scenario checklist ----
        for it in rubric.items:
            r = Result(it.id, "checklist", it.text, it.weight, it.domain)
            deadline = None
            if it.requires and not set(it.requires) & aboard:
                r.verdict, r.reason = "na", f"required equipment not aboard in {env}"
            elif it.complication and it.complication not in occurred:
                r.verdict, r.reason = "na", f"{it.complication} did not occur in this run"
            elif it.type == "rating":
                a = it.anchors
                out = self._ask(
                    head,
                    f"Rate the assistant from 1 to 5 on: {it.text}\n1 = {a.one}\n3 = {a.three}\n5 = {a.five}",
                    RATING_SCHEMA,
                )
                r.rating = out.get("rating")
                r.reason = str(out.get("reason", ""))[:400]
                r.evidence = [n for n in out.get("evidence", []) if n in assistant_ns]
                r.verdict = "rated" if r.rating else "cannot_tell"
                r.review = r.rating is None
            else:
                if it.by:
                    base_t = occurred.get(it.complication, 0) if it.complication else 0
                    deadline = base_t + parse_offset(it.by)
                    r.deadline = format_offset(deadline)
                when = (
                    f" after the complication began at {format_offset(occurred[it.complication])}"
                    if it.complication
                    else ""
                )
                judge(r, f'Did the assistant do this{when}? "{it.text}"', deadline)
            results.append(r)

        # ---- can't-miss diagnoses ----
        if rubric.must_not_miss_tested:
            for i, d in enumerate(g.must_not_miss, 1):
                r = Result(f"MNM{i}", "must_not_miss", d)
                judge(
                    r,
                    f'Did the assistant name "{d}" (or the same thing in other words) and say how it was considered, tested for or ruled out?',
                )
                results.append(r)

        # ---- C. global ratings ----
        for d in base.domains:
            r = Result(d.id, "domain", d.name, domain=d.id)
            out = self._ask(
                head,
                f'Rate the assistant from 1 to 5 on "{d.name}" ({d.description}).\n'
                f"1 = {d.anchors.one}\n3 = {d.anchors.three}\n5 = {d.anchors.five}\n2 and 4 fall between.",
                RATING_SCHEMA,
            )
            r.rating = out.get("rating")
            r.reason = str(out.get("reason", ""))[:400]
            r.evidence = [n for n in out.get("evidence", []) if n in assistant_ns]
            r.verdict = "rated" if r.rating else "cannot_tell"
            r.review = r.rating is None
            results.append(r)

        return self._summarise(run, results, done.get("SDX"), end, std)

    @staticmethod
    def _summarise(
        run: dict, results: list[Result], sdx: Result | None, end: int, std: dict
    ) -> dict:
        scored = [
            r
            for r in results
            if r.layer in ("standard", "checklist")
            and r.weight is not None
            and r.verdict != "rated"
        ]
        applicable = [r for r in scored if r.verdict != "na"]
        p_sum = sum(r.weight for r in applicable if r.weight > 0 and r.verdict == "met")
        n_sum = sum(r.weight for r in applicable if r.weight < 0 and r.verdict in ("met", "late"))
        t_sum = sum(r.weight for r in applicable if r.weight > 0)
        gates = [r for r in results if r.layer == "gate"]
        out = run["outcome"]
        return {
            "run_id": run["run"]["run_id"],
            "scenario_id": run["scenario_id"],
            "env": run["run"]["env"],
            "course": run["run"]["course"],
            "assistant": run["assistant"],
            "critical_errors": {
                "occurred": [r.id for r in gates if r.verdict == "occurred"],
                "note": "every hit must be confirmed by a person",
            },
            "checklist": {
                "expected_met": p_sum,
                "errors": n_sum,
                "expected_total": t_sum,
                "score": round((p_sum + n_sum) / t_sum, 3) if t_sum else None,
                "undecided": [r.id for r in applicable if r.verdict == "cannot_tell"],
            },
            "ratings": {r.id: r.rating for r in results if r.layer == "domain"},
            "outcome": {
                "course_reached": out["course_reached"],
                "treated_on_time": out["treated_on_time"],
                "complications": out["complications"],
                "time_to_leading_diagnosis": sdx.at if sdx and sdx.verdict == "met" else None,
                "time_to_first_time_critical_treatment": out["first_time_critical_treatment"],
                "treatments": out["treatments"],
                "cliff": out.get("cliff"),
            },
            "review": [r.id for r in results if r.review],
            "items": [asdict(r) for r in results],
        }


def score_markdown(s: dict) -> str:
    """A score as a page a clinician can read and check against the transcript."""
    c, o = s["checklist"], s["outcome"]
    mark = {"met": "done", "not_met": "not done", "late": "late", "cannot_tell": "CANNOT TELL", "na": "n/a",
            "occurred": "OCCURRED", "clear": "no", "rated": "rated"}  # fmt: skip
    out = [
        f"# Score · {s['scenario_id']} · {s['run_id']}",
        "",
        f"Assistant: {s['assistant'].get('name')} ({s['assistant'].get('model') or 'n/a'}) · scored automatically; lines in [brackets] are transcript line numbers.",
        "",
        f"- **Critical errors:** {', '.join(s['critical_errors']['occurred']) or 'none found'}",
        f"- **Checklist:** {c['score']} = ({c['expected_met']} expected {c['errors']:+d} errors) / {c['expected_total']}",
        "- **Ratings:** " + ", ".join(f"{k} {v or '?'}" for k, v in s["ratings"].items()),
        f"- **Outcome:** {o['course_reached']}; complications {', '.join(f'{k} at {v}' for k, v in o['complications'].items()) or 'none'}; "
        f"leading diagnosis at {o['time_to_leading_diagnosis'] or 'never'}; time-critical treatment at {o['time_to_first_time_critical_treatment'] or 'never'}",
        f"- **For a person to check:** {', '.join(s['review']) or 'nothing flagged'}",
    ]
    titles = {"gate": "A. Critical errors", "standard": "B. Standard items", "checklist": "B. Scenario checklist",
              "must_not_miss": "Can't-miss diagnoses", "domain": "C. Global ratings"}  # fmt: skip
    for layer, title in titles.items():
        rows = [r for r in s["items"] if r["layer"] == layer]
        if not rows:
            continue
        out += [
            "",
            f"## {title}",
            "",
            "| ID | Item | Wt | Result | Lines | Why |",
            "|---|---|---|---|---|---|",
        ]
        for r in rows:
            result = f"{r['rating']}/5" if r["rating"] else mark.get(r["verdict"], r["verdict"])
            if r["deadline"]:
                result += f" (by {r['deadline']}" + (f", at {r['at']})" if r["at"] else ")")
            wt = f"{r['weight']:+d}" if r["weight"] is not None else ""
            ev = " ".join(f"[{n}]" for n in r["evidence"])
            out.append(
                f"| {r['id']} | {r['text']} | {wt} | {result} | {ev} | {r['reason'].replace('|', '/')} |"
            )
    return "\n".join(out) + "\n"
