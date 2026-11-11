"""The simple twin (Phase B): the patient's state over simulated time, built from the scenario.

It follows the scenario's medical timeline (symptoms, findings and vital-sign keyframes, with
their treated / untreated conditions), the time-critical rule, and complication events. The
course side (best or worst) comes from the run plan; a CLiFF-odds run draws it from the CLiFF.
Phase D replaces the vital-sign model with CLiFF course physiology behind the same interface.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import asdict, dataclass

from medsim_eval.models import Scenario
from medsim_eval.models.scenario import ActionRef, TimelineEntry
from medsim_eval.run.plan import RunSpec
from medsim_eval.simtime import format_offset, parse_duration, parse_offset
from medsim_eval.validate import Library

# What the crew can measure aboard without a lab test.
VITALS = ("hr", "sbp", "dbp", "rr", "spo2", "temp_c", "pain_0_10", "gcs", "mental_status")
DEFAULT_WORST_SHARE = 0.3  # when a CLiFF gives no probability for the worst case


@dataclass
class Given:
    t: int
    kit_id: str | None
    text: str


@dataclass
class KitItem:
    id: str
    name: str
    category: str
    qty: float


class SimpleTwin:
    def __init__(self, sc: Scenario, spec: RunSpec, lib: Library):
        self.sc, self.spec = sc, spec
        self.p = sc.patients[0]
        self.rng = random.Random(spec.seed)
        self.crew = lib.crew.get(self.p.crew_id)
        self.cond = lib.conditions.get(self.p.condition)
        self.end = parse_duration(sc.duration)
        self.t = 0
        self.given: list[Given] = []
        self.used: Counter[str] = Counter()
        self.kit: dict[str, KitItem] = {}
        for h in lib.habitats_in(spec.env):
            for i in [*h.formulary, *h.equipment]:
                if i.qty and i.qty > 0:
                    k = self.kit.setdefault(i.id, KitItem(i.id, i.name, i.category, 0))
                    k.qty += i.qty
        self.side = spec.course if spec.course != "cliff" else self._draw_side()
        # Each complication's chance is decided once, up front, so a seed replays exactly.
        self.rolls = {x.id: self.rng.random() < x.chance for x in self.p.complications}
        self.onsets: dict[str, int] = {}
        self.pending: dict[str, int] = {}
        self.events: list[dict] = []

    # ---- course ------------------------------------------------------------------------
    def _draw_side(self) -> str:
        c = self.cond.course if self.cond else None
        worst = c.treated_worst.probability_pct if c and c.treated_worst else None
        share = (sum(worst) / 2 / 100) if worst else DEFAULT_WORST_SHARE
        return "worst" if self.rng.random() < share else "best"

    def _qualifies(self, action: ActionRef, by: int | None = None) -> bool:
        return any(
            g.kit_id in action.refs and (by is None or g.t <= by) for g in self.given if g.kit_id
        )

    def treated_by(self, t: int) -> bool:
        """Every time-critical intervention given by `t` (or, with none set, any treatment)."""
        if not self.p.time_critical:
            return any(g.t <= t for g in self.given)
        return all(self._qualifies(tc.action, t) for tc in self.p.time_critical)

    def treated_on_time(self) -> bool | None:
        if not self.p.time_critical:
            return None
        return all(self._qualifies(tc.action, parse_offset(tc.by)) for tc in self.p.time_critical)

    def _eligible(self, x) -> bool:
        return self.rolls[x.id] and not (x.worst_course_only and self.side != "worst")

    # ---- actions and time --------------------------------------------------------------
    def kit_items(self) -> list[KitItem]:
        return sorted(self.kit.values(), key=lambda k: k.name.lower())

    def give(self, kit_id: str | None, text: str) -> None:
        """Record a treatment the assistant directed and the crew carried out."""
        if not kit_id or kit_id not in self.kit:
            # Not a kit item here: nothing is given, and the log says so.
            self._event("not_aboard", kit_id=kit_id, text=text)
            return
        if self.kit[kit_id].qty <= 0:
            self._event("out_of_stock", kit_id=kit_id, text=text)
            return
        self.given.append(Given(self.t, kit_id, text))
        if kit_id:
            self.kit[kit_id].qty -= 1
            self.used[kit_id] += 1
        self._event("given", kit_id=kit_id, text=text)
        for x in self.p.complications:
            if (
                x.trigger == "action"
                and kit_id
                and kit_id in x.action.refs
                and x.id not in self.onsets
                and x.id not in self.pending
                and self._eligible(x)
            ):
                self.pending[x.id] = self.t + (parse_duration(x.after) if x.after else 0)

    def advance_to(self, t: int) -> None:
        """Move the clock forward, starting any complication whose time has come."""
        t = max(t, self.t)
        due = []
        for x in self.p.complications:
            if x.id in self.onsets:
                continue
            if x.trigger == "untreated":
                at = parse_offset(x.by)
                if at <= t and self._eligible(x) and not self._qualifies(x.action, at):
                    due.append((at, x.id))
            elif x.trigger == "chance":
                at = parse_offset(x.at)
                if at <= t and self._eligible(x):
                    due.append((at, x.id))
            elif x.id in self.pending and self.pending[x.id] <= t:
                due.append((self.pending.pop(x.id), x.id))
        for at, cid in sorted(due):
            self.onsets[cid] = at
            self._event("complication", id=cid, at=format_offset(at))
        self.t = t

    def next_change_after(self, t: int) -> int | None:
        """The next time something in the scenario can change, after `t`."""
        times = [parse_offset(e.t) for e in self.p.timeline if self._applies(e)]
        for x in self.p.complications:
            if x.id in self.onsets:
                times += [self.onsets[x.id] + parse_offset(f.t) for f in x.findings]
            elif not self._eligible(x):
                continue
            elif x.trigger == "untreated":
                if not self._qualifies(x.action, parse_offset(x.by)):
                    times.append(parse_offset(x.by))
            elif x.trigger == "chance":
                times.append(parse_offset(x.at))
        times += list(self.pending.values())
        later = [x for x in times if x > t]
        return min(later) if later else None

    # ---- what can be observed now --------------------------------------------------------
    def _applies(self, e: TimelineEntry) -> bool:
        at = parse_offset(e.t)
        if e.when == "treated":
            return self.treated_by(at)
        if e.when == "untreated":
            return not self.treated_by(at)
        return True

    def observe(self) -> dict:
        """The patient as the crew could find them now: symptoms, exam findings, vital signs."""
        now = self.t
        entries = [(parse_offset(e.t), e) for e in self.p.timeline if self._applies(e)]
        for cid, onset in self.onsets.items():
            x = next(c for c in self.p.complications if c.id == cid)
            entries += [(onset + parse_offset(f.t), f) for f in x.findings]
        entries = sorted(((at, e) for at, e in entries if at <= now), key=lambda x: x[0])
        vitals: dict = {}
        if self.crew:
            b = self.crew.baseline
            vitals = {k: getattr(b, k) for k in ("hr", "sbp", "dbp", "rr", "spo2", "temp_c")}
        labs: dict = {}
        symptoms, findings = [], []
        for at, e in entries:
            if e.kind == "keyframe":
                for k, v in e.state.items():
                    (vitals if k in VITALS else labs)[k] = v
            elif e.kind == "symptom":
                symptoms.append({"since": format_offset(at), "text": e.text})
            elif e.kind == "finding":
                findings.append({"since": format_offset(at), "text": e.text})
        return {
            "time": format_offset(now),
            "symptoms": symptoms,
            "exam_findings": findings,
            "vitals": vitals,
            "labs": labs,
            "complications": sorted(self.onsets),
        }

    # ---- outcome -------------------------------------------------------------------------
    def outcome(self) -> dict:
        on_time = self.treated_on_time()
        if on_time is None:
            course = None
        else:
            course = f"{'treated' if on_time else 'untreated'}_{self.side}"
        cliff = None
        c = self.cond.course if self.cond else None
        if c and course and getattr(c, course, None):
            cc = getattr(c, course)
            cliff = {
                "probability_pct": cc.probability_pct,
                "rtdc_pct": cc.rtdc_pct,
                "locl_pct": cc.locl_pct,
            }
        first = None
        for g in self.given:
            if any(g.kit_id and g.kit_id in tc.action.refs for tc in self.p.time_critical):
                first = format_offset(g.t)
                break
        return {
            "side": self.side,
            "treated_on_time": on_time,
            "course_reached": course,
            "cliff": cliff,
            "complications": {k: format_offset(v) for k, v in sorted(self.onsets.items())},
            "treatments": [
                {"t": format_offset(g.t), "kit_id": g.kit_id, "text": g.text} for g in self.given
            ],
            "first_time_critical_treatment": first,
            "resources_used": dict(self.used),
            "ended_at": format_offset(self.t),
        }

    def _event(self, kind: str, **data) -> None:
        self.events.append({"t": format_offset(self.t), "kind": kind, **data})

    def snapshot(self) -> dict:
        return {"t": format_offset(self.t), "given": [asdict(g) for g in self.given]}
