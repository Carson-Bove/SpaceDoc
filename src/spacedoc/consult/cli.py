"""The interactive `spacedoc consult` session in a terminal."""

from __future__ import annotations

import click
import typer

from spacedoc.consult.engine import SELF, UNLISTED, Answer, Consult, Turn
from spacedoc.consult.render import (
    record_markdown,
    red_flag_card,
    render_turn,
    save_record,
    timing_summary,
)
from spacedoc.consult.roster import CrewMember
from spacedoc.consult.safety import ScreenItem
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


def _yes_no_questions(turn: Turn) -> list:
    """The questions quick replies can answer: all yes/no, and nothing added by SpaceDoc (a
    "y" could otherwise answer the wrong question)."""
    qs = turn.reply.questions if turn.reply else []
    if not qs or turn.appended or any(q.answer_type != "yes_no" for q in qs):
        return []
    return qs


def quick_answers(text: str, turn: Turn) -> list[Answer] | None:
    """Turn "y" or "y n" into button answers when every question is yes/no; else None."""
    qs = _yes_no_questions(turn)
    tokens = text.lower().replace(",", " ").split()
    if not qs or len(tokens) != len(qs) or not all(t in QUICK for t in tokens):
        return None
    return [Answer(question=q.topic, answer=QUICK[t]) for q, t in zip(qs, tokens, strict=True)]


def exposure_card(items: list[ScreenItem]) -> str:
    lines = ["Exposure check (draft list, not yet clinician-reviewed):"]
    lines += [f"  {i}. {item.question}" for i, item in enumerate(items, 1)]
    return "\n".join(lines)


EXPOSURE_PROMPT = (
    "Exposure: type none, or the numbers that apply; the rest count as No "
    "(add ? if unsure, e.g. 2 5?). Enter to skip"
)


def exposure_answers(text: str, items: list[ScreenItem]) -> list[Answer] | None:
    """Parse "none" or "2 5?" into one answer per item; None if it can't be read."""
    low = text.strip().lower()
    if low in {"none", "no", "n", "none of these", "0"}:
        chosen: dict[int, str] = {}
    else:
        chosen = {}
        for token in low.replace(",", " ").split():
            unsure = token.endswith("?")
            number = token.rstrip("?")
            if not number.isdigit() or not 1 <= int(number) <= len(items):
                return None
            chosen[int(number)] = "Not sure" if unsure else "Yes"
        if not chosen:
            return None
    return [
        Answer(
            kind="screen",
            question=item.question,
            answer=chosen.get(i, "No"),
            screen_id=item.id,
        )
        for i, item in enumerate(items, 1)
    ]


def ask_exposure(items: list[ScreenItem]) -> list[Answer]:
    typer.echo(exposure_card(items))
    while True:
        text = ask(EXPOSURE_PROMPT, default="")
        if not text or text == "/quit":
            return []
        answers = exposure_answers(text, items)
        if answers is not None:
            return answers
        typer.echo(f"Type none, or numbers from 1 to {len(items)}.")


def answer_prompt(turn: Turn) -> str:
    if qs := _yes_no_questions(turn):
        return f"Answer (quick: {' '.join(['y/n/?'] * len(qs))})"
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
        f"Patient record used: {consult.patient_summary}\n"
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
    answers: list[Answer] | None = None
    screen: list[Answer] = []
    while True:
        if text == "/quit":
            break
        if text == "/record":
            typer.echo(record_markdown(consult))
            text = ask("Answer")
            continue
        if text == "/assess" or (not text and not answers and not screen):
            if text == "/assess":
                assess(system, consult)
            text = ask("Add new information to continue, or /quit")
            continue

        turn = system.consult.turn(consult, "" if answers else text, (answers or []) + screen)
        answers, screen = None, []
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
        typer.echo("\n" + render_turn(turn) + "\n")
        reason = system.consult.should_assess(consult)
        if reason:
            typer.echo(reason)
            assess(system, consult)
            text = ask("Add new information to continue, or /quit")
            continue
        if turn.screen:
            screen = ask_exposure(turn.screen)
        text = ask(answer_prompt(turn), default="" if screen else None)
        answers = quick_answers(text, turn)


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
