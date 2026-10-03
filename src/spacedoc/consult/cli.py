"""The interactive `spacedoc consult` session in a terminal."""

from __future__ import annotations

import click
import typer

from spacedoc.consult.engine import SELF, UNLISTED, Consult, Turn
from spacedoc.consult.render import (
    record_markdown,
    red_flag_card,
    render_turn,
    save_record,
    timing_summary,
    urgent_card,
)
from spacedoc.consult.roster import CrewMember
from spacedoc.render.text import render_text
from spacedoc.system import System

COMMANDS = "Commands: /assess (assess now) · /record (show the consult record) · /quit"
QUICK = {"y": "Yes", "yes": "Yes", "n": "No", "no": "No", "?": "Not sure"}


def ask(message: str, default: str | None = None) -> str:
    """Prompt; end of input (Ctrl+D) counts as /quit."""
    try:
        return typer.prompt(message, default=default, show_default=bool(default)).strip()
    except click.exceptions.Abort:
        return "/quit"


def pick_member(answer: str, roster: list[CrewMember]) -> str:
    if answer.isdigit() and 1 <= int(answer) <= len(roster):
        return roster[int(answer) - 1].crew_id
    return answer.upper()


def pick_patient(answer: str, roster: list[CrewMember]) -> str:
    low = answer.lower()
    if low in {"s", "self", "me", "myself"}:
        return SELF
    if low in {"u", "unlisted", "other"}:
        return UNLISTED
    return pick_member(answer, roster)


def expand_quick_reply(text: str, turn: Turn) -> str:
    """Turn "y" or "y n" into full answers when every question is yes/no."""
    qs = turn.reply.questions if turn.reply else []
    tokens = text.lower().replace(",", " ").split()
    if not qs or len(tokens) != len(qs) or any(q.answer_type != "yes_no" for q in qs):
        return text
    if not all(t in QUICK for t in tokens):
        return text
    if len(qs) == 1:
        return QUICK[tokens[0]]
    return " ".join(
        f"{i}. {q.text} {QUICK[t]}." for i, (q, t) in enumerate(zip(qs, tokens, strict=True), 1)
    )


def answer_prompt(turn: Turn) -> str:
    qs = turn.reply.questions if turn.reply else []
    if qs and all(q.answer_type == "yes_no" for q in qs):
        keys = " ".join(["y/n/?"] * len(qs))
        return f"Answer (quick: {keys})"
    return "Answer"


def run_consult(
    system: System,
    user_id: str | None,
    patient_id: str | None,
    tier: str | None,
    practice: bool | None,
    scenario: str | None,
    deep_log: bool,
) -> Consult | None:
    engine = system.consult
    assert engine is not None
    roster = list(engine.roster.values())
    env = system.environment(tier)

    if not user_id or not patient_id:
        typer.echo("Crew roster (synthetic):")
        for i, m in enumerate(roster, 1):
            typer.echo(f"  {i}. {m.label()}")
    if not user_id:
        user_id = pick_member(ask("Who is using SpaceDoc? (number or crew ID)"), roster)
    if not patient_id:
        patient_id = pick_patient(
            ask("Who is the patient? (number or crew ID; s = myself; u = someone not listed)"),
            roster,
        )
    if practice is None:
        practice = ask("Real or practice session? (r/p)", default="p").lower().startswith("p")
    if practice and scenario is None:
        scenario = ask("Scenario ID (Enter to skip)", default="") or None
    try:
        consult = engine.start(user_id, patient_id, env, practice, scenario, deep_log)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e

    kind = "PRACTICE" if consult.practice else "REAL"
    who = "the user" if consult.patient_is_user else consult.patient_label
    typer.echo(
        f"\n{kind} consult {consult.consult_id} · user {consult.user.label()} · patient {who}\n"
        f"{env.summary()}\n"
        f"Deep log: {'on (slower; each turn also shows the estimated time without it)' if deep_log else 'off'}\n"
        f"{COMMANDS}\n"
    )

    try:
        _loop(system, consult)
    except KeyboardInterrupt:
        typer.echo("\nStopped (Ctrl+C).")
    finish(system, consult)
    return consult


def _loop(system: System, consult: Consult) -> None:
    text = ask("Describe the problem")
    while True:
        if text == "/quit":
            break
        if text == "/record":
            typer.echo(record_markdown(consult))
            text = ask("Answer")
            continue
        if text == "/assess" or not text:
            if text == "/assess":
                assess(system, consult)
            text = ask("Add new information to continue, or /quit")
            continue

        turn = system.consult.turn(consult, text)
        if turn.paused:
            typer.echo(red_flag_card(turn.red_flags))
            choice = ask(
                "[a] checked assessment now · [c] continue questions (not an emergency) · [q] quit",
                default="a",
            ).lower()
            if choice.startswith("q"):
                break
            if not choice.startswith("c"):
                assess(system, consult)
                text = ask("Add new information to continue, or /quit")
                continue
            turn = system.consult.resume(consult)
        if turn.reply is None:
            typer.echo(f"SpaceDoc could not continue: {turn.error}")
            text = ask("Try again (or /assess, /quit)")
            continue
        if turn.reply.urgent.flag:
            steps = system.consult.red_flags.steps(delay=consult.delay())
            typer.echo(urgent_card([turn.reply.urgent.reason], steps, "flagged by the model"))
            choice = ask("[a] checked assessment now · [c] continue questions", default="a")
            if not choice.lower().startswith("c"):
                assess(system, consult)
                text = ask("Add new information to continue, or /quit")
                continue
        typer.echo("\n" + render_turn(turn) + "\n")
        reason = system.consult.should_assess(consult)
        if reason:
            typer.echo(reason)
            assess(system, consult)
            text = ask("Add new information to continue, or /quit")
            continue
        text = expand_quick_reply(ask(answer_prompt(turn)), turn)


def assess(system: System, consult: Consult) -> None:
    typer.echo("Preparing the checked assessment (sources, checks; this can take minutes)...")
    v = system.consult.assess(consult)
    typer.echo("\n" + render_text(v))
    typer.echo(f"Full answer saved in the audit log as {v.audit_id}.\n")


def finish(system: System, consult: Consult) -> None:
    path = save_record(consult, system.settings.audit_path.parent / "consults")
    summary = timing_summary(consult)
    if summary:
        typer.echo(summary)
    typer.echo(f"Consult record saved to {path}")
