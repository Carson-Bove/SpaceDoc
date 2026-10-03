"""Plain-text and Markdown views of a consult: turns, urgent cards, timing, the record."""

from __future__ import annotations

import statistics

from spacedoc.consult.engine import Consult, Turn, TurnTiming
from spacedoc.consult.redflags import RedFlagHit
from spacedoc.render.text import render_text

WORKING_LABEL = "Working list (not yet checked)"


def _s(x: float | None) -> str:
    return "?" if x is None else f"{x:.1f} s"


def timing_line(t: TurnTiming | None) -> str:
    if t is None:
        return ""
    parts = []
    if t.load_s and t.load_s >= 0.5:
        parts.append(f"loading model {_s(t.load_s)}")
    if t.prompt_s is not None:
        parts.append(f"reading {_s(t.prompt_s)}")
    if t.gen_s is not None:
        parts.append(f"writing {_s(t.gen_s)}" + (f", {t.tokens} tokens" if t.tokens else ""))
    line = f"⏱ {_s(t.total_s)}" + (f" ({'; '.join(parts)})" if parts else "")
    if t.deep_log:
        est = (
            f"about {_s(t.without_deep_log_s)} without deep log (estimated)"
            if t.without_deep_log_s is not None
            else "time without deep log not available from this server"
        )
        line += f" · deep log on · {est}"
    return line


def urgent_card(reasons: list[str], steps: list[str], source: str) -> str:
    lines = ["", "⚠ POSSIBLE URGENT PROBLEM " + f"({source})"]
    lines += [f"  - {r}" for r in reasons]
    lines.append("  Immediate steps (DRAFT, not yet clinician-reviewed):")
    lines += [f"    {i}. {s}" for i, s in enumerate(steps, 1)]
    return "\n".join(lines)


def red_flag_card(hits: list[RedFlagHit]) -> str:
    steps: list[str] = []
    for h in hits:
        steps += [s for s in h.steps if s not in steps]
    reasons = [f'{h.message} (you wrote "{h.matched}")' for h in hits]
    return urgent_card(reasons, steps, "red-flag rules")


def render_turn(turn: Turn) -> str:
    r = turn.reply
    if r is None:
        return f"SpaceDoc could not continue: {turn.error}" if turn.error else ""
    out: list[str] = []
    if r.working_ddx:
        out.append(f"{WORKING_LABEL}:")
        out += [f"  - {d.condition} · {d.likelihood} · {d.why}" for d in r.working_ddx]
    if r.questions:
        out.append("Questions:")
        for i, q in enumerate(r.questions, 1):
            choices = f" [{' / '.join(q.choices)}]" if q.choices else ""
            out.append(f"  {i}. {q.text}{choices}")
            out.append(f"     why: {q.why}")
    for c in turn.exam_checks:
        eq = ", ".join(c.request.equipment) or "no equipment"
        out.append(f"Exam: {c.request.text} (equipment: {eq})")
        if c.request.why:
            out.append(f"     why: {c.request.why}")
        if c.missing:
            out.append(f"     ✗ NOT ABOARD: {', '.join(c.missing)}. Skip or use what is aboard.")
        for f in c.findings:
            out.append(f"     ✗ {f}")
    out.append(timing_line(turn.timing))
    return "\n".join(out)


def timing_summary(consult: Consult) -> str:
    timed = [t.timing for t in consult.turns if t.reply and t.timing]
    if not timed:
        return ""
    first, rest = timed[0], timed[1:]
    lines = [f"Question turns: {len(timed)}. First turn {_s(first.total_s)} (may include loading)."]
    if rest:
        totals = [t.total_s for t in rest]
        lines.append(
            f"Later turns: median {_s(statistics.median(totals))}, slowest {_s(max(totals))}."
        )
        est = [t.without_deep_log_s for t in rest if t.without_deep_log_s is not None]
        if consult.deep_log and est:
            lines.append(
                f"Estimated without deep log: median {_s(statistics.median(est))} "
                "(an estimate; run without --deep-log to measure)."
            )
    return " ".join(lines)


def record_markdown(consult: Consult) -> str:
    """The consult record: every turn, the working list as it changed, timings, assessments."""
    kind = "practice" if consult.practice else "real"
    scenario = f", scenario {consult.scenario_id}" if consult.scenario_id else ""
    lines = [
        f"# Consult record {consult.consult_id} ({kind}{scenario})",
        "",
        f"- **User:** {consult.user.label()}",
        f"- **Patient:** {'the user' if consult.patient_is_user else consult.patient_label}",
        f"- **Environment:** {consult.env.summary()}",
        f"- **Started:** {consult.started_at} · deep log {'on' if consult.deep_log else 'off'}",
        "",
    ]
    for t in consult.turns:
        lines += [f"## Turn {t.n}", "", f"**{consult.user.crew_id}:** {t.user_text}", ""]
        if t.red_flags:
            state = "continued by the user" if t.red_flags_dismissed else "consult paused"
            flags = "; ".join(f"{h.rule_id} ({h.matched})" for h in t.red_flags)
            lines += [f"**Red flags:** {flags} — {state}", ""]
        r = t.reply
        if r:
            if r.urgent.flag:
                lines += [f"**Model flagged urgent:** {r.urgent.reason}", ""]
            if r.facts:
                lines.append(
                    "**Facts noted:** " + "; ".join(f"{f.item}: {f.value}" for f in r.facts)
                )
                lines.append("")
            if r.working_ddx:
                lines.append(f"**{WORKING_LABEL}:**")
                lines += [f"- {d.condition} · {d.likelihood} · {d.why}" for d in r.working_ddx]
                lines.append("")
            for q in r.questions:
                lines.append(f"- **Asked:** {q.text} _(why: {q.why})_")
            for c in t.exam_checks:
                status = "ok" if c.ok else "; ".join(c.missing + c.findings)
                lines.append(f"- **Exam:** {c.request.text} _(equipment check: {status})_")
            if r.ready_to_assess:
                lines.append("- **Ready to assess**")
            lines.append("")
        if t.thinking:
            lines += ["<details><summary>Thinking notes (deep log, unverified)</summary>", ""]
            lines += [t.thinking, "", "</details>", ""]
        if t.timing:
            lines += [timing_line(t.timing), ""]
    for i, v in enumerate(consult.assessments, 1):
        lines += [f"## Assessment {i} ({v.audit_id})", "", "```", render_text(v), "```", ""]
    summary = timing_summary(consult)
    if summary:
        lines += ["## Timing", "", summary, ""]
    return "\n".join(lines)
